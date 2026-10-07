"""Feature 3's store and recorder: every provider call's usage, saved.

app_spec addition ``additions_spec_llm_usage_tracking.xml``, feature 3:
*System saves every provider call's usage to an append-only
``provider_call_usage`` table, so that each call returns one stored row with
its tokens, attribution and estimated cost.*  Two halves, two groups of
tests:

* :class:`~providers._usage_store.UsageStore` — the table itself:
  :meth:`~providers._usage_store.UsageStore.record` writes and prices one row,
  :meth:`~providers._usage_store.UsageStore.rows` and
  :meth:`~providers._usage_store.UsageStore.totals` read it back, and the
  table is created idempotently on connect (no migration, no prerequisite
  fixture).
* :class:`~providers._usage_store.UsageRecordingProvider` — the wrapper that
  calls :meth:`~providers._usage_store.UsageStore.record` as a side effect of
  completing a call, over a :class:`~providers.Provider` the way
  :mod:`test_budget` drives :class:`~providers.BudgetedProvider` over a
  :class:`~conftest.ScriptedProvider`.

Neither suite reaches the network or needs a migration: the store owns its
own table, created the first time any test connects to the tmp sqlite file
``database_url`` (from the suite's shared ``conftest.py``) names.
"""

from __future__ import annotations

from decimal import Decimal

import providers._usage_store as usage_store_module
import pytest
from providers import (
    BudgetedProvider,
    BudgetExhaustedError,
    ModelPin,
    Provider,
    ProviderError,
    UnknownModelError,
)
from providers._prices import PRICE_TABLE_VERSION
from providers._usage_store import (
    OUTCOME_ERROR,
    OUTCOME_OK,
    OUTCOME_REFUSED_BUDGET,
    PROVIDER_CALL_USAGE_TABLE,
    UsageRecordingProvider,
    UsageRow,
    UsageStore,
    UsageStoreError,
)

# ── Shared builders ───────────────────────────────────────────────────────────


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
) -> UsageRow:
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


@pytest.fixture(autouse=True)
def _reset_store_failure_warning(monkeypatch):
    """Every test starts with a clean "has this process warned yet?" flag.

    The flag :mod:`providers._usage_store` keeps is deliberately process-wide
    (the addition's own word: "logged once per process"), which would
    otherwise make whichever test happens to run first in a worker the only
    one that can ever observe the warning. Resetting it here, before every
    test in this module, makes each test's own observation deterministic
    regardless of what ran before it in this worker — the module's behaviour
    is unchanged, only this suite's starting state is.
    """
    monkeypatch.setattr(usage_store_module, "_STORE_FAILURE_WARNED", False)


# ── UsageStore: construction and resolve() ────────────────────────────────────


def test_resolve_returns_none_without_database_url():
    assert UsageStore.resolve({}) is None
    assert UsageStore.resolve({"DATABASE_URL": "  "}) is None


def test_resolve_returns_a_store_with_database_url(database_url):
    store = UsageStore.resolve({"DATABASE_URL": database_url})
    assert isinstance(store, UsageStore)
    assert store.database_url == database_url


def test_construction_performs_no_io(tmp_path):
    # Building the store must not touch the disk: composition-time work
    # (create_app() on every request) must never create a database file.
    never_created = tmp_path / "untouched.db"
    UsageStore(f"sqlite:///{never_created}")
    assert not never_created.exists()


# ── UsageStore.record(): the ok row, exact counts and cost ───────────────────


def test_record_returns_and_persists_an_ok_row_with_exact_counts_and_cost(
    database_url,
):
    store = UsageStore(database_url)
    row = _record(
        store,
        campaign_id="campaign-42",
        node_id="node-7",
        role="depth",
        pin="anthropic/claude-sonnet-5-5/20260401",
        served_model="claude-sonnet-5-5",
        input_tokens=1_000_000,
        cache_write_tokens=100_000,
        cache_read_tokens=200_000,
        output_tokens=500_000,
        outcome=OUTCOME_OK,
        duration_ms=42,
    )

    # claude-sonnet-5-5: input 2.00, cache write 2.50, cache read 0.20,
    # output 10.00 (USD/million). plain input = 1,000,000 - 100,000 -
    # 200,000 = 700,000.
    # (700,000*2.00 + 100,000*2.50 + 200,000*0.20 + 500,000*10.00) / 1e6
    # = (1,400,000 + 250,000 + 40,000 + 5,000,000) / 1e6 = 6.69
    assert row.id > 0
    assert row.campaign_id == "campaign-42"
    assert row.node_id == "node-7"
    assert row.role == "depth"
    assert row.pin == "anthropic/claude-sonnet-5-5/20260401"
    assert row.served_model == "claude-sonnet-5-5"
    assert row.input_tokens == 1_000_000
    assert row.cache_write_tokens == 100_000
    assert row.cache_read_tokens == 200_000
    assert row.output_tokens == 500_000
    assert row.est_cost_usd == Decimal("6.690000")
    assert row.price_table_version == PRICE_TABLE_VERSION
    assert row.outcome == OUTCOME_OK
    assert row.duration_ms == 42
    assert row.recorded_at  # a non-empty stamp; exact format is this store's own

    # And the row the table holds is the same row record() answered.
    (stored,) = store.rows("campaign-42")
    assert stored == row


