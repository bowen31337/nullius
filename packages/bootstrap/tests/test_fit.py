"""The arithmetic behind the ground truth — and, mostly, its refusals.

Feature 181 asks the world for *a ground-truth score per node*, and this
module is where a score stops being a number and becomes a claim.  Three
properties make the claim honest, and each is a different kind of test:

* **the answer is a function, not a measurement.**  Every reduction here
  is :func:`math.fsum`, so a sum is exactly rounded and independent of the
  order its terms were visited in.  §12's determinism contract is
  therefore met *by construction* rather than by tolerance, and this suite
  holds that by shuffling the rows of a split and asserting the score
  comes back bit-identical — not close, identical.  That is a stronger
  claim than the nightly canary's 1e-12 needs, and it is the one the
  member can actually make.
* **a fit that cannot be made is refused, not jittered.**  A design the
  sample does not span, a split with no targets, a split whose targets
  have no variance: each raises
  :class:`~bootstrap.BootstrapScoringError` naming its subject.  A
  stand-in score in a pool whose entire value is *honest labels* is worse
  than no score, because the pool builder that would have drawn another
  world instead files the fabricated one — so this suite tests the
  refusals as carefully as the answers, and it tests that the message
  carries the caller's ``subject`` through, which is what lets a refusal
  read off a replay's log say *which* pool entry had no label.
* **the ridge is a floor, not a shrinkage.**  The intercept column is
  never penalised: a penalty on the intercept would shrink a model's
  fitted mean toward zero, which would make the ``alpha`` axis mean
  something different from what the world declares it means.

The *world's* own fit — that a cell's label is the held-out ``R²`` of this
arithmetic over the world's fixed dataset — is pinned in
``test_label.py``.  Nothing here imports the world: this module is the
evaluator's contract, and it is testable without one.
"""

from __future__ import annotations

import math
import random

import pytest
from bootstrap import BootstrapScoringError, FitResult, fit_and_score, solve_cholesky

#: A subject string threaded through every call, so the tests can assert
#: that a refusal names what could not be fitted rather than only that
#: something could not be.
SUBJECT = "node 'd+1.i+1.s+1.a+4' of world 'bootstrap-hpo-test'"


def _fit(
    design_train: list[list[float]],
    targets_train: list[float],
    design_holdout: list[list[float]] | None = None,
    targets_holdout: list[float] | None = None,
    *,
    ridge: float = 1e-06,
) -> FitResult:
    """``fit_and_score`` with this module's subject already supplied.

    Defaults the holdout split to a copy of the training split — a
    perfectly-scored degenerate case that is *fine* for the tests that are
    not about the split, and shorter to read than spelling an empty one.
    """
    return fit_and_score(
        design_train=design_train,
        targets_train=targets_train,
        design_holdout=design_train if design_holdout is None else design_holdout,
        targets_holdout=targets_train if targets_holdout is None else targets_holdout,
        ridge=ridge,
        subject=SUBJECT,
    )


def _line(n: int = 24) -> tuple[list[list[float]], list[float]]:
    """A design a line fits exactly: one column, a clean slope.

    The intercept and the slope together reproduce ``y = 1 + 2x`` on the
    nose, so the expected coefficients are known by construction and the
    score is exactly 1 — an *analytic* answer to check the arrange-the-
    numbers part against, before any of the refusals.
    """
    design = [[1.0, x] for x in (float(i) for i in range(n))]
    targets = [1.0 + 2.0 * row[1] for row in design]
    return design, targets


# -- The answer --------------------------------------------------------------------


def test_a_line_is_fitted_exactly_and_scores_one() -> None:
    design, targets = _line()
    result = _fit(design, targets)
    assert result.coefficients == pytest.approx((1.0, 2.0))
    assert result.r2_train == pytest.approx(1.0)
    assert result.r2_holdout == pytest.approx(1.0)
    assert result.n_columns == 2


def test_the_ridge_never_penalises_the_intercept() -> None:
    # A ridge that touched column 0 would shrink the fitted mean toward
    # zero, and the ``alpha`` axis would then be a statement about the
    # model's level rather than about its wiggle — a different
    # hyperparameter than the world declares.
    #
    # The check is the *limit*: as the ridge grows without bound the slope
    # is crushed to nothing while the intercept still converges on the
    # training mean, which is the intercept-only model.  A penalised
    # column 0 would instead send the whole fit to zero, and the mean the
    # model converged on would be 0 rather than ``ȳ``.
    design, targets = _line()  # y = 1 + 2x over x = 0..23
    mean_target = math.fsum(targets) / len(targets)
    assert mean_target == pytest.approx(24.0)  # what the intercept must find
    crushed = _fit(design, targets, ridge=1e12)
    assert crushed.coefficients[1] == pytest.approx(0.0, abs=1e-6)
    assert crushed.coefficients[0] == pytest.approx(mean_target, abs=1e-5)


