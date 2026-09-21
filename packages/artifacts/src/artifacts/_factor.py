"""The book Cholesky factor — §9.3's precompute, feature 177.

app_spec.xml, "Tree & Artifact Persistence", feature 177: *System
precomputes the book Cholesky factor once per replay, which returns a
reusable factor for every candidate.*  docs/nullius-tech-architecture.md
§9.3 states that sentence as the arithmetic half of its answer to the
replay bottleneck — the half that exists to make the other half cheap:

    ``ir_marginal`` arithmetic is negligible: after portfolio
    construction each signal contributes a single T-vector, and the
    book is **fixed during a replay**, so precompute the book's
    Cholesky factor once at ``O(k³)`` and every candidate is a rank-1
    update at ``O(kT + k²)`` — roughly 40 µs.

This module builds the precompute.  The rank-1 update is feature
178's and the marginal number it returns is the evaluator's to define
(feature 83, §6.2); the factor this module answers is the reusable
*input* both stand on — the one expensive thing about the book,
computed once, so that nothing downstream has to compute it again.

**The book is fixed during a replay, and that is the whole trick.**
§10.1 hands every replay its book as an argument
(``replay(policy, tree, book, epoch)``) and the policy commits to it
before the candidates are scored, so within one replay the book's
members — and therefore the book's covariance — do not change.  A
scorer that factored the covariance per candidate would pay ``O(k³)``
per candidate; a scorer that factored it once pays ``O(k³)`` per
*replay* and turns every candidate into §9.3's ``O(kT + k²)`` update.
That asymmetry is the feature: :func:`precompute_book_cholesky` is
called by the replay that holds the book, at the moment the book is
fixed, and the :class:`BookCholesky` it answers is threaded to every
candidate evaluation that follows — the same object, the same bytes,
no per-candidate recomputation anywhere.

**A value, not a residence — and that is deliberate.**  §9.3 closes
with *"no canonical-book cache anywhere"*, and feature 176 made the
decline structural: the cache's residence holds return series and
nothing else, because the book is an *argument* of ``ir_marginal``
rather than a dimension of the data, and an entry keyed by it would
be stale by construction.  The same reasoning forbids a factor cache
— the replay that precomputed a factor for its book is the only
replay that book is fixed in — so this module offers no key, no
mapping, no lookup and no lifetime but the caller's own variable:
the precompute answers an immutable value, the replay owns it for
the duration of its run, and the next replay precomputes its own
from the array *it* pinned.  Nothing can go stale because nothing is
held; "once per replay" is not a policy the module enforces against
the caller but a shape the module makes natural — the value carries
no state to misuse.

**What the factor factors: the members' covariance over the sample
they share.**  The book's members are node ids of the resident
campaign array (feature 174's :class:`~artifacts.CampaignReturns`,
held through feature 175's pin — the same buffer the sweep and
feature 178's updates read), and each member contributes §9.3's
"single T-vector": its row of the array.  The covariance is the
evaluator's own coefficient — each member's row centered on its mean,
population normalisation ``1/T`` (``ddof=0``, the convention
:mod:`evaluator._metrics` pins for ``ir_standalone``'s variance) —
and the sample is the periods **every** member measured: the array
carries :data:`~artifacts.ABSENT` (NaN) where no panel measured, and
a covariance is defined over one sample measured together, so the
sample is the intersection of the members' measured columns, the
campaign-scale analogue of the shortest-shared-horizon policy feature
174 pins.  Members whose measured windows never all overlap refuse,
naming each member's coverage — measurements with no common sample
are measurements no single factor is defined over.  Every sum is
:func:`math.fsum`, so the arithmetic is exactly rounded and two
precomputes over one membership answer identical bytes: §10.4's
"fully deterministic" replay rests on it.

**The axis is the membership, canonically.**  A policy commits to its
book in an order, but the commit order is not part of the factor's
identity — a permutation of the members permutes the covariance and
its factor alike, and every quantity feature 178 computes from the
factor is invariant under it — so the factor's axis is the membership
in the store's canonical sorted order, the order the campaign array's
own row axis uses: the precompute *normalizes* whatever order the
membership was spelled in, while a :class:`BookCholesky` built by hand
refuses an axis not already in that order, because its buffer's rows
are bound to the members in the order spelled and a reordered axis
would re-bind them silently.  The canonical order is what makes two
precomputes over one membership answer identical buffers without the
caller having to remember how it spelled the book, and a member named
twice refuses outright: a repeated signal would make the covariance
singular by construction, and the refusal names it before the
arithmetic tries.

**Positive definiteness is required, not patched.**  The Cholesky
factorization exists only for a positive-definite covariance, and a
book of real signals can fail it three ways, each refused with the
member it is about: a member that never varied over the sample (zero
variance — no factor of a constant exists), a member whose centered
returns are a linear combination of the others' (a duplicate signal
above all — §14.1's anti-convergence clause exists because search
keeps proposing them), and a book wider than its sample: centering
leaves each member's T-vector in the ``(T − 1)``-dimensional subspace
orthogonal to the ones vector, so ``k`` independent members need
``T ≥ k + 1``, and a book this wide over a sample this short is
singular by construction — refused as a shape before the arithmetic
runs.  What this module never does is add jitter: a regularized
factor would feed every candidate an invented covariance dressed as
the book's, and the determinism §10.4 pins would be gone.  A book
that cannot be factored is a fact for the policy to act on, not a
numerical inconvenience to smooth over.

**float64, stdlib, and the buffer is the deliverable.**  The resident
array narrowed to float32 because §9.3 sizes its *residency* in those
bytes; the factor keeps the double — it is the arithmetic, not the
residency, it is ``k × k`` rather than ``k × T`` (2 MB at the
``k = 500`` §9.3's sizing never asks of a book, measured by
:attr:`BookCholesky.footprint_bytes`), and the widening
binary32 → binary64 is exact, so the factor is precisely the float64
arithmetic of the float32 cells.  The computation is stdlib-only —
:mod:`math`, :class:`array.array`, no second decoder, no new
dependency, the same stance feature 174's load takes — and the buffer
supports the buffer protocol, so the day a consumer wants to hand it
to numpy it can, zero-copy.  The precompute touches no store and no
filesystem: it is a pure function of the resident array, which is why
a replay may run it after the campaign's Parquet is cold and why its
only refusals are about the book and the array, never about I/O.

**What this module does not do.**  It performs no rank-1 update and
computes no information ratio — feature 178 owns the update, the
evaluator (feature 83) owns the definition, and this module owns only
the factor both stand on.  It constructs no book (§10.1's policy
commit), it persists nothing (feature 169's store is never reached),
and it holds no residence (feature 174 loaded the array, feature 175
holds it, feature 176 declined to cache anything keyed by a book —
this module adds the factor to that division of labour as a value,
not a place).
"""