def test_record_accepts_a_model_pin_object_rendered_as_its_triple(database_url):
    store = UsageStore(database_url)
    pin = ModelPin(provider="anthropic", model="claude-opus-5", version="20260401")
    row = _record(store, pin=pin)
    assert row.pin == str(pin) == "anthropic/claude-opus-5/20260401"


def test_record_prices_an_unmapped_model_as_none_never_zero(database_url):
    store = UsageStore(database_url)
    row = _record(
        store,
        served_model="some-model-the-price-table-does-not-list",
        input_tokens=1_000,
        output_tokens=1_000,
    )
    assert row.est_cost_usd is None
    # The table consulted is still named, even though it had nothing to say.
    assert row.price_table_version == PRICE_TABLE_VERSION


def test_table_is_created_on_connect_not_at_construction(database_url):
    # No migration brings this table; a fresh file answers an empty read
    # rather than an OperationalError about a table nobody created yet.
    store = UsageStore(database_url)
    assert store.rows() == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"campaign_id": ""},
        {"campaign_id": None},
        {"role": ""},
        {"pin": None},
        {"served_model": ""},
        {"outcome": "retrying"},
        {"input_tokens": -1},
        {"input_tokens": True},
        {"duration_ms": -1},
    ],
)
def test_record_refuses_a_malformed_ask(database_url, overrides):
    store = UsageStore(database_url)
    with pytest.raises(UsageStoreError):
        _record(store, **overrides)


# ── UsageStore.rows(): the point and whole reads ──────────────────────────────


def test_rows_with_no_campaign_reads_every_row(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="c1")
    _record(store, campaign_id="c2")
    assert len(store.rows()) == 2


def test_rows_filters_by_campaign_id(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="c1")
    _record(store, campaign_id="c2")
    _record(store, campaign_id="c2")
    assert [r.campaign_id for r in store.rows("c1")] == ["c1"]
    assert len(store.rows("c2")) == 2


def test_rows_of_an_unknown_campaign_is_empty(database_url):
    store = UsageStore(database_url)
    _record(store, campaign_id="c1")
    assert store.rows("no-such-campaign") == ()


# ── UsageStore.totals(): grouping, summing, unpriced counted separately ──────


def test_totals_groups_sums_tokens_and_cost_and_counts_unpriced_separately(
    database_url,
):
    store = UsageStore(database_url)
    # Two rows share (campaign-1, haiku pin): one priced, one the table does
    # not map. A third row is a different group entirely.
    _record(
        store,
        campaign_id="camp-1",
        pin="anthropic/claude-haiku-4-5/v1",
        served_model="claude-haiku-4-5",
        input_tokens=10_000,
        output_tokens=2_000,
    )
    _record(
        store,
        campaign_id="camp-1",
        pin="anthropic/claude-haiku-4-5/v1",
        served_model="unknown-model-xyz",
        input_tokens=500,
        output_tokens=100,
    )
    _record(
        store,
        campaign_id="camp-2",
        pin="anthropic/claude-opus-5-5/v1",
        served_model="claude-opus-5-5",
        input_tokens=1_000_000,
        output_tokens=100_000,
    )

    totals = store.totals(group_by=("campaign_id", "pin"))
    assert len(totals) == 2

    by_group = {tuple(sorted(t.group.items())): t for t in totals}
    haiku_group = by_group[
        (("campaign_id", "camp-1"), ("pin", "anthropic/claude-haiku-4-5/v1"))
    ]
    assert haiku_group.calls == 2
    assert haiku_group.input_tokens == 10_500
    assert haiku_group.output_tokens == 2_100
    assert haiku_group.cache_write_tokens == 0
    assert haiku_group.cache_read_tokens == 0
    # claude-haiku-4-5: input 1.00, output 5.00 (USD/million).
    # (10,000*1.00 + 2,000*5.00) / 1e6 = 0.02 — only the priced row counts.
    assert haiku_group.est_cost_usd == Decimal("0.020000")
    assert haiku_group.unpriced_calls == 1

    opus_group = by_group[
        (("campaign_id", "camp-2"), ("pin", "anthropic/claude-opus-5-5/v1"))
    ]
    assert opus_group.calls == 1
    # claude-opus-5-5: input 4.00, output 20.00 (USD/million).
    # (1,000,000*4.00 + 100,000*20.00) / 1e6 = 6.00
    assert opus_group.est_cost_usd == Decimal("6.000000")
    assert opus_group.unpriced_calls == 0


