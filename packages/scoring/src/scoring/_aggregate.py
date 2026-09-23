"""Feature 263, the cross-world aggregation — the blend of the stratum
mean and the stratum minimum, over the λ band prd §7.2 states.

app_spec.xml, "Objective Scoring & CVaR Aggregation", feature 263: *System
aggregates across worlds as a blend of the stratum mean and the stratum
minimum, which returns a score with lambda between 0.5 and 0.7* — on the
formula docs/alpha-engine-prd.md §7.2 states (line 336) and
docs/nullius-tech-architecture.md §10.3 restates (line 503), the same
sentence twice:

    V^m = (1 − λ) · mean_g( V_g^m )  +  λ · min_g( V_g^m )    λ ∈ [0.5, 0.7]

where ``g`` indexes regime strata.  The section's own verdict on the two
lines is *"Two lines of code, larger impact than anything else in this
section"*, and the paragraph above the formula is the reason: the paper
averages — ``V^m = (1/t) Σ V_i^m`` — which *"is correct only if worlds
are exchangeable.  Market regimes are not exchangeable."*  A policy that
is brilliant in trending worlds and catastrophic in chop averages to
"fine" and then blows up; the blend is the two-line repair, and it is
CVaR-shaped on purpose — λ is the weight on the worst stratum, the tail
a plain mean averages away.

**The blend is taken over strata, and the strata weigh equally — not by
world count.**  :func:`aggregate_objective` is handed the worlds already
grouped: a mapping of stratum name to that stratum's world scores.  Each
stratum's figure ``V_g^m`` is the mean over the worlds the stratum holds
(the paper's own verb, kept where its assumption holds — within a
stratum, worlds *are* the exchangeable thing; it is across regimes they
are not), and the blend then averages the *figures*: ``mean_g`` is the
unweighted mean over strata and ``min_g`` the minimum over strata, so a
stratum with three worlds and a stratum with thirty weigh the same.  That
is the arithmetic the formula spells and the deliberate half of it: a
mean over worlds weights a regime by how many worlds happen to be stored
in it, and a chop pool twice the size of the trend pool would quietly
halve the chop regime's voice exactly when the blend exists to amplify
it.  The plain mean over worlds — unstratified, world-count-weighted —
is the aggregation feature 264 exists to reject, and an unstratified
collection of world scores is refused here for the same reason, from
this feature's own side of the seam.

**The λ band is the feature's own sentence, and both edges are load
bearing.**  :data:`LAMBDA_FLOOR` and :data:`LAMBDA_CEILING` publish the
band — ``[0.5, 0.7]``, inclusive, exactly as prd §7.2 and docs §10.3
state it — and a λ outside it is refused, because each side of the band
drifts into a different unspecified aggregation: below the floor the
blend slides toward the plain mean (at λ = 0 it *is* the plain mean over
strata, the shape feature 264 rejects), and above the ceiling it
collapses onto the single worst stratum (at λ = 1 it is a pure minimum,
one regime standing for the whole pool).  The band keeps the answer a
*blend*: always at least half the stratum mean, never more than
seven-tenths the worst stratum.  Because the two documents state a band
and not a point, :data:`LAMBDA_DEFAULT` states the midpoint — 0.6 — as a
named default rather than a hidden constant, the same stance feature
228's :data:`PRIOR_STRENGTH` takes for its unstated number: a
parameterization the dreaming loop's own tuning is expected to replace,
refused nowhere inside the band.

**The answer is a convex combination, and cannot flatter.**  For any λ
in the band the score lies between the stratum minimum and the stratum
mean — ``min_g(V_g) ≤ V^m ≤ mean_g(V_g)`` — because λ ∈ [0, 1] makes the
blend a convex combination of the two terms and the minimum of a set is
never above its mean.  Two consequences worth stating as the law's own
guarantees: no λ in the band can rank a policy above its strata-average
figure (the blend cannot flatter), and none can rank it below its worst
stratum's figure (the tail term cannot bury a policy beneath the regime
that actually earned the bottom).  Where the stratum figures all agree,
every λ answers that figure — the blend is then the mean, and only then.

**The seam is duck-typed, and validates what it reads.**  The worlds a
stratum aggregates are world scores — feature 256's
:class:`~scoring.WorldScore`, read by the two attributes the blend needs
(``world_id`` for the identity checks below, ``score`` for every figure)
rather than by ``isinstance``, because the module loader imports this
member under a synthetic name and re-executes it, so a score this process
composed may be a second ``WorldScore`` class object and a type check
would refuse the very objects composition produces — the same stance the
objective's pick seam and the family conditional's carrier take.  What
the seam *reads* it validates: a carrier exposing no readable
``world_id`` and finite ``score`` is refused naming what was carried, a
NaN or ±∞ ``score`` is refused for the reason the objective refuses one
(the miss's ``−∞`` is feature 222's and never carries a pick, so no
aggregation may counterfeit it), and the identity checks the blend's
arithmetic depends on are enforced from this side:

* **one world, one stratum, once.**  A world id repeated inside a
  stratum double-counts that world in the stratum's own mean, and a
  world id carried by two strata double-counts it in the mean over
  strata — the strata of one aggregation partition the worlds (each
  stored world is assigned one stratum, the labeler's law), and both
  repeats are refused naming the strata that saw the world.
* **a stratum that holds no worlds is refused, not zeroed.**  A stratum
  present in the mapping with no world scores has no figure to lend the
  blend, and a fabricated 0.0 would be worse than a hole: read as a
  *measured* catastrophic regime, it would drag ``min_g`` onto a number
  nobody measured.  The honest division of labour is the other way
  round — the coverage ledger (feature 283) names the stratum, feature
  286's ``empty_stratum`` warning reports the hole on the ledger, and
  *this* seam refuses to aggregate over a stratum it was not given
  worlds for.  An aggregation over no strata at all is the same refusal
  one level up: ``min_g`` over an empty set is undefined, and no neutral
  score is invented for an ask with nothing to aggregate.

**Deterministic and pure, to the bit.**  No store, no clock, no
environment: the same strata answer the same score regardless of the
mapping's iteration order or the order of worlds inside a stratum — the
figures are summed with :func:`math.fsum` (exactly rounded, so
order-independent in its result) and the strata are read in sorted-name
order, which also fixes the one place the arithmetic is order-sensitive:
a tie on the minimum names the lexicographically first stratum as
:attr:`AggregatedObjective.worst_stratum`, so the same figures always
name the same worst regime.  That is the replay's determinism law
(docs §10.1) held one level up from the number 256 made deterministic —
the dreaming loop's argmax over candidates (feature 274) ranks on this
scalar, and a ranking that reordered under a dict's whim would be a
selection that changed with nothing.

**What this law deliberately does not do.**  It does not *persist* — the
``policy_revision.aggregate_score`` column is feature 274's, written from
this value when the dreaming loop selects its winner.  It does not name
regimes — a stratum here is any non-empty name, because *which* strata
exist and the refusal of a plain mean across them is feature 264's law
over this seam, and restating its regime vocabulary here would be a
second spelling of a law one feature later.  It does not *calibrate* —
the figures that feed a stratum's worlds are the β-terms' business
(features 257 through 262, through :meth:`WorldScore.adjusted`), and the
blend takes the scores as they were earned.  And it does not *thin* —
whether the pool holds enough worlds to dream on at all is feature
275's precondition, read from the pool, not from this scalar.

Stdlib only, and import-cheap: :mod:`math`, :mod:`numbers`, the
:mod:`collections.abc` and :mod:`types` helpers, :mod:`dataclasses`, and
the member's own error — no third-party import at module scope, so the
factory's scan (which imports this package to fire its ``@register``
builder) pays nothing for the law.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from numbers import Real
from types import MappingProxyType

from .errors import AggregationError

__all__ = [
    "LAMBDA_CEILING",
    "LAMBDA_DEFAULT",
    "LAMBDA_FLOOR",
    "AggregatedObjective",
    "aggregate_objective",
]

#: The floor of the blend's λ band — the least weight the worst stratum
#: may carry, prd §7.2's and docs §10.3's ``λ ∈ [0.5, 0.7]`` stated as a
#: named constant rather than hidden in a comparison.  At the floor the
#: blend is half mean and half minimum, the most mean-leaning posture the
#: documents allow; one notch below it and the answer starts drifting
#: toward the plain mean feature 264 exists to reject.
LAMBDA_FLOOR: float = 0.5

#: The ceiling of the blend's λ band — the most weight the worst stratum
#: may carry.  At the ceiling the blend is seven-tenths the minimum and
#: three-tenths the mean; one notch above it and the answer starts
#: collapsing onto the single worst stratum, a pure minimum nobody
#: specified — one regime standing for the whole pool.
LAMBDA_CEILING: float = 0.7

#: The λ a caller that names none gets — the band's midpoint, 0.6.  Both
#: documents state a band and not a point, so the default is a stated
#: parameterization rather than a hidden constant (the stance feature
#: 228's ``PRIOR_STRENGTH`` takes for its own unstated number): the
#: dreaming loop's offline tuning is expected to sweep the band and pick
#: per cycle, and every value inside ``[LAMBDA_FLOOR, LAMBDA_CEILING]``
#: composes identically.
LAMBDA_DEFAULT: float = 0.6


@dataclass(frozen=True)
class AggregatedObjective:
    """The aggregation's answer — the blended score, the λ that blended
    it, and the stratum figures it was taken over.

    A frozen value, for the same reason :class:`~scoring.WorldScore` is
    frozen one feature earlier: this scalar is what the dreaming loop's
    argmax ranks candidates on (feature 274), and a ranking that moved
    beneath it would be a selection that changed with nothing.  The
    fields carry the blend's own bookkeeping, so the answer is auditable
    without recomputing it:

    * :attr:`score` — ``V^m``, the blend: ``(1 − λ) · stratum_mean +
      λ · stratum_minimum``.  Always between the two terms (a convex
      combination over a λ in the band), so it can neither flatter a
      policy above its strata-average figure nor bury it below its
      worst stratum's.
    * :attr:`lam` — the λ the blend used, in the band by construction.
      The feature's own second clause (*"returns a score with lambda
      between 0.5 and 0.7"*) is a fact about the value, not only about
      the ask, so the score carries the knob it was blended under.
    * :attr:`stratum_mean` and :attr:`stratum_minimum` — the two terms
      the sentence names, ``mean_g(V_g^m)`` and ``min_g(V_g^m)``.
    * :attr:`worst_stratum` — the stratum that earned the minimum: the
      regime to look at when the score disappoints, the operational
      half of *"catastrophic in chop"* (deterministic under ties — the
      lexicographically first stratum among equals).
    * :attr:`stratum_means` — each stratum's own figure, read-only and
      never aliased to the mapping the caller authored, so a caller
      that keeps writing its dict cannot move an aggregate already
      answered.
    * :attr:`world_count` — how many worlds were aggregated — the
      *"across worlds"* of the sentence made countable beside the
      blend.

    Every field is validated at construction, the stance the world score
    takes one feature earlier; the terms additionally cannot disagree
    with the trail they summarize (:attr:`stratum_minimum` must be the
    minimum of :attr:`stratum_means`, and :attr:`worst_stratum` one of
    its keys), because a value that let them disagree could hide which
    regime was worst.
    """

    #: The blended aggregate ``V^m`` — the scalar the dreaming loop's
    #: argmax ranks candidates on.
    score: float

    #: The λ the blend used — a finite real in
    #: ``[LAMBDA_FLOOR, LAMBDA_CEILING]``.
    lam: float

    #: The blend's first term, ``mean_g(V_g^m)`` — the unweighted mean
    #: of the stratum figures.
    stratum_mean: float

    #: The blend's second term, ``min_g(V_g^m)`` — the worst stratum's
    #: figure, the tail a plain mean averages away.
    stratum_minimum: float

    #: The stratum that earned :attr:`stratum_minimum` — one key of
    #: :attr:`stratum_means`, deterministic under ties.
    worst_stratum: str

    #: Each stratum's figure — the mean over that stratum's worlds —
    #: read-only, never aliased to the caller's mapping.
    stratum_means: Mapping[str, float]

    #: How many worlds the aggregate was taken over — every stratum's
    #: worlds, summed.
    world_count: int

    def __post_init__(self) -> None:
        # λ first: the knob is the caller's, and a value outside the band
        # invalidates every figure below it.  The band check is the value's
        # own law as much as the verb's — the sentence's second clause is a
        # fact about the score returned.
        object.__setattr__(self, "lam", _require_lambda(self.lam))
        # The three scalars are finite reals, narrowed like the world
        # score's — the same −∞ argument, one level up: no aggregate may
        # counterfeit the miss's number.
        object.__setattr__(
            self, "score", _finite(self.score, "score", "the blended aggregate")
        )
        object.__setattr__(
            self,
            "stratum_mean",
            _finite(self.stratum_mean, "stratum_mean", "the blend's first term"),
        )
        object.__setattr__(
            self,
            "stratum_minimum",
            _finite(self.stratum_minimum, "stratum_minimum", "the blend's second term"),
        )
        # The stratum figures: a non-empty mapping of names to finite
        # reals, copied into a read-only view — never the caller's dict,
        # however the value was built.
        if not isinstance(self.stratum_means, Mapping) or not self.stratum_means:
            raise AggregationError(
                f"an aggregated objective carries the figures of at least "
                f"one stratum, and these are not a non-empty mapping of "
                f"stratum names to figures: got {self.stratum_means!r} "
                f"({type(self.stratum_means).__name__}). The figures are "
                f"the audit trail the blend was taken over — the stratum "
                f"that earned the minimum is named among them — so a value "
                f"that carries none cannot say what it aggregated "
                f"(feature 263, prd §7.2)"
            )
        figures: dict[str, float] = {}
        for name, figure in self.stratum_means.items():
            if isinstance(name, bool) or not isinstance(name, str) or not name.strip():
                raise AggregationError(
                    f"a stratum figure must be keyed by a stratum named in "
                    f"non-empty text, got {name!r} ({type(name).__name__}): "
                    f"the worst stratum is reported by name, and a stratum "
                    f"that cannot be named cannot be reported (feature 263)"
                )
            figures[name] = _finite(
                figure, f"the {name!r} stratum's figure", "a stratum's mean"
            )
        object.__setattr__(self, "stratum_means", MappingProxyType(figures))
        # The minimum is the figures' minimum, exactly — the value's terms
        # cannot disagree with the trail they are summarized from, or the
        # audit the mapping exists for is a second story beside the score.
        minimum = min(figures.values())
        if self.stratum_minimum != minimum:
            raise AggregationError(
                f"an aggregated objective's stratum_minimum must be the "
                f"minimum of its stratum figures ({minimum!r} over "
                f"{sorted(figures)}), got {self.stratum_minimum!r}: the "
                f"terms and the trail they summarize are one answer, and a "
                f"value that lets them disagree is a value that can hide "
                f"which regime was worst (feature 263, prd §7.2)"
            )
        # The named worst stratum is one of the figures — the name an
        # operator is sent to look at must name a stratum the aggregate
        # actually holds.
        worst = _require_name(
            self.worst_stratum, "worst_stratum", "the stratum that earned the minimum"
        )
        if worst not in figures:
            raise AggregationError(
                f"an aggregated objective's worst_stratum must be one of "
                f"its stratum figures' names ({sorted(figures)}), got "
                f"{worst!r}: the worst stratum is where an operator looks "
                f"when the score disappoints, and a name the aggregate does "
                f"not carry sends them nowhere (feature 263)"
            )
        # The world count is a count — a positive integer, and not a bool
        # wearing one.
        if isinstance(self.world_count, bool) or not isinstance(self.world_count, int):
            raise AggregationError(
                f"an aggregated objective's world_count must be an integer "
                f"count of the worlds it aggregated, got {self.world_count!r} "
                f"({type(self.world_count).__name__}): the count is the "
                f"*across worlds* of the feature's own sentence, stated "
                f"beside the blend (feature 263)"
            )
        if self.world_count < 1:
            raise AggregationError(
                f"an aggregated objective's world_count must count at least "
                f"one world, got {self.world_count!r}: an aggregate over no "
                f"worlds is not a neutral score but an ask with nothing to "
                f"aggregate — refused, never zeroed (feature 263, prd §7.2)"
            )


def aggregate_objective(
    strata: Mapping[str, Iterable[object]],
    *,
    lam: float = LAMBDA_DEFAULT,
) -> AggregatedObjective:
    """Aggregate the world scores across strata — prd §7.2's blend of the
    stratum mean and the stratum minimum.

    The feature's verb.  ``strata`` is the worlds already grouped by the
    axis the blend is taken over: a mapping of stratum name to that
    stratum's world scores (an iterable of world-score values, or a
    mapping of world id to score read for its values).  Each world score
    is feature 256's :class:`~scoring.WorldScore` — read duck-typed, by
    the ``world_id`` and finite ``score`` the blend needs, because the
    module loader's synthetic-name re-execution means an ``isinstance``
    would refuse the very objects composition produces.  ``lam`` —
    keyword-only, defaulting to :data:`LAMBDA_DEFAULT` — is the blend's
    weight on the stratum minimum, and must lie in
    ``[LAMBDA_FLOOR, LAMBDA_CEILING]``.

    The arithmetic, in the two steps the formula spells: each stratum's
    figure is the mean of its worlds' scores (the paper's verb, kept
    where its exchangeability assumption holds), and the answer is
    ``(1 − λ) · mean of the figures + λ · minimum of the figures`` — the
    strata weighing equally, never by world count.

    Answers a frozen :class:`AggregatedObjective`.  Refuses, with
    :class:`~scoring.AggregationError` and nothing partial, an ask that
    cannot be blended:

    * a ``strata`` that is not a mapping — a flat collection of world
      scores is the plain mean over regimes, the aggregation feature 264
      exists to reject, and it cannot say which worlds share a stratum;
    * no strata at all, or a stratum that holds no worlds — ``min_g``
      over nothing is undefined, and no neutral figure is invented for a
      stratum nobody measured (name it in the coverage ledger and let
      feature 286's ``empty_stratum`` warning report the hole);
    * a stratum name that is not a name, or a carrier that is not a
      world score (no readable ``world_id``, or a ``score`` that is not
      a finite real);
    * a world carried twice by one stratum or by two — the strata of one
      aggregation partition the worlds;
    * a λ that is not a finite real in the band.

    Deterministic and pure: no store, no clock, no environment, and the
    same strata answer the same score to the last bit regardless of the
    mapping's iteration order or the order of worlds inside a stratum
    (:func:`math.fsum` over sorted strata; a tie on the minimum names the
    lexicographically first stratum) — the determinism law the per-world
    score states (docs §10.1), held one level up at the number the
    dreaming loop's argmax ranks on.
    """
    figures, world_count = _stratum_figures(strata)
    weight = _require_lambda(lam)
    names = sorted(figures)
    stratum_mean = math.fsum(figures[name] for name in names) / len(names)
    worst_stratum = min(names, key=figures.__getitem__)
    stratum_minimum = figures[worst_stratum]
    score = (1.0 - weight) * stratum_mean + weight * stratum_minimum
    return AggregatedObjective(
        score=score,
        lam=weight,
        stratum_mean=stratum_mean,
        stratum_minimum=stratum_minimum,
        worst_stratum=worst_stratum,
        stratum_means=figures,
        world_count=world_count,
    )


# -- the seam's private vocabulary --------------------------------------------


def _finite(value: object, field: str, what: str) -> float:
    """Narrow a real to a finite ``float``, refusing NaN, ±inf and ``bool``.

    The objective's own stance (``_objective._require_finite``) restated
    for the aggregation's scalars: a ``bool`` is not a reading, ``int``
    is accepted and narrowed, and a non-finite value is refused because
    the only ``−∞`` in the objective's vocabulary is the non-committing
    miss, which feature 222 owns and which never carries a pick — no
    aggregate may counterfeit it.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise AggregationError(
            f"{field} must be {what} as a real number, got {value!r} "
            f"({type(value).__name__}): the aggregate feeds the dreaming "
            f"loop's argmax and the revision store's REAL column, and a "
            f"value that is not a real has no place in either (feature 263)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise AggregationError(
            f"{field} must be finite, got {narrowed!r}: a NaN compares false "
            f"against every score and would silently drop out of the argmax, "
            f"and the only −∞ the objective's vocabulary holds is the "
            f"non-committing miss, which feature 222 owns "
            f"(NON_COMMITTING_SCORE) and which never carries a pick, so no "
            f"aggregate may counterfeit it (feature 263)"
        )
    return narrowed


def _require_name(value: object, field: str, what: str) -> str:
    """Refuse a value that is not a name, answering it unchanged when it is.

    The objective's own spelling of the check, restated for the
    aggregation's names: a ``bool`` is refused before the string check,
    and a blank names nothing — and a stratum that cannot be named cannot
    be reported, warned empty, or weighted.
    """
    if isinstance(value, bool) or not isinstance(value, str) or not value.strip():
        raise AggregationError(
            f"{field} must name {what} by a non-empty string, got {value!r} "
            f"({type(value).__name__}): a name that names nothing has no "
            f"stratum to carry (feature 263, docs §10.3)"
        )
    return value


def _require_lambda(value: object) -> float:
    """Narrow the blend's λ — a finite real in the band, or refuse it.

    The band is prd §7.2's own sentence (``λ ∈ [0.5, 0.7]``, restated by
    docs §10.3), inclusive at both edges, and the refusal names the drift
    each side falls into: below the floor the blend slides toward the
    plain mean feature 264 exists to reject, above the ceiling it
    collapses onto the single worst stratum.  A ``bool`` is refused
    before the real check — a flag is not a weight.
    """
    weight = _finite(value, "lam", "the blend's weight on the stratum minimum")
    if not LAMBDA_FLOOR <= weight <= LAMBDA_CEILING:
        raise AggregationError(
            f"lam must lie in the band [{LAMBDA_FLOOR}, {LAMBDA_CEILING}] — "
            f"prd §7.2's λ, restated by docs §10.3 — got {weight!r}: below "
            f"{LAMBDA_FLOOR} the blend drifts toward the plain mean over "
            f"worlds (the aggregation feature 264 exists to reject: regimes "
            f"would weigh by world count, not as regimes), and above "
            f"{LAMBDA_CEILING} it collapses onto the single worst stratum "
            f"(a pure minimum nobody specified — one regime standing for "
            f"the whole pool). The band keeps the answer a blend: always "
            f"at least half the stratum mean, never more than "
            f"{LAMBDA_CEILING} the worst stratum (feature 263, prd §7.2)"
        )
    return weight


def _stratum_figures(strata: object) -> tuple[dict[str, float], int]:
    """Read the strata — each stratum's figure, and the world count.

    One pass, name by name in the caller's own order (the answer is
    order-independent downstream: the figures are summed with
    :func:`math.fsum` and read sorted).  A stratum's worlds may arrive as
    an iterable of world scores or as a mapping of world id to score
    (read for its values — iterating a mapping would read its keys,
    which are names, not scores).  Every world is read duck-typed and
    validated: a readable ``world_id`` and a finite ``score``, unique
    within its stratum and across the strata — the strata of one
    aggregation partition the worlds, so a world seen twice is a world
    double-counted in a mean.
    """
    if not isinstance(strata, Mapping):
        raise AggregationError(
            f"the aggregated objective stratifies the worlds it is handed — "
            f"a mapping of stratum name to that stratum's world scores — "
            f"and this ask carried {type(strata).__name__}: the strata are "
            f"the axis the blend is taken over (prd §7.2: market regimes "
            f"are not exchangeable), so a flat collection of world scores "
            f"has no aggregation to compute — that is the plain mean "
            f"feature 264 exists to reject, and it cannot say which worlds "
            f"share a regime (feature 263, docs §10.3)"
        )
    if not strata:
        raise AggregationError(
            "an aggregation over no strata has no stratum mean to blend "
            "and no stratum minimum to fear — min_g over an empty set is "
            "undefined, and no neutral score is invented for an ask with "
            "nothing to aggregate: a fabricated figure would enter the "
            "dreaming loop's argmax as though a pool had been measured "
            "(feature 263, prd §7.2)"
        )
    figures: dict[str, float] = {}
    seen: dict[str, str] = {}
    world_count = 0
    for name, worlds in strata.items():
        stratum = _require_name(
            name,
            "a stratum of the aggregation",
            "one of the strata the blend is taken over",
        )
        readings: list[float] = []
        for world in _stratum_worlds(worlds, stratum):
            world_id = _world_identity(world, stratum)
            if (first := seen.get(world_id)) is not None:
                where = (
                    f"twice among the worlds of stratum {stratum!r}"
                    if first == stratum
                    else f"in both stratum {first!r} and stratum {stratum!r}"
                )
                raise AggregationError(
                    f"world {world_id!r} is carried {where}: the strata of "
                    f"one aggregation partition the worlds — each stored "
                    f"world is assigned one stratum by the labeler, and one "
                    f"score is earned per world — so a world counted twice "
                    f"double-counts it in a mean it already belongs to "
                    f"(feature 263, prd §7.2)"
                )
            seen[world_id] = stratum
            readings.append(_world_score(world, stratum, world_id))
        # The empty stratum is refused rather than zeroed: a stratum with
        # no worlds has no figure to lend the blend, and a fabricated 0.0
        # would be read as a *measured* catastrophic regime, dragging
        # min_g onto a number nobody measured.  The coverage ledger names
        # the hole (feature 283) and feature 286's empty_stratum warning
        # reports it; this seam refuses to invent the figure.
        if not readings:
            raise AggregationError(
                f"stratum {stratum!r} holds no world scores, and a stratum "
                f"with no worlds has no mean to lend the blend — a 0.0 "
                f"invented here would be read as a measured catastrophic "
                f"regime and would drag the blend's minimum onto a number "
                f"nobody measured. Name the stratum in the coverage ledger "
                f"and let the empty_stratum warning report the hole "
                f"(feature 286); the aggregation refuses to blend a stratum "
                f"it was not given worlds for (feature 263, prd §7.2)"
            )
        figures[stratum] = math.fsum(readings) / len(readings)
        world_count += len(readings)
    return figures, world_count


def _stratum_worlds(worlds: object, stratum: str) -> Iterable[object]:
    """A stratum's worlds, as an iterable — or a refusal naming the shape.

    An iterable of world scores is the spelling the verb documents; a
    mapping of world id to score is accepted and read for its values,
    because iterating a mapping would read its keys — names, not scores —
    and a seam that refused a right shape spelled the other right way
    would be harder than the law it carries.  A bare string is refused
    as itself (it would otherwise be read as an iterable of characters,
    a message about the wrong repair entirely); so is anything not
    iterable, a single world score included — one world score is one
    world, and the stratum's worlds arrive together.
    """
    if isinstance(worlds, Mapping):
        return worlds.values()
    if isinstance(worlds, (str, bytes)):
        raise AggregationError(
            f"the worlds of stratum {stratum!r} must arrive as an iterable "
            f"of world scores (or a mapping of world id to score), got the "
            f"{type(worlds).__name__} {worlds!r}: a string is a world's "
            f"name, not the stratum's worlds, and reading it as an iterable "
            f"of characters would refuse its first character as a carrier "
            f"— a message about the wrong repair entirely (feature 263)"
        )
    if isinstance(worlds, Iterable):
        return worlds
    raise AggregationError(
        f"the worlds of stratum {stratum!r} must arrive as an iterable of "
        f"world scores (or a mapping of world id to score), got "
        f"{worlds!r} ({type(worlds).__name__}): a single world score is "
        f"one world — hand the stratum's worlds together, and a value "
        f"that is neither iterable nor a mapping cannot say how many "
        f"worlds the stratum holds (feature 263)"
    )


def _world_identity(world: object, stratum: str) -> str:
    """A world's id, read duck-typed — a non-empty string, or a refusal.

    The world score's own validation (feature 256's), restated at the
    seam that reads it: the module loader's synthetic-name re-execution
    means the carrier may be a second ``WorldScore`` class object, so
    the seam reads the attribute and validates what it reads instead of
    testing the type.
    """
    world_id = getattr(world, "world_id", None)
    if isinstance(world_id, bool) or not isinstance(world_id, str) or not world_id.strip():
        raise AggregationError(
            f"every world a stratum aggregates must be a world score — an "
            f"object exposing a world_id and a finite score, feature 256's "
            f"WorldScore duck-typed — and stratum {stratum!r} carried "
            f"{world!r} ({type(world).__name__}), whose world_id is "
            f"{world_id!r}: a world that cannot be named cannot be counted "
            f"once, and the partition of worlds over strata is the blend's "
            f"own arithmetic (feature 263, prd §7.2)"
        )
    return world_id


def _world_score(world: object, stratum: str, world_id: str) -> float:
    """A world's score, read duck-typed and narrowed — the figure the
    stratum's mean is taken over.

    The one scalar the blend reads off each world; validated here rather
    than trusted, because the seam is duck-typed and a carrier that is
    not a world score must be refused at the value it would have
    poisoned the mean with, not at a TypeError from inside
    :func:`math.fsum`.
    """
    return _finite(
        getattr(world, "score", None),
        f"the score of world {world_id!r} in stratum {stratum!r}",
        "a world score",
    )