from __future__ import annotations

import array as _array
import datetime as dt
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ._campaign import CampaignReturns
from ._errors import ArtifactBookFactorError
from ._returns import _validated_horizon

__all__ = [
    "BOOK_FACTOR_POLICY",
    "FACTOR_TYPECODE",
    "BookCholesky",
    "precompute_book_cholesky",
]

#: The typecode of the factor buffer — :mod:`array`'s spelling of C
#: ``double``, IEEE 754 binary64, 8 bytes on every platform CPython
#: builds for.  The resident array is binary32 because §9.3 sizes its
#: *residency* (``500 nodes × 2000 periods × 4 B``); the factor is the
#: *arithmetic* — ``k × k``, not ``k × T`` — and keeps the double the
#: evaluator's own variance convention is computed in, so the
#: factorization's pivots see exactly the arithmetic of the widened
#: cells and nothing narrower.  ``itemsize`` is checked against it at
#: construction: a buffer of any other width is not the factor this
#: module answers.
FACTOR_TYPECODE = "d"

#: The precompute's policy, spelled once the way
#: :data:`~artifacts.CAMPAIGN_LOAD_HORIZON`,
#: :data:`~artifacts.RESIDENT_CACHE_POLICY` and
#: :data:`~artifacts.RESIDENT_PIN_POLICY` spell theirs: a sentence,
#: not a type, because it is the *decision* §9.3's sentence pins and
#: every seam that states it (the precompute's docstrings, the
#: record's, the tests) quotes this one spelling of it.  The second
#: half is the structural half: no book-keyed residence exists
#: anywhere in this module, so the "once per replay" cannot decay into
#: a cache §9.3 forbids.
BOOK_FACTOR_POLICY: str = (
    "precompute the book's Cholesky factor once per replay at O(k³), "
    "over the covariance of its members' T-vectors on the periods they "
    "share, and hand every candidate the same reusable factor — no "
    "book-keyed factor residence exists"
)