def test_totals_with_every_row_unpriced_answers_none_not_zero(database_url):
    store = UsageStore(database_url)
    _record(store, served_model="unknown-a")
    _record(store, served_model="unknown-b")
    (total,) = store.totals(group_by=("campaign_id",))
    assert total.calls == 2
    assert total.unpriced_calls == 2
    assert total.est_cost_usd is None


def test_totals_with_no_rows_is_empty(database_url):
    store = UsageStore(database_url)
    assert store.totals() == ()


def test_totals_refuses_a_column_it_does_not_group_by(database_url):
    store = UsageStore(database_url)
    with pytest.raises(UsageStoreError):
        store.totals(group_by=("input_tokens",))


def test_totals_refuses_an_empty_group_by(database_url):
    store = UsageStore(database_url)
    with pytest.raises(UsageStoreError):
        store.totals(group_by=())


# ── UsageRecordingProvider: the wrapper ───────────────────────────────────────


def test_is_itself_a_provider(scripted_provider, make_completion, database_url):
    wrapped = UsageRecordingProvider(
        scripted_provider(lambda request: make_completion()),
        store=UsageStore(database_url),
        campaign_id="c",
        node_id="n",
        role="depth",
        pin="anthropic/claude-haiku-4-5/v1",
    )
    assert isinstance(wrapped, Provider)


def test_must_wrap_a_provider(database_url):
    with pytest.raises(ProviderError):
        UsageRecordingProvider(
            object(),
            store=UsageStore(database_url),
            campaign_id="c",
            node_id="n",
            role="depth",
            pin="p",
        )


def test_an_ok_completion_is_returned_unchanged_and_recorded_once(
    scripted_provider, make_request, database_url
):
    from providers import Completion, Usage

    completion = Completion(
        content="answer",
        model="claude-sonnet-5-5",
        usage=Usage(
            input_tokens=1_000,
            output_tokens=200,
            cache_write_tokens=50,
            cache_read_tokens=10,
        ),
    )
    store = UsageStore(database_url)
    wrapped = UsageRecordingProvider(
        scripted_provider(lambda request: completion),
        store=store,
        campaign_id="campaign-x",
        node_id="node-y",
        role="root",
        pin="anthropic/claude-sonnet-5-5/20260401",
    )

    result = wrapped.complete(make_request(bodies=(("user", "hi"),)))

    assert result == completion
    (row,) = store.rows("campaign-x")
    assert row.node_id == "node-y"
    assert row.role == "root"
    assert row.pin == "anthropic/claude-sonnet-5-5/20260401"
    assert row.served_model == "claude-sonnet-5-5"
    assert row.input_tokens == 1_000
    assert row.cache_write_tokens == 50
    assert row.cache_read_tokens == 10
    assert row.output_tokens == 200
    assert row.outcome == OUTCOME_OK
    assert row.est_cost_usd is not None


def test_an_exception_is_recorded_as_error_and_reraised_unchanged(
    scripted_provider, make_request, database_url
):
    boom = ValueError("the transport fell over")

    def _raise(request):
        raise boom

    store = UsageStore(database_url)
    wrapped = UsageRecordingProvider(
        scripted_provider(_raise),
        store=store,
        campaign_id="campaign-err",
        node_id=None,
        role="depth",
        pin="anthropic/claude-haiku-4-5/v1",
    )

    with pytest.raises(ValueError) as caught:
        wrapped.complete(make_request())
    assert caught.value is boom  # the same exception object, not a copy

    (row,) = store.rows("campaign-err")
    assert row.outcome == OUTCOME_ERROR
    assert row.node_id is None
    assert row.input_tokens == 0
    assert row.cache_write_tokens == 0
    assert row.cache_read_tokens == 0
    assert row.output_tokens == 0
    assert row.est_cost_usd is None


