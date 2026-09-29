"""Feature 257's law: the beta-one trials penalty.

*System subtracts a beta-one term proportional to trials charged, which
returns a score penalized for consumed statistical budget* (app_spec.xml,
"Objective Scoring & CVaR Aggregation") — prd §7.1's first line
(``− β₁ · trials_charged``, line 320) and docs §10.3's (line 496), the
paper's original ``β₁ N`` rewritten by §7.1's Change B to count the binding
resource (statistical degrees of freedom) rather than the embarrassingly-
parallel agent calls the paper priced.  The tests here hold
:mod:`scoring._trials` to the sentence's clauses, in order:

* **subtracts** — the term can only take away: the count is a count, the
  coefficient is refused when negative, and the delta is one negated
  product of two non-negative factors (:func:`test_the_penalty_never_adds`);
* **proportional to trials charged** — the charge is linear in the count,
  one ``β₁`` per unit of statistical budget consumed, with no square root
  and no logarithm to soften it (:func:`test_the_charge_is_proportional_to_the_count`);
* **which returns a score penalized for consumed statistical budget** —
  the answer is the same frozen :class:`~scoring.WorldScore` with
  :attr:`~scoring.WorldScore.score` moved down through
  :meth:`~scoring.WorldScore.adjusted`, the identity and the measurement
  untouched, and the term composing with the bonus and the penalties that
  ride the same seam in whatever order the caller applies them
  (:func:`test_the_charge_composes_with_the_other_terms`).

The count is **taken directly, not derived** — the feature's own boundary
against its neighbour β₃ (feature 259): β₁ charges the raw statistical
spend, β₃ the multiple-testing bar over the honest ``K_effective`` count,
and the two are two facts about one resource, not two spellings of one
figure.  The suite pins that the seam reads a plain non-negative integer
and refuses the derivation β₃ consumes (:func:`test_the_count_is_taken_directly_not_derived`),
because handing the same derivation to both terms would charge β₁ on a
filtered count and β₃ on a raw one.

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: the default coefficient is 0.25 (dyadic) and the count is an
integer, so every charge is an exact multiple of a quarter and every moved
score is checkable with ``==`` — while the composition test measures
against a score whose every figure is dyadic (``_dyadic_score``, below) so
both orderings of two terms land on the same scalar to the bit.  What these
tests deliberately do not reach: composition (``test_component.py`` — the
penalty needs no component, which is itself pinned here by the member's
surface), and any persistence (the
``replay_score`` row is feature 255's, and it already carries the score and
the β).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest
from scoring import (
    BETA_ONE_DEFAULT,
    AggregationError,
    DeflationPenaltyError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    TrialsPenaltyError,
    WorldObjectiveError,
    WorldScore,
    trials_penalty,
    world_objective,
)

#: The trials-charged count every exact case charges at — one, so the
#: default coefficient's per-trial charge (0.25 · 1) is 0.25 exactly and
#: every multiple below is checkable with ``==``.
_ONE_TRIAL = 1

#: One trial's charge under the default coefficient.
_PER_TRIAL = BETA_ONE_DEFAULT * _ONE_TRIAL


def _dyadic_score() -> WorldScore:
    """A world score whose every figure is exact in binary.

    Readings (3, −1, 3, −1): mean 1, deviations (2, −2, 2, −2),
    population variance 4, so ``ir_oos`` is 1/2 *exactly* — the same panel
    feature 262's and 261's suites reach for when an equality has to be a
    ``==``, and used here for the same reason: two terms composed in both
    orders land on the same scalar only to the bit when every delta in the
    chain is dyadic, and integer readings keep every mean, deviation and
    sum exact.
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


# -- the charge -----------------------------------------------------------------


def test_a_count_of_one_is_charged_one_beta(score: WorldScore) -> None:
    # One budget-charging trial, one β₁: the charge is the coefficient
    # times one — 0.25 exactly under the default, asserted with == because
    # a charge that came out a float epsilon light would be a fixture
    # lying about its own arithmetic, not a tolerance worth honoring.
    moved = trials_penalty(score, _ONE_TRIAL)
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score - _PER_TRIAL
    # Everything the charge did not touch is untouched: the measurement,
    # the identity, the epoch.  The term lands beside the leading term,
    # never through it.
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


def test_the_charge_is_proportional_to_the_count(score: WorldScore) -> None:
    # The feature's own word: *proportional to trials charged*.  Triple
    # the trials, triple the charge; double the coefficient, double the
    # charge — linear in each factor separately, exactly, because each is
    # a factor of the one product the delta negates, with no square root
    # and no logarithm to soften the raw spend.
    once = trials_penalty(score, 1)
    thrice = trials_penalty(score, 3)
    assert once.score == score.score - 1 * _PER_TRIAL
    assert thrice.score == score.score - 3 * _PER_TRIAL
    assert thrice.score == score.score - 3 * (score.score - once.score)
    assert trials_penalty(score, 2, beta=0.5).score == score.score - 4 * _PER_TRIAL


