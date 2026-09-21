"""The fit and its honest score — an exactly-rounded least squares.

This is the arithmetic behind feature 181's ground truth: given the world's
fixed dataset and one node's hyperparameters, fit the model and answer how
well it did on data it was not fitted on.  The score is the held-out
coefficient of determination, ``R²`` on the world's holdout split, and the
whole of this module exists to compute it in an arithmetic that is
*reproducible to the last bit* rather than merely accurate.

**Why not numpy — and it is not about the dependency.**  numpy is not in
this workspace, and adding it for one dense solve would be a poor trade,
but the deeper reason is §12's determinism contract.  ``numpy.linalg.lstsq``
dispatches to whichever LAPACK the deployment's wheel was built against,
and different BLAS builds sum a dot product in different orders; float
addition is not associative, so two machines would answer labels that
differ in the last bits.  §12's canary tolerance is 1e-12 and §10.6 makes
the bootstrap pool the *reference* the financial worlds are calibrated
against, so a label that moved with the C library is a label about the
machine.  Every sum below is therefore :func:`math.fsum` — exactly
rounded, and order-independent by construction — and every other operation
is a single ``+``, ``-``, ``*``, ``/`` or ``sqrt``, each of which has one
correctly rounded float64 result on any conforming platform.

**Normal equations, not QR.**  The textbook objection is real: forming
``Xᵀ X`` squares the condition number, so a solve through the normal
equations loses roughly half the significant digits a QR would keep.  It
is the right trade *here* because the conditioning is controlled rather
than hoped for: the design matrix is column-standardised on the training
split (so no column's scale can wreck the system), the features are
bounded by construction (an Irwin-Hall draw lives on ``[-6, 6]``, so no
generated row can be a wild leverage point), and
a positive ridge — the lattice's smallest ``alpha``, which
:data:`~bootstrap._world.DEFAULT_RIDGE` names — reaches every
non-intercept diagonal.  The ridge is also what makes the choice safe in
the direction that matters: at a heavy enough penalty the system is
dominated by ``alpha·I``, which is the best-conditioned matrix there is,
so a node cannot reach a pathological system by *increasing* its penalty.
What remains is a small (at most 30-odd columns) symmetric system with a
positive diagonal, and Cholesky is the stable, dependency-free way to
solve it.

**The ridge convention is the one the optimizer's.**  The penalty is
applied to every column *after* the intercept, and never to the intercept
— so no ``alpha`` can shrink the model's fitted mean toward zero, which is
what lets a zero-penalty limit be meaningful and keeps a node's
``standardize`` axis from interacting with its ``alpha`` axis in a way the
score cannot show.  This is the convention a ridge regression uses when
the response is not centred, restated: the intercept column is the
unpenalised one.

**The refusals, and what they honestly guard.**  A Cholesky pivot that is
not strictly positive raises
:class:`~bootstrap.errors.BootstrapScoringError` rather than being patched
with a jittered pivot, and a split whose targets are constant raises the
same error rather than answering an infinity.  Both are *guarantees about
what this module will never do* — answer a stand-in where it had no
number — and neither is a routine event, because the world's own ridge
floor keeps them out of reach: ``XᵀX`` is positive semidefinite by
construction, so adding a *positive* ``alpha`` to its diagonal makes
``XᵀX + ridge·I`` positive definite and the factorisation always
completes, and the world's noise gives every split variance to explain.
It is a floor rather than a magic number: the smallest value the lattice
declares, which is what makes the world's fits *total* rather than
depending on which cell a policy happens to ask for.  The refusals are
reachable through this module's own primitives — a caller may hand
:func:`fit_and_score` a design its sample does not span, or a zero ridge —
and they
are the reason a caller can rely on a :class:`FitResult` always holding a
real number rather than a ``nan`` that merely looks like one.  A stand-in
score in a pool whose whole value is *honest labels* would be worse than
no score at all: docs/nullius-tech-architecture.md §10.6's bootstrap
worlds *"give perfect labels"*, and §10.6.1's provenance rule exists to
keep exactly this class of quiet corruption out of the pool.
"""

from __future__ import annotations

import math

from .errors import BootstrapScoringError

__all__ = [
    "FitResult",
    "fit_and_score",
    "solve_cholesky",
]

#: The one place a non-finite value is admitted to the arithmetic: a
#: denominator that is exactly zero is a split with no variance, which is
#: a fact this module reports rather than one it divides by.  Everything
#: else is a comparison against zero.
_ZERO = 0.0


