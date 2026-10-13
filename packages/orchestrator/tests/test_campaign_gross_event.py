"""The node_evaluated event carries ir_tstat_gross beside the net score.

bug_spec_turnover_cost_charge.xml bug 2 asked for the event's score to carry
the gross (pre-turnover-charge) ir_tstat. The evaluation carried it, but the
event builder in _campaign.py (outside that bug's footprint) dropped it, so
archK01's first launch emitted net figures with no gross beside them.
"""

from __future__ import annotations

from orchestrator._campaign import _evaluated_event
from orchestrator._worker import ChildOutcome


def _event(score: object, gross: float | None) -> dict:
    return _evaluated_event(
        "c", "n", 0, fail_class=None, score=score, charges_budget=True,
        ir_tstat_gross=gross,
    )


def test_gross_rides_in_the_score_beside_the_net_figure() -> None:
    event = _event({"ir_tstat": -1.25}, 0.75)
    assert event["score"] == {"ir_tstat": -1.25, "ir_tstat_gross": 0.75}


def test_no_gross_leaves_the_score_untouched() -> None:
    assert _event({"ir_tstat": 1.0}, None)["score"] == {"ir_tstat": 1.0}


def test_a_failed_node_with_no_score_stays_null() -> None:
    assert _event(None, 0.5)["score"] is None


def test_child_outcome_defaults_to_no_gross() -> None:
    outcome = ChildOutcome(
        node_id="n", depth=1, fail_class=None, score=None,
        charges_budget=True, record=None,
    )
    assert outcome.ir_tstat_gross is None