def test_a_hundred_trials_charges_a_hundred_beta(score: WorldScore) -> None:
    # The raw spend, linear: a hundred budget-charging trials cost a
    # hundred β₁, exactly 25 ratio units under the default coefficient —
    # visible beside a leading term of order one, and meant to compound
    # with β₃'s ~0.76 multiple-testing haircut at the same count, not to
    # cancel it.  There is no log here to put the hundredfold search on
    # search's side: β₁ prices that budget was spent, β₃ prices how much
    # the spending should make you doubt.
    moved = trials_penalty(score, 100)
    assert moved.score == score.score - 100 * _PER_TRIAL


def test_the_penalty_never_adds(score: WorldScore) -> None:
    # The spec's verb is *subtracts*, and no count can turn the term
    # around: across a sweep of spends holding zero through six trials the
    # moved score is never above the handed one, and equality is earned
    # exactly at zero trials.  There is no float path by which the
    # subtraction could dress as an addition — the delta is one negated
    # product of two non-negative factors, with no summation and no
    # cancellation in it.
    sweep = [trials_penalty(score, trials) for trials in range(7)]
    assert all(moved.score <= score.score for moved in sweep)
    assert sweep[0].score == score.score


def test_the_charge_composes_with_the_other_terms(score: WorldScore) -> None:
    # The β-terms ride one seam, so the charge must land on a score
    # another term has already moved — the measurement still pinned, the
    # identity still untouched — and the order the caller applies terms in
    # is the caller's: penalty then bonus and bonus then penalty are the
    # same arithmetic over the same factors.
    penalized = score.adjusted(-0.1)
    moved = trials_penalty(penalized, _ONE_TRIAL)
    assert moved.score == penalized.score - _PER_TRIAL
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


def test_both_orders_of_two_terms_land_on_the_same_scalar() -> None:
    # The same composition against the bonus, on figures whose every delta
    # is dyadic (a score of 0.5, a bonus of 0.25 against an orthogonal
    # book, a charge of 0.25): trials then bonus and bonus then trials
    # both land on 0.625, exactly — the property the features landing
    # through the same seam after this one depend on, checked where float
    # association cannot perturb it.
    scored = _dyadic_score()
    pick = {
        dt.date(2026, 3, 1): 3.0,
        dt.date(2026, 3, 2): -1.0,
        dt.date(2026, 3, 3): 3.0,
        dt.date(2026, 3, 4): -1.0,
    }
    book = {
        dt.date(2026, 3, 1): 1.0,
        dt.date(2026, 3, 2): 1.0,
        dt.date(2026, 3, 3): -1.0,
        dt.date(2026, 3, 4): -1.0,
    }
    from scoring import orthogonality_bonus

    penalized = trials_penalty(scored, 1)
    bonused = orthogonality_bonus(scored, pick, book)
    assert penalized.score == 0.25
    assert bonused.score == 0.75
    assert orthogonality_bonus(penalized, pick, book).score == 0.5
    assert trials_penalty(bonused, 1).score == 0.5


# -- the carrier ----------------------------------------------------------------


@dataclass(frozen=True)
class _OnlySeam:
    """A carrier exposing exactly the one attribute this law reads —
    ``adjusted`` — and nothing else, not even a measurement.

    The trials penalty measures nothing off the pick's panel, so unlike
    the bonus it has no panel to pin and no ``ir_oos`` to recompute: this
    shape composes, and composing is what proves the seam validates what
    it reads rather than the type it was handed.
    """

    score: float

    def adjusted(self, delta: float) -> _OnlySeam:
        return _OnlySeam(self.score + delta)


def test_the_term_measures_nothing_off_the_carrier() -> None:
    # β₆ had to pin its panel against the carrier's ir_oos; β₁ has no such
    # read.  A carrier holding a scalar and the seam — no world, no pick,
    # no epoch, no measurement — is charged like any world score, which is
    # the docstring's claim that the charge is a fact about the budget
    # spent, landed beside the score it moves.
    moved = trials_penalty(_OnlySeam(1.0), 1)
    assert moved.score == 1.0 - _PER_TRIAL


def test_a_carrier_without_the_seam_is_refused() -> None:
    with pytest.raises(TrialsPenaltyError, match="adjusted"):
        trials_penalty(object(), 1)


# -- the factors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "beta", [float("nan"), float("inf"), -0.25, -1e-9, True, "0.25", None]
)
def test_a_coefficient_that_cannot_subtract_is_refused(
    score: WorldScore, beta
) -> None:
    # NaN and ±inf are not coefficients; a negative one counterfeits a
    # bonus through the penalty seam (the spec's verb is *subtracts*); a
    # bool is an int in Python's hierarchy and not a weight; a string and
    # a None are type faults.  Every one of them is refused, and the
    # branch each lands in names its own fault.
    with pytest.raises(TrialsPenaltyError) as caught:
        trials_penalty(score, _ONE_TRIAL, beta=beta)
    # Only the negative coefficient is refused on the verb's own sentence —
    # that is the branch whose message says *subtracts*.  A bool is refused
    # one step earlier, by the type gate, and NaN/±inf by the finiteness
    # gate; each names its own fault, which is the point of the split.
    if isinstance(beta, float) and beta < 0.0:
        assert "subtracts" in str(caught.value)