def solve_cholesky(
    gram: list[list[float]],
    rhs: list[float],
    *,
    ridge: float,
    subject: str,
) -> list[float]:
    """Solve ``(gram + ridge·I) · β = rhs`` for a symmetric ``gram``.

    Cholesky factorisation followed by one forward and one backward
    substitution, all in :func:`math.fsum` — the ``O(n³)`` factorisation is
    the only place a dot product is formed, and ``fsum`` makes each of
    those exactly rounded and independent of the order the terms were
    visited in (which is the property §12 needs and the reason a naive
    ``sum`` is not used even though the loop order is fixed).

    ``ridge`` is added to every diagonal from the second column onward: the
    intercept (column 0) is never penalised, the convention this module's
    docstring states and the one that keeps a penalty from shrinking a
    model's fitted mean.

    Refuses with :class:`~bootstrap.errors.BootstrapScoringError` when the
    factored matrix is not positive definite, naming ``subject`` — the
    caller's description of what could not be fitted, so the message can
    say *which* world at *which* node had no label to give.  No jitter is
    added: a pivoted-through solve would answer a plausible coefficient
    vector for a model the data does not support, which is worse than
    answering nothing.  With a positive ``ridge`` this is unreachable —
    ``gram`` is positive semidefinite, so adding a positive constant to
    its diagonal makes the sum positive definite — and the branch is the
    module's guarantee rather than its opinion, see its docstring.
    """
    size = len(gram)
    factor = [[_ZERO] * size for _ in range(size)]
    for row in range(size):
        for col in range(row + 1):
            residual = gram[row][col] - math.fsum(
                factor[row][k] * factor[col][k] for k in range(col)
            )
            if row == col:
                if col > 0:
                    residual += ridge
                if not residual > _ZERO:
                    raise BootstrapScoringError(
                        f"{subject} has no label to give: its design is "
                        f"rank-deficient at column {col} of {size} (the "
                        "pivoting term is non-positive), so the model this "
                        "cell asks for spans more than the world's own "
                        "sample does — a world whose labels are ground "
                        "truth refuses rather than answering a jittered "
                        "fit"
                    )
                factor[row][col] = math.sqrt(residual)
            else:
                factor[row][col] = residual / factor[col][col]

    forward = [_ZERO] * size
    for row in range(size):
        forward[row] = (
            rhs[row] - math.fsum(factor[row][k] * forward[k] for k in range(row))
        ) / factor[row][row]

    coefficients = [_ZERO] * size
    for row in reversed(range(size)):
        coefficients[row] = (
            forward[row]
            - math.fsum(factor[k][row] * coefficients[k] for k in range(row + 1, size))
        ) / factor[row][row]
    return coefficients