# -- The factor, as a value ----------------------------------------------------------


@dataclass(frozen=True)
class BookCholesky:
    """The book's Cholesky factor — one reusable ``k × k`` lower triangle.

    The value :func:`precompute_book_cholesky` answers: the campaign
    and horizon the members were measured on, the membership as the
    factor's canonical axis, the shared sample the covariance was
    computed over, and the factor itself — one contiguous float64
    buffer, row-major, lower-triangular, strictly positive diagonal,
    with ``L·Lᵀ`` the members' population covariance (centered rows,
    ``1/T``) over exactly those periods.

    Frozen and validated at construction (see the module docstring),
    so a value built by hand fails here rather than answering a book
    nobody factored — and so the replay that holds one can thread it
    to every candidate evaluation as a plain immutable value: there is
    no state to release, no residence to outlive, and no second
    spelling of the factor a later feature could grow here by
    accident.
    """

    #: The campaign the members were measured in — §9.2's first key,
    #: the campaign the resident array was loaded from.
    campaign_id: str
    #: The horizon axis the members' T-vectors sit on — the resolved
    #: axis of the campaign array the factor was precomputed over.
    horizon: int
    #: The book's members — the committed picks' node ids, sorted,
    #: each once: the factor's row *and* column axis, in the campaign
    #: array's own canonical order.
    node_ids: tuple[str, ...]
    #: The shared sample — the periods every member measured, sorted,
    #: each once: the columns the covariance was computed over, and
    #: the axis any update against this factor must align on.
    periods: tuple[dt.date, ...]
    #: The factor — float64, row-major, ``len(node_ids)²`` cells, zero
    #: above the diagonal, strictly positive on it.
    factor: _array.array

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, str) or not self.campaign_id.strip():
            raise ArtifactBookFactorError(
                f"a book Cholesky factor names the campaign its members "
                f"were measured in — got {self.campaign_id!r}; the factor "
                "is one book of one campaign's nodes, and a value that "
                "cannot say which campaign's measurements it factors "
                "cannot say what it is a factor of"
            )
        horizon = _validated_horizon(self.horizon)
        members = _validated_members(self.node_ids, normalize=False)
        periods = _validated_sample(self.periods)
        k = len(members)
        if len(periods) < k + 1:
            raise ArtifactBookFactorError(
                f"a book Cholesky factor of {k} members is measured over "
                f"at least {k + 1} periods — got {len(periods)}"
                + (f" ({', '.join(day.isoformat() for day in periods)})"
                   if periods else "")
                + "; centering each member's T-vector on its mean leaves "
                f"it in the {len(periods) - 1}-dimensional subspace "
                "orthogonal to the ones vector, so the covariance of a "
                "book this wide over a sample this short is singular by "
                "construction and no factor of it exists"
            )
        if not isinstance(self.factor, _array.array):
            raise ArtifactBookFactorError(
                "a book Cholesky factor's factor is a float64 buffer — an "
                f"array.array, got {type(self.factor).__name__}; §9.3's "
                "precompute answers one contiguous lower triangle a "
                "candidate's rank-1 update indexes, and any other spelling "
                "of it is not that"
            )
        if self.factor.typecode != FACTOR_TYPECODE:
            raise ArtifactBookFactorError(
                "a book Cholesky factor's factor is float64 — an "
                f"array.array of {FACTOR_TYPECODE!r}, got typecode "
                f"{self.factor.typecode!r} ({self.factor.itemsize} bytes "
                "per cell); the factorization's pivots are the arithmetic "
                "of the widened float32 cells, and a buffer of another "
                "width is either a different decision or a mistaken one"
            )
        expected = k * k
        if len(self.factor) != expected:
            raise ArtifactBookFactorError(
                f"a book Cholesky factor of {k} members is a {k}×{k} "
                f"lower triangle — its buffer holds {expected} cells; it "
                f"holds {len(self.factor)}; the shape is the whole point "
                "(§9.3's rank-1 update indexes it), and a buffer that "
                "does not fill it is a book nobody factored"
            )
        for row in range(k):
            for column in range(k):
                value = self.factor[row * k + column]
                if math.isnan(value) or math.isinf(value):
                    raise ArtifactBookFactorError(
                        f"a book Cholesky factor carries the non-finite "
                        f"value {value!r} at cell ({row}, {column}) "
                        f"(member {members[row]!r}, period "
                        f"{periods[column].isoformat()}); the precompute "
                        "factors finite covariances, so a NaN or infinity "
                        "is a value built by hand or a buffer edited "
                        "outside this package — not a factor any rank-1 "
                        "update should trust"
                    )
                if column > row and value != 0.0:
                    raise ArtifactBookFactorError(
                        f"a book Cholesky factor is lower-triangular — "
                        f"cell ({row}, {column}) above the diagonal is "
                        f"{value!r}; the update reads the lower triangle "
                        "and the diagonal, never the mirror, and a value "
                        "above the diagonal is a buffer built by hand"
                    )
                if column == row and value <= 0.0:
                    raise ArtifactBookFactorError(
                        f"a book Cholesky factor's diagonal is strictly "
                        f"positive — cell ({row}, {row}) (member "
                        f"{members[row]!r}) is {value!r}; the diagonal "
                        "carries each pivot's square root, a zero or "
                        "negative one is a covariance that is not "
                        "positive definite, and the precompute would "
                        "have refused it before answering"
                    )
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "node_ids", members)
        object.__setattr__(self, "periods", periods)

    @property
    def shape(self) -> tuple[int, int]:
        """The factor's shape — ``(k, k)``, the feature's own letter.

        One count for both axes: the factor's rows and columns are the
        same membership, so the pair a rank-1 update shapes its work by
        is square by construction.
        """
        return (len(self.node_ids), len(self.node_ids))

    @property
    def footprint_bytes(self) -> int:
        """What the factor weighs — cells × 8 B, the double it keeps.

        The measurement the resident array's own
        :attr:`~artifacts.CampaignReturns.footprint_bytes` answers for
        its float32 cells, restated for the factor's float64 ones: the
        buffer is ``k² × 8`` bytes — 2,000,000 at the ``k = 500`` no
        book in §9.3's sizing is asked to reach — so an operator
        accounting a replay's residence reads the array's footprint
        and the factor's side by side, never a guess.
        """
        return len(self.factor) * self.factor.itemsize


