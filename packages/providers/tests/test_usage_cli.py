"""Feature 5 of additions_spec_llm_usage_tracking.xml: the usage-reporting CLI.

*System reports spend from* ``python -m providers.usage [--campaign ID]
[--by campaign|pin|role|node]`` *and displays one JSON line per group plus a
total line.* This suite drives :func:`providers.usage.main` directly over a
tmp sqlite store built with :class:`providers.UsageStore` — no subprocess,
no network, no credential — one test per claim the feature sentence makes:

* grouping by each of the four ``--by`` columns;
* ``--campaign latest`` resolving the most recently recorded campaign;
* ``--campaign ID`` narrowing to one campaign;
* an empty store (and an unknown campaign) printing a zero-calls total and
  exiting 0;
* a missing ``DATABASE_URL`` exiting 2, naming it;
* an unpriced row (a dated served id the price table does not map exactly)
  surfacing in ``unpriced_calls`` rather than a guessed cost.
"""

from __future__ import annotations

import json

from providers._prices import PRICE_TABLE_VERSION
from providers._usage_store import OUTCOME_OK, UsageStore
from providers.usage import DATABASE_URL_ENV, EXIT_CONFIG, EXIT_OK, main


def _record(
    store: UsageStore,
    *,
    campaign_id: str = "campaign-1",
    node_id: str | None = "node-1",
    role: str = "depth",
    pin: str = "anthropic/claude-haiku-4-5/20260401",
    served_model: str = "claude-haiku-4-5",
    input_tokens: int = 100,
    cache_write_tokens: int = 0,
    cache_read_tokens: int = 0,
    output_tokens: int = 50,
    outcome: str = OUTCOME_OK,
    duration_ms: int = 10,
):
    return store.record(
        campaign_id=campaign_id,
        node_id=node_id,
        role=role,
        pin=pin,
        served_model=served_model,
        input_tokens=input_tokens,
        cache_write_tokens=cache_write_tokens,
        cache_read_tokens=cache_read_tokens,
        output_tokens=output_tokens,
        outcome=outcome,
        duration_ms=duration_ms,
    )


def _lines(database_url: str, argv: list[str]) -> list[dict]:
    out: list[str] = []
    exit_code = main(argv, env={"DATABASE_URL": database_url}, emit=out.append)
    return [json.loads(line) for line in out], exit_code  # type: ignore[return-value]


# -- Grouping -----------------------------------------------------------------


def test_groups_by_campaign_with_one_line_per_campaign_plus_a_total(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="alpha", input_tokens=100, output_tokens=50)
    _record(store, campaign_id="alpha", input_tokens=200, output_tokens=25)
    _record(store, campaign_id="beta", input_tokens=10, output_tokens=5)

    lines, exit_code = _lines(database_url, ["--by", "campaign"])

    assert exit_code == EXIT_OK
    assert len(lines) == 3  # two campaign groups + the total
    *groups, total = lines
    by_campaign = {g["campaign_id"]: g for g in groups}
    assert by_campaign.keys() == {"alpha", "beta"}
    assert by_campaign["alpha"]["calls"] == 2
    assert by_campaign["alpha"]["input_tokens"] == 300
    assert by_campaign["alpha"]["output_tokens"] == 75
    assert by_campaign["beta"]["calls"] == 1
    assert total["calls"] == 3
    assert total["input_tokens"] == 310
    assert total["price_table_version"] == PRICE_TABLE_VERSION
    # Group lines never name the price table version; only the total does.
    for group in groups:
        assert "price_table_version" not in group


def test_groups_by_pin(database_url):
    store = UsageStore(database_url)
    _record(store, pin="anthropic/claude-haiku-4-5/20260401")
    _record(store, pin="anthropic/claude-haiku-4-5/20260401")
    _record(store, pin="anthropic/claude-sonnet-5-5/20260401", served_model="claude-sonnet-5-5")

    lines, exit_code = _lines(database_url, ["--by", "pin"])

    assert exit_code == EXIT_OK
    *groups, total = lines
    by_pin = {g["pin"]: g for g in groups}
    assert by_pin["anthropic/claude-haiku-4-5/20260401"]["calls"] == 2
    assert by_pin["anthropic/claude-sonnet-5-5/20260401"]["calls"] == 1
    assert total["calls"] == 3


def test_groups_by_role(database_url):
    store = UsageStore(database_url)
    _record(store, role="depth")
    _record(store, role="signal")
    _record(store, role="signal")

    lines, exit_code = _lines(database_url, ["--by", "role"])

    assert exit_code == EXIT_OK
    *groups, total = lines
    by_role = {g["role"]: g for g in groups}
    assert by_role["depth"]["calls"] == 1
    assert by_role["signal"]["calls"] == 2
    assert total["calls"] == 3