class FitResult:
    """One hyperparameter setting fitted and scored — the world's label.

    ``coefficients`` is the fitted model in the *standardised* design's
    coordinates (intercept first, then the columns
    :func:`~bootstrap._world.design_columns` names), ``r2_train`` and
    ``r2_holdout`` are the two coefficients of determination, and
    ``n_columns`` is the design width the fit actually used — the figure a
    policy reading two cells side by side needs in order to tell "a wider
    model did worse" from "a wider model was not what I asked for".

    ``r2_holdout`` is the feature's ground truth.  ``r2_train`` is carried
    beside it deliberately: the *gap* between the two is the meta-overfit
    signal the dreaming loop watches on financial worlds
    (docs/nullius-tech-architecture.md §14's ``meta_overfit`` row), and a
    bootstrap world is where that signal is *calibrated* — the honest
    label pair is the reference showing what the gap looks like when the
    score is not being gamed.
    """

    __slots__ = ("coefficients", "n_columns", "r2_holdout", "r2_train")

    def __init__(
        self,
        *,
        coefficients: tuple[float, ...],
        r2_train: float,
        r2_holdout: float,
        n_columns: int,
    ) -> None:
        self.coefficients = coefficients
        self.r2_train = r2_train
        self.r2_holdout = r2_holdout
        self.n_columns = n_columns

    @property
    def overfit_gap(self) -> float:
        """``r2_train − r2_holdout`` — how much of the fit was memorised.

        A derived figure rather than a stored one: it is a difference of
        the two numbers already held, so computing it here is the one
        spelling of it and no stored copy can drift from the pair it was
        taken from.  Positive is ordinary (a fit does better where it was
        fitted); the *size* is what the meta-selection guard reads.
        """
        return self.r2_train - self.r2_holdout

    def row(self) -> dict[str, float | int]:
        """The label as a store-shaped mapping — what a caller writes down.

        The response's own key names (§9.1's ``world_score`` shape is a
        scalar score per ``(policy, world)`` pair; this is the *world's*
        half of that pair), a fresh dict per call, never a shared one.
        """
        return {
            "world_score": self.r2_holdout,
            "train_score": self.r2_train,
            "overfit_gap": self.overfit_gap,
            "n_columns": self.n_columns,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FitResult(r2_holdout={self.r2_holdout!r}, "
            f"r2_train={self.r2_train!r}, n_columns={self.n_columns})"
        )


def fit_and_score(
    *,
    design_train: list[list[float]],
    targets_train: list[float],
    design_holdout: list[list[float]],
    targets_holdout: list[float],
    ridge: float,
    subject: str,
) -> FitResult:
    """Fit the design on the training split and score it on the holdout.

    The whole of the label computation, in one place so the two halves
    cannot be spelled differently: build the Gram matrix and the
    right-hand side over the training rows, solve with the ridge, then
    measure ``R²`` on each split against that split's *own* mean — the
    standard coefficient of determination, ``1 − SS_res / SS_tot``.

    Every reduction is :func:`math.fsum`, so the answer is exactly rounded
    and independent of the row order the split happened to present.  The
    holdout design must already be built in the *training* split's
    standardisation — :func:`~bootstrap._world.design_columns` takes the
    statistics as an argument for exactly this reason — because a holdout
    scored in its own scale would be measuring a different model than the
    one that was fitted.

    Refuses with :class:`~bootstrap.errors.BootstrapScoringError`, naming
    ``subject``, on every way the world can have no honest label: an empty
    or ragged design split, a design the sample does not span (forwarded
    from :func:`solve_cholesky`), and a split whose targets have no
    variance, for which ``R²`` is not ``0`` but undefined — answering
    ``nan`` would let a NaN into the pool wearing a score's clothes, which
    is the failure the member's ``row()`` shape and the artifacts layer's
    non-finite refusals both exist to prevent.
    """
    width = len(design_train[0]) if design_train else 0
    if not design_train:
        raise BootstrapScoringError(
            f"{subject} has no label to give: its training split is empty, "
            "so there is nothing to fit the model to"
        )
    if not design_holdout:
        raise BootstrapScoringError(
            f"{subject} has no label to give: its holdout split is empty, "
            "so there is no held-out data to score the fit against"
        )
    if width == 0 or any(len(row) != width for row in design_train):
        raise BootstrapScoringError(
            f"{subject} has no label to give: its design rows are not all "
            f"the same width (expected {width})"
        )

    gram = [
        [
            math.fsum(row[left] * row[right] for row in design_train)
            for right in range(width)
        ]
        for left in range(width)
    ]
    rhs = [
        math.fsum(row[column] * target for row, target in zip(design_train, targets_train))
        for column in range(width)
    ]
    coefficients = solve_cholesky(gram, rhs, ridge=ridge, subject=subject)
    return FitResult(
        coefficients=tuple(coefficients),
        r2_train=_r_squared(design_train, targets_train, coefficients, subject),
        r2_holdout=_r_squared(design_holdout, targets_holdout, coefficients, subject),
        n_columns=width,
    )


def _r_squared(
    design: list[list[float]],
    targets: list[float],
    coefficients: list[float],
    subject: str,
) -> float:
    """``1 − SS_res / SS_tot`` over one split, exactly rounded.

    ``SS_tot`` is measured against the split's own mean, which is the
    definition of ``R²`` for a model fitted with an intercept.  A split
    whose ``SS_tot`` is exactly zero has no variance for the fit to
    explain, and ``R²`` is undefined there rather than infinite: the
    division is refused rather than performed, for the reason this
    module's docstring gives.
    """
    mean = math.fsum(targets) / len(targets)
    total = math.fsum((target - mean) ** 2 for target in targets)
    if total == _ZERO:
        raise BootstrapScoringError(
            f"{subject} has no label to give: this split's targets are "
            "constant, so there is no variance for the fit to explain and "
            "R² is undefined — a world whose labels are ground truth "
            "refuses rather than answering an infinity dressed as a score"
        )
    residual = math.fsum(
        (target - math.fsum(coefficient * value for coefficient, value in zip(coefficients, row)))
        ** 2
        for row, target in zip(design, targets)
    )
    return 1.0 - residual / total
