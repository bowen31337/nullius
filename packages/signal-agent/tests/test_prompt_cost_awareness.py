"""additions_spec_cost_aware_selection.xml, feature 4 — the rendered
authoring prompt tells the agent how costs judge its signal.

The M2 baseline (docs/user-journeys/_run-log.md, Run 10 addendum 2) found
selection cost-blind: a committed pick's in-sample IC survives, but its
post-cost book loses money out of sample, because nothing in the prompt
said that cost — not rank IC — is what the node is judged on. This suite
pins the three things feature 4 adds, and that everything else about the
rendered prompt stays exactly as it was:

* the task's new ``cost_awareness`` key carries the selection statement,
  the evaluation grid's cadence, the cost model's per-rebalance cost and
  one line of turnover guidance (:func:`_cost_awareness_part`);
* each history block's new ``cost figures`` line names ``ic_tstat``,
  ``ir_tstat``, ``turnover`` and ``cost_adjusted_ir`` off the prior's
  recorded score explicitly (:func:`_cost_figures`);
* an absent figure — a context with no cadence or cost wired in, a score
  with no recorded metric, or no recorded score at all — renders the
  literal ``"unmeasured"``, never ``null`` and never a missing key.

No module-level state, so the suite is order- and worker-independent under
pytest-xdist.
"""

from __future__ import annotations

from types import SimpleNamespace

from signal_agent import PriorProposal, ScoreRecord
from signal_agent._authoring_prompt import build_authoring_prompt, to_request

#: A workspace, duck-typed as a plain namespace — the same shape
#: test_authoring_prompt.py's own WORKSPACE pins.
WORKSPACE = SimpleNamespace(
    campaign_id="8f14e45f-cea3-4f93-8d2e-000000000002",
    theme_root="momentum",
    depth=1,
)

#: The archive configs' own cadence (docs/user-journeys/_run-log.md: "235
#: weekly dates") — three dates, seven days apart, is enough to name it.
WEEKLY_DATES = ("2026-01-07", "2026-01-14", "2026-01-21")


def _prior(node_id: str, proposal: str = "def signal(ctx, seed): ...", code_hash: str = "a" * 64) -> PriorProposal:
    return PriorProposal(node_id=node_id, proposal=proposal, code_hash=code_hash)


def _system(parts) -> str:
    return to_request(parts, model="test-model", temperature=0.0, max_tokens=512).messages[0].content


def _user(parts) -> str:
    return to_request(parts, model="test-model", temperature=0.0, max_tokens=512).messages[1].content


# -- the cost-awareness section: cadence and per-rebalance cost --------------


def test_rendered_prompt_contains_cadence_and_per_rebalance_cost_from_a_fixture_context() -> None:
    evaluation = SimpleNamespace(evaluation_dates=WEEKLY_DATES, per_rebalance_cost_bps=23.5)
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)

    cost_awareness = parts.task["cost_awareness"]
    assert cost_awareness["cadence"] == "weekly"
    assert cost_awareness["per_rebalance_cost_bps"] == 23.5

    system = _system(parts)
    assert '"cadence": "weekly"' in system
    assert '"per_rebalance_cost_bps": 23.5' in system


def test_cost_awareness_states_the_post_cost_selection_rule() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    statement = parts.task["cost_awareness"]["selection_statement"]
    assert "post-cost IR t-statistic" in statement
    assert "ir_tstat" in statement
    assert "dollar-neutral book" in statement
    assert "evaluation grid" in statement


def test_cost_awareness_states_what_the_per_rebalance_cost_covers_and_turnover() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    basis = parts.task["cost_awareness"]["cost_basis"]
    assert "fees" in basis
    assert "spread" in basis
    assert "bps of traded notional" in basis
    assert "turnover" in basis.lower()


def test_cost_awareness_carries_the_one_line_of_turnover_guidance() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    guidance = parts.task["cost_awareness"]["guidance"]
    assert "turnover" in guidance.lower()
    assert "information only" in guidance
    assert "judges nothing" in guidance


def test_cadence_is_derived_from_the_grids_own_spacing() -> None:
    weekly = SimpleNamespace(evaluation_dates=WEEKLY_DATES)
    daily = SimpleNamespace(evaluation_dates=("2026-01-01", "2026-01-02", "2026-01-03"))
    irregular = SimpleNamespace(evaluation_dates=("2026-01-01", "2026-01-02", "2026-01-10"))

    def cadence(evaluation) -> str:
        parts = build_authoring_prompt(WORKSPACE, (), clause="c", evaluation=evaluation)
        return parts.task["cost_awareness"]["cadence"]

    assert cadence(weekly) == "weekly"
    assert cadence(daily) == "daily"
    assert cadence(irregular) == "irregular"


