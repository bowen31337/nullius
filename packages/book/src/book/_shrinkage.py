"""The covariance shrinkage — feature 302: Ledoit-Wolf before the combination.

app_spec.xml, "Portfolio Book Construction", feature 302: *System applies
Ledoit-Wolf shrinkage to the signal covariance before combination, which
returns a stabilized weight vector.*  This module is that act.  It takes the
promoted signals — the same values :func:`book.combine` reads, one step
earlier in §C8's own chain — estimates the **signal covariance** from them,
shrinks that estimate the Ledoit-Wolf way, and answers the weight vector the
shrunk covariance stabilizes::

    S        = the signals' sample covariance           (estimated, p × p)
    m        = tr(S) / p                                (the average variance)
    Σ        = ρ·m·I + (1 − ρ)·S                        (the shrunk estimate)
    v        = Σ⁻¹ · IR                                 (the stabilized direction)
    w_i      = v_i / Σ_j |v_j|                          (one unit of gross)

docs/alpha-engine-prd.md §C8 states the step inside the chain's own first
arrow — *"Signal book → IR-weighted combination **with shrinkage** →
volatility targeting → position and concentration limits → orders"* — so the
shrinkage is not a step after the combination but the qualifier *on* it, and
this module sits **before** :func:`book.combine` in the order the sentence
names: it answers the weighting the combination is to be read under, and the
combiner's own information-ratio weighting stays exactly where feature 301
pinned it.  The two agree precisely on the book where the covariance adds
nothing — orthogonal signals of equal variance shrink fully to the identity,
and the stabilized vector *is* the information-ratio weighting.

Five decisions carry the feature, and each is a pin rather than a knob:

*the covariance is the signals' own, and the symbols are its observations.*
    The signal covariance is the ``p × p`` matrix of the signals' demeaned
    per-symbol target scores, estimated over the union of the symbols the
    book covers with the maximum-likelihood divisor ``1/n`` — each symbol is
    one *joint* observation of all the signals, which is the only joint
    sample a promoted signal carries: it holds no history of itself, only the
    cross-section it was promoted on.  (The ``1/n`` convention is Ledoit &
    Wolf (2004), *"A Well-Conditioned Estimator for Large-Dimensional
    Covariance Matrices"*, Journal of Multivariate Analysis 88(2) — the
    estimator below is that paper's, spelled on the page rather than
    imported, because the member is stdlib-only and a workspace member never
    imports another workspace member.)

*the target is the scaled identity, and the intensity is estimated — never
configured.*
    The shrinkage target is ``F = m·I`` with ``m = tr(S)/p`` the average
    variance, and the intensity is the paper's own data-derived figure::

        d²  = ‖S − m·I‖² / p                     (dispersion from the target)
        b̄²  = (1/n²) Σ_s ‖x_s x_sᵀ − S‖² / p     (estimation error of S)
        ρ   = min(b̄², d²) / d²                   (clipped to [0, 1] by the min)

    with ``‖A‖² = tr(AAᵀ)/p`` the paper's normalized Frobenius norm and
    ``x_s`` one symbol's demeaned observation of all the signals.  The
    sentence names *Ledoit-Wolf*, and what that names over a bare
    *shrinkage* is precisely this: the intensity is a measurement the
    estimator takes from the sample, not a number a caller sets.  A
    ``shrinkage=`` keyword would be a knob §C8 states no figure for — the
    same boundary feature 303 draws on its target and feature 308 on its
    quarter — and a deployment that could dial the intensity to zero would
    hold the raw sample covariance wearing a stabilized name.  The one
    spelling of the shrunk matrix, :func:`_shrunk_matrix`, is shared by the
    verb and the record's own check, so the two cannot drift.

*the isotropic sample is its own target, and the intensity's limit is total.*
    When ``d² = 0`` the sample covariance already equals ``m·I``, every
    intensity answers the same matrix, and the estimator's own limit — as
    dispersion collapses, ``min(b̄², d²)/d²`` goes to one — is taken: ``ρ``
    is recorded as ``1.0`` and the shrunk estimate is the target itself.  A
    one-signal book lands here too (its ``1 × 1`` covariance is its own
    average variance), and its stabilized weight vector is the whole book —
    weight ``1.0`` — answered rather than refused, because nothing divides
    by nothing on that path and a refusal would invent a degeneracy the
    arithmetic does not have.

*the weight vector is the standing conditioned on risk — ``Σ⁻¹·IR``, gross
normalized.*
    The vector the shrunk covariance stabilizes is the solve
    ``v = Σ⁻¹ · IR`` — the weighting that maximizes the combined information
    ratio under ``Σ`` (the tangency weighting of the signals, each signal's
    IR its standing and the shrunk covariance its risk) — because inverting
    the raw sample is exactly what Ledoit-Wolf exists to make safe: the
    sample inverse amplifies the estimation noise ``b̄²`` measures, and the
    shrunk inverse damps it.  The answer is ``v`` normalized to **one unit
    of gross**, ``w_i = v_i / Σ_j |v_j|`` — the same gross-not-net
    convention feature 303 states one arrow later, read here on the
    combination's own weights: a correlated signal can stabilize to a
    *negative* weight (the hedge the arithmetic produces — a signal
    redundant with a stronger one earns its keep by fading it), the sign is
    the view, and a net divisor would divide by whatever the hedges happened
    to cancel to.

*absence is not zero, twice.*
    A book whose every signal scores every symbol at the same value has no
    dispersion at all — the demeaned observations are all zero, the sample
    covariance is the zero matrix, and there is no second moment for
    shrinkage to stabilize: refused as ``dispersionless_book``, because
    answering a weight vector from no variance would counterfeit a
    stabilization no sample supports (a one-symbol book is always this
    refusal — a cross-section of one has no dispersion after demeaning).
    And a book whose shrunk covariance has no inverse has no weight vector
    to stabilize: refused as ``singular_covariance``.  The shrunk matrix
    ``ρmI + (1−ρ)S`` is positive definite whenever ``ρ > 0``, so the second
    refusal fires only when the estimator shrank *nothing* (``b̄² = 0``:
    every observation's own outer product already equals the sample) and
    the sample is itself rank-deficient — and ``n`` demeaned observations
    span at most ``n − 1`` dimensions, so a two-symbol book of two or more
    signals is always this refusal.  A book the sample alone could not
    invert — three signals over three symbols — is *answered*, because the
    estimator shrank it off its deficiency: that rescue is the sentence's
    *stabilized* made structural.

**The record is a check rather than a claim.**  :class:`StabilizedWeights`
carries the weights (the answer), the direction the normalization reduces
from, the shrinkage intensity, the information ratios, the sample covariance
and the shrunk covariance, and construction enforces the act's own terms:
the mappings name one signal set; the intensity sits in ``[0, 1]``; the
matrices are symmetric; the shrunk covariance is exactly the recorded
intensity's mixture of the recorded sample and the scaled identity; every
weight is its direction over the direction's gross; the weights are a book
at one unit of gross; and the direction solves the shrunk covariance against
the ratios — ``Σ·v = IR``, checked with the one tolerance this module
states: the solve's round-trip through Gaussian elimination rounds, so an
exact test would refuse honest records (the exception feature 303's own
gross-one law states for its division), while a part in a million still
catches every disagreement that matters.  The identities the verb computes
with its own operations stay exact.

**What this module does not do.**  It combines nothing (feature 301's verb,
whose information-ratio weighting it does not re-open — it answers a vector
beside the combiner's, and the two are read against each other, not merged),
scales to no volatility (feature 303's), bounds no position or
concentration (feature 304's), caps no leverage (feature 308's), publishes
no final set (feature 305's) and persists no rebalance (feature 309's).  It
takes the promoted signals and answers exactly one question: *what weight
vector do these signals carry when their standing is conditioned on the
covariance Ledoit-Wolf stabilizes?*

**No new component, and the layering note.**  The act is a free function
beside the combiner, the way features 303 through 308 do: its whole input is
the signals the caller already holds, so there is nothing for the factory
to compose, nothing for a deployment to configure through the registry, and
— the feature's own point — no intensity for anyone to set: the one figure
the act produces is estimated from the sample at the call.  No
``@register``, no table, no endpoint, no migration, no seat edit, and no
third-party import — ``math``, ``collections``, ``dataclasses``, ``types``,
``typing`` and the member's own ``.errors`` — so the factory's scan, which
imports this package on every ``create_app()`` to fire its ``@register``,
pays nothing for the act beyond the import it already paid for the
combiner, and the replay path stays import-cheap.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import BookConstructionError, ShrinkageError, ShrinkageRequestError

__all__ = [
    "DISPERSIONLESS_BOOK_CODE",
    "SINGULAR_COVARIANCE_CODE",
    "StabilizedWeights",
    "stabilize_weights",
]

#: The code a *dispersionless-book* refusal opens with — every promoted
#: signal scores every symbol the book covers at the same value, so the
#: demeaned observations are all zero, the sample signal covariance is the
#: zero matrix and there is no second moment for Ledoit-Wolf shrinkage to
#: stabilize — so the refusal is greppable by the word that names it.  The
#: word is minted on the ``flat_book`` / ``leverage_above_quarter_kelly``
#: convention the workspace states for the one refusal an operator greps a
#: deployment log for: *why was this book not stabilized?*  A one-symbol
#: book is always this refusal (a cross-section of one demeans to nothing),
#: which is the same division-by-exactly-nothing shape feature 303's
#: ``flat_book`` states one arrow later — read here on the covariance's own
#: divisor rather than the book's.
DISPERSIONLESS_BOOK_CODE = "dispersionless_book"

#: The code a *singular-covariance* refusal opens with — the Ledoit-Wolf
#: shrunk signal covariance has no inverse, so no weight vector solves
#: ``Σ·w = IR``.  The shrunk matrix ``ρmI + (1−ρ)S`` is positive definite
#: whenever the intensity is positive, so this fires only when the estimator
#: shrank nothing (every observation's own outer product already equalled
#: the sample) over a rank-deficient sample — ``n`` demeaned observations
#: span at most ``n − 1`` dimensions — and the repair it names is the
#: sentence's own: more symbols, or fewer signals, because no arithmetic
#: down here invents a direction the sample does not carry.
SINGULAR_COVARIANCE_CODE = "singular_covariance"

#: A pivot at or below this fraction of the shrunk matrix's largest entry is
#: zero for every purpose a book has.  Gaussian elimination with partial
#: pivoting finds no usable pivot exactly where the matrix is singular in
#: exact arithmetic, but float noise leaves a denormal crumb there instead,
#: and solving through it would answer float noise dressed as weights — the
#: instability this feature exists to remove, re-entering through its own
#: back door.  A trillionth is far below any conditioning an honest book
#: carries and far above the crumbs degeneracy leaves.
_SINGULAR_RATIO = 1e-12

#: Sentinel for "attribute not present" when reading a signal's surface, so
#: a missing field is distinguished from one present-and-``None`` — the same
#: discipline the combiner, the guard and the companion state for their own
#: reads, keeping *the signal named nothing* apart from *the signal named
#: ``None``*.
_MISSING = object()


def _demeaned_scores(
    ids: list[str], symbols: list[str], contributions: dict[str, dict[str, float]]
) -> dict[str, list[float]]:
    """Each signal's per-symbol scores, demeaned over the book's symbols.

    The covariance the estimator wants is of the *variation* around the
    cross-sectional mean, not the level — a signal that scores every symbol
    high is not more variable for it — so each signal's scores are centred
    on their own mean before they enter any product.  The mean is an
    :func:`math.fsum` over the symbols in sorted order, so the demeaned
    observation is exact in its addition and independent of the symbols'
    order: the one spelling both the sample covariance and the intensity's
    estimation-error figure reduce from, computed once here so the two
    cannot disagree about what an observation was.
    """
    count = len(symbols)
    return {
        signal_id: [
            contributions[signal_id][symbol]
            - math.fsum(contributions[signal_id][seen] for seen in symbols) / count
            for symbol in symbols
        ]
        for signal_id in ids
    }


def _sample_covariance(
    ids: list[str], demeaned: dict[str, list[float]]
) -> dict[str, dict[str, float]]:
    """The signals' sample covariance — the matrix the sentence shrinks.

    Entry ``(i, j)`` is the mean over the book's symbols of signal ``i``'s
    and signal ``j``'s demeaned scores — the ``1/n`` maximum-likelihood
    divisor Ledoit & Wolf (2004) state, with the sums taken by
    :func:`math.fsum` so the estimate is exact in its additions and
    independent of the symbols' order.  Computed once per pair and
    mirrored, so the matrix is exactly symmetric — the property the
    record's own check then reads back.
    """
    count = len(next(iter(demeaned.values())))
    covariance: dict[str, dict[str, float]] = {}
    for row, first in enumerate(ids):
        entries: dict[str, float] = {}
        for second in ids[: row + 1]:
            product = (
                math.fsum(
                    demeaned[first][index] * demeaned[second][index]
                    for index in range(count)
                )
                / count
            )
            entries[second] = product
            if second != first:
                covariance.setdefault(second, {})[first] = product
        covariance[first] = entries
    return covariance


def _average_variance(
    ids: list[str], covariance: Mapping[str, Mapping[str, float]]
) -> float:
    """``tr(S)/p`` — the average variance, the shrinkage target's own scale.

    The one spelling of the target's scale, used by the verb and by the
    record's own mixture check, so the two cannot disagree about what ``m``
    is — the discipline :func:`book._volatility._scale` states for keeping
    one module's arithmetic from drifting.  A positive real whenever the
    book is not dispersionless, because the sample covariance of demeaned
    scores is positive semidefinite and a zero trace is the zero matrix.
    """
    return math.fsum(covariance[signal_id][signal_id] for signal_id in ids) / len(ids)


def _shrunk_matrix(
    ids: list[str],
    intensity: float,
    average: float,
    sample: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    """``ρ·m·I + (1−ρ)·S`` — the Ledoit-Wolf estimate, spelled once.

    The one spelling the verb computes with and the record's own check
    recomputes from its carried fields, so a record whose shrunk covariance
    is not its own sample under its own intensity is refused — the same
    exact-identity discipline feature 303's ``TargetWeights`` states for its
    scale, and the reason this is a function rather than an inline
    expression: the check and the verb must run *these* operations, in this
    order, or the comparison is not exact.
    """
    return {
        first: {
            second: (
                intensity * average + (1.0 - intensity) * entry
                if second == first
                else (1.0 - intensity) * entry
            )
            for second, entry in row.items()
        }
        for first, row in sample.items()
    }


def _solve(matrix: list[list[float]], vector: list[float], symbols: int) -> list[float]:
    """Solve ``matrix · x = vector`` by elimination with partial pivoting.

    The shrunk matrix is positive definite whenever the intensity is
    positive, so this solve is the well-conditioned one Ledoit-Wolf buys;
    the pivoting is partial (the largest remaining column entry), which is
    enough for a symmetric positive definite system.  A pivot at or below
    :data:`_SINGULAR_RATIO` of the matrix's own largest entry refuses with
    :class:`ShrinkageError` — see the constant for why the threshold, rather
    than a bare zero test, is the honest spelling of *singular* — naming
    both counts the refusal turns on: the signals the matrix is keyed by
    and the symbols it was estimated over.
    """
    size = len(vector)
    scale = max(abs(entry) for row in matrix for entry in row)
    rows = [matrix[index][:] + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda row: abs(rows[row][column]))
        pivot = rows[pivot_row][column]
        if abs(pivot) <= _SINGULAR_RATIO * scale:
            raise ShrinkageError(
                f"{SINGULAR_COVARIANCE_CODE}: the Ledoit-Wolf shrunk signal "
                "covariance has no inverse, so no weight vector solves "
                "Σ·w = IR. The book carries "
                f"{size} signal{'s' if size != 1 else ''} estimated over "
                f"{symbols} symbol{'s' if symbols != 1 else ''}, and "
                f"{symbols} demeaned observations span at most "
                f"{symbols - 1} dimension{'s' if symbols - 1 != 1 else ''} — "
                "the sample cannot carry a book that wide and the "
                "estimator's shrinkage was not enough to lift it off that "
                "(a two-symbol book of two or more signals is always this "
                "refusal). The repair is the sentence's own: more symbols "
                "or fewer signals — no arithmetic down here invents a "
                "direction the sample does not carry"
            )
        if pivot_row != column:
            rows[column], rows[pivot_row] = rows[pivot_row], rows[column]
        for below in range(column + 1, size):
            factor = rows[below][column] / pivot
            if factor == 0.0:
                continue
            for entry in range(column, size + 1):
                rows[below][entry] -= factor * rows[column][entry]
    answer = [0.0] * size
    for index in range(size - 1, -1, -1):
        answer[index] = (
            rows[index][size]
            - math.fsum(
                rows[index][entry] * answer[entry] for entry in range(index + 1, size)
            )
        ) / rows[index][index]
    return answer


@dataclass(frozen=True)
class StabilizedWeights:
    """The stabilized weight vector — feature 302's answer.

    The one vector :func:`stabilize_weights` returns: each signal's
    stabilized weight (the gross-normalized solve of the shrunk covariance
    against the information ratios), the direction that normalization
    reduces from, the Ledoit-Wolf intensity, and the record that makes the
    answer checkable — the ratios, the sample covariance the sentence
    shrinks and the shrunk covariance the weights solve against.  Frozen,
    for the reason :class:`book.CompositeBook` and
    :class:`book.TargetWeights` are: these are weights a caller reads a
    book's combination under, and a value that could move after it was read
    would be a stabilization that changed beneath the book it stabilized.

    The record is a check rather than a claim — construction enforces the
    act's own terms, and the identities the verb computes with its own
    operations stay exact (the mixture, the normalization), while the two
    that cannot be exact in binary arithmetic carry the stated tolerances
    (the solve's residual, the gross-one law), the exception feature 303's
    ``TargetWeights`` states for its own division.  The *policy* (a ratio
    must be strictly positive) lives in the verb — feature 301's own split
    between the value's shape and the combiner's judgment.
    """

    #: The stabilized weights — ``Σ⁻¹·IR`` normalized to one unit of gross,
    #: keyed by signal_id in sorted order so two calls over the same signals
    #: answer identical values.  A weight may be negative: the hedge a
    #: correlated signal earns, whose sign is the view.
    weights: Mapping[str, float]
    #: The solve's raw vector — the direction ``Σ⁻¹·IR`` before the gross
    #: normalization, carried so the weights are checkable against it and
    #: the residual check below has a subject.
    direction: Mapping[str, float]
    #: The Ledoit-Wolf shrinkage intensity — a measurement the estimator
    #: took from the sample, in ``[0, 1]``: 0 the raw sample, 1 the scaled
    #: identity outright.  Never a configuration.
    shrinkage: float
    #: Each signal's information ratio — the standing the solve conditions
    #: on, keyed by signal_id.
    information_ratios: Mapping[str, float]
    #: The sample signal covariance — the matrix the sentence's shrinkage
    #: is applied *to*, keyed by signal_id then signal_id, exactly
    #: symmetric.
    sample_covariance: Mapping[str, Mapping[str, float]]
    #: The Ledoit-Wolf shrunk covariance — the matrix the weights solve
    #: against, ``ρ·m·I + (1−ρ)·S`` under the carried intensity.
    covariance: Mapping[str, Mapping[str, float]]

    def weight(self, signal_id: str) -> float:
        """The stabilized weight for one signal — the vector's entry for it.

        Refuses with :class:`~book.errors.BookConstructionError` a signal
        the vector does not carry, rather than answering a fabricated zero:
        a signal the book holds no weight for is not a signal this
        stabilization weighed, and a zero would read as *this signal is
        stabilizable to nothing* — a weighting decision this act never
        made.  The message carries no code word, the reason feature 309's
        ask states for its own per-signal facts: it names the signal and
        the ones carried, and that is the whole fact.
        """
        try:
            return self.weights[signal_id]
        except KeyError:
            raise BookConstructionError(
                f"the stabilized weights carry no weight for signal "
                f"{signal_id!r}; the book carries {sorted(self.weights)}"
            ) from None

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize:
        # this value validates and freezes, like CompositeBook and
        # TargetWeights.  The ask's own facts first — a field that is not
        # what it must be is refused before any identity between fields is
        # checked — the ordering every verdict and record in this workspace
        # states.
        weights = self._captured_vector(self.weights, "weights")
        direction = self._captured_vector(self.direction, "direction")
        ratios = self._captured_vector(self.information_ratios, "information_ratios")
        object.__setattr__(self, "weights", MappingProxyType(weights))
        object.__setattr__(self, "direction", MappingProxyType(direction))
        object.__setattr__(self, "information_ratios", MappingProxyType(ratios))

        if isinstance(self.shrinkage, bool) or not isinstance(
            self.shrinkage, (int, float)
        ):
            raise ShrinkageRequestError(
                "the stabilized weights' shrinkage intensity is a finite real "
                f"in [0, 1] — got {self.shrinkage!r} "
                f"({type(self.shrinkage).__name__}); the intensity is the "
                "measurement the estimator took from the sample, and a "
                "record that states it as anything else states no "
                "stabilization"
            )
        intensity = float(self.shrinkage)
        if not math.isfinite(intensity):
            raise ShrinkageRequestError(
                "the stabilized weights' shrinkage intensity is a finite real "
                f"in [0, 1] — got {self.shrinkage!r}; a NaN or ±inf intensity "
                "mixes no matrix, and every weight solved through it would "
                "be a weight that is not one"
            )
        if intensity < 0.0 or intensity > 1.0:
            raise ShrinkageRequestError(
                "the stabilized weights' shrinkage intensity sits in "
                f"[0, 1] — got {self.shrinkage!r}; the intensity is the "
                "mixture's weight between the sample covariance and the "
                "scaled identity, and a figure outside the unit interval is "
                "neither — it extrapolates past both matrices into a "
                "covariance nobody estimated"
            )
        object.__setattr__(self, "shrinkage", intensity)

        sample = self._captured_matrix(self.sample_covariance, "sample_covariance")
        shrunk = self._captured_matrix(self.covariance, "covariance")
        object.__setattr__(self, "sample_covariance", sample)
        object.__setattr__(self, "covariance", shrunk)

        # One book read five ways: a signal weighed without the ratio,
        # direction or covariance row its weight is checked against would
        # make every check below vacuous, so the coverage is settled first.
        carried = [set(weights), set(direction), set(ratios), set(sample), set(shrunk)]
        for named in carried[1:]:
            if named != carried[0]:
                raise ShrinkageRequestError(
                    "the stabilized weights' five surfaces name one signal "
                    f"set — the weights carry {sorted(carried[0])} while "
                    f"another carries {sorted(named)}; a weight is a "
                    "signal's solve of the one covariance, so the record's "
                    "own readings must name the same signals"
                )

        ids = sorted(weights)
        # The mixture, exact: the shrunk covariance is the carried intensity
        # applied to the carried sample, recomputed by the verb's own one
        # spelling of the expression.
        expected = _shrunk_matrix(
            ids, intensity, _average_variance(ids, sample), sample
        )
        for first in ids:
            for second in ids:
                if shrunk[first][second] != expected[first][second]:
                    raise ShrinkageRequestError(
                        f"the stabilized weights say the shrunk covariance at "
                        f"({first!r}, {second!r}) is "
                        f"{shrunk[first][second]!r} but their own intensity "
                        f"{intensity!r} applied to their own sample "
                        f"({sample[first][second]!r}) gives "
                        f"{expected[first][second]!r}; the record disagrees "
                        "with itself — the shrunk covariance is "
                        "ρ·(average variance)·I + (1 − ρ)·S"
                    )

        # The normalization, exact: every weight is its direction over the
        # direction's gross, one division the verb and the check both take.
        gross = math.fsum(abs(direction[signal_id]) for signal_id in ids)
        if gross == 0.0:
            raise ShrinkageRequestError(
                "the stabilized weights' direction is the zero vector, so "
                "there is no weight vector to normalize: the solve of a "
                "covariance against positive ratios is never zero, and a "
                "record that carries a zero direction carries no "
                "stabilization at all"
            )
        for signal_id in ids:
            if weights[signal_id] != direction[signal_id] / gross:
                raise ShrinkageRequestError(
                    f"the stabilized weights say the weight for signal "
                    f"{signal_id!r} is {weights[signal_id]!r} but their own "
                    f"direction {direction[signal_id]!r} over the direction's "
                    f"gross {gross!r} gives "
                    f"{direction[signal_id] / gross!r}; the record disagrees "
                    "with itself — a weight is its direction normalized to "
                    "one unit of gross"
                )
        # The gross-one law, and the one comparison this side of the record
        # takes with a tolerance: Σ|direction/gross| is not exactly one in
        # binary arithmetic for an arbitrary direction (each division
        # rounds), so an exact test would refuse honest books — the
        # exception feature 303's TargetWeights states for the same law.
        held = math.fsum(abs(weights[signal_id]) for signal_id in ids)
        if not math.isclose(held, 1.0, rel_tol=1e-9, abs_tol=1e-12):
            raise ShrinkageRequestError(
                "the stabilized weights are a vector at one unit of gross — "
                f"they sum in absolute value to {held!r}, not 1.0; the "
                "direction is normalized to unit gross before it is called "
                "a weight, because the solve's raw scale carries the "
                "covariance's units and a weight does not"
            )

        # The solve, with the tolerance it cannot shed: the direction
        # answers the shrunk covariance against the ratios, and the
        # round-trip through Gaussian elimination rounds, so the residual is
        # compared at a part in a million — far above the elimination's own
        # noise and far below any disagreement a book could care about.
        for first in ids:
            residual = math.fsum(
                shrunk[first][second] * direction[second] for second in ids
            )
            if not math.isclose(residual, ratios[first], rel_tol=1e-6, abs_tol=1e-9):
                raise ShrinkageRequestError(
                    f"the stabilized weights say the direction for signal "
                    f"{first!r} solves the shrunk covariance against its "
                    f"ratio {ratios[first]!r}, but Σ·direction gives "
                    f"{residual!r}; the record disagrees with itself — the "
                    "direction is the solve of the shrunk covariance against "
                    "the information ratios, and a vector that does not "
                    "solve it is not the stabilization it claims"
                )

    @staticmethod
    def _captured_vector(values: Any, field: str) -> dict[str, float]:
        """Read one of the record's signal-to-real mappings, or refuse it.

        The three vector surfaces (weights, direction, ratios) are one
        shape — non-empty signal ids to finite reals — so they are read by
        one helper that names which was ill-stated.  The scalar checks are
        the discipline :func:`book._combine._validate_number` states: a
        ``bool`` is a flag where a magnitude belongs, and a ``NaN`` / ``inf``
        is not a weight, a standing or a direction at all.
        """
        if not isinstance(values, Mapping):
            raise ShrinkageRequestError(
                f"the stabilized weights' {field} must be a mapping of "
                f"signal_id to a finite real — got {type(values).__name__}"
            )
        if not values:
            raise ShrinkageRequestError(
                f"the stabilized weights' {field} must carry at least one "
                "signal — got none; a stabilized book of zero signals was "
                "never a book at all"
            )
        captured: dict[str, float] = {}
        for signal_id, value in values.items():
            if not isinstance(signal_id, str) or not signal_id.strip():
                raise ShrinkageRequestError(
                    f"the stabilized weights' {field} must be keyed by "
                    f"non-empty signal ids — got {signal_id!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ShrinkageRequestError(
                    f"the stabilized weights' {field} for signal "
                    f"{signal_id!r} must be a finite real — got {value!r} "
                    f"({type(value).__name__})"
                )
            number = float(value)
            if not math.isfinite(number):
                raise ShrinkageRequestError(
                    f"the stabilized weights' {field} for signal "
                    f"{signal_id!r} is not finite ({value!r}); a NaN or ±inf "
                    "would reach the weights dressed as a measurement, and "
                    "no normalization downstream could bound it"
                )
            captured[signal_id] = number
        return captured

    @staticmethod
    def _captured_matrix(values: Any, field: str) -> dict[str, Mapping[str, float]]:
        """Read one of the record's two covariance matrices, or refuse it.

        Both matrices are one shape — signal_id to signal_id to finite real,
        square and exactly symmetric (the sample is computed once per pair
        and mirrored, and the mixture of a symmetric matrix with the
        identity stays symmetric) — and the symmetry is *settled* here
        rather than averaged away, because a record whose ``(i, j)`` and
        ``(j, i)`` disagree is not one covariance stated twice but two, and
        which one the solve used would be the record's untold half.
        """
        if not isinstance(values, Mapping):
            raise ShrinkageRequestError(
                f"the stabilized weights' {field} must be a mapping of "
                f"signal_id to row — got {type(values).__name__}"
            )
        if not values:
            raise ShrinkageRequestError(
                f"the stabilized weights' {field} must carry at least one "
                "signal's row — got none; a covariance of no signals was "
                "never a covariance at all"
            )
        captured: dict[str, dict[str, float]] = {}
        for signal_id, row in values.items():
            if not isinstance(signal_id, str) or not signal_id.strip():
                raise ShrinkageRequestError(
                    f"the stabilized weights' {field} must be keyed by "
                    f"non-empty signal ids — got {signal_id!r}"
                )
            if not isinstance(row, Mapping):
                raise ShrinkageRequestError(
                    f"the stabilized weights' {field} row for signal "
                    f"{signal_id!r} must be a mapping of signal_id to a "
                    f"finite real — got {type(row).__name__}"
                )
            entries: dict[str, float] = {}
            for other, value in row.items():
                if not isinstance(other, str) or not other.strip():
                    raise ShrinkageRequestError(
                        f"the stabilized weights' {field} row for signal "
                        f"{signal_id!r} must be keyed by non-empty signal "
                        f"ids — got {other!r}"
                    )
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ShrinkageRequestError(
                        f"the stabilized weights' {field} at "
                        f"({signal_id!r}, {other!r}) must be a finite real — "
                        f"got {value!r} ({type(value).__name__})"
                    )
                number = float(value)
                if not math.isfinite(number):
                    raise ShrinkageRequestError(
                        f"the stabilized weights' {field} at "
                        f"({signal_id!r}, {other!r}) is not finite "
                        f"({value!r}); a NaN or ±inf covariance entry is "
                        "not a co-movement, and every weight solved through "
                        "it would be unboundable"
                    )
                entries[other] = number
            captured[signal_id] = entries
        for first, row in captured.items():
            for second, entry in row.items():
                if second not in captured or captured[second].get(first) != entry:
                    raise ShrinkageRequestError(
                        f"the stabilized weights' {field} is exactly "
                        f"symmetric — ({first!r}, {second!r}) is "
                        f"{entry!r} but ({second!r}, {first!r}) is not the "
                        f"same; a covariance that disagrees with itself "
                        "across its diagonal is two matrices, and which one "
                        "the solve used is the record's untold half"
                    )
        return {first: MappingProxyType(row) for first, row in captured.items()}


def stabilize_weights(signals: Iterable[object]) -> StabilizedWeights:
    """Shrink the signal covariance Ledoit-Wolf and answer the stabilized
    weights — 302's act.

    Feature 302's verb, in the order the refusals must fire.  ``signals`` is
    the promoted signals — the same values :func:`book.combine` reads: each
    a :class:`book.PromotedSignal` or any object exposing the same
    ``signal_id`` / ``information_ratio`` / ``target_scores`` surface, read
    duck-typed because a member never isinstance-gates the value a
    composition seam hands out — and the answer is a frozen
    :class:`StabilizedWeights` carrying the gross-normalized solve of the
    Ledoit-Wolf shrunk covariance against the information ratios.

    The steps, in the order they must happen, each refusal leaving no value:
    (1) collect the signals, refusing an empty set as ``empty_book``; (2)
    read each signal's ``signal_id``, ``information_ratio`` and
    ``target_scores`` with feature 301's own refusals — ``unnamed_signal``,
    ``duplicate_signal``, ``non_finite_ir``, ``non_positive_ir``,
    ``signal_without_scores``, ``non_finite_score`` — the same facts about
    the same surface the combiner reads, one step earlier on the chain, in
    this act's own class; (3) require full coverage over the union symbol
    set, refusing a gap as ``uncovered_symbol``; (4) estimate the sample
    covariance of the demeaned scores over the symbols, refusing a book
    with no dispersion as ``dispersionless_book``; (5) take the Ledoit-Wolf
    intensity from the sample — ``min(b̄², d²)/d²``, total when the sample
    is already its own target; (6) form the shrunk covariance and solve it
    against the ratios, refusing a matrix with no inverse as
    ``singular_covariance``; (7) normalize the solve to one unit of gross
    and answer the :class:`StabilizedWeights`, whose construction re-checks
    the mixture, the normalization and the solve.

    Deterministic and order-independent: signals and symbols are read in
    sorted order and every sum is an :func:`math.fsum`, so a re-run over
    the same signals in a different order answers an identical record, and
    two deployments handed the same book read the same stabilization.

    **The answer may carry a negative weight, and that is the point.**  A
    signal correlated with a stronger one stabilizes to a hedge — the
    arithmetic's way of saying the book already holds that view — and the
    sign is preserved by the gross normalization (feature 303's own
    convention, read one arrow earlier: a net divisor would divide by
    whatever the hedges cancelled to).  The information-ratio weighting
    feature 301 answers cannot hedge, because every ratio is positive;
    this vector can, because it conditions the standing on the covariance
    — which is exactly what the sentence's *before combination* buys: a
    weighting that knows how the signals move together before they are
    combined.
    """
    if signals is None:
        raise ShrinkageRequestError(
            "empty_book: stabilize_weights takes the promoted signals whose "
            "covariance it shrinks, got None; hand the promoted signals, or "
            "an empty iterable to be refused as empty_book"
        )
    if isinstance(signals, (str, bytes)) or not isinstance(signals, Iterable):
        raise ShrinkageRequestError(
            "empty_book: stabilize_weights takes an iterable of promoted "
            f"signals, got {type(signals).__name__}; the signals are the "
            "book whose covariance is estimated"
        )
    collected = list(signals)
    if not collected:
        raise ShrinkageRequestError(
            "empty_book: stabilize_weights was handed no promoted signals, "
            "so there is no covariance to estimate and no weight vector to "
            "stabilize; a book of zero signals has neither"
        )

    information_ratios: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    for signal in collected:
        raw_id = getattr(signal, "signal_id", _MISSING)
        if raw_id is _MISSING or not isinstance(raw_id, str) or not raw_id.strip():
            raise ShrinkageRequestError(
                "unnamed_signal: a promoted signal carries no signal_id to "
                f"attribute a stabilized weight to, got {raw_id!r}"
            )
        signal_id = raw_id.strip()
        if signal_id in information_ratios:
            raise ShrinkageRequestError(
                f"duplicate_signal: two promoted signals carry signal_id "
                f"{signal_id!r}, so no covariance could be attributed to one "
                "set of signals; one signal, one id"
            )
        raw_ir = getattr(signal, "information_ratio", _MISSING)
        if raw_ir is _MISSING:
            raise ShrinkageRequestError(
                f"non_finite_ir: promoted signal {signal_id!r} carries no "
                "information_ratio; a signal that states no standing has "
                "nothing for the solve to condition"
            )
        if isinstance(raw_ir, bool) or not isinstance(raw_ir, (int, float)):
            raise ShrinkageRequestError(
                f"non_finite_ir: promoted signal {signal_id!r}'s "
                f"information_ratio must be a finite real, got {raw_ir!r}"
            )
        ir = float(raw_ir)
        if not math.isfinite(ir):
            raise ShrinkageRequestError(
                f"non_finite_ir: promoted signal {signal_id!r}'s "
                f"information_ratio is not finite ({raw_ir!r}); a NaN or ±inf "
                "would reach the stabilized weights dressed as a standing"
            )
        if ir <= 0.0:
            raise ShrinkageRequestError(
                f"non_positive_ir: promoted signal {signal_id!r}'s "
                f"information_ratio is {ir!r}, so its standing to weight the "
                "book is undefined; a non-positive ratio is refused rather "
                "than zero-weighted, because silently dropping a losing "
                "signal would hide a portfolio decision (feature 301's own "
                "line, read before the combination)"
            )

        raw_scores = getattr(signal, "target_scores", _MISSING)
        if raw_scores is _MISSING or not isinstance(raw_scores, Mapping):
            raise ShrinkageRequestError(
                f"signal_without_scores: promoted signal {signal_id!r} carries "
                "no target_scores mapping; a signal that expresses no view "
                "contributes no observation to the covariance"
            )
        if not raw_scores:
            raise ShrinkageRequestError(
                f"signal_without_scores: promoted signal {signal_id!r} carries "
                "an empty target_scores; a signal that expresses no view "
                "contributes no observation to the covariance"
            )
        scores: dict[str, float] = {}
        for symbol, score in raw_scores.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ShrinkageRequestError(
                    f"signal_without_scores: promoted signal {signal_id!r}'s "
                    f"target_scores must be keyed by non-empty symbols, got "
                    f"{symbol!r}"
                )
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise ShrinkageRequestError(
                    f"non_finite_score: promoted signal {signal_id!r}'s score "
                    f"for symbol {symbol!r} must be a finite real, got "
                    f"{score!r}"
                )
            number = float(score)
            if not math.isfinite(number):
                raise ShrinkageRequestError(
                    f"non_finite_score: promoted signal {signal_id!r}'s score "
                    f"for symbol {symbol!r} is not finite ({score!r}); a NaN "
                    "or ±inf would reach the covariance dressed as an "
                    "observation"
                )
            scores[symbol] = number

        information_ratios[signal_id] = ir
        contributions[signal_id] = scores

    # Full coverage, feature 301's own law: the covariance is estimated over
    # the symbols the book covers — the union — and every signal must
    # observe every symbol of it, or the joint sample the estimate needs is
    # a grid with holes in it.
    symbols: set[str] = set()
    for per_symbol in contributions.values():
        symbols.update(per_symbol)
    for signal_id, per_symbol in contributions.items():
        for symbol in sorted(symbols):
            if symbol not in per_symbol:
                raise ShrinkageRequestError(
                    f"uncovered_symbol: promoted signal {signal_id!r} carries "
                    f"no target score for symbol {symbol!r}, which the book "
                    "covers; every signal must observe every symbol the book "
                    "covers — the covariance is a joint sample, and a signal "
                    "that missed a symbol observed a different book"
                )

    ids = sorted(information_ratios)
    ordered_symbols = sorted(symbols)
    count = len(ordered_symbols)

    demeaned = _demeaned_scores(ids, ordered_symbols, contributions)
    sample = _sample_covariance(ids, demeaned)
    average = _average_variance(ids, sample)
    if average == 0.0:
        # The average variance of a positive semidefinite matrix is zero
        # exactly when the matrix is the zero matrix, which is exactly when
        # every demeaned observation is zero — no dispersion anywhere.
        raise ShrinkageError(
            f"{DISPERSIONLESS_BOOK_CODE}: every promoted signal scores every "
            "symbol the book covers at the same value, so the demeaned "
            "observations are all zero, the sample signal covariance is the "
            "zero matrix and there is no second moment for Ledoit-Wolf "
            f"shrinkage to stabilize. The book covers {ordered_symbols}"
            + (
                " — and a book of one symbol is always this refusal, because "
                "a cross-section of one demeans to nothing"
                if count == 1
                else ""
            )
            + ". The repair is the one that exists: hand signals whose "
            "scores vary across the symbols — a stabilization is a "
            "measurement of co-movement, and this book expresses none"
        )

    # The Ledoit-Wolf intensity, the paper's own figures: d² the sample's
    # dispersion from the scaled identity, b̄² the sample's own estimation
    # error read off the observations, the intensity their clipped ratio —
    # total when the sample is already its own target (d² = 0), the
    # estimator's limit as dispersion collapses.  Each sum is an
    # :func:`math.fsum` over sorted keys, so the figures are exact in their
    # additions and independent of every order the caller might have used.
    dispersion = math.fsum(
        (sample[first][second] - (average if second == first else 0.0)) ** 2
        for first in ids
        for second in ids
    ) / len(ids)
    estimation_error = (
        math.fsum(
            math.fsum(
                (
                    demeaned[first][index] * demeaned[second][index]
                    - sample[first][second]
                )
                ** 2
                for first in ids
                for second in ids
            )
            / len(ids)
            for index in range(count)
        )
        / count**2
    )
    intensity = (
        min(estimation_error, dispersion) / dispersion if dispersion > 0.0 else 1.0
    )

    shrunk = _shrunk_matrix(ids, intensity, average, sample)
    direction = _solve(
        [[shrunk[first][second] for second in ids] for first in ids],
        [information_ratios[signal_id] for signal_id in ids],
        count,
    )
    gross = math.fsum(abs(entry) for entry in direction)
    weights = {
        signal_id: direction[index] / gross for index, signal_id in enumerate(ids)
    }

    return StabilizedWeights(
        weights=weights,
        direction={signal_id: direction[index] for index, signal_id in enumerate(ids)},
        shrinkage=intensity,
        # Keyed in sorted order, like every mapping on the record, so two
        # calls over the same signals in a different order answer records
        # that read identically however the caller iterates them.
        information_ratios={
            signal_id: information_ratios[signal_id] for signal_id in ids
        },
        sample_covariance=sample,
        covariance=shrunk,
    )