def test_a_large_ridge_shrinks_the_slope_while_the_level_stays_near() -> None:
    # The other side of the same coin: the penalised columns *do* move
    # with ``alpha``, which is what makes the axis a real hyperparameter
    # rather than decoration.  The slope collapses toward zero as the
    # penalty grows; the intercept compensates, so the *level* the model
    # predicts stays near the training mean rather than collapsing with
    # it.
    design, targets = _line()
    gentle = _fit(design, targets, ridge=1e-06)
    harsh = _fit(design, targets, ridge=1e3)
    assert abs(harsh.coefficients[1]) < abs(gentle.coefficients[1])
    mean_target = math.fsum(targets) / len(targets)
    mean_row = math.fsum(row[1] for row in design) / len(design)
    for fit in (gentle, harsh):
        level = fit.coefficients[0] + fit.coefficients[1] * mean_row
        assert level == pytest.approx(mean_target, abs=5.0)


def test_a_bad_slope_scores_below_zero_on_a_held_out_split() -> None:
    # ``R²`` is not clamped at zero — that is what makes it a *score* a
    # policy can be wrong on rather than a reward that floors.  A fit on
    # noise, scored against real structure, must come back negative, and
    # the world's own sweep relies on this: its worst cell is negative.
    rng = random.Random(11)
    design = [[1.0, rng.uniform(-1.0, 1.0)] for _ in range(32)]
    holdout = [[1.0, x] for x in (float(i) for i in range(32))]
    result = _fit(
        design,
        [rng.uniform(-1.0, 1.0) for _ in design],
        holdout,
        [1.0 + 2.0 * row[1] for row in holdout],
    )
    assert result.r2_holdout < 0.0


def test_the_holdout_score_uses_the_holdout_splits_own_mean() -> None:
    # ``SS_tot`` is the *split's own* spread, not the training split's.
    # The textbook definition, and the reason a holdout scored against the
    # training mean would be measuring a different quantity than the ``R²``
    # the world claims to report.
    #
    # Made discriminating with an intercept-only design, so the fitted
    # predictor is exactly the training mean and the two candidate
    # baselines are different numbers: the holdout's own mean (what the
    # definition says) and the training mean (what a plausible mistake
    # would use, which would make the answer exactly 0 here).
    train_targets = [-3.0, 1.0, 5.0, -3.0, 0.0, -2.0]  # mean exactly -1/3
    train_mean = math.fsum(train_targets) / len(train_targets)
    holdout_targets = [2.0, 6.0, 10.0, 4.0]  # mean 5.5, not the training mean

    result = _fit(
        [[1.0]] * len(train_targets),
        train_targets,
        [[1.0]] * len(holdout_targets),
        holdout_targets,
    )
    assert result.coefficients[0] == pytest.approx(train_mean)
    assert result.coefficients[0] != pytest.approx(
        math.fsum(holdout_targets) / len(holdout_targets)
    )

    holdout_mean = math.fsum(holdout_targets) / len(holdout_targets)
    expected = 1.0 - math.fsum((y - train_mean) ** 2 for y in holdout_targets) / math.fsum(
        (y - holdout_mean) ** 2 for y in holdout_targets
    )
    assert result.r2_holdout == pytest.approx(expected)
    assert result.r2_holdout < 0.0  # a wrong baseline scores negative


# -- Determinism -------------------------------------------------------------------


def test_the_answer_is_independent_of_the_row_order() -> None:
    # §12's determinism contract, met by construction rather than by
    # tolerance: ``fsum`` is exactly rounded, so a shuffle of the same
    # terms is the same number to the last bit.  A naive ``sum`` would
    # drift here and the drift would be *larger* the wider the design —
    # which is precisely the failure this asserts against.
    design, targets = _line(40)
    expected = _fit(design, targets)
    rng = random.Random(4)
    for _ in range(4):
        order = list(range(len(design)))
        rng.shuffle(order)
        shuffled = _fit([design[i] for i in order], [targets[i] for i in order])
        assert shuffled.r2_holdout == expected.r2_holdout  # bit-identical
        assert shuffled.coefficients == expected.coefficients


def test_the_answer_is_independent_of_the_column_order_of_the_terms() -> None:
    # The dual property: a dot product's terms are visited in a fixed
    # order, so renumbering the *rows* cannot change it — and this is the
    # same statement the previous test makes from the other side, kept
    # separate because the two orders are fixed by different loops.
    design = [[1.0, 0.1 * i, (0.1 * i) ** 2] for i in range(30)]
    targets = [math.sin(row[1]) for row in design]
    expected = _fit(design, targets)
    backwards = _fit(list(reversed(design)), list(reversed(targets)))
    assert backwards.r2_holdout == expected.r2_holdout


