"""§7.4's detectability test: the two-sample Kolmogorov–Smirnov p-value.

app_spec.xml, "Null Oracle & Planted Nulls", feature 123: *System persists
the p-value of a two-sample Kolmogorov-Smirnov test comparing in-sample
scores of null nodes against real nodes per campaign.*  This module is the
*test* — the statistic and its p-value — and :mod:`nulloracle.ksguard` is
the persistence half, split the way :mod:`nulloracle.assignment` (schema)
and :mod:`nulloracle.envelope` (cipher) are split from
:mod:`nulloracle.sidecar` (file): the numbers can be reasoned about and
tested with no database in the way, and the store can be tested with a
hand-built record rather than a hand-built sample.

docs/nullius-tech-architecture.md §7.4 states what the number is for::

    if ks_pvalue < 0.05:
        campaign.calibration_status = VOID
        alert("nulls may be detectable — investigate block length")
        halt_dreaming()

and the PRD's §4.3 says why: *"the nulls are detectable, the agent may be
learning to identify them, and the campaign's calibration is void."*
Feature 124 is the feature that compares the p-value to 0.05 and voids the
campaign; this one stops at the number.  The threshold is deliberately
**not** a constant of this module: a test that also decided the verdict
would be two features wearing one name, and the level belongs to the
feature whose sentence spells it.

**Why this member carries its own KS test.**  The standard library ships
no Kolmogorov–Smirnov test, and the two alternatives both lose.  SciPy is
the obvious one — and it is exactly what the tripwires member refused for
its own single missing function (:mod:`tripwires.normal`: *"a dependency
graph the frozen evaluator §12's determinism story does not want inside a
hash-pinned image"*).  A member that needs one statistic does not get to
hand the whole workspace a compiled numerical stack to get it.  The
alternative — shelling out, or trusting a p-value computed somewhere else
— would leave the *only* number that can void a campaign outside the
member that owns it, which is worse than either.

**The partition is the secret, so nothing here carries node identities.**
§4.2 draws the information barrier: *"``is_null`` is visible to exactly one
component: the replay scorer"*, and it must never appear in the discovery
agent's context, the exploration policy's prefix, *"any stored artifact the
policy can read during replay"*, or any log the policy-development agent
reads.  §7.4 names the one sanctioned exception — *"a job holding the
sidecar key runs a two-sample KS test on in-sample score distributions,
null nodes vs. real nodes"* — so this member is the process that may open
the labels, not a component that may keep them.  The consequence is a
design rule the code below obeys: :class:`KolmogorovSmirnov` carries the
*sizes* of the two samples, the statistic and the p-value, and **not** the
scores, and not a single node id.  A caller can audit what the test saw
(*how many on each side, how far apart*) without the value it hands on
ever naming which node was null.  The caller's own mapping is the caller's
to keep, and :mod:`nulloracle.ksguard` writes none of it.

**Two estimators, one switchpoint, and the switchpoint is pinned.**  The
p-value is computed by one of two methods, and which one ran is *reported*
on the record rather than left implicit:

* **exact**, for samples small enough to enumerate: the two-sided
  two-sample p-value is a lattice-path count — the probability that the
  maximum gap between the two empirical CDFs reaches the observed one is
  one minus the fraction of the ``C(n+m, n)`` interleavings whose every
  prefix keeps ``|i·m − j·n|`` strictly below the observed count.  That is
  a dynamic program over the ``(i, j)`` grid, computed in Python's
  arbitrary-precision integers so the count is exact and the only floating
  operation is the final division.  Campaign-sized samples (feature 174's
  ~500 nodes per campaign, §4.1.1's ``φ`` of 0.15–0.35 planted nulls) land
  here, which is the point: the common case is the exact one.
* **asymptotic**, for samples too large to enumerate: the Kolmogorov
  distribution ``Q(λ) = 2·Σⱼ(−1)^(j−1)·exp(−2j²λ²)`` at
  ``λ = √(n·m/(n+m))·D``, the series Numerical Recipes publishes and this
  module mirrors term for term.  It is reached only when both samples are
  large (see :data:`KS_ASYMPTOTIC_FLOOR`), and the branch is *reported*, so
  a reader can tell which estimator produced a stored number.

**On ties, and on the direction the approximation errs.**  The exact count
assumes the underlying scores are continuous, which in-sample scores are
not guaranteed to be — an agent that emits the same score for many nodes,
or a book that is flat on most dates, produces ties.  Ties *inflate* the
reported p-value: the exact count over all interleavings includes paths
that a tie-constrained sequence could never take, so the statistic is
compared against a null distribution that admits more extreme arrangements
than the data can actually produce, and the test is conservative.  That is
stated rather than papered over, because it is the honest limitation of
every exact lattice implementation and because it errs away from voiding
(§7.4's alert) rather than toward it.  The statistic itself is
tie-corrected: the gap is measured at each distinct score value, with both
ECDFs stepped together, which is the standard two-sample definition and the
one scipy computes.

**The asymptotic branch is not bit-reproducible across libm versions.**
``math.exp`` is a platform call, and the tripwires member's determinism
note names the same trade for the calls it avoided
(:mod:`tripwires.normal`: *"no platform-dependent calls (no ``math.erf``,
no libm ``ndtri``)"*).  The exact branch has no such dependency — integer
arithmetic and one division — so the branch §12's determinism contract
actually bites on is stable, and the fallback is documented instead of
pretended away.

What this module does not do: it does not decide the verdict (feature
124's), it does not know what a campaign is beyond an id string, it does
not read the sidecar, and it does not touch a database.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import comb
from typing import Any

from .assignment import normalize_node_id
from .errors import KsTestError

__all__ = [
    "KS_ASYMPTOTIC",
    "KS_ASYMPTOTIC_FLOOR",
    "KS_EXACT",
    "KS_EXACT_CELLS",
    "KS_MIN_SAMPLE",
    "KS_SERIES_TERMS",
    "KolmogorovSmirnov",
    "ks_pvalue",
    "ks_two_sample",
    "two_sample_statistic",
]

#: The method name :class:`KolmogorovSmirnov` reports for the lattice-path
#: count.  Spelled as a constant because the stored ``method`` column of
#: :mod:`nulloracle.ksguard` carries exactly this word, and a reader of a
#: stored row is entitled to compare it against a spelling rather than
#: against a string they guessed.
KS_EXACT = "exact"

#: The method name reported for the asymptotic Kolmogorov series.
KS_ASYMPTOTIC = "asymptotic"

#: The largest ``n·m`` this module will enumerate exactly.
#:
#: The exact count is a dynamic program over the ``(i, j)`` grid, banded to
#: the ``|i·m − j·n| ≤ K−1`` window, so its cost is the window's area rather
#: than the full ``n·m`` product — but the window can be the whole grid, and
#: 250 000 cells of Python big-integer addition is the point where the
#: computation stops being obviously cheap for a per-campaign job.  It is a
#: *feasibility* bound, not a statistical one: below it the exact estimator
#: is used at every sample size, and the boundary is set well past the
#: campaign sizes this system actually produces (feature 174's 500-node
#: campaigns sit at ``n·m`` around 47 000 at ``φ = 0.25``).
KS_EXACT_CELLS = 250_000

#: The smallest per-side sample the asymptotic branch will accept.
#:
#: Only reachable when ``n·m`` exceeds :data:`KS_EXACT_CELLS`, which already
#: implies both sides are large — but the product is not quite a statement
#: about each side (``n=3, m=100_000`` exceeds it too), and the Kolmogorov
#: series is a large-sample limit that says nothing about a three-point
#: empirical CDF.  So a sample this lopsided is refused by name rather than
#: estimated, because a p-value computed from three points wearing the
#: asymptotic branch's authority is the exact failure this module's
#: validation exists to prevent.
KS_ASYMPTOTIC_FLOOR = 200

#: How many terms of the Kolmogorov series to sum before giving up.
#:
#: Numerical Recipes' own cap.  Convergence is normally reached in a handful
#: of terms; the cap is reached only as ``λ → 0``, where the alternating
#: series is not converging at all and the answer is 1 — the value the
#: fallback returns.  100 is the published figure, kept rather than tuned.
KS_SERIES_TERMS = 100

#: The two convergence tolerances of the series, Numerical Recipes' ``EPS1``
#: and ``EPS2``: stop when a term is negligible relative to both the previous
#: term and the running sum.  Named because they are part of the pinned
#: algorithm a reproduction of a stored p-value would have to match.
_SERIES_EPS1 = 1e-6
_SERIES_EPS2 = 1e-16

#: The smallest sample, per side, that can support a verdict.
#:
#: Two: a distribution of one point has no shape to compare, so a sample of
#: one is refused by name.  The floor is structural rather than statistical
#: — a two-point sample has almost no power to detect a difference — and
#: that distinction is deliberate.  *What to do about a campaign whose
#: samples are too small to decide anything* is a question about the
#: campaign (feature 124's verdict, or the orchestrator's planning), not
#: about the arithmetic; this module's floor refuses only what cannot be
#: computed at all, because a guard that refused low-power campaigns would
#: also be a guard that could never void one.
KS_MIN_SAMPLE = 2


def _validated_scores(sample: Any, *, side: str) -> tuple[float, ...]:
    """One side's in-sample scores, as a sorted tuple of finite floats.

    Accepts the mapping a campaign naturally holds — ``{node_id: score}`` —
    or a plain iterable of scores.  The keys of a mapping are validated
    through :func:`~nulloracle.assignment.normalize_node_id` even though the
    scores are all this module needs from them: a caller whose sample is
    keyed by something that cannot join the tree store's ``node.id`` has
    assembled the sample from the wrong source, and that is worth learning
    at the guard rather than after a campaign has been voided on it.

    Every score must be a finite real.  ``nan``, an infinity, a ``None`` a
    caller's truthiness test dropped one entry too late, and a bool (Python
    makes ``True`` an ``int``, and a sample of flags is not a sample of
    scores) are each refused with :class:`~nulloracle.errors.KsTestError`
    naming the side and the value.  A sorted tuple is returned so the
    statistic walks two ordered sequences without re-sorting, and so the
    returned value cannot be mutated under a later reader.
    """
    if isinstance(sample, Mapping):
        values: list[Any] = []
        for node_id, score in sample.items():
            try:
                normalize_node_id(node_id)
            except Exception as exc:  # noqa: BLE001 - re-raised by name below
                raise KsTestError(
                    f"the {side} sample is keyed by {node_id!r}, which is not "
                    f"a node id: {exc}"
                ) from exc
            values.append(score)
    elif isinstance(sample, Iterable) and not isinstance(sample, (str, bytes)):
        values = list(sample)
    else:
        raise KsTestError(
            f"the {side} sample must be a mapping of node id to in-sample "
            f"score, or an iterable of scores; got {type(sample).__name__}. "
            "§7.4's guard compares two *populations* of scores, so a single "
            "number or a bare string is not a sample"
        )
    if len(values) < KS_MIN_SAMPLE:
        raise KsTestError(
            f"the {side} sample holds {len(values)} score(s); §7.4's guard "
            f"compares two distributions and a sample of fewer than "
            f"{KS_MIN_SAMPLE} points has none to compare — the p-value that "
            "decides whether a campaign is voided cannot be computed from it"
        )
    scores: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise KsTestError(
                f"the {side} sample holds a score that is not a real number: "
                f"{value!r} ({type(value).__name__}). A p-value computed over "
                "a sample an in-sample score never belonged to would be a "
                "statistic about a population the campaign did not have"
            )
        number = float(value)
        if not math.isfinite(number):
            raise KsTestError(
                f"the {side} sample holds the non-finite score {number!r}; a "
                "non-finite in-sample score is a measurement that failed, and "
                "silently dropping it would compare two distributions neither "
                "of which is the one the campaign produced"
            )
        scores.append(number)
    scores.sort()
    return tuple(scores)


def _require_disjoint(
    null_sample: Mapping[Any, Any], real_sample: Mapping[Any, Any]
) -> None:
    """Refuse two samples that name the same node on both sides.

    A node is null or it is real; §7.1's sidecar keys exactly one bit per
    node.  A node appearing in both samples means the caller assembled them
    from two disagreeing sources, and the p-value that followed would be a
    statistic about a partition the campaign never had — the kind of
    plausible-looking number this whole member exists to keep out of the
    calibration record.  Only answerable for two mappings (an iterable of
    bare scores carries no identities), which is one more reason to hand
    this function the mapping a campaign actually holds.
    """
    shared = set(null_sample) & set(real_sample)
    if shared:
        example = min(str(node) for node in shared)
        raise KsTestError(
            f"the two samples share {len(shared)} node id(s) — {example} is "
            "named as both null and real; a node's null status is one bit in "
            "§7.1's sidecar, so two samples that disagree about it are not "
            "the two populations §7.4's guard compares"
        )


def _max_scaled_gap(null_scores: tuple[float, ...], real_scores: tuple[float, ...]) -> int:
    """The two-sample KS statistic, as the integer ``D·n·m``.

    Returned as an integer because that is exactly what it is: both ECDFs
    step by ``1/n`` and ``1/m``, so their gap at any threshold is
    ``|i·m − j·n| / (n·m)`` for integer ``i`` and ``j``, and the maximum gap
    is ``K / (n·m)`` for an integer ``K``.  Carrying ``K`` rather than its
    float quotient is what lets the exact estimator compare against the
    lattice without a tolerance, and it is the reason the statistic is
    tie-correct: the walk steps both ECDFs past every tied value together,
    which is the standard two-sample definition.

    A two-pointer merge over the two sorted samples, so the cost is linear.
    """
    n = len(null_scores)
    m = len(real_scores)
    i = j = 0
    best = 0
    while i < n or j < m:
        # The next value at which the pair of ECDFs is evaluated: the smaller
        # of the two heads, and every tied copy of it on either side.
        if j >= m or (i < n and null_scores[i] <= real_scores[j]):
            value = null_scores[i]
        else:
            value = real_scores[j]
        while i < n and null_scores[i] == value:
            i += 1
        while j < m and real_scores[j] == value:
            j += 1
        gap = abs(i * m - j * n)
        if gap > best:
            best = gap
    return best


def _exact_pvalue(null_count: int, real_count: int, scaled_gap: int) -> float:
    """``P(D ≥ scaled_gap/(n·m))``, by exact enumeration of the lattice paths.

    The two-sample KS statistic's null distribution has a closed form only
    for small samples, and this is it: draw an interleaving of ``n`` null
    and ``m`` real scores uniformly from the ``C(n+m, n)`` possibilities,
    walk the ``(i, j)`` grid it traces, and ask how often the walk's
    ``|i·m − j·n|`` ever *reaches* ``scaled_gap``.  The complement — the
    walks whose every prefix keeps the gap strictly below it — is a
    dynamic program with the recurrence ``ways(i, j) = ways(i−1, j) +
    ways(i, j−1)``, banded to the ``|i·m − j·n| ≤ scaled_gap − 1`` window
    because every point outside it is already a failure.

    The counts are exact integers, so the only floating-point operation is
    the final division; the form ``(total − reached)/total`` rather than
    ``1 − reached/total`` avoids the cancellation that would otherwise
    erase a genuinely tiny p-value into a hard zero.

    A row with no admissible point admits no path at all — the walk visits
    some point at every ``i`` — so it returns 1 either for that reason or
    because the grid is empty of paths, and both are the same answer: the
    observed gap is not reached more often than not.
    """
    if scaled_gap <= 0:
        # A zero statistic: the two ECDFs coincide, so the observed gap is
        # reached by nothing.  Not reachable from a real sample unless every
        # score on both sides is equal, which the disjointness check leaves
        # possible and this branch keeps honest.
        return 1.0
    total = comb(null_count + real_count, null_count)
    limit = scaled_gap - 1
    n, m = null_count, real_count
    previous: dict[int, int] = {}
    for i in range(n + 1):
        low = -((limit - i * m) // n)  # ceil((i·m − limit)/n)
        high = (i * m + limit) // n
        if low < 0:
            low = 0
        if high > m:
            high = m
        if low > high:
            return 1.0
        current: dict[int, int] = {}
        for j in range(low, high + 1):
            if i == 0 and j == 0:
                ways = 1
            else:
                ways = 0
                if i > 0:
                    ways += previous.get(j, 0)
                if j > 0:
                    ways += current.get(j - 1, 0)
            if ways:
                current[j] = ways
        previous = current
    reached = previous.get(m, 0)
    return (total - reached) / total


def _kolmogorov_series(lam: float) -> float:
    """``Q(λ)``, the Kolmogorov distribution — Numerical Recipes' ``probks``.

    ``Q(λ) = 2·Σⱼ(−1)^(j−1)·exp(−2j²λ²)``, summed term for term as the
    published algorithm does, including its alternating ``2, −2`` factor and
    its two relative convergence tolerances.  Mirroring the published loop
    rather than restating it algebraically is deliberate: this is a pinned
    numerical recipe whose stored outputs a reproduction has to match, and a
    "cleaner" rearrangement would silently shift the last digits of every
    p-value ever persisted.

    ``λ ≤ 0`` answers 1 — the two distributions are indistinguishable — and
    a series that fails to converge within :data:`KS_SERIES_TERMS` answers 1
    as well, which is the same statement and the value the published
    fallback returns.
    """
    if lam <= 0.0:
        return 1.0
    a2 = -2.0 * lam * lam
    factor = 2.0
    total = 0.0
    previous = 0.0
    for j in range(1, KS_SERIES_TERMS + 1):
        term = factor * math.exp(a2 * j * j)
        total += term
        if abs(term) <= _SERIES_EPS1 * previous or abs(term) <= _SERIES_EPS2 * total:
            return min(1.0, max(0.0, total))
        factor = -factor
        previous = abs(term)
    return 1.0


def two_sample_statistic(
    null_scores: Mapping[Any, Any] | Iterable[float],
    real_scores: Mapping[Any, Any] | Iterable[float],
) -> float:
    """The two-sided two-sample KS statistic ``D``, alone.

    Exposed because ``D`` is the half of §7.4's result an operator can act
    on: it says *how far apart* the two score distributions are, in the
    same units as the scores themselves, and it is what the architecture's
    advice to "investigate the block length and permutation scheme" is
    actually about.  The p-value says whether that distance is surprising;
    this says how large it is.

    The samples are validated exactly as :func:`ks_two_sample` validates
    them — including the disjointness check when both are mappings — so a
    caller cannot reach a statistic over a sample the full test would have
    refused.
    """
    return _statistic_of(null_scores, real_scores)[0]


def _statistic_of(
    null_scores: Mapping[Any, Any] | Iterable[float],
    real_scores: Mapping[Any, Any] | Iterable[float],
) -> tuple[float, int, int, int]:
    """The statistic and the three integers behind it: ``(D, n, m, K)``.

    The one place both spellings funnel through, so the validation, the
    ordered samples and the integer gap are computed once and the public
    functions cannot drift apart on how a sample is read.
    """
    if isinstance(null_scores, Mapping) and isinstance(real_scores, Mapping):
        _require_disjoint(null_scores, real_scores)
    null_ordered = _validated_scores(null_scores, side="null")
    real_ordered = _validated_scores(real_scores, side="real")
    n = len(null_ordered)
    m = len(real_ordered)
    scaled = _max_scaled_gap(null_ordered, real_ordered)
    return scaled / (n * m), n, m, scaled


@dataclass(frozen=True)
class KolmogorovSmirnov:
    """§7.4's result: the statistic, its p-value, and what the test saw.

    Four fields, and the fourth — :attr:`method` — is the one a reader of a
    *stored* number needs: it says which estimator produced the p-value, so
    a value computed by the large-sample series is never mistaken for an
    exact one.  The two sample sizes are carried for the same reason §9.1's
    provenance triple is carried on a charge: a p-value is only interpretable
    beside the number of observations it was computed over, and a record that
    stored the p-value alone would leave "0.31 from 400 nodes" and "0.31
    from 4" indistinguishable.

    Frozen, and deliberately **without** the scores and without a single
    node id — see the module docstring.  This value crosses into the store
    and, through the store, into a row an operator reads; the sample sizes
    are a statement about the campaign that leaks nothing, and a score list
    keyed by node would be the label partition in disguise.  Validated in
    :meth:`__post_init__` rather than only where it is built, because a
    record reconstructed from a stored row passes no factory: a row whose
    p-value is not a probability, or whose method is not one of the two this
    member computes, fails to reconstruct rather than loading as a
    plausible-looking lie.
    """

    #: The two-sided two-sample KS statistic ``D``, in ``[0, 1]``.
    statistic: float
    #: Its p-value — the number feature 123 persists and feature 124 voids on.
    pvalue: float
    #: How many nodes were on the null side.
    null_count: int
    #: How many nodes were on the real side.
    real_count: int
    #: Which estimator produced :attr:`pvalue` — :data:`KS_EXACT` or
    #: :data:`KS_ASYMPTOTIC`.
    method: str

    def __post_init__(self) -> None:
        for name, count in (("null_count", self.null_count), ("real_count", self.real_count)):
            if isinstance(count, bool) or not isinstance(count, int) or count < 1:
                raise KsTestError(
                    f"{name} must be a positive integer, got {count!r}; §7.4's "
                    "guard compares two non-empty populations of scores"
                )
        for name, value in (("statistic", self.statistic), ("pvalue", self.pvalue)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise KsTestError(
                    f"{name} must be a real number, got {value!r} "
                    f"({type(value).__name__})"
                )
            number = float(value)
            if not math.isfinite(number):
                raise KsTestError(f"{name} must be finite, got {number!r}")
            if not 0.0 <= number <= 1.0:
                raise KsTestError(
                    f"{name} must lie in [0, 1], got {number!r}; a KS "
                    "statistic and a p-value are both probabilities, and a "
                    "value outside that range would enter feature 124's "
                    "`p < 0.05` comparison as a number no test produced"
                )
        if self.method not in (KS_EXACT, KS_ASYMPTOTIC):
            raise KsTestError(
                f"method must be {KS_EXACT!r} or {KS_ASYMPTOTIC!r}, got "
                f"{self.method!r}; the estimator that produced a stored "
                "p-value is part of what the number means"
            )

    @property
    def observations(self) -> int:
        """The total number of in-sample scores the test was computed over."""
        return self.null_count + self.real_count

    @property
    def exact(self) -> bool:
        """Whether the p-value came from the exact lattice count."""
        return self.method == KS_EXACT

    def to_payload(self) -> dict[str, Any]:
        """The result as a plain mapping, for a store or a log record.

        The field names are the record's own — a stored row and a rendered
        mapping name the same things the same way, so an operator reading a
        guard row and an operator reading a log line are reading one
        vocabulary.  Floats render as their repr, which round-trips exactly,
        so the store's re-derivation is a bitwise comparison rather than a
        tolerant one.
        """
        return {
            "statistic": self.statistic,
            "pvalue": self.pvalue,
            "null_count": self.null_count,
            "real_count": self.real_count,
            "method": self.method,
        }


def ks_two_sample(
    null_scores: Mapping[Any, Any] | Iterable[float],
    real_scores: Mapping[Any, Any] | Iterable[float],
) -> KolmogorovSmirnov:
    """§7.4's test: both samples in, the statistic and p-value out.

    ``null_scores`` is the in-sample scores of the campaign's planted null
    nodes and ``real_scores`` those of its real nodes, each a mapping of
    node id to score (the form that gets the disjointness check) or a plain
    iterable of scores.  The estimator is chosen by
    :data:`KS_EXACT_CELLS` and :data:`KS_ASYMPTOTIC_FLOOR` and named on the
    result; see the module docstring for what each one is and where each one
    is accurate.

    Refuses — with :class:`~nulloracle.errors.KsTestError`, never with a
    quietly computed number — a sample that is empty, smaller than
    :data:`KS_MIN_SAMPLE` on either side, keyed by something that is not a
    node id, holding a score that is not a finite real, or naming a node on
    both sides.  The refusals are the feature: §7.4's p-value is what voids
    a campaign, halts dreaming and removes the campaign from the replay
    pool, and a number produced from a sample that never existed would do
    all three for the wrong reason.
    """
    statistic, n, m, scaled = _statistic_of(null_scores, real_scores)
    cells = n * m
    if cells <= KS_EXACT_CELLS:
        return KolmogorovSmirnov(
            statistic=statistic,
            pvalue=_exact_pvalue(n, m, scaled),
            null_count=n,
            real_count=m,
            method=KS_EXACT,
        )
    if n < KS_ASYMPTOTIC_FLOOR or m < KS_ASYMPTOTIC_FLOOR:
        raise KsTestError(
            f"the samples hold {n} null and {m} real scores: too many to "
            f"enumerate exactly ({cells} lattice cells against this module's "
            f"limit of {KS_EXACT_CELLS}) and too lopsided for the large-sample "
            f"series, which needs at least {KS_ASYMPTOTIC_FLOOR} per side. No "
            "estimator this member carries is valid for this shape of sample, "
            "so no p-value is reported rather than one from a limit the "
            "sample does not satisfy"
        )
    return KolmogorovSmirnov(
        statistic=statistic,
        pvalue=_kolmogorov_series(math.sqrt(n * m / (n + m)) * statistic),
        null_count=n,
        real_count=m,
        method=KS_ASYMPTOTIC,
    )


def ks_pvalue(
    null_scores: Mapping[Any, Any] | Iterable[float],
    real_scores: Mapping[Any, Any] | Iterable[float],
) -> float:
    """The p-value alone — the number feature 123's sentence names.

    A thin spelling of :func:`ks_two_sample` for the caller that wants only
    the figure, kept so that the feature's sentence (*"the p-value of a
    two-sample Kolmogorov-Smirnov test"*) has a function of the same shape.
    A caller that is *persisting* the number should take the whole
    :class:`KolmogorovSmirnov` instead: the store records the statistic, the
    sample sizes and the estimator beside it, and a p-value stored without
    them is a number nobody can check.
    """
    return ks_two_sample(null_scores, real_scores).pvalue
