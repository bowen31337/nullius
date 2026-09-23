"""Feature 261's law: the beta-five switch penalty.

*System subtracts a beta-five term proportional to switch cost times
regime switch count, which returns the adjusted score* (app_spec.xml,
"Objective Scoring & CVaR Aggregation") — prd §7.1's fifth line
(``− β₅ · switch_cost · n_regime_switches``, line 323) and docs §10.3's
(line 497), one of the formula's five subtractions.  The tests here
hold :mod:`scoring._switches` to the sentence's clauses, in order:

* **subtracts** — the term can only take away: the count is a count,
  the coefficient and the cost are refused when negative, and the
  delta is one negated product of three non-negative factors
  (:func:`test_the_penalty_never_adds`);
* **proportional to switch cost times regime switch count** — the
  charge is linear in each factor, and the count is *this module's*
  spelling over the ordered path of regime labels: one switch per
  adjacent pair of windows whose labels differ, consecutive windows
  holding one label one regime held, and a path re-ordered a different
  horizon (:func:`test_a_horizon_that_crossed_once_is_charged_once`,
  :func:`test_consecutive_windows_of_one_regime_are_one_regime_held`,
  :func:`test_the_count_is_a_fact_about_order`);
* **which returns the adjusted score** — the answer is the same frozen
  :class:`~scoring.WorldScore` with :attr:`~scoring.WorldScore.score`
  moved down through :meth:`~scoring.WorldScore.adjusted`, the identity
  and the measurement untouched, and the term composing with the bonus
  and the penalties that ride the same seam in whatever order the
  caller applies them (:func:`test_the_charge_composes_with_the_other_terms`).

Exactness is the suite's own discipline, inherited from the conftest's
fixtures: the cost every exact case charges at is 0.5 and the default
coefficient is 0.25, so one switch costs exactly 0.125 — a dyadic
number, and every count's charge an exact multiple of it — while the
composition test measures against a score whose every figure is dyadic
(``_dyadic_score``, below) so both orderings of two terms land on the
same scalar to the bit.  What these tests deliberately do not reach:
composition (``test_component.py`` — the penalty needs no component,
which is itself pinned here by the member's surface), the seat
(``test_app_module.py``), and any persistence (the ``replay_score``
row is feature 255's, and it already carries the score and the β).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest
from scoring import (
    BETA_FIVE_DEFAULT,
    AggregationError,
    OrthogonalityError,
    RegimeIndexError,
    ScoringError,
    SwitchPenaltyError,
    WorldObjectiveError,
    WorldScore,
    orthogonality_bonus,
    switch_penalty,
    world_objective,
)

#: The regime names the paths below are written in — feature 283's own
#: sentence ("high-volatility trend", "low-volatility chop", "crash"),
#: restated here rather than imported because a member never imports
#: another member, and because the count turns on *difference* of names,
#: never on which names: any three would carry the law as exactly.
_TREND = "high-volatility trend"
_CHOP = "low-volatility chop"
_CRASH = "crash"

#: The switch cost every exact case charges at — one half, dyadic, so
#: the default coefficient's per-switch charge (0.25 · 0.5) is 0.125
#: exactly and every multiple below is checkable with ``==``.
_COST = 0.5

#: One switch's charge under the default coefficient at :data:`_COST`.
_PER_SWITCH = BETA_FIVE_DEFAULT * _COST


def _crossings(count: int) -> tuple[str, ...]:
    """A horizon that crossed exactly ``count`` times, however long it ran.

    Built by flipping between the two regimes at every window after the
    first, so the path's boundary count is the argument and nothing
    else — the fixture the proportionality and sweep tests count on,
    spelled once so no test re-derives it and mis-derives it.
    """
    labels = [_TREND]
    for _ in range(count):
        labels.append(_CHOP if labels[-1] == _TREND else _TREND)
    return tuple(labels)


def _dyadic_score() -> WorldScore:
    """A world score whose every figure is exact in binary.

    Readings (3, −1, 3, −1): mean 1, deviations (2, −2, 2, −2),
    population variance 4, so ``ir_oos`` is 1/2 *exactly* — the same
    panel feature 262's suite reaches for when an equality has to be a
    ``==``, and used here for the same reason: two terms composed in
    both orders land on the same scalar only to the bit when every
    delta in the chain is dyadic, and integer readings keep every mean,
    deviation and sum exact.
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
    (2, −2, −2, 2), which cancels as exact real values — so ρ is a
    signed zero to the bit and the beta-six bonus on this pair is the
    coefficient exactly (0.25), dyadic like the penalty beside it, which
    is what lets the composition test assert both orderings equal.
    """
    return {
        dt.date(2026, 3, 1): 1.0,
        dt.date(2026, 3, 2): 1.0,
        dt.date(2026, 3, 3): -1.0,
        dt.date(2026, 3, 4): -1.0,
    }


# -- the charge -----------------------------------------------------------------


def test_a_horizon_that_crossed_once_is_charged_once(score: WorldScore) -> None:
    # Four windows, two regimes, one boundary between them: the charge
    # is the coefficient times the cost times one — 0.125 exactly under
    # the fixtures' dyadic figures, asserted with == because a charge
    # that came out a float epsilon light would be a fixture lying
    # about its own arithmetic, not a tolerance worth honoring.
    moved = switch_penalty(score, (_TREND, _TREND, _CHOP, _CHOP), switch_cost=_COST)
    assert isinstance(moved, WorldScore)
    assert moved.score == score.score - _PER_SWITCH
    # Everything the charge did not touch is untouched: the measurement,
    # the identity, the epoch.  The term lands beside the leading term,
    # never through it.
    assert moved.ir_oos == score.ir_oos
    assert moved.world_id == score.world_id
    assert moved.node_id == score.node_id
    assert moved.epoch_id == score.epoch_id
    # And the score that was handed over is frozen through the call.
    assert score.score == score.ir_oos


def test_a_horizon_that_held_one_regime_is_charged_nothing(score: WorldScore) -> None:
    # A horizon whose every window holds one label crossed nothing, so
    # there is no charge: the returned score equals the handed one field
    # for field — the delta is a negated product whose count factor is
    # zero, and adding negative zero to a float is the identity.  A
    # single window is the same horizon at its smallest: one regime
    # held, zero boundaries, nothing to charge.
    for one_regime in (
        (_TREND, _TREND, _TREND, _TREND),
        (_CHOP,),
    ):
        moved = switch_penalty(score, one_regime, switch_cost=_COST)
        assert moved == score
        assert moved.score == score.score


def test_consecutive_windows_of_one_regime_are_one_regime_held(
    score: WorldScore,
) -> None:
    # The count is of *boundaries*, not of windows and not of labels:
    # three trend windows then two chop windows crossed once however
    # long the trend ran, and a horizon that returns to a regime it
    # left pays for every re-entry — (trend, chop, chop, trend, trend,
    # chop) crosses three times.  Both charges exact multiples of the
    # per-switch figure.
    held = switch_penalty(
        score, (_TREND, _TREND, _TREND, _CHOP, _CHOP), switch_cost=_COST
    )
    assert held.score == score.score - 1 * _PER_SWITCH
    returning = switch_penalty(
        score, (_TREND, _CHOP, _CHOP, _TREND, _TREND, _CHOP), switch_cost=_COST
    )
    assert returning.score == score.score - 3 * _PER_SWITCH


def test_the_count_is_a_fact_about_order(score: WorldScore) -> None:
    # The same labels in two orders are two different horizons: twice
    # trend then twice chop crossed once; alternating crossed three
    # times.  Order is information — which is why the path is a sequence
    # and a collection that cannot say which window followed which is
    # refused below — and it is also why the count is derived here
    # rather than handed over: only the path carries the fact.
    settled = switch_penalty(
        score, (_TREND, _TREND, _CHOP, _CHOP), switch_cost=_COST
    )
    churned = switch_penalty(
        score, (_TREND, _CHOP, _TREND, _CHOP), switch_cost=_COST
    )
    assert settled.score == score.score - 1 * _PER_SWITCH
    assert churned.score == score.score - 3 * _PER_SWITCH
    # And nothing is normalised: names that differ only by case are
    # different regimes, the census's near-miss business and not this
    # member's to repair, so the boundary between them is a switch.
    assert switch_penalty(
        score, ("Trend", "trend"), switch_cost=_COST
    ).score == score.score - _PER_SWITCH


def test_the_charge_is_proportional_in_each_factor(score: WorldScore) -> None:
    # The feature's own word: *proportional to switch cost times regime
    # switch count*.  Triple the crossings, triple the charge; double
    # the cost, double the charge; double the coefficient, double the
    # charge — linear in each factor separately, exactly, because each
    # is a factor of the one product the delta negates.
    once = switch_penalty(score, _crossings(1), switch_cost=_COST)
    thrice = switch_penalty(score, _crossings(3), switch_cost=_COST)
    assert once.score == score.score - _PER_SWITCH
    assert thrice.score == score.score - 3 * _PER_SWITCH
    assert thrice.score == score.score - 3 * (score.score - once.score)
    assert switch_penalty(score, _crossings(1), switch_cost=1.0).score == (
        score.score - 2 * _PER_SWITCH
    )
    assert (
        switch_penalty(score, _crossings(1), switch_cost=_COST, beta=0.5).score
        == score.score - 2 * _PER_SWITCH
    )


def test_the_penalty_never_adds(score: WorldScore) -> None:
    # The spec's verb is *subtracts*, and no path can turn the term
    # around: across a sweep of horizons holding zero through five
    # boundaries the moved score is never above the handed one, and
    # equality is earned exactly at zero crossings.  There is no float
    # path by which the subtraction could dress as an addition — the
    # delta is one negated product of three non-negative factors, with
    # no summation and no cancellation in it.
    sweep = [
        switch_penalty(score, _crossings(boundaries), switch_cost=_COST)
        for boundaries in range(6)
    ]
    assert all(moved.score <= score.score for moved in sweep)
    assert sweep[0].score == score.score


def test_the_charge_composes_with_the_other_terms(score: WorldScore) -> None:
    # The β-terms ride one seam, so the charge must land on a score
    # another term has already moved — the measurement still pinned,
    # the identity still untouched — and the order the caller applies
    # terms in is the caller's: penalty then bonus and bonus then
    # penalty are the same arithmetic over the same factors.
    penalized = score.adjusted(-0.1)
    moved = switch_penalty(penalized, (_TREND, _CHOP), switch_cost=_COST)
    assert moved.score == penalized.score - _PER_SWITCH
    assert moved.ir_oos == score.ir_oos
    assert moved.node_id == score.node_id


def test_both_orders_of_two_terms_land_on_the_same_scalar() -> None:
    # The same composition against the bonus, on figures whose every
    # delta is dyadic (a score of 0.5, a bonus of 0.25 against a book
    # orthogonal to the bit, a charge of 0.125): penalty then bonus and
    # bonus then penalty both land on 0.625, exactly — the property the
    # features landing through the same seam after this one depend on,
    # checked where float association cannot perturb it.
    scored = _dyadic_score()
    pick = {
        dt.date(2026, 3, 1): 3.0,
        dt.date(2026, 3, 2): -1.0,
        dt.date(2026, 3, 3): 3.0,
        dt.date(2026, 3, 4): -1.0,
    }
    penalized = switch_penalty(scored, (_TREND, _CHOP), switch_cost=_COST)
    bonused = orthogonality_bonus(scored, pick, _dyadic_book())
    assert penalized.score == 0.375
    assert bonused.score == 0.75
    assert orthogonality_bonus(penalized, pick, _dyadic_book()).score == 0.625
    assert switch_penalty(bonused, (_TREND, _CHOP), switch_cost=_COST).score == 0.625


# -- the carrier ----------------------------------------------------------------


@dataclass(frozen=True)
class _OnlySeam:
    """A carrier exposing exactly the one attribute this law reads —
    ``adjusted`` — and nothing else, not even a measurement.

    The switch penalty measures nothing off the pick's panel, so unlike
    the bonus it has no panel to pin and no ``ir_oos`` to recompute:
    this shape composes, and composing is what proves the seam validates
    what it reads rather than the type it was handed.
    """

    score: float

    def adjusted(self, delta: float) -> _OnlySeam:
        return _OnlySeam(self.score + delta)


def test_the_term_measures_nothing_off_the_carrier() -> None:
    # β₆ had to pin its panel against the carrier's ir_oos; β₅ has no
    # such read.  A carrier holding a scalar and the seam — no world,
    # no pick, no epoch, no measurement — is charged like any world
    # score, which is the docstring's claim that the charge is a fact
    # about the horizon, landed beside the score it moves.
    moved = switch_penalty(_OnlySeam(1.0), (_TREND, _CHOP), switch_cost=_COST)
    assert moved.score == 1.0 - _PER_SWITCH


def test_a_carrier_without_the_seam_is_refused() -> None:
    with pytest.raises(SwitchPenaltyError, match="adjusted"):
        switch_penalty(object(), (_TREND, _CHOP), switch_cost=_COST)


# -- the factors ----------------------------------------------------------------


@pytest.mark.parametrize(
    "beta", [float("nan"), float("inf"), -0.25, -1e-9, True, "0.25", None]
)
def test_a_coefficient_that_cannot_subtract_is_refused(
    score: WorldScore, beta
) -> None:
    # NaN and ±inf are not coefficients; a negative one counterfeits a
    # bonus through the penalty seam (the spec's verb is *subtracts*);
    # a bool is an int in Python's hierarchy and not a weight; a string
    # and a None are type faults.  Every one of them is refused, and
    # the branch each lands in names its own fault.
    with pytest.raises(SwitchPenaltyError) as caught:
        switch_penalty(score, (_TREND, _CHOP), switch_cost=_COST, beta=beta)
    # Only the negative coefficient is refused on the verb's own
    # sentence — that is the branch whose message says *subtracts*.
    # A bool is refused one step earlier, by the type gate, and NaN/±inf
    # by the finiteness gate; each names its own fault, which is the
    # point of the split.
    if isinstance(beta, float) and beta < 0.0:
        assert "subtracts" in str(caught.value)


@pytest.mark.parametrize(
    "cost", [float("nan"), float("inf"), -0.5, -1e-9, True, "0.5", None]
)
def test_a_cost_that_cannot_be_charged_is_refused(
    score: WorldScore, cost
) -> None:
    # The price of one switch is the term's other factor, and it is
    # held to the coefficient's own discipline: finite, real, and —
    # because the term subtracts — non-negative.  A negative price
    # would pay the policy for every crossing it makes, which is the
    # bonus counterfeited from the penalty's side of the formula.
    with pytest.raises(SwitchPenaltyError) as caught:
        switch_penalty(score, (_TREND, _CHOP), switch_cost=cost)
    if isinstance(cost, float) and cost < 0.0:
        assert "bonus" in str(caught.value)


def test_a_zero_factor_declines_the_charge_not_the_term(
    score: WorldScore,
) -> None:
    # Zero is admitted for both factors — an ablation the documents
    # leave to the deployment, not a contradiction of the term: a cost
    # model that prices a switch at nothing has declined to charge, and
    # a zeroed coefficient declines the weighting the same way feature
    # 262 admits a zeroed β₆.
    assert switch_penalty(score, (_TREND, _CHOP), switch_cost=0.0) == score
    assert (
        switch_penalty(score, (_TREND, _CHOP), switch_cost=_COST, beta=0.0) == score
    )


def test_the_default_coefficient_is_a_stated_parameterization() -> None:
    # Neither document sizes β₅ — the formula spells the term and moves
    # on — so the default is the member's own stated parameterization,
    # a quarter of the deployment's switch price charged per crossing:
    # visible beside a leading term of order one, never so large that
    # sitting still beats being right, and dyadic so this suite's exact
    # cases stay exact — the same stance λ's and β₆'s defaults take.
    assert BETA_FIVE_DEFAULT == 0.25


# -- the path -------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        {_TREND, _CHOP},  # a set: no order, no adjacency
        {_TREND: _CHOP},  # a mapping: keyed, not sequential
        _TREND,  # one name is one window's label, not a path of them
        b"trend",  # bytes is a sequence — of characters nobody meant
        3,
        None,
    ],
)
def test_a_path_that_cannot_hold_order_is_refused(
    score: WorldScore, path
) -> None:
    # The count is a fact about the *order* of the labels, so the input
    # must be the thing that carries order: an ordered sequence, one
    # name per consecutive window.  A set cannot say which window
    # followed which, a mapping keys its labels instead of sequencing
    # them, a bare string (and bytes with it) would be counted by its
    # characters, and a number or a None is a type fault.  Each is
    # refused naming what a path is.
    with pytest.raises(SwitchPenaltyError, match="ordered sequence"):
        switch_penalty(score, path, switch_cost=_COST)


@pytest.mark.parametrize("label", ["", "   ", 3, True, 2.5, None])
def test_a_label_that_names_no_regime_is_refused(
    score: WorldScore, label
) -> None:
    # Each window must name its regime by a non-empty string: the count
    # turns on which adjacent windows hold different regimes, and a
    # label that names nothing cannot be switched from or to.  Nothing
    # is normalised — near-miss spellings are the census's business,
    # and the vocabulary is the caller's to declare.
    with pytest.raises(SwitchPenaltyError, match="non-empty string"):
        switch_penalty(score, (_TREND, label, _CHOP), switch_cost=_COST)


@pytest.mark.parametrize("empty", [[], ()])
def test_a_path_with_no_windows_at_all_is_refused(
    score: WorldScore, empty
) -> None:
    # An unlabelled horizon is a census that has not run, not a horizon
    # that never switched: reading an empty path as zero switches would
    # price a horizon nobody labelled, and the two readings send the
    # operator to different repairs — which is why one is a refusal and
    # the other is a charge of nothing (one regime held, above).
    with pytest.raises(SwitchPenaltyError) as caught:
        switch_penalty(score, empty, switch_cost=_COST)
    assert "no windows" in str(caught.value)


# -- determinism, vocabulary, surface -------------------------------------------


def test_the_same_path_answers_the_same_charge(score: WorldScore) -> None:
    # Deterministic and pure: the same path — spelled as a list, as a
    # tuple, or asked twice — answers the same charge to the last bit,
    # because the count is exact integer arithmetic over the sequence's
    # own order and the delta is one product of that count with two
    # validated factors.  There is no summation whose order could
    # matter, and no clock, store or environment anywhere in the term.
    as_list = switch_penalty(score, [_TREND, _CHOP, _TREND], switch_cost=_COST)
    as_tuple = switch_penalty(score, (_TREND, _CHOP, _TREND), switch_cost=_COST)
    again = switch_penalty(score, (_TREND, _CHOP, _TREND), switch_cost=_COST)
    assert as_list == as_tuple
    assert again == as_tuple
    assert as_list.score == score.score - 2 * _PER_SWITCH


def test_the_error_is_a_sibling_of_the_others() -> None:
    # 256 refuses an ask that cannot be scored; 262 refuses one whose
    # bonus cannot be measured; 261 refuses one whose charge cannot be
    # counted — and the repairs differ (a sequestration fault, a
    # resident-array hole, a census that has not run or a mis-set
    # price), so the classes stay distinguishable behind separate
    # excepts — the reasoning that keeps every sibling in this member
    # apart, held here for the penalties' first.
    assert issubclass(SwitchPenaltyError, ScoringError)
    for other in (
        WorldObjectiveError,
        OrthogonalityError,
        AggregationError,
        RegimeIndexError,
    ):
        assert not issubclass(SwitchPenaltyError, other)
        assert not issubclass(other, SwitchPenaltyError)


def test_the_term_is_pure_arithmetic_not_a_component() -> None:
    # Like the blend, the index and the bonus, the penalty owns no
    # deployment state, so it adds no component beside the objective
    # and no seat beside the member's: the surface it joins is the
    # member's namespace, and the composed "scoring" component stays
    # the per-world objective — the growth pattern every free seam in
    # this workspace takes.
    import scoring

    assert "switch_penalty" in scoring.__all__
    assert "BETA_FIVE_DEFAULT" in scoring.__all__
    assert "SwitchPenaltyError" in scoring.__all__
    assert scoring.COMPONENT_NAME == "scoring"