def test_evaluation_context_is_duck_typed_and_accepts_a_mapping() -> None:
    evaluation = {"evaluation_dates": list(WEEKLY_DATES), "per_rebalance_cost_bps": 12}
    parts = build_authoring_prompt(WORKSPACE, (), clause="c", evaluation=evaluation)
    assert parts.task["cost_awareness"]["cadence"] == "weekly"
    assert parts.task["cost_awareness"]["per_rebalance_cost_bps"] == 12


# -- prior proposals: the four figures ----------------------------------------


def test_prior_proposals_show_the_four_cost_figures_from_their_recorded_score() -> None:
    score = ScoreRecord(
        ic_tstat=3.8, ir_tstat=2.1, turnover=0.66, cost_adjusted_ir=-0.42, fail_class=None
    )
    history = ((_prior("n1"), score),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")

    user = _user(parts)
    assert '"ic_tstat": 3.8' in user
    assert '"ir_tstat": 2.1' in user
    assert '"turnover": 0.66' in user
    assert '"cost_adjusted_ir": -0.42' in user


# -- the absent-figure path: "unmeasured", never null or a missing key -------


def test_a_node_with_no_recorded_score_renders_all_four_figures_as_unmeasured() -> None:
    history = ((_prior("n1"), None),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")

    user = _user(parts)
    assert '"ic_tstat": "unmeasured"' in user
    assert '"ir_tstat": "unmeasured"' in user
    assert '"turnover": "unmeasured"' in user
    assert '"cost_adjusted_ir": "unmeasured"' in user
    # score.json itself is unaffected -- still the literal null it always was.
    assert "score.json:\nnull" in user


def test_a_recorded_score_missing_some_metrics_renders_unmeasured_for_those_only() -> None:
    score = ScoreRecord(ic_tstat=3.8, fail_class=None)  # ir_tstat/turnover/cost_adjusted_ir absent
    history = ((_prior("n1"), score),)
    parts = build_authoring_prompt(WORKSPACE, history, clause="clause text")

    user = _user(parts)
    assert '"ic_tstat": 3.8' in user
    assert '"ir_tstat": "unmeasured"' in user
    assert '"turnover": "unmeasured"' in user
    assert '"cost_adjusted_ir": "unmeasured"' in user


def test_no_evaluation_context_renders_cadence_and_cost_as_unmeasured() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    cost_awareness = parts.task["cost_awareness"]
    assert cost_awareness["cadence"] == "unmeasured"
    assert cost_awareness["per_rebalance_cost_bps"] == "unmeasured"


def test_too_few_dates_to_name_a_spacing_renders_unmeasured() -> None:
    evaluation = SimpleNamespace(evaluation_dates=("2026-01-07",), per_rebalance_cost_bps=None)
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    cost_awareness = parts.task["cost_awareness"]
    assert cost_awareness["cadence"] == "unmeasured"
    assert cost_awareness["per_rebalance_cost_bps"] == "unmeasured"


# -- every other rendered section is byte-identical to before ----------------


def test_task_carries_exactly_the_prior_keys_plus_cost_awareness() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    assert set(parts.task) == {
        "campaign_id",
        "theme_root",
        "depth",
        "contract",
        "answer_format",
        "cost_awareness",
    }
    assert parts.task["campaign_id"] == WORKSPACE.campaign_id
    assert parts.task["theme_root"] == "momentum"
    assert parts.task["depth"] == 1
    assert parts.task["answer_format"]["mechanism_line"].startswith(
        "Exactly one line starting 'Mechanism:'"
    )


def test_still_exactly_the_three_named_parts() -> None:
    evaluation = SimpleNamespace(evaluation_dates=WEEKLY_DATES, per_rebalance_cost_bps=1.0)
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    assert {"task", "anti_convergence", "history"} == {
        name for name in ("task", "anti_convergence", "history") if hasattr(parts, name)
    }
    assert not hasattr(parts, "cost_awareness")


def test_history_blocks_prefix_is_unchanged_and_cost_figures_is_strictly_appended() -> None:
    score = ScoreRecord(
        ic_tstat=3.8, ir_tstat=2.1, turnover=0.66, cost_adjusted_ir=-0.42, fail_class=None
    )
    prior = _prior("n1", "the proposal text", "a" * 64)
    parts = build_authoring_prompt(WORKSPACE, ((prior, score),), clause="clause text")
    user = _user(parts)

    expected_prefix = (
        f"### node n1 (code_hash {'a' * 64})\n"
        "proposal.md:\nthe proposal text\n\n"
        f"score.json:\n{score.to_json()}"
    )
    index = user.index(expected_prefix)
    tail = user[index + len(expected_prefix) :]
    assert tail.startswith("\n\ncost figures:")


def test_anti_convergence_part_is_unaffected() -> None:
    evaluation = SimpleNamespace(evaluation_dates=WEEKLY_DATES, per_rebalance_cost_bps=5.0)
    parts = build_authoring_prompt(
        WORKSPACE, (), clause="Do not propose a 400th variant.", evaluation=evaluation
    )
    assert parts.anti_convergence == "Do not propose a 400th variant."