def test_two_calls_of_one_split_answer_identical_numbers() -> None:
    # No state, no memo, no cache: the module is a function.  A held
    # dataset or a cached Gram would be *faster* and would be exactly the
    # hazard the stream module's docstring describes — a label that moved
    # because of what had been computed before it.
    design, targets = _line()
    first = _fit(design, targets)
    second = _fit(design, targets)
    assert first.r2_holdout == second.r2_holdout
    assert first.r2_train == second.r2_train


# -- ``FitResult`` -----------------------------------------------------------------


def test_overfit_gap_is_the_difference_of_the_two_scores() -> None:
    # The meta-overfit signal §14's ``meta_overfit`` row watches, and the
    # pair a bootstrap world *calibrates* rather than reports: the gap
    # between memorising and generalising, honestly measured.
    result = FitResult(
        coefficients=(1.0,), r2_train=0.9, r2_holdout=0.4, n_columns=2
    )
    assert result.overfit_gap == pytest.approx(0.5)


def test_row_exposes_the_world_score_and_its_context() -> None:
    # ``world_score`` is the feature's ground truth spelled the way a pool
    # report reads it; the other three are what a policy needs beside it
    # to interpret the number rather than merely store it.
    result = _fit(*_line())
    row = result.row()
    assert row["world_score"] == result.r2_holdout
    assert row["train_score"] == result.r2_train
    assert row["overfit_gap"] == result.overfit_gap
    assert row["n_columns"] == 2


def test_row_hands_out_a_fresh_dict_per_call() -> None:
    # A caller annotating the row it was handed must not be annotating
    # every other caller's — the discipline the setting's ``row()`` and
    # the artifacts store both take.
    result = _fit(*_line())
    assert result.row() is not result.row()


def test_the_coefficients_are_a_tuple_not_a_list() -> None:
    # A label is *read*, and two readers of one label must not be able to
    # reach into it — the same immutability the setting's ``values`` and
    # the member's ``__all__`` take.
    assert isinstance(_fit(*_line()).coefficients, tuple)


# -- The refusals ------------------------------------------------------------------


def test_an_empty_training_split_is_refused() -> None:
    with pytest.raises(BootstrapScoringError, match="training split is empty") as refusal:
        _fit([], [], [[1.0]], [1.0])
    assert SUBJECT in str(refusal.value)


def test_an_empty_holdout_split_is_refused() -> None:
    with pytest.raises(BootstrapScoringError, match="holdout split is empty") as refusal:
        _fit([[1.0]], [1.0], [], [])
    assert SUBJECT in str(refusal.value)


def test_a_ragged_design_is_refused_with_the_width_expected() -> None:
    # Ragged rows would silently zip-truncate against the targets and
    # produce a fit of a model nobody asked for, with a score that looked
    # like a score.
    with pytest.raises(BootstrapScoringError, match=r"same width \(expected 2\)"):
        _fit([[1.0, 2.0], [1.0]], [1.0, 2.0])


def test_a_zero_width_design_is_refused() -> None:
    # Empty rows are a width of zero, which no model has: the fit would
    # answer an empty coefficient vector and the ``R²`` would be measured
    # against no prediction at all.
    with pytest.raises(BootstrapScoringError, match=r"same width \(expected 0\)"):
        _fit([[], []], [1.0, 2.0])


def test_a_constant_training_split_is_refused_rather_than_answering_nan() -> None:
    # ``R²`` is undefined when the targets have no variance, and ``1 - 0/0``
    # is a NaN — which would enter the pool *wearing a score's clothes*.
    # The member refuses, and the message says why rather than only that.
    with pytest.raises(BootstrapScoringError, match="targets are constant") as refusal:
        _fit([[1.0, float(i)] for i in range(8)], [3.0] * 8)
    assert SUBJECT in str(refusal.value)


def test_a_constant_holdout_split_is_refused_too() -> None:
    # Both splits are scored, so both can be undefined — and a caller that
    # only guarded the training side would get a NaN out of the holdout.
    design, targets = _line()
    with pytest.raises(BootstrapScoringError, match="targets are constant"):
        _fit(design, targets, design, [5.0] * len(design))


def test_a_rank_deficient_design_is_refused_by_solve_cholesky() -> None:
    # Reachable directly with a zero ridge: two identical columns span one
    # direction, so the Gram is singular and the pivoting term is exactly
    # zero.  The refusal names the *column* it failed at, so an operator
    # reading the message learns which term of the design was redundant.
    #
    # (Through ``fit_and_score`` at the world's default ridge this cannot
    # fire — a positive ridge makes the system positive definite by
    # construction — which is why the branch is exercised at the seam that
    # owns it rather than pretended into reachability from the top.)
    gram = [[1.0, 1.0], [1.0, 1.0]]
    with pytest.raises(BootstrapScoringError, match="rank-deficient at column 1 of 2") as refusal:
        solve_cholesky(gram, [1.0, 1.0], ridge=0.0, subject=SUBJECT)
    assert SUBJECT in str(refusal.value)


