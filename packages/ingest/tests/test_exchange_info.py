"""Daily exchangeInfo filters, persisted version-on-version.

These tests are the feature statement for app_spec.xml feature 24 —
*"System ingests exchangeInfo filters daily, persisting each fetch as a new
version rather than overwriting the prior one"* — read as behaviour of the
version store, the daily worker and the parser they stand on:

* a fetch lands as the next version in an append-only log, and a prior
  version's bytes are never rewritten by a later one;
* a fetch that repeats the previous filters is *still* a new version — the
  feature says each fetch is persisted, and "the refresh ran and nothing
  changed" is exactly the fact an operator needs to tell apart from "the
  refresh never ran";
* the daily cadence is decided from the durable log, so a restart mid-day
  does not re-fetch and a process that was down across a boundary fetches
  on its next cycle;
* a failed fetch — a rate-limit body, a truncated document — is refused
  *before* anything is written, so the log never records a refresh that did
  not happen;
* the §13.2 constants the order path must never hardcode (``stepSize``,
  ``tickSize``, ``minNotional``) are read back off the persisted version in
  the venue's own spelling, and damaged bytes are refused rather than
  parsed into a plausible-looking tick size.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nullius_ingest import (
    EXCHANGE_INFO_STREAM,
    DailyExchangeInfoWorker,
    ExchangeInfoCorruptError,
    ExchangeInfoDocument,
    ExchangeInfoError,
    ExchangeInfoParseError,
    ExchangeInfoVersion,
    ExchangeInfoVersionStore,
    FilterType,
    StagingArea,
    StreamClass,
    SymbolFilters,
    parse_exchange_info,
)
from nullius_ingest.exchange_info import register_exchange_info_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A day well inside the current UTC day's past, so "was this fetched on an
#: earlier date?" is unambiguous without depending on when the suite runs.
DAY_ONE = datetime(2026, 3, 1, 6, 30, tzinfo=UTC)

#: The same day, later — a restart mid-day, which must not re-fetch.
SAME_DAY_LATER = datetime(2026, 3, 1, 23, 45, tzinfo=UTC)

#: The next UTC day, so a fetch becomes due again.
DAY_TWO = datetime(2026, 3, 2, 0, 5, tzinfo=UTC)


def btc_filters(step_size: str = "0.001", tick_size: str = "0.10") -> dict:
    """One venue-shaped symbol entry, the way an exchangeInfo response spells it."""
    return {
        "symbol": "BTCUSDT",
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "minPrice": "0.01",
                "maxPrice": "1000000.00",
                "tickSize": tick_size,
            },
            {
                "filterType": "LOT_SIZE",
                "minQty": "0.001",
                "maxQty": "9000.000",
                "stepSize": step_size,
            },
            {
                "filterType": "NOTIONAL",
                "minNotional": "10.00000000",
                "applyToMarket": True,
            },
        ],
    }


def eth_filters() -> dict:
    return {
        "symbol": "ETHUSDT",
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "minPrice": "0.01",
                "maxPrice": "100000.00",
                "tickSize": "0.01",
            },
            {"filterType": "LOT_SIZE", "minQty": "0.01", "stepSize": "0.01"},
        ],
    }


def document(*symbols: dict) -> dict:
    """A full exchangeInfo response carrying the given symbol entries."""
    return {"timezone": "UTC", "symbols": list(symbols)}


# -- Parsing the venue's document -------------------------------------------


def test_parses_the_filters_of_every_symbol() -> None:
    parsed = parse_exchange_info(document(btc_filters(), eth_filters()))

    assert isinstance(parsed, ExchangeInfoDocument)
    assert parsed.symbol_names == ("BTCUSDT", "ETHUSDT")
    assert len(parsed) == 2
    assert parsed.for_symbol("BTCUSDT") is not None
    assert parsed.for_symbol("SOLUSDT") is None


def test_filter_values_are_kept_verbatim_in_the_venues_spelling() -> None:
    # The record must not round anything: whether the venue said "0.001" or
    # "0.0010" is a fact about the venue, and re-rendering it would make an
    # audit unable to tell a venue change from our own lossy parse.
    parsed = parse_exchange_info(document(btc_filters(step_size="0.0010")))
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.step_size == "0.0010"
    assert btc.tick_size == "0.10"
    assert btc.filter(FilterType.LOT_SIZE) == {
        "minQty": "0.001",
        "maxQty": "9000.000",
        "stepSize": "0.0010",
    }


def test_scalar_fields_arrive_as_the_string_spelling() -> None:
    # Venues are inconsistent about JSON types for the same field — a boolean
    # flag, a bare integer — so scalars are spelled rather than rejected.
    parsed = parse_exchange_info(document(btc_filters()))
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    # ``applyToMarket`` came through as JSON ``true``.
    assert btc.value(FilterType.NOTIONAL, "applyToMarket") == "true"


def test_unknown_filter_types_and_fields_are_kept_not_dropped() -> None:
    # A venue adding a filter is a schema change to absorb, not a fetch to
    # discard — and a version is written once, so a field dropped at persist
    # time is a field lost forever.
    parsed = parse_exchange_info(
        document(
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {
                        "filterType": "MAX_NUM_ORDERS",
                        "maxNumOrders": 200,
                        "someNewField": "kept",
                    }
                ],
            }
        )
    )
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.filter("MAX_NUM_ORDERS") == {
        "maxNumOrders": "200",
        "someNewField": "kept",
    }


def test_accepts_the_wrapped_document_some_endpoints_use() -> None:
    wrapped = {"exchangeInfo": document(btc_filters())}

    parsed = parse_exchange_info(wrapped)

    assert parsed.symbol_names == ("BTCUSDT",)


def test_accepts_json_bytes_and_strings() -> None:
    import json

    payload = json.dumps(document(btc_filters())).encode()

    assert parse_exchange_info(payload).symbol_names == ("BTCUSDT",)
    assert parse_exchange_info(payload.decode()).symbol_names == ("BTCUSDT",)


def test_an_empty_document_is_refused() -> None:
    # An exchangeInfo response with no symbols is a rate-limit body, an error
    # page or a truncated read — never a refresh.  Persisting it would make a
    # failed fetch indistinguishable from a successful one.
    with pytest.raises(ExchangeInfoParseError, match="at least one symbol"):
        parse_exchange_info({"symbols": []})


def test_a_symbol_listed_twice_is_refused() -> None:
    # A duplicate makes "the filters for BTCUSDT" ambiguous, and picking one
    # arbitrarily is a silent choice between two different tick sizes.
    with pytest.raises(ExchangeInfoParseError, match="listed more than once"):
        parse_exchange_info(document(btc_filters(), btc_filters()))


def test_a_symbol_without_filters_is_refused() -> None:
    with pytest.raises(ExchangeInfoParseError, match="carries no filters"):
        parse_exchange_info(document({"symbol": "BTCUSDT", "filters": []}))


def test_a_filter_without_a_type_is_refused() -> None:
    with pytest.raises(ExchangeInfoParseError, match="no non-empty 'filterType'"):
        parse_exchange_info(
            document({"symbol": "BTCUSDT", "filters": [{"tickSize": "0.1"}]})
        )


def test_a_container_field_value_is_refused() -> None:
    # A nested object is a shape this module does not model; storing its repr
    # would be a record that looks like data and is not.
    with pytest.raises(ExchangeInfoParseError, match="must be scalars"):
        parse_exchange_info(
            document(
                {
                    "symbol": "BTCUSDT",
                    "filters": [
                        {"filterType": "ODD", "nested": {"a": 1}},
                    ],
                }
            )
        )


def test_a_payload_that_is_not_json_is_refused() -> None:
    with pytest.raises(ExchangeInfoParseError, match="not valid JSON"):
        parse_exchange_info(b"<html>rate limited</html>")


def test_same_filters_hash_the_same_whatever_order_they_arrive_in() -> None:
    # The content hash answers "did the filters change?", so a venue that
    # merely reordered its listing has not changed a single filter.
    forward = parse_exchange_info(document(btc_filters(), eth_filters()))
    reversed_ = parse_exchange_info(document(eth_filters(), btc_filters()))

    assert forward.source_sha256 == reversed_.source_sha256
    # ...while the persisted document keeps the venue's own order, because
    # that is what a human diffing two versions reads.
    assert forward.symbol_names == ("BTCUSDT", "ETHUSDT")
    assert reversed_.symbol_names == ("ETHUSDT", "BTCUSDT")


def test_same_filters_hash_the_same_whatever_order_the_filters_arrive_in() -> None:
    # The same rule one level down: a venue that reordered its *filter list*
    # has not changed a filter either.  Safe to sort by filter type because
    # the parser has already refused a duplicate type within a symbol.
    forward = parse_exchange_info(
        {"symbols": [{"symbol": "BTCUSDT", "filters": btc_filters()["filters"]}]}
    )
    reversed_ = parse_exchange_info(
        {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "filters": list(reversed(btc_filters()["filters"])),
                }
            ]
        }
    )

    assert forward.source_sha256 == reversed_.source_sha256
    # ...while the venue's own filter order is what the persisted document
    # keeps and what the accessors read back.
    btc = forward.for_symbol("BTCUSDT")
    assert btc is not None
    assert btc.filter_types == ("PRICE_FILTER", "LOT_SIZE", "NOTIONAL")
    assert btc.step_size == "0.001" and btc.tick_size == "0.10"


def test_changing_one_filter_value_changes_the_hash() -> None:
    before = parse_exchange_info(document(btc_filters(step_size="0.001")))
    after = parse_exchange_info(document(btc_filters(step_size="0.002")))

    assert before.source_sha256 != after.source_sha256


# -- SymbolFilters accessors: the §13.2 constants ----------------------------


def test_the_order_paths_constants_read_off_the_parsed_filters() -> None:
    parsed = parse_exchange_info(document(btc_filters()))
    btc = parsed.for_symbol("BTCUSDT")

    assert isinstance(btc, SymbolFilters)
    assert btc.step_size == "0.001"
    assert btc.tick_size == "0.10"
    assert btc.min_qty == "0.001"
    assert btc.min_notional == "10.00000000"


def test_min_notional_falls_back_to_the_older_spelling() -> None:
    # A venue that spells it MIN_NOTIONAL has not stopped having a minimum
    # order value.
    parsed = parse_exchange_info(
        document(
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5.0"},
                ],
            }
        )
    )
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.min_notional == "5.0"


def test_an_absent_filter_is_none_not_an_empty_mapping() -> None:
    # "the venue did not send a NOTIONAL filter" and "the venue sent an empty
    # one" are different facts, and a caller deciding whether an order is
    # placeable needs to tell them apart.
    parsed = parse_exchange_info(document(eth_filters()))
    eth = parsed.for_symbol("ETHUSDT")

    assert eth is not None
    assert eth.filter(FilterType.NOTIONAL) is None
    assert eth.min_notional is None
    assert eth.tick_size == "0.01"


# -- The version log --------------------------------------------------------


def make_store(tmp_path) -> ExchangeInfoVersionStore:
    return ExchangeInfoVersionStore(StagingArea(tmp_path / "staging"))


def test_the_first_fetch_lands_as_version_one(tmp_path) -> None:
    store = make_store(tmp_path)

    version = store.record(document(btc_filters(), eth_filters()), fetched_at=DAY_ONE)

    assert isinstance(version, ExchangeInfoVersion)
    assert version.version == 1
    assert version.symbol_count == 2
    assert version.symbols == ("BTCUSDT", "ETHUSDT")
    assert version.path == tmp_path / "staging" / "exchangeInfo" / "1.bin"
    assert version.path.read_bytes()  # the version is durably on disk


def test_each_fetch_is_a_new_version_rather_than_an_overwrite(tmp_path) -> None:
    # The feature statement, read as the log's behaviour.
    store = make_store(tmp_path)

    first = store.record(document(btc_filters()), fetched_at=DAY_ONE)
    second = store.record(document(btc_filters(step_size="0.002")), fetched_at=DAY_TWO)

    assert (first.version, second.version) == (1, 2)
    assert first.path != second.path
    # Version 1's bytes are untouched by version 2's arrival: the log is a
    # history, not a slot.
    assert store.version(1) is not None
    assert store.version(1).filters_for("BTCUSDT").step_size == "0.001"
    assert store.version(2).filters_for("BTCUSDT").step_size == "0.002"


def test_an_earlier_versions_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)
    committed = (tmp_path / "staging" / "exchangeInfo" / "1.bin").read_bytes()

    store.record(document(btc_filters(step_size="9.0")), fetched_at=DAY_TWO)
    store.record(document(eth_filters()), fetched_at=DAY_TWO)

    assert (tmp_path / "staging" / "exchangeInfo" / "1.bin").read_bytes() == committed


def test_a_repeated_fetch_still_lands_as_a_new_version(tmp_path) -> None:
    # "Each fetch" is persisted — a version that repeats the prior content is
    # not suppressed, because "the refresh ran and nothing changed" and "the
    # refresh never ran" are different facts an operator must be able to tell
    # apart when orders start being rejected for a stale tick size.
    store = make_store(tmp_path)

    first = store.record(document(btc_filters()), fetched_at=DAY_ONE)
    second = store.record(document(btc_filters()), fetched_at=DAY_TWO)

    assert second.version == 2
    assert second.carries_same_filters_as(first)  # same filters...
    assert second.source_sha256 == first.source_sha256
    assert second.payload_sha256 != first.payload_sha256  # ...different fetch


def test_versions_are_read_back_oldest_first(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)
    store.record(document(eth_filters()), fetched_at=DAY_TWO)

    versions = store.versions()

    assert [v.version for v in versions] == [1, 2]
    assert versions[0].fetched_at == DAY_ONE
    assert versions[1].fetched_at == DAY_TWO


def test_current_and_previous_name_the_comparison_point(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.current() is None  # nothing fetched yet — no tick size to offer
    assert store.previous() is None

    store.record(document(btc_filters()), fetched_at=DAY_ONE)
    assert store.previous() is None  # a first version has nothing behind it

    store.record(document(btc_filters(step_size="0.002")), fetched_at=DAY_TWO)

    current, previous = store.current(), store.previous()
    assert current is not None and previous is not None
    assert (previous.version, current.version) == (1, 2)
    assert not current.carries_same_filters_as(previous)
    assert store.latest_filters("BTCUSDT").step_size == "0.002"


def test_the_log_survives_a_restart(tmp_path) -> None:
    # A fresh store over the same staging tree resumes appending past what a
    # prior run persisted — the seed-from-what-is-durable moment the resume
    # watermark gives a restarted worker, applied to the version log.
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    restarted = ExchangeInfoVersionStore(StagingArea(tmp_path / "staging"))
    second = restarted.record(document(eth_filters()), fetched_at=DAY_TWO)

    assert second.version == 2
    assert [v.version for v in restarted.versions()] == [1, 2]


def test_a_failed_parse_consumes_no_version(tmp_path) -> None:
    # Parse-then-write, so a rate-limit body never appears in the log as a
    # refresh that happened.
    store = make_store(tmp_path)

    with pytest.raises(ExchangeInfoParseError):
        store.record({"symbols": []}, fetched_at=DAY_ONE)

    assert store.versions() == ()
    assert store.current() is None
    # And the next honest fetch still claims version 1: no hole was left.
    assert store.record(document(btc_filters()), fetched_at=DAY_TWO).version == 1


def test_a_naive_fetched_at_is_refused(tmp_path) -> None:
    # The daily cadence is a UTC calendar-day rule, so a naive timestamp is
    # ambiguous at exactly the boundary the rule turns on.
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.record(document(btc_filters()), fetched_at=datetime(2026, 3, 1))


def test_fetched_at_is_normalised_to_utc(tmp_path) -> None:
    store = make_store(tmp_path)
    offset = timezone(timedelta(hours=9))

    version = store.record(
        document(btc_filters()), fetched_at=datetime(2026, 3, 1, 15, 0, tzinfo=offset)
    )

    assert version.fetched_at == datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
    assert version.fetched_at.tzinfo is UTC


# -- Damage is refused, not parsed around -----------------------------------


def test_damaged_version_bytes_are_refused(tmp_path) -> None:
    # A log the order path trusts for venue constants must not hand back a
    # plausible-looking tick size assembled from bytes that changed.
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    path = tmp_path / "staging" / "exchangeInfo" / "1.bin"
    payload = path.read_bytes().replace(b'"0.001"', b'"9.999"')
    assert payload != path.read_bytes()  # the tamper actually changed bytes
    path.write_bytes(payload)

    restarted = ExchangeInfoVersionStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(ExchangeInfoCorruptError, match="not the\\s+bytes that were committed"):
        restarted.current()


def test_unreadable_version_bytes_are_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    (tmp_path / "staging" / "exchangeInfo" / "1.bin").write_bytes(b"not json")

    restarted = ExchangeInfoVersionStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(ExchangeInfoCorruptError, match="not readable as a"):
        restarted.versions()


def test_a_version_file_that_disagrees_with_its_name_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    path = tmp_path / "staging" / "exchangeInfo" / "1.bin"
    path.write_bytes(path.read_bytes().replace(b'"version":1', b'"version":7'))

    restarted = ExchangeInfoVersionStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(ExchangeInfoCorruptError, match="does not describe itself"):
        restarted.versions()


def test_reading_a_version_that_was_never_recorded_is_none(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    # An honest absence, distinct from the corrupt-bytes case above: a number
    # that simply never happened is not damage.
    assert store.version(9) is None
    with pytest.raises(ValueError, match="must be positive"):
        store.version(0)


# -- The daily cadence ------------------------------------------------------


def clock_at(moment: datetime):
    return lambda: moment


def test_a_fetch_is_due_immediately_on_an_empty_store(tmp_path) -> None:
    # §13.2's "at startup": startup is simply the first cycle of a process
    # whose store is empty.
    worker = DailyExchangeInfoWorker(
        make_store(tmp_path), lambda: document(btc_filters()), clock=clock_at(DAY_ONE)
    )

    assert worker.last_fetched_at() is None
    assert worker.is_due() is True


def test_a_second_cycle_on_the_same_utc_day_is_not_due(tmp_path) -> None:
    worker = DailyExchangeInfoWorker(
        make_store(tmp_path), lambda: document(btc_filters()), clock=clock_at(DAY_ONE)
    )
    worker.run_cycle()

    later = DailyExchangeInfoWorker(
        worker.store, lambda: document(btc_filters()), clock=clock_at(SAME_DAY_LATER)
    )
    assert later.is_due() is False


def test_the_next_utc_day_is_due_again(tmp_path) -> None:
    store = make_store(tmp_path)
    DailyExchangeInfoWorker(
        store, lambda: document(btc_filters()), clock=clock_at(DAY_ONE)
    ).run_cycle()

    next_day = DailyExchangeInfoWorker(
        store, lambda: document(btc_filters()), clock=clock_at(DAY_TWO)
    )
    assert next_day.is_due() is True


def test_the_cadence_is_read_from_the_durable_log_not_memory(tmp_path) -> None:
    # A restart mid-day must not re-fetch the day's filters: the deployment
    # table calls ingest restart-safe, and a cadence held in process memory
    # would re-fetch on every restart and skip a day whenever the process was
    # down at the wrong moment.
    DailyExchangeInfoWorker(
        make_store(tmp_path), lambda: document(btc_filters()), clock=clock_at(DAY_ONE)
    ).run_cycle()

    restarted = DailyExchangeInfoWorker(
        ExchangeInfoVersionStore(StagingArea(tmp_path / "staging")),
        lambda: document(btc_filters()),
        clock=clock_at(SAME_DAY_LATER),
    )

    assert restarted.last_fetched_at() == DAY_ONE
    assert restarted.is_due() is False


def test_a_cycle_persists_a_version_and_reports_its_sequence(tmp_path) -> None:
    calls = []

    def fetch() -> dict:
        calls.append(1)
        return document(btc_filters(), eth_filters())

    worker = DailyExchangeInfoWorker(make_store(tmp_path), fetch, clock=clock_at(DAY_ONE))

    result = worker.run_cycle()

    assert result.sequence == 1  # the version, i.e. the log's watermark
    assert result.rows_written == 2  # the symbols the version carries
    assert len(calls) == 1
    assert worker.stream_class is StreamClass.EXCHANGE_INFO
    assert worker.store.current().version == 1


def test_a_not_due_cycle_fetches_nothing_and_claims_no_progress(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    def fetch() -> dict:
        raise AssertionError("a not-due cycle must not reach the exchange")

    worker = DailyExchangeInfoWorker(
        store, fetch, clock=clock_at(SAME_DAY_LATER)
    )

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.versions()) == 1  # no second version was written


def test_a_failed_fetch_leaves_the_log_untouched_and_raises(tmp_path) -> None:
    # The failure the supervisor converts into this stream's StreamFailure:
    # the worker raises, the boundary records it, no version is consumed.
    store = make_store(tmp_path)
    worker = DailyExchangeInfoWorker(
        store, lambda: b"<html>429</html>", clock=clock_at(DAY_ONE)
    )

    with pytest.raises(ExchangeInfoParseError):
        worker.run_cycle()

    assert store.versions() == ()
    assert worker.is_due() is True  # still owed a refresh, honestly


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(TypeError, match="persists into an ExchangeInfoVersionStore"):
        DailyExchangeInfoWorker("not a store", lambda: document(btc_filters()))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        DailyExchangeInfoWorker(store, "not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        DailyExchangeInfoWorker(store, lambda: document(btc_filters()), clock=7)  # type: ignore[arg-type]


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        ExchangeInfoVersionStore("not staging")  # type: ignore[arg-type]


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_exchangeinfo_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert EXCHANGE_INFO_STREAM in default_worker_registry()
    assert StreamClass.EXCHANGE_INFO in default_worker_registry()


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires a client does not end up with two
    # exchangeInfo workers competing for the same version numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    register_exchange_info_worker(
        lambda: document(btc_filters()),
        store=store,
        clock=clock_at(DAY_ONE),
        registry=registry,
    )
    # Registering the same class again replaces the factory in place.
    register_exchange_info_worker(
        lambda: document(eth_filters()),
        store=store,
        clock=clock_at(DAY_ONE),
        registry=registry,
    )

    assert len(registry) == 1
    worker = registry.build_workers()[0]
    assert worker.run_cycle().sequence == 1
    assert store.current().symbols == ("ETHUSDT",)


def test_registering_an_explicit_fetch_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring an
    # explicit fetch must not replace the auto-discovered worker for every
    # later composition in the process — which is exactly how a test would be
    # handed a worker bound to a store that has since been deleted.
    auto_discovered = default_worker_registry().build_workers()[0]
    store = make_store(tmp_path)

    factory = register_exchange_info_worker(
        lambda: document(btc_filters()), store=store, clock=clock_at(DAY_ONE)
    )

    # The caller gets its wired worker...
    assert factory().store.staging.root == store.staging.root
    # ...while the default registry still composes the environment-resolved
    # one, untouched by the registration above.
    still_default = default_worker_registry().build_workers()[0]
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def test_registering_a_non_callable_fetch_is_refused() -> None:
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        register_exchange_info_worker("nope")  # type: ignore[arg-type]


def test_the_composed_worker_reports_an_unconfigured_fetch_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: an unconfigured stream is that stream's own
    # failure in the report and every other stream keeps ingesting — not a
    # component that fails to compose.
    from nullius_ingest import FunctionWorker, IngestSupervisor

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    worker = DailyExchangeInfoWorker(
        ExchangeInfoVersionStore(StagingArea(tmp_path / "lake" / "staging")),
        lambda: (_ for _ in ()).throw(ExchangeInfoError("no fetch wired")),
    )
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.EXCHANGE_INFO)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "ExchangeInfoError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


def test_versions_land_where_the_seal_looks(tmp_path) -> None:
    # §4.2's snapshot layout carries an exchangeinfo/ directory: the stream's
    # staging log is what a seal copies into it, so the versioned history
    # becomes part of the sealed record rather than a sidecar a replay would
    # have to reconstruct from live requests.
    store = make_store(tmp_path)
    store.record(document(btc_filters()), fetched_at=DAY_ONE)

    assert store.root == tmp_path / "staging" / "exchangeInfo"
    assert store.root.is_dir()
    assert store.staging.root == tmp_path / "staging"
