"""The rank-1 update — §9.3's per-candidate half, feature 178.

app_spec.xml, "Tree & Artifact Persistence", feature 178: *System
evaluates a candidate as a rank-1 update against the precomputed
factor, which returns ir_marginal in roughly 40 microseconds.*
docs/nullius-tech-architecture.md §9.3 states the sentence both
features share — *"the book is **fixed during a replay**, so precompute
the book's Cholesky factor once at ``O(k³)`` and every candidate is a
rank-1 update at ``O(kT + k²)`` — roughly 40 µs"* — and closes with
the shape this module completes: *"`ir_marginal` then becomes array
indexing plus a rank-1 update, with no canonical-book cache
anywhere."*  Feature 177 built the once-per-replay half; this module
is the per-candidate half that exists to be cheap.

**The definition is the evaluator's, and the update is its fast
spelling.**  ``ir_marginal`` is §6.2's ``IR(book ∪ {v}) − IR(book)``
— feature 83's increment, the equal-weight book's information ratio
measured twice and differenced — and the update computes exactly that
number, no second definition: the same population ``1/T`` coefficient
(:mod:`evaluator._metrics`' ``ddof=0``, the convention features 80
and 83 pin), the same equal-weight re-normalisation (each member at
``1/k``, the candidate joining at ``1/(k+1)``), the same difference of
two ratios.  What differs is *how*: the evaluator reduces per-date
series to means and variances each time it is asked, at ``O(kT)``
bookkeeping per call and ``O(k²T)`` if the covariance were rebuilt;
the update reduces the candidate once against the factor the replay
already paid for, and reads every variance as a quadratic form through
that factor.  The two spellings agree to the rounding of the
factorization (the suite pins the agreement on exact-dyadic data),
because they are one arithmetic with the book's covariance computed
once instead of twice.

**What a rank-1 update is, exactly.**  The candidate contributes its
T-vector — §9.3's "single T-vector", its row of the resident array
aligned on the factor's shared sample — and the update reads three
things off it at ``O(kT)``: its mean, its variance, and its covariance
``γ`` with each member.  Then the factor does the ``O(k²)`` work no
candidate can avoid and none needs to repeat: the forward substitution
``L·w = γ`` (the candidate's coordinates against the book), the
residual variance ``d² = σ_v² − wᵀw`` (the variance the candidate
*adds* once the book's explanation of it is subtracted), and the two
equal-weight variances as quadratic forms — the book's
``‖Lᵀ·1‖²/k²``, and the combined book-plus-candidate's
``‖Lᵀ·1 + w‖² + d²`` over ``(k+1)²``, which is the rank-1-updated
factor ``L′ = [[L, 0], [wᵀ, d]]`` acting on the ones vector without
ever being materialised.  That augmented triangle is the "rank-1
update" of §9.3's sentence and of the numerical-linear-algebra
sentence it borrows: appending one row to a Cholesky factor costs one
triangular solve, never a refactorisation.

**The book is fixed during a replay, so the update never grows the
factor.**  ``L′`` is computed in the coordinates of a quadratic form
and discarded; no spelling of this module answers it, stores it, or
hands it to the next candidate.  A policy grows its book *between*
replays (§10.1's commit), and the replay that holds the wider book
precomputes its own factor at ``O(k³)`` (feature 177) — threading a
grown factor from candidate to candidate inside one replay would be
both the stale-book bug §9.3's fixedness exists to prevent and a
factor residence §9.3 forbids.  The same discipline bounds what the
update recomputes per candidate: ``Lᵀ·1`` is the same for every
candidate against one factor, and a cache would hold it — so it is
recomputed inside each call, inside the ``O(k²)`` budget §9.3 prices
the update at, because the factor is a value with no state and the
"once per replay" shape of feature 177 is kept a shape, not a
residence.

**Array indexing, not I/O.**  The candidate and the members are rows
of the resident campaign array — feature 174's load, feature 175's
pin, reached through :meth:`~artifacts.CampaignReturns.row`, the one
API §9.3's "array indexing" describes — and the update touches no
store, no filesystem and no second decoder.  Its only inputs are the
factor and the array, and its only refusals about *them* are that they
must describe one book: the same campaign, the same horizon, a sample
axis the array's columns address, members the array holds rows for.
The sample is the factor's own — the periods every member measured —
and the update aligns the candidate on exactly those columns, so a
candidate that measured more periods than the book is scored on the
sample the covariance was defined over and no other.

**Absence is not zero.**  A candidate that carries
:data:`~artifacts.ABSENT` (NaN) on a period of the shared sample is
refused, naming the periods — a hole in the resident array is not a
zero return (feature 75's rule, restated for the candidate; the
evaluator states it from the other side: every book signal must cover
every date the candidate was priced on, and here the priced dates are
the book's own sample).  A member row with a hole on the sample
refuses the same way, as a factor that was not precomputed over this
array's cells — the precompute's intersection is the sample's
definition, so a hole there means the factor speaks for measurements
this array does not hold.

**Positive definiteness is required, not patched — the span
refusal.**  A candidate whose variance the book already explains to
the last digit of this arithmetic (``d² ≤ 0``) is refused, the
residual named, jitter never added: a candidate the book spans adds no
dimension, its marginal is zero by construction rather than by
measurement, and the rounding noise a patched pivot would dress as a
score would break the determinism §10.4 pins.  It is the same verdict
the precompute takes on a dependent member, taken here on the
candidate — and §14.1's anti-convergence clause exists because search
keeps proposing exactly these.  A candidate that never varied over
the sample refuses earlier and louder (its information ratio is
undefined, the evaluator's own stance on a constant side), and a
candidate already committed to the book refuses before the arithmetic
runs at all.

**float64, stdlib, fsum — determinism.**  The arithmetic runs in the
float64 the factor keeps, on the binary32 cells widened exactly, and
every sum is :func:`math.fsum` — exactly rounded, order-independent —
so two evaluations of one candidate against one factor answer
identical floats, whatever else the replay scored between them.  The
factor is read and never written: its buffer's bytes are identical
after any number of updates, which is what makes threading one
``BookCholesky`` through a whole replay safe.  The module is
stdlib-only — :mod:`math`, :func:`itertools.islice`,
:func:`operator.mul` — no second decoder, no new dependency, the same
stance the load and the precompute take.

**Roughly 40 µs, made checkable.**  §9.3's figure prices the
arithmetic, not a machine: the sizing it was read at is spelled once
(:data:`RANK1_UPDATE_SIZING_BOOK` members over
:data:`RANK1_UPDATE_SIZING_SAMPLE` shared periods — the ``O(kT + k²)``
work the figure describes) and the suite's timing test measures the
whole call there and holds it inside a five-fold band around
:data:`RANK1_UPDATE_COST_MICROSECONDS`, so the seam cannot silently
regress to the ``O(k²T)`` covariance rebuild or the ``O(k³)``
refactorisation the precompute exists to spare it.  The recorded
answer carries no clock: a value that measured itself would not be a
function of its arguments, and §10.4's "fully deterministic" replay
rests on this one being exactly that.

**What this module does not do.**  It computes no other metric —
``ir_standalone`` is feature 80's question, and the update answers it
only as the candidate's own ratio among its terms.  It persists
nothing (feature 169's store is never reached), loads nothing (174),
pins nothing (175), caches nothing (176 — the decline stands, and the
update is the *instead*: a pure function whose book is an argument,
asked per candidate, holding nothing between asks), precomputes
nothing (177), and grows no factor (the book is fixed during a
replay).  Its record carries moments, not per-date series — a handful
of floats that check the scalar, not an ``O(T)`` series that would
recreate the residency the resident array already owns.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from itertools import islice
from operator import mul
from typing import Any

from ._campaign import CampaignReturns
from ._errors import ArtifactRank1UpdateError, ArtifactsError
from ._factor import BookCholesky, _validated_members, _validated_sample
from ._returns import _validated_horizon

__all__ = [
    "RANK1_UPDATE_COST_MICROSECONDS",
    "RANK1_UPDATE_POLICY",
    "RANK1_UPDATE_SIZING_BOOK",
    "RANK1_UPDATE_SIZING_SAMPLE",
    "Rank1Update",
    "evaluate_rank1_update",
]

#: The update's policy, spelled once the way
#: :data:`~artifacts.BOOK_FACTOR_POLICY`,
#: :data:`~artifacts.RESIDENT_CACHE_POLICY` and
#: :data:`~artifacts.RESIDENT_PIN_POLICY` spell theirs: a sentence,
#: not a type, because it is the *decision* §9.3's sentence pins and
#: every seam that states it (the update's docstrings, the record's,
#: the tests) quotes this one spelling of it.  The structural half is
#: the sentence's last clause: no book-keyed or candidate-keyed
#: residence exists anywhere in this module — the factor and the array
#: are arguments, the answer is a value, and nothing survives the
#: call.
RANK1_UPDATE_POLICY: str = (
    "evaluate every candidate as a rank-1 update against the "
    "precomputed factor — O(kT + k²) per candidate, roughly 40 µs — "
    "answering ir_marginal as IR(book ∪ {v}) − IR(book) over the "
    "factor's own shared sample, with no canonical-book cache anywhere"
)

#: §9.3's figure for the per-candidate arithmetic — the "roughly
#: 40 µs" of the feature's own sentence, the number the precompute
#: exists to make true.  It prices the arithmetic, not a machine: the
#: moments and the solve the module runs over the sizing spelled
#: beside this read at the figure on the reference interpreter of
#: this worktree, and the whole call — which adds the candidate's
#: validation and the answer's own construction checks, this
#: package's honesty discipline rather than §9.3's priced arithmetic —
#: reads at roughly twice it.  The suite's timing test holds the
#: whole call inside a five-fold band around this figure, so
#: "roughly" is a checkable band rather than a hope, and a regression
#: to the O(k²T) covariance rebuild, the O(k³) refactorisation or a
#: per-candidate reload would leave the band by multiples, not by a
#: rounding.
RANK1_UPDATE_COST_MICROSECONDS: float = 40.0

#: The book size §9.3's figure was read at — six members, the k of
#: the ``O(kT + k²)`` the figure prices.  A book, not a campaign:
#: §9.3's 500-node sizing is what the *array* may reach, while the
#: book a policy commits to inside one replay is the handful of
#: signals its candidates are scored against, and six of them over
#: the sample spelled beside this is the shape whose arithmetic reads
#: at the figure — the anchor that keeps the constant, the docstrings
#: and the timing test from drifting apart on which book "roughly
#: 40 µs" describes.
RANK1_UPDATE_SIZING_BOOK = 6

#: The sample length §9.3's figure was read at — 48 shared periods,
#: the T of the ``O(kT + k²)``, for ``kT + k² = 324`` element
#: operations: the count the figure prices, and the term that scales
#: when either half of the shape does.  A sample this size is a
#: quarter-year of daily rebalances; §9.3's 2000-period campaigns
#: widen it forty-fold, which is the scaling caveat the module's
#: docstring and feature 180's downsample both stand ready for.
RANK1_UPDATE_SIZING_SAMPLE = 48


# -- The answer, as a value ----------------------------------------------------------


@dataclass(frozen=True)
class Rank1Update:
    """One candidate's marginal information ratio — the update's answer.

    The one number feature 178's sentence names — :attr:`ir_marginal`
    — with the terms it reduces from, because a scalar alone cannot be
    checked or read: the three information ratios the increment is
    measured between, the mean and standard deviation each ratio
    reduces from, the covariances that say how the candidate sits
    against the book, and the axes the whole measurement ran on (the
    campaign, the horizon, the book's canonical membership, the shared
    sample, the candidate's own node id).  Moments, deliberately, and
    not per-date series: the resident array owns the cells, the
    evaluator's record owns the series, and this record carries the
    handful of floats that check the scalar without recreating an
    ``O(T)`` residency.

    Frozen and validated at construction (see the module docstring):
    a value built by hand fails here rather than answering a marginal
    no update measured — every ratio must be its own mean over its own
    standard deviation, the increment must be the difference of its
    own two ratios, the combined mean must be the equal-weight fold of
    the book's and the candidate's, and the combined variance must be
    the quadratic fold of the book's, the candidate's and the
    covariance between them.
    """

    #: The campaign the book and the candidate were measured in — the
    #: factor's own, checked against the array's before any arithmetic.
    campaign_id: str
    #: The horizon axis the measurement ran on — the factor's and the
    #: array's, one axis or no update.
    horizon: int
    #: The candidate the update scored — its row of the resident array.
    node_id: str
    #: The book the candidate was scored against — the factor's
    #: canonical axis, restated so the answer names what it increment.
    node_ids: tuple[str, ...]
    #: The shared sample — the periods every member and the candidate
    #: were measured on, the factor's own column axis.
    periods: tuple[dt.date, ...]
    #: How many signals the book held — the denominator of the book
    #: weight, ``k`` of §9.3's ``O(kT + k²)``.
    book_size: int
    #: How many periods the sample measured — ``T`` of the same
    #: arithmetic, the evidence behind every moment here.
    dates: int
    #: The equal-weight book's information ratio — ``IR(book)``.
    book_ir: float
    #: The equal-weight book-plus-candidate information ratio —
    #: ``IR(book ∪ {v})``.
    combined_ir: float
    #: The candidate's own standalone information ratio — feature 80's
    #: question, answered as a term rather than computed as a metric.
    candidate_ir: float
    #: ``combined_ir − book_ir`` — ``ir_marginal``, the increment the
    #: feature's sentence returns.
    ir_marginal: float
    #: The equal-weight book's mean per-date return over the sample.
    book_mean: float
    #: The equal-weight book's population standard deviation —
    #: ``‖Lᵀ·1‖/k``, the factor's own quadratic form.
    book_std: float
    #: The combined book-plus-candidate mean — the equal-weight fold
    #: ``(k·book_mean + candidate_mean)/(k + 1)``.
    combined_mean: float
    #: The combined book-plus-candidate population standard deviation —
    #: ``√(‖Lᵀ·1 + w‖² + d²)/(k + 1)``, the rank-1-updated factor's
    #: quadratic form, never materialised as a buffer.
    combined_std: float
    #: The candidate's mean per-date return over the sample.
    candidate_mean: float
    #: The candidate's population standard deviation — ``σ_v``, the
    #: variance the update splits into explained and residual.
    candidate_std: float
    #: The covariance of the equal-weight book's per-date return with
    #: the candidate's — ``Σᵢ γᵢ``, the direction the candidate pushes
    #: the book, and the term the combined variance folds twice.
    book_candidate_covariance: float
    #: The variance of the candidate the book explains — ``wᵀw`` with
    #: ``L·w = γ``: the part of ``σ_v²`` the factor accounts for.
    explained_variance: float
    #: The variance the candidate adds — ``d² = σ_v² − wᵀw``, the new
    #: pivot of the rank-1-updated factor, strictly positive or the
    #: update refused the candidate as one the book already spans.
    residual_variance: float

    def __post_init__(self) -> None:
        if not isinstance(self.campaign_id, str) or not self.campaign_id.strip():
            raise ArtifactRank1UpdateError(
                f"a rank-1 update names the campaign its book and candidate "
                f"were measured in — got {self.campaign_id!r}; the answer is "
                "one measurement of one campaign's nodes, and a value that "
                "cannot say which campaign's cannot say what it increments"
            )
        horizon = _translated(_validated_horizon, self.horizon)
        if not isinstance(self.node_id, str) or not self.node_id:
            raise ArtifactRank1UpdateError(
                f"a rank-1 update names the candidate it scored — got "
                f"{self.node_id!r}; the candidate is a node of the resident "
                "array, and an update that cannot name its candidate cannot "
                "say whose increment it answers"
            )
        members = _translated(
            _validated_members, self.node_ids, normalize=False
        )
        periods = _translated(_validated_sample, self.periods)
        k = len(members)
        if len(periods) < k + 2:
            raise ArtifactRank1UpdateError(
                f"a rank-1 update of a {k}-member book was measured over "
                f"{len(periods)} sample periods — too few: the augmented book "
                f"holds {k + 1} centered T-vectors in the "
                f"{len(periods) - 1}-dimensional subspace centering leaves, "
                f"so it needs T ≥ {k + 2} or the candidate is singular by "
                "construction and no update of it exists"
            )
        if self.node_id in members:
            raise ArtifactRank1UpdateError(
                f"the book already holds the candidate {self.node_id!r}; "
                "ir_marginal is the increment a candidate *adds* to a book, "
                "and a signal the book already holds adds none — the "
                "precompute would refuse the doubled member and the update "
                "refuses the doubled candidate, for the same reason"
            )
        if isinstance(self.book_size, bool) or not isinstance(self.book_size, int):
            raise ArtifactRank1UpdateError(
                f"a rank-1 update's book_size is an integer signal count — "
                f"got {self.book_size!r}"
            )
        if self.book_size != k:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says its book holds {self.book_size} "
                f"members but its own node_ids hold {k}; the count is the "
                "denominator of every weight here, and a record whose "
                "denominator disagrees with its own axis is a record no "
                "reader can size"
            )
        if isinstance(self.dates, bool) or not isinstance(self.dates, int):
            raise ArtifactRank1UpdateError(
                f"a rank-1 update's dates is an integer period count — got "
                f"{self.dates!r}"
            )
        if self.dates != len(periods):
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says it measured {self.dates} dates but "
                f"its own periods hold {len(periods)}; the count is the "
                "denominator of every moment here, and a record that "
                "disagrees with its own sample is a record no reader can "
                "size the evidence behind"
            )
        for field in (
            "book_ir",
            "combined_ir",
            "candidate_ir",
            "ir_marginal",
            "book_mean",
            "book_std",
            "combined_mean",
            "combined_std",
            "candidate_mean",
            "candidate_std",
            "book_candidate_covariance",
            "explained_variance",
            "residual_variance",
        ):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ArtifactRank1UpdateError(
                    f"a rank-1 update's {field} is a number — got {value!r}"
                )
            if not math.isfinite(float(value)):
                raise ArtifactRank1UpdateError(
                    f"a rank-1 update's {field} is not finite ({value!r}); a "
                    "NaN or ±inf would reach the node record dressed as a "
                    "measurement"
                )
            object.__setattr__(self, field, float(value))
        for field in ("book_std", "combined_std", "candidate_std"):
            if getattr(self, field) <= 0.0:
                raise ArtifactRank1UpdateError(
                    f"a rank-1 update's {field} is strictly positive — got "
                    f"{getattr(self, field)!r}; a standard deviation of zero "
                    "names an information ratio that is a division by zero, "
                    "and the update would have refused the constant side "
                    "before answering"
                )
        if self.explained_variance < 0.0:
            raise ArtifactRank1UpdateError(
                f"a rank-1 update's explained_variance is a squared norm — "
                f"non-negative, got {self.explained_variance!r}; a negative "
                "value is a book that explains away more variance than the "
                "candidate holds, which no covariance of one sample admits"
            )
        if self.residual_variance <= 0.0:
            raise ArtifactRank1UpdateError(
                f"a rank-1 update's residual_variance is strictly positive — "
                f"got {self.residual_variance!r}; it is the new pivot of the "
                "rank-1-updated factor, and a zero or negative one is a "
                "candidate the book already spans — the verdict the update "
                "takes before answering, never a value it answers with"
            )
        # Each ratio must be its own mean over its own standard deviation,
        # and the marginal their difference — the self-consistency that
        # makes the record a check rather than a claim, the same defence
        # the evaluator's record applies to its per-date series.
        if self.book_ir != self.book_mean / self.book_std:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says book_ir is {self.book_ir!r} but its "
                f"own book_mean/book_std is "
                f"{self.book_mean / self.book_std!r}; the record disagrees "
                "with itself — a scalar the node record would trust and be "
                "wrong by"
            )
        if self.combined_ir != self.combined_mean / self.combined_std:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says combined_ir is "
                f"{self.combined_ir!r} but its own combined_mean/"
                f"combined_std is "
                f"{self.combined_mean / self.combined_std!r}; the record "
                "disagrees with itself"
            )
        if self.candidate_ir != self.candidate_mean / self.candidate_std:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says candidate_ir is "
                f"{self.candidate_ir!r} but its own candidate_mean/"
                f"candidate_std is "
                f"{self.candidate_mean / self.candidate_std!r}; the record "
                "disagrees with itself"
            )
        if self.ir_marginal != self.combined_ir - self.book_ir:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says ir_marginal is "
                f"{self.ir_marginal!r} but its own combined_ir − book_ir is "
                f"{self.combined_ir - self.book_ir!r}; the record disagrees "
                "with itself — ir_marginal is the increment, and a record "
                "whose increment is not the difference of its own two "
                "ratios is a record no reader can trust"
            )
        if self.combined_mean != (k * self.book_mean + self.candidate_mean) / (
            k + 1
        ):
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says combined_mean is "
                f"{self.combined_mean!r} but the equal-weight fold of its "
                f"own terms is {(k * self.book_mean + self.candidate_mean) / (k + 1)!r}; "
                "the candidate joins the book at 1/(k+1) with the book "
                "re-normalised to match, and a record whose combined mean "
                "is not that fold describes a weighting no replay ran"
            )
        # The variance folds, to tolerance rather than to the bit: the
        # explained and residual parts of the candidate's variance sum to
        # it (an isclose pair, because the split is computed as a
        # subtraction), and the combined variance is the quadratic fold of
        # the book's, the candidate's and the covariance between them (an
        # inequality scaled by the magnitudes that cancel, because the
        # record computes the combined variance through the factor and the
        # fold checks it against the moments — two routes that agree to
        # rounding, not to the last bit).  A record that mixed numbers
        # from another book or sample misses by the scale itself, not by
        # a rounding.
        if not math.isclose(
            self.explained_variance + self.residual_variance,
            self.candidate_std**2,
            rel_tol=1e-12,
        ):
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says the book explains "
                f"{self.explained_variance!r} of the candidate's variance "
                f"and the candidate adds {self.residual_variance!r}, but "
                f"their sum is not the candidate's own variance "
                f"({self.candidate_std**2!r}); explained plus residual is "
                "the candidate's variance split at the book, and a record "
                "whose split does not sum is a record whose candidate "
                "nobody measured"
            )
        combined_quadratic = (k + 1) ** 2 * self.combined_std**2
        moment_fold = (
            k * k * self.book_std**2
            + 2.0 * self.book_candidate_covariance
            + self.candidate_std**2
        )
        fold_scale = (
            k * k * self.book_std**2
            + 2.0 * abs(self.book_candidate_covariance)
            + self.candidate_std**2
        )
        if abs(combined_quadratic - moment_fold) > 1e-9 * fold_scale:
            raise ArtifactRank1UpdateError(
                f"the rank-1 update says its combined variance folds from "
                f"the book's, the candidate's and the covariance between "
                f"them, but {(k + 1) ** 2}·combined_std² is "
                f"{combined_quadratic!r} against the fold's "
                f"{moment_fold!r}; the two spellings of one variance "
                "disagree, so the record was built somewhere other than "
                "this module's arithmetic — a combined ratio no replay "
                "measured"
            )
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "node_ids", members)
        object.__setattr__(self, "periods", periods)


# -- The update ----------------------------------------------------------------------


def evaluate_rank1_update(
    factor: BookCholesky, returns: CampaignReturns, candidate: str
) -> Rank1Update:
    """Evaluate one candidate as a rank-1 update — §9.3's ``ir_marginal``.

    The feature's sentence as one call: the candidate's T-vector is
    indexed out of the resident campaign array (feature 174's load,
    feature 175's pin — ``returns.row``, the array indexing §9.3 says
    ``ir_marginal`` is), aligned on the factor's shared sample, and
    scored against the book the factor factors — ``O(kT)`` to read its
    mean, its variance and its covariance with each member, ``O(k²)``
    to solve its coordinates against the factor and read both
    equal-weight variances through it, and never ``O(k²T)`` or
    ``O(k³)`` again, because the replay paid those once (feature 177).
    The answer is §6.2's ``IR(book ∪ {v}) − IR(book)`` under the
    evaluator's own coefficient — equal weights, population ``1/T``,
    :func:`fsum` — as a frozen value carrying its terms.

    ``factor`` is the precompute the replay holds; ``returns`` is the
    resident array that precompute was taken over (same campaign, same
    horizon, sample columns the array addresses); ``candidate`` is a
    node id of that array the book does not already hold.  Nothing is
    keyed, stored or held between calls — §9.3's *"no canonical-book
    cache anywhere"* — and the factor is read, never written.

    Refusals, each naming what it refuses: a factor that is not
    feature 177's record; an array that is not feature 174's; a factor
    and an array of different campaigns or horizons; a sample period
    the array's axis holds no column for; a member the array holds no
    row for, or one carrying ABSENT on a sample period (a factor not
    precomputed over this array's cells); a candidate that is not a
    node id, that the array holds no row for, that the book already
    holds, that measured no return on a sample period, that returned a
    constant over the sample, or that the book already explains to the
    last digit of this arithmetic (residual variance at or below zero
    — no jitter, ever).
    """
    if not isinstance(factor, BookCholesky):
        raise ArtifactRank1UpdateError(
            "the rank-1 update is taken against the book's precomputed "
            "Cholesky factor — a BookCholesky, feature 177's precompute, "
            f"got {type(factor).__name__} {factor!r}; §9.3's sentence hands "
            "every candidate the same reusable factor, and an update "
            "against anything else is an update against a book nobody "
            "factored"
        )
    if not isinstance(returns, CampaignReturns):
        raise ArtifactRank1UpdateError(
            "the rank-1 update reads the candidate and the book as rows of "
            "one resident campaign array — a CampaignReturns, got "
            f"{type(returns).__name__} {returns!r}; feature 174's load and "
            "feature 175's pin are the only decoder and lifetime this "
            "update trusts, and a candidate read anywhere else is a "
            "measurement this system never made"
        )
    if not isinstance(candidate, str) or not candidate:
        raise ArtifactRank1UpdateError(
            "the candidate is a node id of the resident array — got "
            f"{candidate!r} ({type(candidate).__name__}); the update scores "
            "one node's T-vector, and anything else is not a row it can "
            "index"
        )
    if factor.campaign_id != returns.campaign_id:
        raise ArtifactRank1UpdateError(
            f"the factor is the book of campaign {factor.campaign_id!r} and "
            f"the array is campaign {returns.campaign_id!r}; the factor was "
            "precomputed over this array's cells or over none of them, and "
            "an update that mixed the two would score candidates against "
            "the covariance of another campaign's measurements"
        )
    if factor.horizon != returns.horizon:
        raise ArtifactRank1UpdateError(
            f"the factor was measured at horizon {factor.horizon} and the "
            f"array at horizon {returns.horizon}; the cells the update "
            "would index are not the cells the covariance was taken over — "
            "load the campaign at the factor's horizon or precompute the "
            "factor at the array's (feature 174's pin and feature 177's "
            "precompute meet on one axis or not at all)"
        )
    column_of = {day: column for column, day in enumerate(returns.periods)}
    unaddressed = [day for day in factor.periods if day not in column_of]
    if unaddressed:
        raise ArtifactRank1UpdateError(
            "the factor's sample names period(s) the array's column axis "
            "holds none for — "
            + ", ".join(day.isoformat() for day in unaddressed)
            + f"; the shared sample is the market calendar the covariance "
            f"was measured over, and this array of campaign "
            f"{returns.campaign_id!r} is not the measurement the factor "
            "was taken over"
        )
    held_rows = set(returns.node_ids)
    unheld = [node for node in factor.node_ids if node not in held_rows]
    if unheld:
        raise ArtifactRank1UpdateError(
            f"the factor's book names node(s) the resident array of "
            f"{returns.campaign_id!r} holds no row for — "
            + ", ".join(repr(node) for node in unheld)
            + "; the members' T-vectors are rows of the array the "
            "covariance was computed over, and a factor naming rows this "
            "array does not hold was not precomputed over it"
        )
    if candidate in factor.node_ids:
        raise ArtifactRank1UpdateError(
            f"the book already holds the candidate {candidate!r}; a rank-1 "
            "update appends a signal the book does not have, and the "
            "precompute would refuse the doubled member (its covariance "
            "singular by construction) — the marginal contribution of a "
            "signal the book already holds is not this update's question"
        )
    if candidate not in held_rows:
        raise ArtifactRank1UpdateError(
            f"the candidate names a node the resident array of "
            f"{returns.campaign_id!r} holds no row for — {candidate!r}; "
            f"the array holds {len(returns.node_ids)} rows, and a "
            "candidate this campaign did not measure has no T-vector to "
            "update with"
        )

    # Array indexing: the sample's columns and the two rows the update
    # reads — the candidate's, and every member's.  Absence refuses
    # rather than zero-fills, on either side of the book.
    chosen = [column_of[day] for day in factor.periods]
    periods = factor.periods
    k = len(factor.node_ids)
    count = len(periods)
    candidate_cells = _sample_cells(
        returns.row(candidate), chosen, candidate, periods
    )
    member_cells = []
    for node in factor.node_ids:
        row = returns.row(node)
        cells = _sample_cells(row, chosen, node, periods, member=True)
        member_cells.append(cells)

    # The candidate's moments — O(T), the first term of §9.3's price.
    candidate_mean = math.fsum(candidate_cells) / count
    centered_candidate = [cell - candidate_mean for cell in candidate_cells]
    candidate_variance = (
        math.fsum(map(mul, centered_candidate, centered_candidate)) / count
    )
    if candidate_variance == 0.0:
        raise ArtifactRank1UpdateError(
            f"the candidate {candidate!r} returned a constant over the "
            f"{count} sample periods, so its variance is zero and its "
            "information ratio undefined; refusing rather than dividing by "
            "a fabricated zero — the same stance the evaluator's own "
            "coefficient takes on a constant side"
        )

    # The book-and-candidate cross-moments — O(kT), the term §9.3's
    # figure prices: each member's mean and its covariance with the
    # candidate, every sum fsum so the split is exactly rounded.
    member_means = []
    covariances = []
    for node, cells in zip(factor.node_ids, member_cells):
        mean = math.fsum(cells) / count
        member_means.append(mean)
        centered = [cell - mean for cell in cells]
        covariances.append(
            math.fsum(map(mul, centered, centered_candidate)) / count
        )

    # The O(k²) half, against the factor: the equal-weight exposure
    # Lᵀ·1 (inside the budget, recomputed per candidate because the
    # factor is a value with no state a residence could hang it in),
    # the candidate's coordinates w = L⁻¹·γ by forward substitution,
    # the residual variance d² the update exists to read, and both
    # equal-weight variances as quadratic forms through L — the
    # combined one through the rank-1-updated factor L′, which is
    # never materialised: the book is fixed during a replay, so
    # nothing downstream would ever read the buffer.
    cells = factor.factor
    exposure = [
        math.fsum(cells[m * k + i] for m in range(i, k)) for i in range(k)
    ]
    coordinates = [0.0] * k
    for j in range(k):
        coordinates[j] = (
            covariances[j]
            - math.fsum(
                map(
                    mul,
                    islice(coordinates, j),
                    islice(cells, j * k, j * k + j),
                )
            )
        ) / cells[j * k + j]
    explained_variance = math.fsum(map(mul, coordinates, coordinates))
    residual_variance = candidate_variance - explained_variance
    if residual_variance <= 0.0:
        raise ArtifactRank1UpdateError(
            f"the book already explains the candidate {candidate!r} — its "
            f"residual variance is {residual_variance!r}, not positive: the "
            f"variance it holds ({candidate_variance!r}) is not more than "
            f"the variance the factor explains away "
            f"({explained_variance!r}); either the candidate adds no "
            "dimension the book does not hold (a duplicate the search "
            "proposed — §14.1's anti-convergence clause) or the factor was "
            "not precomputed over this array's cells; no jitter is added, "
            "because a patched pivot would score an invented candidate and "
            "break the determinism §10.4 pins — the same verdict the "
            "precompute takes on a dependent member, taken here on the "
            "candidate"
        )
    augmented = [
        together + coordinate for together, coordinate in zip(exposure, coordinates)
    ]
    book_variance = math.fsum(map(mul, exposure, exposure)) / (k * k)
    combined_variance = (
        math.fsum(map(mul, augmented, augmented)) + residual_variance
    ) / ((k + 1) * (k + 1))

    # The ratios, in the record's own spelling so the value and its
    # check cannot drift apart: the combined mean is the equal-weight
    # fold of the book's mean and the candidate's, each ratio is its
    # own mean over its own standard deviation, and the marginal is
    # the difference of the two ratios it was always defined as.
    book_mean = math.fsum(member_means) / k
    combined_mean = (k * book_mean + candidate_mean) / (k + 1)
    book_std = math.sqrt(book_variance)
    combined_std = math.sqrt(combined_variance)
    candidate_std = math.sqrt(candidate_variance)
    book_ir = book_mean / book_std
    combined_ir = combined_mean / combined_std
    candidate_ir = candidate_mean / candidate_std
    return Rank1Update(
        campaign_id=factor.campaign_id,
        horizon=factor.horizon,
        node_id=candidate,
        node_ids=factor.node_ids,
        periods=factor.periods,
        book_size=k,
        dates=count,
        book_ir=book_ir,
        combined_ir=combined_ir,
        candidate_ir=candidate_ir,
        ir_marginal=combined_ir - book_ir,
        book_mean=book_mean,
        book_std=book_std,
        combined_mean=combined_mean,
        combined_std=combined_std,
        candidate_mean=candidate_mean,
        candidate_std=candidate_std,
        book_candidate_covariance=math.fsum(covariances),
        explained_variance=explained_variance,
        residual_variance=residual_variance,
    )


# -- The update's own reading and validation, spelled once ---------------------------


def _translated(call, *args, **kwargs):
    """One of the factor's shared axis validators, translated at the seam.

    The membership and sample validators are feature 177's, spelled
    once for the precompute and its record, and the horizon validator
    is feature 170's — so their refusals speak the *factor's* and the
    *store's* vocabulary (:class:`ArtifactBookFactorError`,
    :class:`ArtifactStoreError`).  A rank-1 update built by hand that
    lies about its axis broke *this* feature's contract, so the seam
    translates rather than passes the foreign class through: the
    message stays the validator's own (the offending value and the
    rule, spelled once for the whole member), the class becomes the
    update's, and a caller catching
    :class:`~artifacts.ArtifactRank1UpdateError` is never answered by
    a class it does not catch.
    """
    try:
        return call(*args, **kwargs)
    except ArtifactsError as refusal:
        raise ArtifactRank1UpdateError(
            "the rank-1 update restates the precomputed factor's own "
            f"axis, so the factor's refusal is the update's as well: {refusal}"
        ) from refusal


def _sample_cells(
    row: Any,
    chosen: list[int],
    node: str,
    periods: tuple[dt.date, ...],
    *,
    member: bool = False,
) -> list[float]:
    """One row's cells over the sample columns — absence refused, named.

    The array indexing half of §9.3's "array indexing plus a rank-1
    update": the factor's sample spells the columns, the row spells
    the node, and the two together spell the T-vector.  A cell no
    panel measured (:data:`~artifacts.ABSENT`, NaN) refuses rather
    than zero-fills — for the candidate, feature 75's absence rule
    restated; for a member, the proof the factor was not precomputed
    over this array, since the precompute's sample is by construction
    the periods every member measured.
    """
    cells = [row[column] for column in chosen]
    # NaN is the only float unequal to itself, and the only non-finite
    # value the resident buffer may carry (an inf is refused at the
    # array's own construction), so the self-compare is the absence
    # test — spelled this way rather than as a math.isnan call because
    # this is the innermost loop of §9.3's per-candidate cost, and a
    # comparison is what the figure prices.
    absent = [day for day, cell in zip(periods, cells) if cell != cell]
    if absent:
        if member:
            raise ArtifactRank1UpdateError(
                f"the book's member {node!r} carries ABSENT on "
                + ", ".join(day.isoformat() for day in absent)
                + " — periods of the sample the factor was measured over; "
                "the precompute's sample is the periods every member "
                "measured, so a hole there means the factor was not "
                "precomputed over this array's cells, and an update that "
                "zero-filled it would score candidates against a "
                "covariance the book never had"
            )
        raise ArtifactRank1UpdateError(
            f"the candidate {node!r} measured no return on "
            + ", ".join(day.isoformat() for day in absent)
            + " — periods of the sample the book was measured over; a "
            "covariance is defined over one sample measured together, and "
            "a candidate that misses a sample period is a hole in the "
            "resident array, not a zero return (feature 75's absence rule, "
            "restated for the candidate — the evaluator states it from the "
            "other side: every book signal must cover every date the "
            "candidate was priced on, and here the priced dates are the "
            "book's own sample)"
        )
    return cells