def test_a_budget_refusal_is_recorded_as_refused_budget_and_reraised_unchanged(
    scripted_provider, make_completion, make_request, database_url
):
    inner = scripted_provider(lambda request: make_completion(input_tokens=999))
    budgeted = BudgetedProvider(inner, max_input_tokens=0, max_output_tokens=0)
    store = UsageStore(database_url)
    wrapped = UsageRecordingProvider(
        budgeted,
        store=store,
        campaign_id="campaign-budget",
        node_id="node-1",
        role="policy",
        pin="anthropic/claude-haiku-4-5/v1",
    )

    with pytest.raises(BudgetExhaustedError):
        wrapped.complete(make_request())

    (row,) = store.rows("campaign-budget")
    assert row.outcome == OUTCOME_REFUSED_BUDGET
    assert row.input_tokens == 0
    assert row.output_tokens == 0
    # Nothing served the call, so the row attributes it to what was asked.
    assert row.served_model == "test-model"
    # The budget's own totals are unaffected by the recorder sitting outside it.
    assert budgeted.spent() == (0, 0)


def test_check_model_passes_through_and_records_nothing(
    scripted_provider, make_request, database_url
):
    inner = scripted_provider(lambda request: request, models={"allowed"})
    store = UsageStore(database_url)
    wrapped = UsageRecordingProvider(
        inner,
        store=store,
        campaign_id="campaign-checks",
        node_id=None,
        role="depth",
        pin="anthropic/claude-haiku-4-5/v1",
    )

    assert wrapped.check_model("allowed") == "allowed"
    with pytest.raises(UnknownModelError):
        wrapped.check_model("forbidden")
    with pytest.raises(UnknownModelError):
        wrapped.complete(make_request(model="forbidden"))

    # check_model is not a completion: no row is written for either call.
    assert store.rows() == ()


def test_a_failing_store_leaves_an_ok_call_intact(
    scripted_provider, make_completion, make_request, caplog
):
    class _BrokenStore:
        def record(self, **kwargs):
            raise RuntimeError("store is unreachable")

    completion = make_completion(input_tokens=5, output_tokens=5)
    wrapped = UsageRecordingProvider(
        scripted_provider(lambda request: completion),
        store=_BrokenStore(),
        campaign_id="c",
        node_id="n",
        role="depth",
        pin="p",
    )

    caplog.set_level("WARNING", logger="providers.usage_store")
    result = wrapped.complete(make_request())

    assert result == completion
    assert any(
        "usage" in record.message.lower() for record in caplog.records
    )


def test_a_failing_store_leaves_a_raised_exception_intact(
    scripted_provider, make_request
):
    class _BrokenStore:
        def record(self, **kwargs):
            raise RuntimeError("store is unreachable")

    boom = KeyError("missing field")

    def _raise(request):
        raise boom

    wrapped = UsageRecordingProvider(
        scripted_provider(_raise),
        store=_BrokenStore(),
        campaign_id="c",
        node_id="n",
        role="depth",
        pin="p",
    )

    with pytest.raises(KeyError) as caught:
        wrapped.complete(make_request())
    assert caught.value is boom


def test_a_store_failure_is_logged_only_once_per_process(
    scripted_provider, make_completion, make_request, caplog
):
    class _BrokenStore:
        def record(self, **kwargs):
            raise RuntimeError("store is unreachable")

    wrapped = UsageRecordingProvider(
        scripted_provider(lambda request: make_completion()),
        store=_BrokenStore(),
        campaign_id="c",
        node_id="n",
        role="depth",
        pin="p",
    )

    caplog.set_level("WARNING", logger="providers.usage_store")
    wrapped.complete(make_request())
    wrapped.complete(make_request())
    wrapped.complete(make_request())

    warnings = [r for r in caplog.records if r.name == "providers.usage_store"]
    assert len(warnings) == 1


def test_batches_are_refused_by_the_base_classs_not_implemented_error(
    scripted_provider, make_completion, make_request, database_url
):
    from providers import BatchRequest, NotImplementedBatchError

    wrapped = UsageRecordingProvider(
        scripted_provider(lambda request: make_completion()),
        store=UsageStore(database_url),
        campaign_id="c",
        node_id="n",
        role="depth",
        pin="p",
    )
    with pytest.raises(NotImplementedBatchError):
        wrapped.complete_batch(BatchRequest(requests=(make_request(),)))


def test_the_provider_call_usage_table_name_is_stable():
    # A reporter or a dashboard that reads the table directly (feature 5)
    # needs this name to be the one contract both sides share.
    assert PROVIDER_CALL_USAGE_TABLE == "provider_call_usage"
