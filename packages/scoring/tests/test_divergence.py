"""Feature 260's law: the beta-four divergence penalty.

*System subtracts a beta-four term proportional to absolute divergence
between forward and backtest information coefficient, which returns the
adjusted score* (app_spec.xml, "Objective Scoring & CVaR Aggregation") —
prd §7.1's fourth line (``− β₄ · | IC_forward − IC_backtest |``, line 322)
and docs §10.3's (line 497), one of the formula's five subtractions.  The
tests here hold :mod:`scoring._divergence` to the sentence's clauses, in
order:

* **subtracts** — the term can only take away: the divergence is an
  absolute value and the coefficient is refused when negative, so the
  delta is one negated product of three non-negative factors with no
  float path that could dress the subtraction as an addition
  (:func:`test_the_penalty_never_adds`);
* **proportional to absolute divergence** — the charge is linear in the
  gap, and *symmetric* in the two figures (a signal that over-delivered
  is as badly calibrated as one that under-delivered, which is the whole
  difference between this term and prd §11's retention *ratio*), read
  as the absolute difference over the pair and never as a scalar handed
  over (:func:`test_the_charge_is_proportional_in_the_gap`,
  :func:`test_the_divergence_is_symmetric_in_the_two_figures`);
* **between forward and backtest information coefficient** — both inputs
  are information coefficients, and therefore correlations bounded in
  ``[−1, 1]``: a figure outside the bound is a number that has stopped
  being an IC and is refused rather than clamped, and an *absent* figure
  — the pick §7.1 says β₄ is not yet computable for — cannot be handed
  over at all (:func:`test_a_figure_outside_the_bound_is_refused`,
  :func:`test_an_absent_figure_cannot_be_handed_over`);
* **which returns the adjusted score** — the answer is the same frozen
  :class:`~scoring.WorldScore` with :attr:`~scoring.WorldScore.score`
  moved down through :meth:`~scoring.WorldScore.adjusted`, the identity
  and the measurement untouched, and the term composing with the bonus
  and the other penalties that ride the same seam in whatever order the
  caller applies them (:func:`test_the_charge_composes_with_the_other_terms`).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: every figure below is dyadic (halves, quarters, eighths) and the
default coefficient is a half, so every charge is an exact multiple of a
sixteenth and is checkable with ``==`` — and the composition test measures
against a score whose every figure is dyadic (``_dyadic_score``, below) so
both orderings of two terms land on the same scalar to the bit.  What
these tests deliberately do not reach: composition (``test_component.py``
— the penalty needs no component, which is itself pinned here by the
member's surface), the seat (``test_app_module.py``), and any persistence
or any read of the forward-test record (the ``replay_score`` row is
feature 255's, and reaching the record is the forward-tracking member's
data access — this seam is a function of the two figures it is handed).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest
from scoring import (
    BETA_FOUR_DEFAULT,
    IC_BOUND,
    AggregationError,
    DivergencePenaltyError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    WorldObjectiveError,
    WorldScore,
    divergence_penalty,
    orthogonality_bonus,
    switch_penalty,
    world_objective,
)

#: The three regime names the composition test's switch charge is written
#: in — feature 283's own sentence, restated here rather than imported for
#: the reason every member suite restates what it crosses (a member never
#: imports another member, and the count turns on *difference* of names).
_TREND = "high-volatility trend"
_CHOP = "low-volatility chop"

#: The one switch the composition test charges for, at the deployment's own
#: price — dyadic, so the β₅ charge is 0.125 exactly beside the β₄
#: charge's dyadic multiples.
_COST = 0.5


def _dyadic_score() -> WorldScore:
    """A world score whose every figure is exact in binary.

    Readings (3, −1, 3, −1): mean 1, deviations (2, −2, 2, −2), population
    variance 4, so ``ir_oos`` is 1/2 *exactly* — the panel feature 261's
    and 262's suites both reach for when an equality has to be a ``==``,
    used here for the same reason: two terms composed in both orders land
    on the same scalar only to the bit when every delta in the chain is
    dyadic.
    """
    return world_objective(
        "financial-campaign-01",
        "node-a",
        {
            dt.date(2026, 3, 1): 3.0,
            dt.date(2026, 3, 2): -1.0,
            dt.date(2026, 3, 3): 3.0,
            dt.date(2026, 3, 4): -1.0,
        },
    )


def _dyadic_book() -> dict[dt.date, float]:
    """A committed book orthogonal to the dyadic pick, by construction.

    Deviations (1, 1, −1, −1) pair against the pick's (2, −2, 2, −2) as
    (2, −2, −2, 2), which cancels as exact real values — so ρ is a signed
    zero to the bit and the β₆ bonus on this pair is the coefficient
    exactly (0.25), dyadic like the β₄ charge beside it, which is what
    lets the composition test assert both orderings equal.
    """
    return {
        dt.date(2026, 3, 1): 1.0,
        dt.date(2026, 3, 2): 1.0,
        dt.date(2026, 3, 3): -1.0,
        dt.date(2026, 3, 4): -1.0,
    }


# -- the charge -----------------------------------------------------------------


def test_a_backtest_the_forward_test_vindicated_is_charged_nothing(
    score: WorldScore,
) -> None:
    # The term's reason for existing, in its smallest case: two equal
    # figures are a pick whose simulation forecast its forward behaviour,
    # so there is nothing to charge however *large* the two figures are.
    # A pick at a strong 0.5 both ways is as unpenalized as one at zero
    # both ways — prd §7.1's line 329 asks for honest backtests, not
    # small ones, so the charge is on the gap and never on the level.
    for level in (0.0, 0.25, 0.5, -0.5):
        moved = divergence_penalty(
            score, ic_forward=level, ic_backtest=level
        )
        assert moved == score
        assert moved.score == score.score


def test_a_backtest_that_flattered_the_pick_is_charged_the_gap(
    score: WorldScore,
) -> None:
    # The canonical case the sentence names, and the one §C10's
    # divergence monitor watches for: a backtest IC of 0.5 against a
    # forward IC of 0.25 is a gap of a quarter, charged at the default
    # coefficient of a half — 0.125 exactly, asserted with == because a
    # charge that came out a float epsilon light would be the fixture
    # lying about its own arithmetic, not a tolerance worth honoring.
    moved = divergence_penalty(score, ic_forward=0.25, ic_backtest=0.5)
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score - 0.125
    # Everything the charge did not touch is untouched: the measurement,
    # the identity, the epoch.  The term lands beside the leading term,
    # never through it.
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


def test_the_divergence_is_symmetric_in_the_two_figures(
    score: WorldScore,
) -> None:
    # The feature's own word is *divergence*, not retention: a signal
    # that over-delivered forward is as badly calibrated as one that
    # under-delivered — both taught the meta-policy to trust a backtest
    # that does not forecast — so the two figures swap freely and the
    # charge is identical.  This is the whole difference between this
    # term and prd §11's *ratio* (``live IC ÷ backtest IC``, line 541),
    # which would read the over-delivering pick as a number above one
    # rather than as the same-sized gap it is.
    over = divergence_penalty(score, ic_forward=0.5, ic_backtest=0.25)
    under = divergence_penalty(score, ic_forward=0.25, ic_backtest=0.5)
    assert over == under
    assert over.score == score.score - 0.125
    # A pick that measured nothing forward against a strong backtest is
    # the worst case the bound admits, and it is charged in full — the
    # divergence is 0.5, not the 1.0 a ratio-based reading would reach.
    washed_out = divergence_penalty(score, ic_forward=0.0, ic_backtest=0.5)
    assert washed_out.score == score.score - 0.25


def test_the_charge_is_proportional_in_the_gap(score: WorldScore) -> None:
    # The feature's own word: *proportional to absolute divergence*.
    # Double the gap, double the charge; double the coefficient, double
    # the charge — linear in each factor separately, exactly, because
    # each is a factor of the one product the delta negates.  The gaps
    # are measured off a fixed forward figure so the proportionality is
    # in the divergence and not in either input.
    quarter = divergence_penalty(score, ic_forward=0.0, ic_backtest=0.25)
    half = divergence_penalty(score, ic_forward=0.0, ic_backtest=0.5)
    assert quarter.score == score.score - 0.125
    assert half.score == score.score - 0.25
    assert half.score == score.score - 2 * (score.score - quarter.score)
    assert (
        divergence_penalty(
            score, ic_forward=0.0, ic_backtest=0.25, beta=1.0
        ).score
        == score.score - 0.25
    )


def test_the_penalty_never_adds(score: WorldScore) -> None:
    # The spec's verb is *subtracts*, and no path can turn the term
    # around: across a sweep of figure pairs spanning the whole bound the
    # moved score is never above the handed one, and equality is earned
    # exactly where the two figures agree.  There is no float path by
    # which the subtraction could dress as an addition — the delta is one
    # negated product of three non-negative factors, with no summation
    # and no cancellation in it.
    sweep = [
        divergence_penalty(score, ic_forward=forward, ic_backtest=backtest)
        for forward in (-1.0, -0.5, 0.0, 0.5, 1.0)
        for backtest in (-1.0, -0.5, 0.0, 0.5, 1.0)
    ]
    assert all(moved.score <= score.score for moved in sweep)
    assert sum(1 for moved in sweep if moved.score == score.score) == 5


def test_the_extremes_of_the_bound_are_charged_in_full(
    score: WorldScore,
) -> None:
    # The largest divergence an information coefficient admits: a pick
    # that measured the perfect opposite of what its backtest claimed,
    # corner to corner.  At the default coefficient the gap of 2.0
    # charges a full ratio unit — visible beside a leading term of order
    # one, and the figure prd §C10's 40%-of-backtest demotion threshold
    # is a far milder version of.
    inverted = divergence_penalty(score, ic_forward=-1.0, ic_backtest=1.0)
    assert inverted.score == score.score - 2 * BETA_FOUR_DEFAULT
    assert inverted.ir_oos == score.ir_oos


def test_the_charge_composes_with_the_other_terms(score: WorldScore) -> None:
    # The β-terms ride one seam, so the charge must land on a score
    # another term has already moved — the measurement still pinned, the
    # identity still untouched — and the order the caller applies terms
    # in is the caller's.
    penalized = score.adjusted(-0.1)
    moved = divergence_penalty(penalized, ic_forward=0.0, ic_backtest=0.25)
    assert moved.score == penalized.score - 0.125
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


def test_both_orders_of_two_terms_land_on_the_same_scalar() -> None:
    # The same composition against the bonus, on figures whose every
    # delta is dyadic (a score of 0.5, a β₆ bonus of 0.25 against a book
    # orthogonal to the bit, a β₄ charge of 0.125): divergence then bonus
    # and bonus then divergence both land on 0.625, exactly — the
    # property the features landing through the same seam after this one
    # depend on, checked where float association cannot perturb it.
    scored = _dyadic_score()
    pick = {
        dt.date(2026, 3, 1): 3.0,
        dt.date(2026, 3, 2): -1.0,
        dt.date(2026, 3, 3): 3.0,
        dt.date(2026, 3, 4): -1.0,
    }
    charged = divergence_penalty(scored, ic_forward=0.25, ic_backtest=0.5)
    bonused = orthogonality_bonus(scored, pick, _dyadic_book())
    assert charged.score == 0.375
    assert bonused.score == 0.75
    assert orthogonality_bonus(
        charged, pick, _dyadic_book()
    ).score == 0.625
    assert divergence_penalty(
        bonused, ic_forward=0.25, ic_backtest=0.5
    ).score == 0.625
    # And with the switch penalty, the third term on the same seam: its
    # one crossing at the dyadic cost is 0.125 too, so all three terms
    # land on the same scalar — 0.5 + 0.25 − 0.125 − 0.125 = 0.5, the
    # score the three of them share — whichever order they are applied
    # in.  Three orders, because two would only pin one association.
    assert charged.score == 0.375
    assert switch_penalty(
        bonused, (_TREND, _CHOP), switch_cost=_COST
    ).score == 0.625
    bonus_divergence_switch = switch_penalty(
        divergence_penalty(bonused, ic_forward=0.25, ic_backtest=0.5),
        (_TREND, _CHOP),
        switch_cost=_COST,
    )
    switch_divergence_bonus = orthogonality_bonus(
        divergence_penalty(
            switch_penalty(scored, (_TREND, _CHOP), switch_cost=_COST),
            ic_forward=0.25,
            ic_backtest=0.5,
        ),
        pick,
        _dyadic_book(),
    )
    divergence_switch_bonus = orthogonality_bonus(
        switch_penalty(charged, (_TREND, _CHOP), switch_cost=_COST),
        pick,
        _dyadic_book(),
    )
    assert bonus_divergence_switch.score == 0.5
    assert switch_divergence_bonus.score == 0.5
    assert divergence_switch_bonus.score == 0.5


# -- the carrier ----------------------------------------------------------------


@dataclass(frozen=True)
class _OnlySeam:
    """A carrier exposing exactly the one attribute this law reads —
    ``adjusted`` — and nothing else, not even a measurement.

    The divergence penalty measures nothing off the pick's panel, so
    unlike the bonus it has no panel to pin and no ``ir_oos`` to
    recompute: this shape composes, and composing is what proves the
    seam validates what it reads rather than the type it was handed.
    """

    score: float

    def adjusted(self, delta: float) -> _OnlySeam:
        return _OnlySeam(self.score + delta)


def test_the_term_measures_nothing_off_the_carrier() -> None:
    # β₆ had to pin its panel against the carrier's ir_oos; β₄ has no
    # such read.  A carrier holding a scalar and the seam — no world, no
    # pick, no epoch, no measurement — is charged like any world score,
    # which is the docstring's claim that the divergence is a fact about
    # the two figures, landed beside the score it moves.
    moved = divergence_penalty(_OnlySeam(1.0), ic_forward=0.0, ic_backtest=0.25)
    assert moved.score == 1.0 - 0.125


def test_a_carrier_without_the_seam_is_refused() -> None:
    with pytest.raises(DivergencePenaltyError, match="adjusted"):
        divergence_penalty(object(), ic_forward=0.0, ic_backtest=0.25)


# -- the coefficient ------------------------------------------------------------


@pytest.mark.parametrize(
    "beta", [float("nan"), float("inf"), -0.5, -1e-9, True, "0.5", None]
)
def test_a_coefficient_that_cannot_subtract_is_refused(
    score: WorldScore, beta
) -> None:
    # NaN and ±inf are not coefficients; a negative one counterfeits a
    # bonus through the penalty seam (the spec's verb is *subtracts*);
    # a bool is an int in Python's hierarchy and not a weight; a string
    # and a None are type faults.  Every one of them is refused, and the
    # branch each lands in names its own fault.
    with pytest.raises(DivergencePenaltyError) as caught:
        divergence_penalty(
            score, ic_forward=0.0, ic_backtest=0.25, beta=beta
        )
    # Only the negative coefficient is refused on the verb's own
    # sentence — that is the branch whose message names the inversion of
    # §7.1's "honest, not merely high".  A bool is refused one step
    # earlier, by the type gate, and NaN/±inf by the finiteness gate.
    if isinstance(beta, float) and beta < 0.0:
        assert "honest" in str(caught.value)


def test_a_zero_coefficient_declines_the_charge_not_the_term(
    score: WorldScore,
) -> None:
    # Zero is admitted — an ablation the documents leave to the
    # deployment, not a contradiction of the term: a deployment that
    # zeroes β₄ has declined to price sim-reality divergence, the way
    # feature 262 admits a zeroed β₆ and feature 261 a zeroed β₅.
    assert (
        divergence_penalty(
            score, ic_forward=0.0, ic_backtest=0.5, beta=0.0
        )
        == score
    )


def test_the_default_coefficient_is_a_stated_parameterization() -> None:
    # Neither document sizes β₄ — the formula spells the term and moves
    # on — so the default is the member's own stated parameterization.
    # A half is deliberately *steeper* than β₅'s and β₆'s quarter, and
    # the test pins the difference rather than only the figure, because
    # the reason is on the feature's own sentence: §7.1 line 329 gives
    # this term the job of teaching the loop to prefer honest backtests,
    # §C10 makes live IC below 40% of backtest an automatic demotion, and
    # the whole outer loop exists to recalibrate this one number — so it
    # must charge more than a nudge.  Dyadic, so this suite's exact cases
    # stay exact.
    from scoring import BETA_FIVE_DEFAULT, BETA_SIX_DEFAULT

    assert BETA_FOUR_DEFAULT == 0.5
    assert BETA_FOUR_DEFAULT > BETA_FIVE_DEFAULT
    assert BETA_FOUR_DEFAULT > BETA_SIX_DEFAULT


# -- the two figures ------------------------------------------------------------


@pytest.mark.parametrize(
    "figure",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        1.5,
        -1.5,
        2.0,
        1.0 + 1e-9,
        -1.0 - 1e-9,
        100.0,
    ],
)
def test_a_figure_outside_the_bound_is_refused(
    score: WorldScore, figure: float
) -> None:
    # An information coefficient is a *correlation* — prd §6.1's ic_mean
    # is the mean of the per-date coefficients the decay profile measures,
    # and those are rank correlations — so it is bounded in [−1, 1] by
    # construction whatever the estimator.  A figure outside the bound is
    # not a large IC; it is a number that has stopped being one, and its
    # presence says the caller handed over something else (a z-score, a
    # hit rate, an IR) under this field name.  Refused rather than
    # clamped: clamping would charge the maximum divergence for a pair
    # that may well be honest, which fabricates in the other direction.
    # Refused on *both* sides of the pair, from either position, so the
    # gate is the figure's and not the argument order's.
    with pytest.raises(DivergencePenaltyError, match="information coefficient"):
        divergence_penalty(score, ic_forward=figure, ic_backtest=0.25)
    with pytest.raises(DivergencePenaltyError, match="information coefficient"):
        divergence_penalty(score, ic_forward=0.25, ic_backtest=figure)


def test_the_bounds_themselves_are_information_coefficients(
    score: WorldScore,
) -> None:
    # The bound is closed, not open: ±1.0 is a real information
    # coefficient — perfect rank agreement or perfect inversion — and it
    # is charged, not refused.  And IC_BOUND is exported as the figure
    # the refusals above are stated against, so a caller reporting the
    # bound names the same number the seam enforces.
    assert IC_BOUND == 1.0
    assert (
        divergence_penalty(score, ic_forward=-IC_BOUND, ic_backtest=IC_BOUND).score
        == score.score - 2 * BETA_FOUR_DEFAULT
    )
    assert (
        divergence_penalty(score, ic_forward=IC_BOUND, ic_backtest=IC_BOUND)
        == score
    )


@pytest.mark.parametrize("figure", [None, "0.25", 0.25 + 0j, [0.25], object()])
def test_a_figure_that_is_not_a_reading_is_refused(
    score: WorldScore, figure: object
) -> None:
    # An *absent* forward IC cannot be handed over at all, and that is
    # the class's sharpest edge: prd §7.1's own sentence is that β₄ "is
    # computable only for nodes that have been through the forward-test
    # queue", so a pick with no forward record has no figure — and the
    # two cheap readings of that absence are both wrong.  Read as zero,
    # it charges the pick its entire backtest on no evidence; read as
    # "no divergence", it pays it in full.  A None, a string, a complex
    # or a collection is refused here as the type fault it is, before
    # any arithmetic, so no stand-in can be mistaken for a measurement.
    with pytest.raises(DivergencePenaltyError, match="real number"):
        divergence_penalty(score, ic_forward=figure, ic_backtest=0.25)
    with pytest.raises(DivergencePenaltyError, match="real number"):
        divergence_penalty(score, ic_forward=0.25, ic_backtest=figure)


def test_an_absent_figure_cannot_be_handed_over() -> None:
    # The same law stated as the feature's own sentence, without a score
    # in the way: there is no call that means "this pick has no forward
    # record yet".  The seam takes two figures or it refuses; a caller
    # whose pick has not been through the forward-test queue must not
    # call this term, because §7.1 says β₄ is not computable for it —
    # and inventing a number to pass here would be the member reading a
    # measurement nobody made.
    with pytest.raises(DivergencePenaltyError):
        divergence_penalty(object(), ic_forward=None, ic_backtest=0.5)


@pytest.mark.parametrize("integer", [0, 1, -1])
def test_whole_number_figures_are_readings_like_any_other(
    score: WorldScore, integer: int
) -> None:
    # An int is admitted and narrowed — a whole-number IC is still an
    # IC, and ±1 is the bound itself.  A bool is refused one branch
    # earlier (it is an int in Python's hierarchy and not a reading),
    # which is why True/False are not in this parametrization.
    moved = divergence_penalty(score, ic_forward=integer, ic_backtest=0)
    assert moved.score == score.score - BETA_FOUR_DEFAULT * abs(integer)


@pytest.mark.parametrize("boolean", [True, False])
def test_a_boolean_is_not_a_reading(score: WorldScore, boolean: bool) -> None:
    # True is one keystroke from 1, and it is not a correlation: the same
    # refusal the objective's own finiteness gate makes for a bool
    # reading, held here for the two figures.
    with pytest.raises(DivergencePenaltyError, match="real number"):
        divergence_penalty(score, ic_forward=boolean, ic_backtest=0)


# -- determinism, vocabulary, surface -------------------------------------------


def test_the_same_pair_answers_the_same_charge(score: WorldScore) -> None:
    # Deterministic and pure: the same pair — asked twice, or asked on a
    # score another term has moved — answers the same charge to the last
    # bit, because the divergence is one absolute difference of two
    # validated reals and the delta one negated product of it.  There is
    # no summation whose order could matter, and no clock, store or
    # environment anywhere in the term.
    first = divergence_penalty(score, ic_forward=0.25, ic_backtest=0.5)
    again = divergence_penalty(score, ic_forward=0.25, ic_backtest=0.5)
    assert first == again
    assert first.score == score.score - 0.125


def test_the_error_is_a_sibling_of_the_others() -> None:
    # 256 refuses an ask that cannot be scored; 262 one whose bonus
    # cannot be measured; 261 one whose charge cannot be counted; 260 one
    # whose divergence cannot be read — and the repairs differ (a
    # sequestration fault, a resident-array hole, a census that has not
    # run or a mis-set price, the forward-test record), so the classes
    # stay distinguishable behind separate excepts — the reasoning that
    # keeps every sibling in this member apart, held here for the third
    # β-term to land.
    assert issubclass(DivergencePenaltyError, ScoringError)
    for other in (
        WorldObjectiveError,
        OrthogonalityError,
        SwitchPenaltyError,
        AggregationError,
        RegimeIndexError,
    ):
        assert not issubclass(DivergencePenaltyError, other)
        assert not issubclass(other, DivergencePenaltyError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend, the index, the bonus and the switch penalty, the
    # divergence charge owns no deployment state, so it adds no component
    # beside the objective and no seat beside the member's: the surface
    # it joins is the member's namespace, and the composed "scoring"
    # component stays the per-world objective — the growth pattern every
    # free seam in this workspace takes.
    import scoring

    assert "divergence_penalty" in scoring.__all__
    assert "BETA_FOUR_DEFAULT" in scoring.__all__
    assert "IC_BOUND" in scoring.__all__
    assert "DivergencePenaltyError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"
