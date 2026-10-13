"""additions_spec_research_book_v2.xml, feature 4 — the rendered authoring
prompt tells the agent which book and instrument it is scored on.

The in-sample IC→book diagnostic behind this spec found the research book
itself unstated to the agent: a node can be scored on a plain dollar-neutral
spot book, a BTC-beta-neutral book, or a USD-M perpetual book with funding
carry — and nothing in the prompt said which. This suite pins the three new
facts :func:`_cost_awareness_part` folds into ``cost_awareness``, the one
information-only line beside them, and that every other rendered section is
unchanged:

* ``instrument`` — "spot", or the USD-M perpetual funding statement, read
  duck-typed off ``evaluation.instrument``;
* ``book`` — "dollar-neutral", or the BTC-beta-neutral statement, read off
  ``evaluation.book.beta_neutral``;
* ``cost_per_unit_traded_bps`` — the fee per unit of traded notional, read
  the same way ``per_rebalance_cost_bps`` already is, "unmeasured" for
  anything else.

No module-level state, so the suite is order- and worker-independent under
pytest-xdist.
"""

from __future__ import annotations

from types import SimpleNamespace

from signal_agent._authoring_prompt import build_authoring_prompt

WORKSPACE = SimpleNamespace(
    campaign_id="8f14e45f-cea3-4f93-8d2e-000000000003",
    theme_root="momentum",
    depth=1,
)


# -- the perp plus beta-neutral rendering -------------------------------------


def test_perp_and_beta_neutral_book_render_their_statements_and_fee() -> None:
    evaluation = SimpleNamespace(
        instrument="perp",
        book=SimpleNamespace(beta_neutral=True, beta_window_days=60, beta_benchmark="BTCUSDT"),
        cost_per_unit_traded_bps=5.0,
    )
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    cost_awareness = parts.task["cost_awareness"]

    assert cost_awareness["instrument"] == (
        "USD-M perpetual; longs pay and shorts receive funding over the "
        "holding period"
    )
    assert cost_awareness["book"] == (
        "dollar- and BTC-beta-neutral (legs rescaled to equal 60-day beta)"
    )
    assert cost_awareness["cost_per_unit_traded_bps"] == 5.0


def test_instrument_book_guidance_names_funding_and_market_direction() -> None:
    evaluation = SimpleNamespace(
        instrument="perp", book=SimpleNamespace(beta_neutral=True)
    )
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    guidance = parts.task["cost_awareness"]["instrument_book_guidance"]

    assert "funding" in guidance
    assert "market direction" in guidance
    assert "cross-sectional" in guidance
    assert "information only" in guidance
    assert "judges nothing" in guidance


def test_cost_per_unit_traded_basis_names_the_turnover_relationship() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    basis = parts.task["cost_awareness"]["cost_per_unit_traded_basis"]

    assert "fee per unit of traded notional" in basis
    assert "Δw" in basis


# -- the default rendering ----------------------------------------------------


def test_no_evaluation_context_renders_spot_and_dollar_neutral_and_unmeasured_fee() -> None:
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text")
    cost_awareness = parts.task["cost_awareness"]

    assert cost_awareness["instrument"] == "spot"
    assert cost_awareness["book"] == "dollar-neutral"
    assert cost_awareness["cost_per_unit_traded_bps"] == "unmeasured"


def test_evaluation_with_no_instrument_or_book_attribute_renders_the_same_defaults() -> None:
    evaluation = SimpleNamespace(evaluation_dates=("2026-01-07", "2026-01-14"))
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    cost_awareness = parts.task["cost_awareness"]

    assert cost_awareness["instrument"] == "spot"
    assert cost_awareness["book"] == "dollar-neutral"


def test_book_with_beta_neutral_false_renders_dollar_neutral() -> None:
    evaluation = SimpleNamespace(book=SimpleNamespace(beta_neutral=False))
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    assert parts.task["cost_awareness"]["book"] == "dollar-neutral"


def test_instrument_other_than_perp_renders_spot() -> None:
    evaluation = SimpleNamespace(instrument="futures")
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    assert parts.task["cost_awareness"]["instrument"] == "spot"


def test_evaluation_context_is_duck_typed_and_accepts_a_mapping() -> None:
    evaluation = {
        "instrument": "perp",
        "book": {"beta_neutral": True},
        "cost_per_unit_traded_bps": 5.0,
    }
    parts = build_authoring_prompt(WORKSPACE, (), clause="clause text", evaluation=evaluation)
    cost_awareness = parts.task["cost_awareness"]

    assert cost_awareness["instrument"].startswith("USD-M perpetual")
    assert cost_awareness["book"].startswith("dollar- and BTC-beta-neutral")
    assert cost_awareness["cost_per_unit_traded_bps"] == 5.0


# -- every other rendered section is byte-identical ---------------------------


def test_every_other_rendered_section_is_byte_identical() -> None:
    perp_evaluation = SimpleNamespace(
        evaluation_dates=("2026-01-07", "2026-01-14", "2026-01-21"),
        per_rebalance_cost_bps=23.5,
        instrument="perp",
        book=SimpleNamespace(beta_neutral=True),
        cost_per_unit_traded_bps=5.0,
    )
    default_evaluation = SimpleNamespace(
        evaluation_dates=("2026-01-07", "2026-01-14", "2026-01-21"),
        per_rebalance_cost_bps=23.5,
    )

    perp_parts = build_authoring_prompt(
        WORKSPACE, (), clause="clause text", evaluation=perp_evaluation
    )
    default_parts = build_authoring_prompt(
        WORKSPACE, (), clause="clause text", evaluation=default_evaluation
    )

    perp_cost_awareness = dict(perp_parts.task["cost_awareness"])
    default_cost_awareness = dict(default_parts.task["cost_awareness"])

    changed = {"instrument", "book", "cost_per_unit_traded_bps"}
    for key in changed:
        del perp_cost_awareness[key]
        del default_cost_awareness[key]
    assert perp_cost_awareness == default_cost_awareness

    perp_task = dict(perp_parts.task)
    default_task = dict(default_parts.task)
    del perp_task["cost_awareness"]
    del default_task["cost_awareness"]
    assert perp_task == default_task

    assert perp_parts.anti_convergence == default_parts.anti_convergence
    assert perp_parts.history == default_parts.history
