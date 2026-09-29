"""Feature 258's law: the beta-two null-pick penalty.

*System subtracts a beta-two term proportional to null pick rate, which
returns the planted-null penalty that calibration depends on*
(app_spec.xml, "Objective Scoring & CVaR Aggregation") — prd §7.1's second
line (``− β₂ · null_pick_rate``, line 320) and docs §10.3's (line 496),
one of the formula's five subtractions.  The tests here hold
:mod:`scoring._nullpicks` to the sentence's clauses, in order:

* **subtracts** — the term can only take away: the rate is a fraction and
  therefore non-negative, the coefficient is refused when negative, and
  the delta is one negated product of two non-negative factors
  (:func:`test_the_penalty_never_adds`,
  :func:`test_the_charge_is_proportional_in_each_factor`);
* **a beta-two term proportional to null pick rate** — the charge is
  linear in each factor, the rate is *the caller's figure* (prd §4.4's
  fraction of committed picks that were planted nulls) handed over rather
  than derived here, both ends of the ``[0, 1]`` interval are measured
  states that are honored, and the figure is **not** reweighted to a
  deployment base rate, which is ``FDR_deploy``'s arithmetic and not this
  term's (:func:`test_a_clean_campaign_is_charged_nothing`,
  :func:`test_every_pick_a_null_charges_the_whole_coefficient`,
  :func:`test_the_rate_is_taken_as_handed_not_reweighted`);
* **which returns the planted-null penalty that calibration depends on** —
  the answer is the same frozen :class:`~scoring.WorldScore` with
  :attr:`~scoring.WorldScore.score` moved down through
  :meth:`~scoring.WorldScore.adjusted`, the identity and the measurement
  untouched, and the term composing with the bonus and the penalties that
  ride the same seam in whatever order the caller applies them
  (:func:`test_the_charge_composes_with_the_other_terms`,
  :func:`test_both_orders_of_two_terms_land_on_the_same_scalar`).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: the default coefficient is 0.5 and the rates below are dyadic,
so every charge is exact in binary and the law's own arithmetic is the
only thing any ``==`` here is asserting — the whole suite is
``pytest.approx``-free on purpose.  What these tests deliberately do not
reach: composition (``test_component.py`` — the penalty needs no
component, which is itself pinned here by the member's surface), the
*computation* of the rate (feature 265's
scorer process, which holds the sidecar key; this seam is a function of
the number it answers), and any persistence (the ``replay_score`` row is
feature 255's, and it already carries the score and the β).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import pytest
from scoring import (
    BETA_FIVE_DEFAULT,
    BETA_FOUR_DEFAULT,
    BETA_SIX_DEFAULT,
    BETA_THREE_DEFAULT,
    BETA_TWO_DEFAULT,
    RATE_BOUND,
    AggregationError,
    DeflationPenaltyError,
    DivergencePenaltyError,
    NullPickPenaltyError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    WorldObjectiveError,
    WorldScore,
    deflation_penalty,
    divergence_penalty,
    null_pick_penalty,
    orthogonality_bonus,
    switch_penalty,
    world_objective,
)

#: The switch cost the composition test charges for, at the deployment's
#: own price — dyadic, and the same figure the sibling suites compose
#: with, so the terms' charges are comparable beside each other.
_COST = 0.5

#: The forward/backtest information-coefficient gap the composition test
#: lands beside this term's charge — a half unit between two dyadic
#: figures, so β₄'s product over it is exact.
_GAP = 0.5

#: The two regime names the composition test's switch charge is written
#: in — restated here rather than imported for the reason every member
#: suite restates what it crosses (a member never imports another member,
#: and the count turns on *difference* of names).
_TREND = "high-volatility trend"
_CHOP = "low-volatility chop"


@dataclass(frozen=True)
class _OnlySeam:
    """A carrier exposing exactly the one attribute this law reads —
    ``adjusted`` — and nothing else, not even a measurement.

    The null-pick penalty measures nothing off the pick's panel, so unlike
    the bonus it has no panel to pin and no ``ir_oos`` to recompute: this
    shape composes, and composing is what proves the seam validates what
    it reads rather than the type it was handed.
    """

    score: float

    def adjusted(self, delta: float) -> _OnlySeam:
        return _OnlySeam(self.score + delta)


@dataclass(frozen=True)
class _PooledView:
    """A stand-in for the ``K_effective`` derivation, for the one
    composition check that lands β₃ beside this term.

    The same one-attribute shape the deflation suite's view carries: the
    figure that term consumes is ``total``, and nothing else here needs to
    know how a ledger derives it.
    """

    total: int


def _dyadic_score() -> WorldScore:
    """A world score whose every figure is exact in binary.

    Readings (3, −1, 3, −1): mean 1, deviations (2, −2, 2, −2),
    population variance 4, so ``ir_oos`` is 1/2 *exactly* — the same panel
    the switch and orthogonality suites reach for when an equality has to
    be a ``==``.
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
    zero to the bit and the beta-six bonus on this pair is the coefficient
    exactly (0.25), dyadic like the charge beside it, which is what lets
    the composition test assert both orderings equal.
    """
    return {
        dt.date(2026, 3, 1): 1.0,
        dt.date(2026, 3, 2): 1.0,
        dt.date(2026, 3, 3): -1.0,
        dt.date(2026, 3, 4): -1.0,
    }


# -- the charge -----------------------------------------------------------------


def test_the_charge_is_the_coefficient_times_the_rate(score: WorldScore) -> None:
    # The feature's own arithmetic: beta-two times the null pick rate, one
    # product, negated.  A campaign that committed to a null in one world
    # of four (rate 0.25) is charged 0.125 of a ratio unit at the default
    # coefficient — dyadic, asserted with == because a charge that came
    # out a float epsilon light would be a fixture lying about its own
    # arithmetic, not a tolerance worth honoring.  Everything the charge
    # did not touch is untouched: the measurement, the identity, the
    # epoch.  The term lands beside the leading term, never through it.
    moved = null_pick_penalty(score, null_pick_rate=0.25)
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score - BETA_TWO_DEFAULT * 0.25
    assert moved.score == score.score - 0.125
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


def test_a_clean_campaign_is_charged_nothing(score: WorldScore) -> None:
    # Rate zero is prd §4.4's other measured state: a campaign whose every
    # committed pick was a real node.  There is no false discovery to
    # charge, so the returned score equals the handed one *field for
    # field* — the delta is a negated product whose rate factor is zero,
    # and adding negative zero to a float is the identity.  The term is
    # still callable: it declines the charge rather than refusing to be
    # asked, the same stance the deflation term takes toward K = 0.
    moved = null_pick_penalty(score, null_pick_rate=0.0)
    assert moved == score
    assert moved.score == score.score
    # An int zero is the same measurement as a float zero — a caller whose
    # count arithmetic produced a whole number has measured the same fact.
    assert null_pick_penalty(score, null_pick_rate=0) == score


def test_every_pick_a_null_charges_the_whole_coefficient(
    score: WorldScore,
) -> None:
    # The interval's other end is a measurement too, and the worst one the
    # mechanism can produce: every committed pick landed on a planted
    # null, so the rate is 1.0 and the charge is the coefficient entire.
    # Admitting the endpoint is deliberate — refusing it would make the
    # worst campaign the mechanism can produce a figure no consumer may
    # state, the same reason the deflation term admits K = 0.
    moved = null_pick_penalty(score, null_pick_rate=RATE_BOUND)
    assert moved.score == score.score - BETA_TWO_DEFAULT
    assert moved.score == score.score - 0.5


def test_the_charge_is_proportional_in_each_factor(score: WorldScore) -> None:
    # The feature's own word: *proportional to null pick rate*.  Double
    # the rate, double the charge; double the coefficient, double the
    # charge — linear in each factor separately, exactly, because each is
    # a factor of the one product the delta negates.
    once = null_pick_penalty(score, null_pick_rate=0.125)
    twice = null_pick_penalty(score, null_pick_rate=0.25)
    assert once.score == score.score - 0.0625
    assert twice.score == score.score - 2 * (score.score - once.score)
    assert null_pick_penalty(score, null_pick_rate=0.125, beta=1.0).score == (
        score.score - 2 * (score.score - once.score)
    )
    # A zeroed coefficient is an ablation the documents leave to the
    # deployment: the term is charged nothing whatever the rate.
    assert null_pick_penalty(score, null_pick_rate=1.0, beta=0.0) == score


def test_the_rate_is_taken_as_handed_not_reweighted(score: WorldScore) -> None:
    # The rate is the campaign's own realized false discovery rate — what
    # the policy *did* — and this term applies no reweighting to it.  The
    # base-rate projection into a 90%-null deployment (prd §4.1.3's
    # FDR_deploy at π₀ ≈ 0.9) is feature 267's arithmetic and feature
    # 268's headline; folding it in here would make β₂ a function of a
    # design constant rather than of the world just replayed.  The test
    # states the law as the *absence* of the operation: the charge is the
    # product of exactly the two numbers handed over, so a reweighted
    # figure would have to arrive as a different rate argument.
    for rate in (0.0, 0.125, 0.25, 0.5, 0.75, 1.0):
        assert null_pick_penalty(score, null_pick_rate=rate).score == (
            score.score - BETA_TWO_DEFAULT * rate
        )
        # No arithmetic on pi_0, phi or any other design constant is
        # reachable: the moved score depends on the rate alone.
        assert null_pick_penalty(score, null_pick_rate=rate).score == (
            null_pick_penalty(score, null_pick_rate=rate, beta=BETA_TWO_DEFAULT).score
        )


def test_the_penalty_never_adds(score: WorldScore) -> None:
    # The spec's verb is *subtracts*, and no path can turn the term
    # around: across a sweep of rates from a clean campaign to an all-null
    # one the moved score is never above the handed one, and equality is
    # earned exactly at zero.  There is no float path by which the
    # subtraction could dress as an addition — the delta is one negated
    # product of two non-negative factors, with no summation and no
    # cancellation in it.
    sweep = [
        null_pick_penalty(score, null_pick_rate=rate)
        for rate in (0.0, 0.125, 0.25, 0.5, 0.75, 1.0)
    ]
    assert all(moved.score <= score.score for moved in sweep)
    assert sweep[0].score == score.score
    # And monotonically worse as the rate rises: more false discoveries is
    # never the better campaign.  Compared through the *charges* rather
    # than the moved scalars, because the leading term the fixtures pin is
    # irrational and subtracting a dyadic delta from it does not preserve
    # the order of the deltas in the same bits — the law's claim is about
    # the charge, so that is what the assertion reads.
    charges = [score.score - moved.score for moved in sweep]
    assert charges == sorted(charges)
    assert charges[-1] > charges[0]


# -- the seam -------------------------------------------------------------------


def test_the_term_measures_nothing_off_the_carrier() -> None:
    # The bonus had to pin its panel against the carrier's ir_oos; this
    # term has no such read.  A carrier holding a scalar and the seam —
    # no world, no pick, no epoch, no measurement — is charged like any
    # world score, which is the docstring's claim that the charge is a
    # fact about the campaign's picks, landed beside the score it moves.
    moved = null_pick_penalty(_OnlySeam(1.0), null_pick_rate=0.25)
    assert moved.score == 1.0 - 0.125


def test_a_carrier_without_the_seam_is_refused() -> None:
    with pytest.raises(NullPickPenaltyError, match="adjusted"):
        null_pick_penalty(object(), null_pick_rate=0.25)


def test_the_charge_composes_with_the_other_terms(score: WorldScore) -> None:
    # The β-terms ride one seam, so the charge must land on a score
    # another term has already moved — the measurement still pinned, the
    # identity still untouched — and the order the caller applies terms in
    # is the caller's.
    penalized = score.adjusted(-0.1)
    moved = null_pick_penalty(penalized, null_pick_rate=0.25)
    assert moved.score == penalized.score - 0.125
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


def test_both_orders_of_two_terms_land_on_the_same_scalar() -> None:
    # The same composition against the bonus, on figures whose every delta
    # is dyadic (a score of 0.5, a bonus of 0.25 against a book orthogonal
    # to the bit, a charge of 0.125): penalty then bonus and bonus then
    # penalty both land on 0.625, exactly — the property the features
    # landing through the same seam depend on, checked where float
    # association cannot perturb it.
    scored = _dyadic_score()
    pick = {
        dt.date(2026, 3, 1): 3.0,
        dt.date(2026, 3, 2): -1.0,
        dt.date(2026, 3, 3): 3.0,
        dt.date(2026, 3, 4): -1.0,
    }
    penalized = null_pick_penalty(scored, null_pick_rate=0.25)
    bonused = orthogonality_bonus(scored, pick, _dyadic_book())
    assert penalized.score == 0.375
    assert bonused.score == 0.75
    assert orthogonality_bonus(penalized, pick, _dyadic_book()).score == 0.625
    assert null_pick_penalty(bonused, null_pick_rate=0.25).score == 0.625


def test_the_charge_composes_with_the_four_landed_siblings() -> None:
    # Five β-terms now land through one seam, and four of their five
    # charges are dyadic — the exception is β₃'s bar, irrational for every
    # K ≥ 2, which is why one assertion below is an approx with the reason
    # stated rather than a fixture pretending √(2·ln 4) is dyadic.  The
    # property under test is the seam's, not the arithmetic's: no term's
    # delta can see another's, so the order the caller composes them in
    # does not move the scalar.
    scored = _OnlySeam(0.5)
    charged = null_pick_penalty(scored, null_pick_rate=0.25)
    diverged = divergence_penalty(scored, ic_forward=0.0, ic_backtest=_GAP)
    switched = switch_penalty(scored, (_TREND, _CHOP), switch_cost=_COST)
    # The four dyadic charges, composed in two different orders.
    order_a = switch_penalty(
        divergence_penalty(charged, ic_forward=0.0, ic_backtest=_GAP),
        (_TREND, _CHOP),
        switch_cost=_COST,
    )
    order_b = null_pick_penalty(
        switch_penalty(
            divergence_penalty(scored, ic_forward=0.0, ic_backtest=_GAP),
            (_TREND, _CHOP),
            switch_cost=_COST,
        ),
        null_pick_rate=0.25,
    )
    expected = (
        0.5
        - BETA_TWO_DEFAULT * 0.25
        - BETA_FOUR_DEFAULT * _GAP
        - BETA_FIVE_DEFAULT * _COST
    )
    assert order_a.score == expected
    assert order_b.score == expected
    assert order_a == order_b
    # And with β₃'s irrational bar beside them, the same scalar to within
    # a float epsilon — the only place in this suite a tolerance is the
    # honest assertion.
    hairy = deflation_penalty(order_a, k_effective=_PooledView(4))
    assert hairy.score == pytest.approx(
        expected - BETA_THREE_DEFAULT * math.sqrt(2.0 * math.log(4)), rel=1e-12
    )
    assert charged.score == 0.5 - 0.125
    assert diverged.score == 0.5 - BETA_FOUR_DEFAULT * _GAP
    assert switched.score == 0.5 - BETA_FIVE_DEFAULT * _COST


# -- refusals -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rate",
    [True, False, "0.25", None, [0.25], {0.25}, object()],
)
def test_a_rate_that_is_not_a_real_is_refused(rate: object) -> None:
    # ``bool`` is refused first because it is an ``int`` in Python's
    # hierarchy — ``False`` would otherwise arrive as a legitimate rate of
    # zero, and ``True`` as one, on the strength of a type that means
    # neither.  Everything else is refused as the type fault it is rather
    # than escaping as a ``TypeError`` from inside the arithmetic.
    with pytest.raises(NullPickPenaltyError, match="real number"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=rate)  # type: ignore[arg-type]


@pytest.mark.parametrize("rate", [float("nan"), float("inf"), float("-inf")])
def test_a_rate_that_is_not_finite_is_refused(rate: float) -> None:
    # A NaN charge would be a NaN the dreaming loop's argmax silently
    # drops — the ordering the scalar exists to feed — and an infinity is
    # not a fraction of committed picks.
    with pytest.raises(NullPickPenaltyError, match="finite"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=rate)


@pytest.mark.parametrize("rate", [1.0000001, 1.4, 2.0, 47.0, -0.0001, -1.0])
def test_a_rate_outside_the_bound_is_refused_not_clamped(rate: float) -> None:
    # The refusal this module adds to the member's finiteness gate: the
    # rate is prd §4.4's fraction of committed picks that were planted
    # nulls, so it is bounded in [0, 1] by construction.  Refused rather
    # than clamped, because both directions of clamping are fabrications —
    # 1.4 pinned to one charges the maximum penalty for what may be an
    # honest figure, and 47 is a *count* of null picks handed where a rate
    # belongs (the likeliest confusion at this seam) which pinned to one
    # would charge a full ratio unit for a rate nobody computed.
    with pytest.raises(NullPickPenaltyError, match=r"\[0.0, 1.0\]"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=rate)


def test_a_count_of_null_picks_is_refused_where_a_rate_belongs() -> None:
    # The count-for-a-rate substitution named explicitly, because it is
    # the shape a caller reaching for the numerator instead of the
    # quotient produces and the message must send them back for the
    # fraction.  A count of one is indistinguishable from a rate of one
    # and is *not* refused — provenance is not checkable at a seam, the
    # same stance feature 259 takes toward a lucky integer — but a count
    # above one is not a rate and is refused as itself.
    with pytest.raises(NullPickPenaltyError, match="count"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=3)
    with pytest.raises(NullPickPenaltyError, match="false discovery rate"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=100)


@pytest.mark.parametrize("beta", [True, False, "0.5", None, [0.5], object()])
def test_a_beta_that_is_not_a_real_is_refused(beta: object) -> None:
    with pytest.raises(NullPickPenaltyError, match="real number"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=0.25, beta=beta)  # type: ignore[arg-type]


@pytest.mark.parametrize("beta", [float("nan"), float("inf"), float("-inf")])
def test_a_beta_that_is_not_finite_is_refused(beta: float) -> None:
    with pytest.raises(NullPickPenaltyError, match="finite"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=0.25, beta=beta)


@pytest.mark.parametrize("beta", [-0.25, -1.0, -0.0 - 1e-12])
def test_a_negative_beta_is_refused(beta: float) -> None:
    # The spec's verb is *subtracts*: a negative coefficient would
    # counterfeit a bonus through the penalty seam, teaching the loop that
    # landing on the nulls prd §4 planted is profitable — the exact
    # inversion of §7.1 line 327's *"without which none of this works"*.
    with pytest.raises(NullPickPenaltyError, match="negative"):
        null_pick_penalty(_OnlySeam(1.0), null_pick_rate=0.25, beta=beta)


def test_the_rate_has_no_default_and_must_be_stated() -> None:
    # Keyword-only and required: the rate is the figure a scorer process
    # answers about *this* campaign, and a member that defaulted it would
    # be inventing a false discovery rate for a campaign it never read.
    # The coefficient, by contrast, is a knob with a stated default — the
    # asymmetry is the same one the switch penalty draws between its
    # coefficient and its cost.
    with pytest.raises(TypeError):
        null_pick_penalty(_OnlySeam(1.0))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        null_pick_penalty(_OnlySeam(1.0), 0.25)  # type: ignore[misc]


# -- determinism, vocabulary, surface --------------------------------------------


def test_the_same_rate_answers_the_same_charge(score: WorldScore) -> None:
    # Deterministic and pure: the same rate — asked twice, or asked on a
    # score another term has moved — answers the same charge to the last
    # bit, because the delta is one product of two validated reals and one
    # negation.  There is no summation whose order could matter, and no
    # clock, store or environment anywhere in the term.
    first = null_pick_penalty(score, null_pick_rate=0.375)
    again = null_pick_penalty(score, null_pick_rate=0.375)
    assert first == again
    assert first.score == score.score - 0.1875
    # Asked on a score another term has already moved, the same rate
    # applies the same delta — the charge is a function of the rate and
    # the carrier's scalar, and of nothing about how the scalar got there.
    # Spelled in the same association the call chain uses, because the two
    # additions are not associative over an irrational leading term and
    # the law's claim is about the delta, not about float association.
    penalized = score.adjusted(-0.1)
    moved = null_pick_penalty(penalized, null_pick_rate=0.375)
    assert moved.score == penalized.score - 0.1875
    assert moved.ir_oos == score.ir_oos


def test_the_error_is_a_sibling_of_the_others() -> None:
    # 256 refuses an ask that cannot be scored; 262 one whose bonus cannot
    # be measured; 261 one whose charge cannot be counted; 260 one whose
    # divergence cannot be read; 259 one whose haircut cannot be trusted;
    # 258 one whose false discovery cannot be charged — and the repairs
    # differ (a sequestration fault, a resident-array hole, a census that
    # has not run, a mis-set price, the forward-test record, the trial
    # ledger, the scorer process holding the sidecar key), so the classes
    # stay distinguishable behind separate excepts.  β₂ and β₅ in
    # particular are *not* one class: prd §4.1.2's "separate the error
    # accounting" (line 140) makes a null commitment and a horizon's churn
    # two different failures with two different next steps.
    assert issubclass(NullPickPenaltyError, ScoringError)
    for other in (
        WorldObjectiveError,
        OrthogonalityError,
        SwitchPenaltyError,
        DivergencePenaltyError,
        DeflationPenaltyError,
        AggregationError,
        RegimeIndexError,
    ):
        assert not issubclass(NullPickPenaltyError, other)
        assert not issubclass(other, NullPickPenaltyError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend, the index, the bonus and the four landed β-terms,
    # the null-pick charge owns no deployment state, so it adds no
    # component beside the objective and no seat beside the member's: the
    # surface it joins is the member's namespace, and the composed
    # "scoring" component stays the per-world objective — the growth
    # pattern every free seam in this workspace takes.  The rate's
    # *computation* is the feature of this category that does own state
    # (265's scorer process, holding the sidecar key), and it takes its own
    # component name when it lands rather than widening this term's.
    import scoring

    assert "null_pick_penalty" in scoring.__all__
    assert "BETA_TWO_DEFAULT" in scoring.__all__
    assert "RATE_BOUND" in scoring.__all__
    assert "NullPickPenaltyError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"
    assert BETA_TWO_DEFAULT == 0.5
    assert RATE_BOUND == 1.0
    # The coefficient is the knob and the rate is not: that asymmetry is
    # the same one every rescued input on this seam draws.
    assert BETA_SIX_DEFAULT == 0.25