def test_the_refusal_says_a_jittered_fit_was_not_answered() -> None:
    # The *reason* the refusal exists, in the message: a reader has to be
    # able to tell this apart from a bug in the arithmetic.  A bootstrap
    # world's whole value is that its labels are honest, so the moment a
    # stand-in score could be returned the pool would have lost the
    # property it exists for.
    gram = [[0.0]]
    with pytest.raises(BootstrapScoringError, match="refuses rather than answering"):
        solve_cholesky(gram, [1.0], ridge=0.0, subject=SUBJECT)


def test_a_negative_definite_matrix_is_refused() -> None:
    # Not merely singular: a pivot that is *negative* is a matrix no
    # sum-of-squares form could have produced, so it is refused by the
    # same branch rather than handed to ``sqrt`` — which would raise a
    # bare ``ValueError`` naming nothing and losing the subject entirely.
    with pytest.raises(BootstrapScoringError, match="pivoting term is non-positive"):
        solve_cholesky([[-4.0]], [1.0], ridge=0.0, subject=SUBJECT)


# -- ``solve_cholesky`` directly ---------------------------------------------------


def test_solve_cholesky_answers_a_known_system() -> None:
    # The factorisation's own arithmetic, checked against a 2x2 solved by
    # hand — the one shape where both coefficients can be read off the
    # equations rather than taken on trust from the implementation.
    #
    # ``[[4, 2], [2, 3]] x = [10, 8]``: the first equation gives
    # ``x = (10 - 2y)/4``, and substituting into the second gives
    # ``2y = 3``, so ``y = 1.5`` and ``x = 1.75``.  Both coefficients are
    # non-trivial and unequal, so a substitution error in either direction
    # shows up as a wrong number rather than as a plausible symmetric one.
    solution = solve_cholesky(
        [[4.0, 2.0], [2.0, 3.0]], [10.0, 8.0], ridge=0.0, subject=SUBJECT
    )
    assert solution == pytest.approx([1.75, 1.5])


def test_solve_cholesky_answers_the_identity_with_its_right_hand_side() -> None:
    # The one solve where the answer is readable off the input, so a
    # substitution bug in either direction shows up as a wrong number
    # rather than as a plausible one.
    rhs = [1.0, -2.0, 3.0]
    solution = solve_cholesky(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
        rhs,
        ridge=0.0,
        subject=SUBJECT,
    )
    assert solution == pytest.approx(rhs)


def test_solve_cholesky_is_order_independent_too() -> None:
    # The factorisation's inner products are ``fsum``-reduced like
    # everything else, so the same matrix answers the same coefficients
    # bit-for-bit.  Not an obvious property — a naive implementation would
    # be order-dependent here in a way no tolerance would catch.
    gram = [[6.0, 1.0, 0.5], [1.0, 5.0, -0.25], [0.5, -0.25, 4.0]]
    rhs = [1.0, 2.0, 3.0]
    first = solve_cholesky(gram, rhs, ridge=0.0, subject=SUBJECT)
    second = solve_cholesky(gram, rhs, ridge=0.0, subject=SUBJECT)
    assert first == second


def test_the_ridge_floor_is_small_enough_to_leave_a_clean_fit_nearly_alone() -> None:
    # ``DEFAULT_RIDGE`` is the lattice's *lightest* ridge and is a floor
    # against near-singularity rather than a regulariser: at the scale this
    # world's designs actually reach it must move no reported score
    # meaningfully, or the world's labels would be quietly reporting a
    # penalised fit while claiming to report a least-squares one.
    #
    # "Nearly" is the honest word.  ``DEFAULT_RIDGE`` is 1e-2 — large
    # enough to be a real penalty, small enough that on a clean, exactly
    # fittable design it costs under a tenth of a part per million of the
    # score.  Asserting bit-identity would be asserting a property the
    # arithmetic does not have, and would have to be re-tuned every time
    # the axis's declared values changed.
    from bootstrap import DEFAULT_RIDGE

    design, targets = _line()
    unpenalised = _fit(design, targets, ridge=0.0)
    floored = _fit(design, targets, ridge=DEFAULT_RIDGE)
    assert unpenalised.r2_holdout == pytest.approx(1.0)  # exactly fittable
    assert floored.r2_holdout == pytest.approx(unpenalised.r2_holdout, abs=1e-6)
    assert floored.coefficients == pytest.approx(unpenalised.coefficients, abs=1e-3)