@pytest.mark.parametrize(
    "trials", [True, -1, -100, 2.0, 3.5, "3", None, object()]
)
def test_a_count_that_cannot_be_charged_is_refused(
    score: WorldScore, trials
) -> None:
    # The raw statistical spend is a non-negative integer count of
    # budget-charging trials — feature 221's BudgetAccount.charged, §6.1's
    # trials_charged column — and nothing else is one.  A bool is an int
    # wearing a truth value, a negative count would pay the policy for
    # having searched, a float is a measurement where a count belongs, and
    # a string, a None or an object is a type fault.  Each is refused
    # naming what the count is.
    with pytest.raises(TrialsPenaltyError) as caught:
        trials_penalty(score, trials)
    assert "trials_charged" in str(caught.value)


def test_the_count_is_taken_directly_not_derived(score: WorldScore) -> None:
    # The feature's own boundary against β₃ (feature 259): β₁ charges the
    # raw spend, β₃ the honest count, and the two are two facts about one
    # resource.  A K_effective derivation — the very carrier β₃ consumes,
    # exposing a pooled total — is therefore refused here, whatever its
    # total happens to be: it is not the raw spend this term names, and a
    # number that cannot say whether it was counted honestly is β₃'s
    # business, not this one's.  The seam reads the count directly and
    # never reaches for a total.
    @dataclass(frozen=True)
    class HonestCount:
        total: int

    with pytest.raises(TrialsPenaltyError, match="trials_charged"):
        trials_penalty(score, HonestCount(total=47))


def test_a_zero_spend_declines_the_charge_not_the_term(
    score: WorldScore,
) -> None:
    # Zero is admitted for both factors — an ablation the documents leave
    # to the deployment, not a contradiction of the term: a campaign that
    # consumed no statistical budget (the bootstrap pool's zero-cost
    # worlds, docs §10.6) pays no trials penalty, and a zeroed coefficient
    # declines the weighting the same way feature 262 admits a zeroed β₆.
    assert trials_penalty(score, 0) == score
    assert trials_penalty(score, 3, beta=0.0) == score


def test_the_default_coefficient_is_a_stated_parameterization() -> None:
    # Neither document sizes β₁ — the formula spells the term and moves on
    # — so the default is the member's own stated parameterization, a
    # quarter of the deployment's switch-price base, dyadic so this suite's
    # exact cases stay exact — the same stance λ's and every β-sibling's
    # default takes.
    assert BETA_ONE_DEFAULT == 0.25


# -- determinism, vocabulary, surface -------------------------------------------


def test_the_same_count_answers_the_same_charge(score: WorldScore) -> None:
    # Deterministic and pure: the same count — asked twice, or as an int
    # literal — answers the same charge to the last bit, because the delta
    # is one product of that count with a validated coefficient.  There is
    # no summation whose order could matter, and no clock, store or
    # environment anywhere in the term.
    again = trials_penalty(score, 3)
    assert again == trials_penalty(score, 3)
    assert again.score == score.score - 3 * _PER_TRIAL


def test_the_error_is_a_sibling_of_the_others() -> None:
    # 256 refuses an ask that cannot be scored; 262 refuses one whose
    # bonus cannot be measured; 261 refuses one whose charge cannot be
    # counted; 259 refuses one whose haircut cannot be trusted; and 257
    # refuses one whose statistical spend cannot be counted — and the
    # repairs differ (a sequestration fault, a resident-array hole, a
    # census that has not run, a mis-set price or a caller that reached for
    # the wrong count), so the classes stay distinguishable behind separate
    # excepts — the reasoning that keeps every sibling in this member
    # apart, held here for the penalties' first by feature number.
    assert issubclass(TrialsPenaltyError, ScoringError)
    for other in (
        WorldObjectiveError,
        OrthogonalityError,
        AggregationError,
        RegimeIndexError,
        DeflationPenaltyError,
    ):
        assert not issubclass(TrialsPenaltyError, other)
        assert not issubclass(other, TrialsPenaltyError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend, the index, the bonus and the five landed penalties,
    # the trials penalty owns no deployment state, so it adds no component
    # beside the objective and no seat beside the member's: the surface it
    # joins is the member's namespace, and the composed "scoring" component
    # stays the per-world objective — the growth pattern every free seam in
    # this workspace takes.
    import scoring

    assert "trials_penalty" in scoring.__all__
    assert "BETA_ONE_DEFAULT" in scoring.__all__
    assert "TrialsPenaltyError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"
