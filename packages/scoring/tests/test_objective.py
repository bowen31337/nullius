"""Feature 256's law: the per-world objective.

*System computes the per-world objective starting from out-of-sample
information ratio of the committed pick, which returns a scalar world
score* (app_spec.xml, "Objective Scoring & CVaR Aggregation").  The tests
here hold the module :mod:`scoring._objective` to the sentence's three
clauses, in order:

* **the ratio** — one spelling, feature 80's: mean over population
  standard deviation, exact under iteration order, refused when the
  panel cannot define one (:func:`test_the_ratio_is_the_one_spelling`,
  :func:`test_the_score_is_order_independent`, and the refusal tests);
* **the committed pick** — one node, named once, by address or by the
  committed value, never a batch and never a blank
  (:func:`test_a_pick_is_named_by_address_or_by_the_committed_value` and
  its refusals);
* **the scalar world score** — born equal to the leading term, frozen,
  always finite, and movable only by :meth:`WorldScore.adjusted`, the
  seam the six β-terms of prd §7.1 (features 257-262) ride
  (:func:`test_the_score_starts_from_the_leading_term`,
  :func:`test_an_adjustment_moves_the_score_not_the_measurement`).

The −∞ division of labour is pinned from this side too
(:func:`test_a_world_score_is_always_finite`): the non-committing miss
is feature 222's value, answered by the termination and never carrying a
pick, so a world score may not counterfeit it — and the refusal message
says whose number it is.

What these tests deliberately do not reach: composition (that is
``test_component.py``), the seat (``test_app_module.py``), and anything
about aggregating across worlds — a mean over worlds computed here would
be the plain-mean aggregation feature 264 exists to reject.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import FrozenInstanceError, dataclass

import pytest
from scoring import (
    IR_DATES_MINIMUM,
    ScoringError,
    WorldObjectiveError,
    WorldScore,
    world_objective,
)

WORLD = "financial-campaign-01"
EPOCH = "sequestered-2026q1"


@dataclass(frozen=True)
class _DuckPick:
    """The committed value's shape, spelled inside the test that constructs
    bad ones — a plain object exposing ``node_id``, the whole of the
    duck-typed seam's demand (feature 222's pick among the objects that
    satisfy it; a member never imports another member to prove it)."""

    node_id: object


# -- the leading term ---------------------------------------------------------


def test_the_score_starts_from_the_leading_term(score: WorldScore) -> None:
    # Feature 256's own shape: the objective *starts from* the committed
    # pick's out-of-sample information ratio, so at this feature's stage the
    # scalar IS the leading term — pinned as an exact equality, not an
    # approximation, because a construction that left them a float apart
    # would be a construction that already applied a term nobody wrote.
    assert score.score == score.ir_oos
    # And the leading term is the hand-computed ratio of the panel:
    # mean 0.05 over population std 0.05·√5 = 1/√5.
    assert score.ir_oos == pytest.approx(1 / math.sqrt(5))


def test_the_ratio_is_the_one_spelling() -> None:
    # Feature 80's spelling, restated: the *population* standard deviation
    # (ddof=0), not the sample one.  Over (1.0, 2.0): mean 1.5, population
    # variance 0.25, ratio 3.0 exactly — the sample convention (ddof=1)
    # would answer 1.5/√0.5 ≈ 2.1213, and a world score measured on that
    # axis would be a second ruler beside the node metrics the policy read
    # in-sample.
    panel = {dt.date(2026, 1, 5): 1.0, dt.date(2026, 1, 6): 2.0}
    result = world_objective(WORLD, "node-a", panel)
    assert result.ir_oos == 3.0


def test_the_score_is_order_independent(panel: dict[dt.date, float]) -> None:
    # Same panel, reversed iteration order over the dates: the same score
    # to the last bit, because the dates are sorted before they are read
    # and summed with math.fsum — the determinism the replay's own law
    # (docs §10.1) demands of the number everything downstream ranks on.
    reversed_panel = {day: panel[day] for day in sorted(panel, reverse=True)}
    assert list(reversed_panel) != list(panel)
    first = world_objective(WORLD, "node-a", panel)
    second = world_objective(WORLD, "node-a", reversed_panel)
    assert second.score == first.score
    assert second.ir_oos == first.ir_oos


def test_a_losing_pick_scores_negative() -> None:
    # The objective is signed, not floored at zero: a pick whose sequestered
    # panel lost on average scores below every honest winner, which is the
    # information the dreaming loop's argmax is for.  Pinning this because
    # a "score" that quietly clipped negatives would make every policy
    # equally bad at the bottom and destroy the ranking the scalar feeds.
    panel = {
        dt.date(2026, 2, 1): -0.3,
        dt.date(2026, 2, 2): 0.1,
        dt.date(2026, 2, 3): -0.2,
        dt.date(2026, 2, 4): 0.0,
    }
    result = world_objective(WORLD, "node-a", panel)
    assert result.score < 0.0
    assert result.score == result.ir_oos


def test_int_readings_are_reals() -> None:
    # A caller whose panel is whole numbers has measured the same fact a
    # fractional panel has; the seam narrows to float rather than refusing.
    panel = {dt.date(2026, 1, 5): 1, dt.date(2026, 1, 6): 2}
    result = world_objective(WORLD, "node-a", panel)
    assert isinstance(result.ir_oos, float)
    assert result.ir_oos == 3.0


# -- the committed pick -------------------------------------------------------


def test_a_pick_is_named_by_address_or_by_the_committed_value(
    pick: object, pick_node_id: str, panel: dict[dt.date, float]
) -> None:
    # The two spellings of the seam: the address itself, or the committed
    # value exposing node_id (feature 222's pick, duck-typed because the
    # loader's synthetic-name re-execution means an isinstance would refuse
    # the very objects composition produces).  Both name one node, and
    # both answer the same score.
    by_address = world_objective(WORLD, pick_node_id, panel)
    by_value = world_objective(WORLD, pick, panel)
    assert by_address.node_id == pick_node_id
    assert by_value.node_id == pick_node_id
    assert by_value.score == by_address.score


@pytest.mark.parametrize(
    "carried",
    [
        None,
        "",
        "   ",
        True,
        False,
        ["node-a", "node-b"],
        ("node-a",),
        {"node_id": "node-a"},
        42,
        object(),
    ],
)
def test_a_pick_that_names_no_node_is_refused(
    carried: object, panel: dict[dt.date, float]
) -> None:
    # One pick, one node: the commit's own cardinality (feature 222)
    # read from the scoring side.  A collection is a batch spelled where
    # one pick belongs; a mapping is a pick's shadow, not the pick; a
    # bool is not a name; an empty-string pick names nothing to score.
    with pytest.raises(WorldObjectiveError, match="committed pick"):
        world_objective(WORLD, carried, panel)


def test_a_pick_whose_node_id_is_not_a_name_is_refused(
    panel: dict[dt.date, float],
) -> None:
    # The duck-typed seam validates what it reads: an object that exposes
    # a node_id which is itself blank or not a string is refused as a pick
    # that names no node, not silently accepted as one.
    for bad in ("", "   ", 7, True, None):
        with pytest.raises(WorldObjectiveError, match="committed pick"):
            world_objective(WORLD, _DuckPick(bad), panel)


# -- the panel ----------------------------------------------------------------


@pytest.mark.parametrize("readings", [{}, {dt.date(2026, 1, 5): 0.1}])
def test_a_panel_of_fewer_than_two_dates_defines_no_ratio(
    readings: dict[dt.date, float],
) -> None:
    # An information ratio is a mean over a standard deviation, and a
    # standard deviation over a single date is zero — dividing by it would
    # fabricate an infinity that outranks every honest score.  The refusal
    # names the count, and the floor is the published constant.
    with pytest.raises(WorldObjectiveError, match="0 date|1 date"):
        world_objective(WORLD, "node-a", readings)
    assert IR_DATES_MINIMUM == 2


def test_a_panel_that_never_varied_has_no_ratio() -> None:
    # A constant series has a zero standard deviation and no
    # reward-to-variance ratio — the pick measured nothing, and no default
    # invented here would make the number mean anything.
    panel = {
        dt.date(2026, 1, 5): 0.01,
        dt.date(2026, 1, 6): 0.01,
        dt.date(2026, 1, 7): 0.01,
    }
    with pytest.raises(WorldObjectiveError, match="never varied|standard deviation is zero"):
        world_objective(WORLD, "node-a", panel)


@pytest.mark.parametrize("reading", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_reading_is_refused(reading: float) -> None:
    # A NaN reading would make the ratio a NaN, and the store's law is
    # that a score row is the record of a *completed* measurement
    # (migration 0109); a NaN compares false against everything and would
    # silently drop out of the argmax (feature 222's own argument, held
    # here for the reading rather than the scalar).
    panel = {dt.date(2026, 1, 5): 0.1, dt.date(2026, 1, 6): reading}
    with pytest.raises(WorldObjectiveError, match="finite"):
        world_objective(WORLD, "node-a", panel)


@pytest.mark.parametrize("reading", [True, False, "0.1", None, 0.1 + 0.2j])
def test_a_reading_that_is_not_a_real_is_refused(reading: object) -> None:
    # bool is an int in Python's hierarchy and not a reading; a string is
    # not a reading; a complex is not a real.  The seam refuses what it
    # cannot read rather than letting a TypeError escape from inside the
    # arithmetic.
    panel = {dt.date(2026, 1, 5): 0.1, dt.date(2026, 1, 6): reading}  # type: ignore[dict-item]
    with pytest.raises(WorldObjectiveError, match="real"):
        world_objective(WORLD, "node-a", panel)


@pytest.mark.parametrize(
    "key", [dt.datetime(2026, 1, 5, 12, 30), "2026-01-05", 5, None]
)
def test_a_panel_keyed_by_anything_but_a_date_is_refused(key: object) -> None:
    # The ratio is over per-date readings.  A datetime is a date with a
    # clock bolted on — refused as itself, because silently truncating it
    # to its calendar day would hide a caller's confusion about the
    # panel's grain; a string or a number is not a day at all.
    panel = {dt.date(2026, 1, 5): 0.1, key: -0.1}  # type: ignore[dict-item]
    with pytest.raises(WorldObjectiveError, match="keyed by dates"):
        world_objective(WORLD, "node-a", panel)


@pytest.mark.parametrize("panel", [[0.1, -0.1], (0.1, -0.1), None, 0.1])
def test_a_panel_that_is_not_a_mapping_is_refused(panel: object) -> None:
    # One reading per date is the panel's own law, and a mapping holds it
    # for free — a sequence cannot, and a scalar is not a panel at all.
    with pytest.raises(WorldObjectiveError, match="mapping of dates"):
        world_objective(WORLD, "node-a", panel)


# -- the identity fields ------------------------------------------------------


@pytest.mark.parametrize("world", ["", "   ", 7, True, None, ["w"]])
def test_a_world_that_is_not_a_name_is_refused(
    world: object, panel: dict[dt.date, float]
) -> None:
    # world_id is the address the aggregated objective stratifies by and
    # the two-pool report keys on (docs §10.6) — a value that names
    # nothing has no score to carry.
    with pytest.raises(WorldObjectiveError, match="world_id"):
        world_objective(world, "node-a", panel)  # type: ignore[arg-type]


def test_the_epoch_is_carried_not_derived(
    pick: object, panel: dict[dt.date, float]
) -> None:
    # The sequestered epoch the panel was drawn from, when the caller can
    # name it: carried into the record unchanged; None when it cannot —
    # the score is the same number either way, and the record is the
    # poorer field, not the wrong score.
    named = world_objective(WORLD, pick, panel, epoch_id=EPOCH)
    unnamed = world_objective(WORLD, pick, panel)
    assert named.epoch_id == EPOCH
    assert unnamed.epoch_id is None
    assert named.score == unnamed.score


@pytest.mark.parametrize("epoch", ["", "   ", 7, True])
def test_a_blank_epoch_is_refused(
    epoch: object, panel: dict[dt.date, float]
) -> None:
    # A blank epoch id is a missing one wearing a name: refused rather
    # than carried, because a record that says "scored on epoch '   '"
    # lies about its own provenance.  None is the honest missing value
    # and is accepted.
    with pytest.raises(WorldObjectiveError, match="epoch_id"):
        world_objective(WORLD, "node-a", panel, epoch_id=epoch)  # type: ignore[arg-type]


# -- the value ----------------------------------------------------------------


def test_a_world_score_is_always_finite() -> None:
    # NaN and both infinities are refused at construction — the miss's −∞
    # is feature 222's value (NON_COMMITTING_SCORE), answered by the
    # termination and never carrying a pick, so a world score holding it
    # would be the miss wearing a pick.  The refusal names whose number
    # it is, so an operator reading it knows where to look.
    for scalar in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(WorldObjectiveError, match="NON_COMMITTING_SCORE"):
            WorldScore(
                world_id=WORLD, node_id="node-a", ir_oos=scalar, score=0.1
            )
        with pytest.raises(WorldObjectiveError, match="NON_COMMITTING_SCORE"):
            WorldScore(
                world_id=WORLD, node_id="node-a", ir_oos=0.1, score=scalar
            )


def test_the_value_is_frozen(score: WorldScore) -> None:
    # A score that could move after it was read would be a ranking that
    # changed beneath the dreaming loop's argmax — the same guarantee the
    # committed pick makes for the decision.
    with pytest.raises(FrozenInstanceError):
        score.score = 0.9  # type: ignore[misc]


def test_the_error_is_the_member_vocabulary(panel: dict[dt.date, float]) -> None:
    # One base class for the member, so a replay loop wrapping its scoring
    # step in a single except catches the objective's laws and nothing
    # else.  Pinned because a refusal that escaped as a bare TypeError
    # would defeat exactly that caller.
    with pytest.raises(WorldObjectiveError):
        world_objective(WORLD, None, panel)
    assert issubclass(WorldObjectiveError, ScoringError)
    with pytest.raises(ScoringError):
        world_objective(WORLD, None, panel)


def test_a_refusal_answers_nothing_partial(panel: dict[dt.date, float]) -> None:
    # The objective either answers a complete frozen value or raises — a
    # caller can never hold a half-scored world it must remember to
    # discard.  The invalid-world ask and the valid one on either side of
    # it answer independently, so the refusal left no state behind.
    before = world_objective(WORLD, "node-a", panel)
    with pytest.raises(WorldObjectiveError):
        world_objective(WORLD, "", panel)
    after = world_objective(WORLD, "node-a", panel)
    assert after == before


# -- the adjustment seam (features 257-262 ride this) -------------------------


def test_an_adjustment_moves_the_score_not_the_measurement(
    score: WorldScore,
) -> None:
    # prd §7.1's remaining terms — β₁'s trials through β₆'s orthogonality
    # — land as signed deltas on the scalar, beside a frozen measurement.
    # A penalty must never reach back into the leading term it sits
    # beside, or every comparison of two picks becomes unauditable.
    penalized = score.adjusted(-0.25)
    assert penalized.score == pytest.approx(score.score - 0.25)
    assert penalized.ir_oos == score.ir_oos
    assert penalized.world_id == score.world_id
    assert penalized.node_id == score.node_id
    assert penalized.epoch_id == score.epoch_id
    # The original is untouched — the seam answers a new value.
    assert score.score == score.ir_oos


def test_an_adjustment_may_add(score: WorldScore) -> None:
    # β₆'s orthogonality bonus is added, not subtracted (feature 262), so
    # the sign is the feature's own arithmetic and the seam's is none.
    bonused = score.adjusted(0.1)
    assert bonused.score == pytest.approx(score.score + 0.1)


def test_adjustments_compose(score: WorldScore) -> None:
    # Six terms, six calls: the order-independent chain a replay applies
    # when features 257-262 have all landed, ending at the score the
    # aggregated objective (263) would blend across worlds.
    chain = score.adjusted(-0.1).adjusted(-0.2).adjusted(-0.3)
    assert chain.score == pytest.approx(score.score - 0.6)
    assert chain.ir_oos == score.ir_oos


@pytest.mark.parametrize("delta", [float("nan"), float("inf"), float("-inf"), True])
def test_an_adjustment_that_is_not_finite_is_refused(
    delta: object, score: WorldScore
) -> None:
    # A NaN delta would eat the ordering the scalar exists to feed, and an
    # infinite one would counterfeit the miss's −∞ — the non-committing
    # floor is a termination's answer (feature 222), and no β-term may
    # push a made pick's score onto it.  (A ``bool`` is refused one branch
    # earlier — it is not a real at all — hence the two-pattern match.)
    with pytest.raises(WorldObjectiveError, match="real number|must be finite"):
        score.adjusted(delta)  # type: ignore[arg-type]