def test_groups_by_node_including_unattributed_calls(database_url):
    store = UsageStore(database_url)
    _record(store, node_id="node-1")
    _record(store, node_id=None)

    lines, exit_code = _lines(database_url, ["--by", "node"])

    assert exit_code == EXIT_OK
    *groups, total = lines
    by_node = {g["node_id"]: g for g in groups}
    assert by_node["node-1"]["calls"] == 1
    assert by_node[None]["calls"] == 1
    assert total["calls"] == 2


def test_default_by_is_campaign(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="alpha")

    lines, exit_code = _lines(database_url, [])

    assert exit_code == EXIT_OK
    assert len(lines) == 2
    assert lines[0]["campaign_id"] == "alpha"


# -- --campaign ID and --campaign latest ---------------------------------------


def test_campaign_filter_narrows_to_one_campaigns_rows(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="alpha", role="depth")
    _record(store, campaign_id="alpha", role="signal")
    _record(store, campaign_id="beta", role="depth")

    lines, exit_code = _lines(database_url, ["--campaign", "alpha", "--by", "role"])

    assert exit_code == EXIT_OK
    *groups, total = lines
    assert total["calls"] == 2
    assert {g["role"] for g in groups} == {"depth", "signal"}


def test_campaign_latest_selects_the_most_recently_recorded_campaign(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="older")
    _record(store, campaign_id="older")
    _record(store, campaign_id="newer")

    lines, exit_code = _lines(database_url, ["--campaign", "latest", "--by", "campaign"])

    assert exit_code == EXIT_OK
    *groups, total = lines
    assert len(groups) == 1
    assert groups[0]["campaign_id"] == "newer"
    assert total["calls"] == 1


def test_unknown_campaign_id_prints_a_zero_calls_total_and_exits_0(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="alpha")

    lines, exit_code = _lines(database_url, ["--campaign", "does-not-exist"])

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    assert lines[0]["calls"] == 0


# -- The empty store ------------------------------------------------------------


def test_empty_store_prints_a_zero_calls_total_and_exits_0(database_url):
    lines, exit_code = _lines(database_url, [])

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    total = lines[0]
    assert total["calls"] == 0
    assert total["input_tokens"] == 0
    assert total["cache_write_tokens"] == 0
    assert total["cache_read_tokens"] == 0
    assert total["output_tokens"] == 0
    assert total["est_cost_usd"] is None
    assert total["unpriced_calls"] == 0
    assert total["price_table_version"] == PRICE_TABLE_VERSION


def test_campaign_latest_on_an_empty_store_prints_a_zero_calls_total(database_url):
    lines, exit_code = _lines(database_url, ["--campaign", "latest"])

    assert exit_code == EXIT_OK
    assert len(lines) == 1
    assert lines[0]["calls"] == 0


# -- Missing DATABASE_URL --------------------------------------------------------


def test_missing_database_url_exits_2_naming_it():
    import io
    from contextlib import redirect_stderr

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env={}, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert DATABASE_URL_ENV in stderr.getvalue()


def test_blank_database_url_exits_2(database_url):
    import io
    from contextlib import redirect_stderr

    stderr = io.StringIO()
    with redirect_stderr(stderr):
        exit_code = main([], env={"DATABASE_URL": "   "}, emit=lambda _line: None)

    assert exit_code == EXIT_CONFIG
    assert "DATABASE_URL" in stderr.getvalue()


# -- An unpriced row --------------------------------------------------------------


def test_unpriced_row_surfaces_in_unpriced_calls_not_a_guessed_cost(database_url):
    store = UsageStore(database_url)
    # claude-haiku-4-5 is priced; the dated served id below is a different
    # string the table does not map exactly (providers._prices' own
    # contract), so this row's est_cost_usd is None.
    _record(store, campaign_id="alpha", served_model="claude-haiku-4-5")
    _record(
        store,
        campaign_id="alpha",
        served_model="claude-haiku-4-5-20251001",
        input_tokens=1000,
        output_tokens=500,
    )

    lines, exit_code = _lines(database_url, ["--campaign", "alpha"])

    assert exit_code == EXIT_OK
    group, total = lines
    assert group["calls"] == 2
    assert group["unpriced_calls"] == 1
    assert group["est_cost_usd"] is not None  # the priced row's own cost
    assert total["unpriced_calls"] == 1
    assert total["est_cost_usd"] == group["est_cost_usd"]


def test_a_group_wholly_unpriced_has_a_null_est_cost_usd(database_url):
    store = UsageStore(database_url)
    _record(
        store,
        campaign_id="alpha",
        role="depth",
        served_model="claude-haiku-4-5-20251001",
    )

    lines, exit_code = _lines(database_url, ["--campaign", "alpha", "--by", "role"])

    assert exit_code == EXIT_OK
    group, total = lines
    assert group["unpriced_calls"] == 1
    assert group["est_cost_usd"] is None
    assert total["est_cost_usd"] is None