# -- The precompute ------------------------------------------------------------------


def precompute_book_cholesky(
    returns: CampaignReturns, node_ids: Iterable[str]
) -> BookCholesky:
    """Precompute the book's Cholesky factor — once, for every candidate.

    The feature's sentence as one call: the book's members are rows of
    the resident campaign array (feature 174's load, feature 175's
    pin — the only decoder and the only lifetime this precompute
    trusts), their covariance is computed over the periods every
    member measured — each row centered on its mean, population
    ``1/T``, the evaluator's own coefficient, every sum :func:`fsum`
    — and factored once, ``O(k³)`` (over a Gram matrix that costs
    ``O(k²T)`` to fill), into the lower triangle this function
    answers.  The replay calls this at the moment its book is fixed
    and threads the value to every candidate; nothing in this module
    recomputes, stores or keys it, because §9.3 pins *"no canonical-
    book cache anywhere"* and the book is an argument, not a
    dimension.

    The members may be spelled in any order — the axis is the
    membership in the campaign array's canonical sorted order, which
    is what makes two precomputes over one book answer identical
    bytes — and each member must be a row the array holds.

    Refusals, each naming what it refuses: a first argument that is
    not a :class:`~artifacts.CampaignReturns`; a book holding no
    members (an empty book has no covariance to factor — the
    evaluator's own stance, and the candidate-alone question is
    feature 80's); a member named twice; a member the array holds no
    row for; members sharing no period every one measured; a book
    wider than its sample (``k`` members over fewer than ``k + 1``
    shared periods — singular by construction); and a member linearly
    dependent on the ones before it, pivot named, jitter never added.
    """
    if not isinstance(returns, CampaignReturns):
        raise ArtifactBookFactorError(
            "the book Cholesky factor is precomputed over one resident "
            "campaign array — a CampaignReturns, got "
            f"{type(returns).__name__} {returns!r}; the members' T-vectors "
            "are rows of the array §9.3 says to load and pin (feature "
            "174's load, feature 175's hold), and a factor computed over "
            "anything else is a factor of nothing this system measured"
        )
    members = _validated_members(node_ids)
    _require_resident_members(returns, members)
    periods, coverage = _shared_sample(returns, members)
    if not periods:
        raise _no_shared_sample_refusal(returns, members, coverage)
    k = len(members)
    if len(periods) < k + 1:
        raise ArtifactBookFactorError(
            f"the book of campaign {returns.campaign_id!r} holds {k} "
            f"members over {len(periods)} shared periods — too few: "
            "centering each member's T-vector on its mean leaves it in "
            f"the {len(periods) - 1}-dimensional subspace orthogonal to "
            f"the ones vector, so {k} independent members need T ≥ k + 1 "
            "and the covariance of a book this wide over a sample this "
            "short is singular by construction; §9.3's rank-1 update has "
            "no factor to update (narrow the book, or pin the horizon "
            "that widens the shared sample)"
        )
    covariance = _members_covariance(returns, members, periods)
    factor = _factorize(
        covariance,
        k,
        members=members,
        periods=periods,
        campaign_id=returns.campaign_id,
    )
    return BookCholesky(
        campaign_id=returns.campaign_id,
        horizon=returns.horizon,
        node_ids=members,
        periods=periods,
        factor=factor,
    )


# -- The precompute's own validation and arithmetic, spelled once ---------------------


def _validated_members(values: Any, *, normalize: bool = True) -> tuple[str, ...]:
    """The book's members as they must be — ids, each once, answered sorted.

    A policy commits to its book in an order; the commit order is not
    part of the factor's identity (see the module docstring), so the
    *precompute's* input is normalized to the canonical sorted order
    rather than refused — but the two lie-shaped spellings still are:
    a bare string or bytes (an iterable of characters, not of node
    ids) and a member named twice, which would ask one T-vector to
    carry two dimensions of the book and make the covariance singular
    by construction.  The record built by hand passes
    ``normalize=False`` and refuses an axis not already sorted,
    because its buffer's rows are bound to the members in the order
    spelled: an axis reordered underneath its buffer would silently
    re-bind those rows to different members — the same reason
    :func:`_validated_sample` refuses a sample not already sorted.
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ArtifactBookFactorError(
            "the book's members are the committed picks as a sequence of "
            f"node ids — got {type(values).__name__} {values!r}"
        )
    axis = tuple(values)
    if not axis:
        raise ArtifactBookFactorError(
            "the book holds no members — an empty book has no covariance "
            "to factor; the evaluator's own stance (feature 83: a book of "
            "zero signals has no information ratio to increment from) "
            "makes the candidate-alone question feature 80's "
            "ir_standalone, so the replay whose book is empty scores "
            "every candidate standalone and precomputes when the book "
            "holds its first committed member"
        )
    for position, value in enumerate(axis):
        if not isinstance(value, str) or not value:
            raise ArtifactBookFactorError(
                f"the book's members are node ids — got {value!r} "
                f"({type(value).__name__}) at position {position}"
            )
    if len(set(axis)) != len(axis):
        repeated = sorted({node for node in axis if axis.count(node) > 1})
        raise ArtifactBookFactorError(
            "the book's members are each committed once — "
            + ", ".join(repr(node) for node in repeated)
            + " named twice; a repeated signal would ask one T-vector to "
            "carry two dimensions of the book, and the covariance of a "
            "book holding a member twice is singular by construction"
        )
    if not normalize and list(axis) != sorted(axis):
        raise ArtifactBookFactorError(
            "a book Cholesky factor's node_ids are the sorted membership, "
            "each node once — the axis as given is not that order; the "
            "buffer's rows are bound to the members in the order spelled, "
            "and an axis reordered underneath its buffer would silently "
            "re-bind those rows to different members"
        )
    return tuple(sorted(axis)) if normalize else axis


def _require_resident_members(
    returns: CampaignReturns, members: tuple[str, ...]
) -> None:
    """Refuse a book naming a node the resident array holds no row for.

    The members are picks this campaign measured — a replay reveals
    and scores the campaign's own nodes, so the book it commits to is
    rows of the very array it pinned.  A foreign node id is refused
    here, naming every one of them, rather than answered as a row of
    zeros or NaNs: the factor would then speak for measurements nobody
    made.
    """
    held = set(returns.node_ids)
    missing = [node for node in members if node not in held]
    if missing:
        raise ArtifactBookFactorError(
            f"the book names node(s) the resident campaign array of "
            f"{returns.campaign_id!r} holds no row for — "
            + ", ".join(repr(node) for node in missing)
            + f"; the array holds {len(returns.node_ids)} rows, and the "
            "book's members are picks this campaign measured (a replay "
            "reveals and scores the campaign's nodes), so a node no "
            "panel measured has no T-vector to factor"
        )


def _shared_sample(
    returns: CampaignReturns, members: tuple[str, ...]
) -> tuple[tuple[dt.date, ...], dict[str, set[dt.date]]]:
    """The sample every member measured — the intersection, spelled once.

    A covariance is defined over one sample measured together, and the
    resident array carries :data:`~artifacts.ABSENT` (NaN) where no
    panel measured, so the honest sample is the columns every member
    measured — the campaign-scale analogue of the shortest-shared-
    horizon policy feature 174 pins.  Each member's coverage is
    answered beside the intersection for the refusal that names it.
    """
    coverage: dict[str, set[dt.date]] = {}
    for node in members:
        row = returns.row(node)
        coverage[node] = {
            day
            for day, cell in zip(returns.periods, row)
            if not math.isnan(cell)
        }
    shared = set.intersection(*coverage.values())
    return tuple(sorted(shared)), coverage


def _no_shared_sample_refusal(
    returns: CampaignReturns,
    members: tuple[str, ...],
    coverage: dict[str, set[dt.date]],
) -> ArtifactBookFactorError:
    """The refusal for members whose measured windows never all overlap."""
    spelled = "; ".join(
        "node {!r} measured {}".format(
            node,
            ", ".join(day.isoformat() for day in sorted(coverage[node]))
            or "no period",
        )
        for node in members
    )
    return ArtifactBookFactorError(
        f"the members of the book of campaign {returns.campaign_id!r} "
        f"share no period every one of them measured — {spelled}; a "
        "covariance is defined over one sample measured together, and "
        "members whose measured windows never all overlap are "
        "measurements no single factor is defined over (load the "
        "campaign at the horizon that aligns them, or commit a book "
        "measured on one window)"
    )


def _members_covariance(
    returns: CampaignReturns,
    members: tuple[str, ...],
    periods: tuple[dt.date, ...],
) -> _array.array:
    """The members' covariance over the shared sample — symmetric, float64.

    The evaluator's own coefficient: each member's cells over the
    shared columns (binary32 widened to binary64, exactly), centered
    on their ``fsum`` mean, products summed with ``fsum``, population
    normalisation ``1/T`` — the ``ddof=0`` convention
    :mod:`evaluator._metrics` pins for ``ir_standalone``'s variance,
    so the factor and the evaluator's ratios speak of one covariance.
    Both triangles are filled (the factorization reads the lower one
    and zeroes the mirror at the end).
    """
    k = len(members)
    column_of = {day: column for column, day in enumerate(returns.periods)}
    chosen = [column_of[day] for day in periods]
    rows = {node: returns.row(node) for node in members}
    centered = []
    for node in members:
        cells = [rows[node][column] for column in chosen]
        mean = math.fsum(cells) / len(periods)
        centered.append([value - mean for value in cells])
    covariance = _array.array(FACTOR_TYPECODE, [0.0] * (k * k))
    for i in range(k):
        for j in range(i + 1):
            value = math.fsum(
                centered[i][t] * centered[j][t] for t in range(len(periods))
            ) / len(periods)
            covariance[i * k + j] = value
            if i != j:
                covariance[j * k + i] = value
    return covariance


def _factorize(
    covariance: _array.array,
    k: int,
    *,
    members: tuple[str, ...],
    periods: tuple[dt.date, ...],
    campaign_id: str,
) -> _array.array:
    """Factor the covariance in place — Banachiewicz, pivot-guarded.

    The ``O(k³)`` §9.3 prices as the once-per-replay cost: row by
    row, the lower triangle of the Gram matrix is overwritten with
    the lower triangle of its Cholesky factor, every inner sum
    :func:`fsum` so the arithmetic is exactly rounded and two
    precomputes over one membership answer identical bytes.  A pivot
    that is not strictly positive refuses, naming the member it
    broke on — never jittered, per the module docstring — and the
    symmetric upper mirror is zeroed at the end, because the factor
    this module answers is the triangle, not the matrix.
    """
    for i in range(k):
        for j in range(i):
            running = math.fsum(
                covariance[i * k + m] * covariance[j * k + m]
                for m in range(j)
            )
            covariance[i * k + j] = (
                covariance[i * k + j] - running
            ) / covariance[j * k + j]
        running = math.fsum(
            covariance[i * k + m] * covariance[i * k + m] for m in range(i)
        )
        pivot = covariance[i * k + i] - running
        if not pivot > 0.0:
            raise ArtifactBookFactorError(
                f"member {members[i]!r} (row {i} of the book's canonical "
                f"axis) is linearly dependent on the members before it "
                f"over the {len(periods)} shared periods of campaign "
                f"{campaign_id!r} — the Cholesky pivot for the member is "
                f"{pivot!r}, not positive; a duplicate signal, a signal "
                "that never varied, or a linear combination of the "
                "committed ones has no factor, and no jitter is added "
                "because a patched factor would feed every candidate an "
                "invented covariance and break the determinism §10.4 "
                "pins; drop the dependent member from the book"
            )
        covariance[i * k + i] = math.sqrt(pivot)
    for i in range(k):
        for j in range(i + 1, k):
            covariance[i * k + j] = 0.0
    return covariance


def _validated_sample(values: Any) -> tuple[dt.date, ...]:
    """The shared sample as it must be — non-empty, dates, sorted, once.

    The factor's column axis is the market calendar the covariance
    was measured over.  A :class:`~datetime.datetime` is refused
    before the date check (it is a subclass and would pass one) for
    the same reason the file layer refuses instants: a column keyed
    by an instant is one no rebalance date can address.
    """
    if isinstance(values, (str, bytes)) or not hasattr(values, "__iter__"):
        raise ArtifactBookFactorError(
            "a book Cholesky factor's periods are the shared sample as a "
            f"sequence of dates — got {type(values).__name__}"
        )
    axis = tuple(values)
    if not axis:
        raise ArtifactBookFactorError(
            "a book Cholesky factor's periods cannot be empty; the "
            "precompute factors the periods every member measured, and "
            "an empty sample is a book nobody factored"
        )
    for position, value in enumerate(axis):
        if isinstance(value, dt.datetime) or not isinstance(value, dt.date):
            raise ArtifactBookFactorError(
                "a book Cholesky factor's periods are calendar dates — "
                f"got {value!r} ({type(value).__name__}) at position "
                f"{position}; the sample is the market calendar the "
                "panels priced, and a key that is not a date is a period "
                "no rebalance can address"
            )
    if list(axis) != sorted(axis) or len(set(axis)) != len(axis):
        raise ArtifactBookFactorError(
            "a book Cholesky factor's periods are the sorted shared "
            "sample, each date once — the axis as given is not that "
            "order; column order is part of the factor's identity, and a "
            "repeated date would give one period two columns"
        )
    return axis
