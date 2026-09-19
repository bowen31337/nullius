"""Funding rate and margin borrow rate ingest, polled every 60 seconds and retained permanently.

These tests are the feature statement for app_spec.xml feature 23 —
*"System ingests funding rate and margin borrow rate every 60 seconds,
persisting rows retained permanently"* — read as behaviour of the rate store,
the 60-second worker and the parser they stand on:

* a poll lands as the next record in an append-only log, and a prior record's
  bytes are never rewritten by a later one;
* each poll is persisted — the feature says *each* poll is persisted, and the
  log is the permanent history the cost and crowding paths reach back across;
* the 60-second cadence is decided from the durable log, so a restart inside
  the window does not re-poll and a process that was down across a boundary
  polls on its next cycle;
* a failed poll — a rate-limit body, a truncated document — is refused
  *before* anything is written, so the log never records a poll that did not
  happen;
* the two rates (funding rate, borrow rate) are read back off the persisted
  record in the venue's own spelling, and damaged bytes are refused rather
  than parsed into a plausible-looking rate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nullius_ingest import (
    FUNDING_STREAM,
    FundingCorruptError,
    FundingDocument,
    FundingError,
    FundingParseError,
    FundingRateStore,
    FundingRateWorker,
    FundingReading,
    FundingRecord,
    StagingArea,
    StreamClass,
    StampedReading,
    parse_funding,
)
from nullius_ingest.funding import register_funding_worker
from nullius_ingest.registry import WorkerRegistry, default_worker_registry

UTC = timezone.utc

#: A poll instant; the cadence is decided from elapsed time, so the tests use
#: explicit instants rather than depending on when the suite runs.
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

#: Thirty seconds after T0 — inside the 60-second window, so not due.
T_PLUS_30 = datetime(2026, 3, 1, 12, 0, 30, tzinfo=UTC)

#: Exactly 60 seconds after T0 — the window boundary, so due again.
T_PLUS_60 = datetime(2026, 3, 1, 12, 1, 0, tzinfo=UTC)

#: Well past the window — due, unambiguously.
T_PLUS_120 = datetime(2026, 3, 1, 12, 2, 0, tzinfo=UTC)


def btc_reading(
    funding_rate: str = "0.0001", borrow_rate: str = "0.00003"
) -> dict:
    """One venue-shaped reading, the way a funding response spells it."""
    return {
        "symbol": "BTCUSDT",
        "funding_rate": funding_rate,
        "borrow_rate": borrow_rate,
        # A real premiumIndex response carries a mark price, index price and
        # next funding time alongside the two rates; they are ignored, so a
        # reading that carries them must still parse.
        "markPrice": "61234.50",
        "indexPrice": "61230.10",
        "nextFundingTime": 1772222400000,
    }


def eth_reading() -> dict:
    return {
        "symbol": "ETHUSDT",
        "funding_rate": "0.00005",
        "borrow_rate": "0.00001",
    }


def reading(symbol: str, funding_rate: str, borrow_rate: str) -> FundingReading:
    return FundingReading(symbol=symbol, funding_rate=funding_rate, borrow_rate=borrow_rate)


def payload(*readings: dict) -> dict:
    """A full funding response carrying the given readings, wrapped in ``symbols``."""
    return {"symbols": list(readings)}


def data_wrapped_payload(*readings: dict) -> dict:
    """The ``{"data": [...]}`` wrapper some endpoints use."""
    return {"data": list(readings)}


# -- Parsing the venue's document -------------------------------------------


def test_parses_the_rates_of_every_reading() -> None:
    parsed = parse_funding(payload(btc_reading(), eth_reading()))

    assert isinstance(parsed, FundingDocument)
    assert parsed.symbols == ("BTCUSDT", "ETHUSDT")
    assert len(parsed) == 2
    assert parsed.for_symbol("BTCUSDT") is not None
    assert parsed.for_symbol("SOLUSDT") is None


def test_rate_values_are_kept_verbatim_in_the_venues_spelling() -> None:
    # The record must not round anything: whether the venue said "0.0001" or
    # "0.00010" is a fact about the venue, and re-rendering it would make an
    # audit unable to tell a venue change from our own lossy parse.
    parsed = parse_funding(payload(btc_reading(borrow_rate="0.000030")))
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.funding_rate == "0.0001"
    assert btc.borrow_rate == "0.000030"


def test_a_reading_with_extra_fields_parses() -> None:
    # A premiumIndex response carries a mark price, index price and next
    # funding time alongside the two rates; they are ignored, not refused.
    parsed = parse_funding(payload(btc_reading()))
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.funding_rate == "0.0001"
    assert btc.borrow_rate == "0.00003"


def test_a_numeric_rate_is_spelled_as_a_string() -> None:
    # Venues are inconsistent about JSON types for the same field — a borrow
    # rate arrives as a bare number — so scalars are spelled, not rejected.
    parsed = parse_funding(
        {"symbols": [{"symbol": "BTCUSDT", "funding_rate": 0.0001, "borrow_rate": 3e-05}]}
    )
    btc = parsed.for_symbol("BTCUSDT")

    assert btc is not None
    assert btc.funding_rate == repr(0.0001)
    assert btc.borrow_rate == repr(3e-05)


def test_accepts_a_bare_list_of_readings() -> None:
    parsed = parse_funding([btc_reading(), eth_reading()])

    assert parsed.symbols == ("BTCUSDT", "ETHUSDT")


def test_accepts_the_wrapped_response_some_endpoints_use() -> None:
    parsed = parse_funding(data_wrapped_payload(btc_reading(), eth_reading()))

    assert parsed.symbols == ("BTCUSDT", "ETHUSDT")


def test_accepts_a_single_symbol_response() -> None:
    # /fapi/v1/premiumIndex?symbol=BTCUSDT returns one object, not a list.
    parsed = parse_funding(btc_reading())

    assert parsed.symbols == ("BTCUSDT",)


def test_accepts_json_bytes() -> None:
    import json

    payload_bytes = json.dumps(payload(btc_reading())).encode()

    assert parse_funding(payload_bytes).symbols == ("BTCUSDT",)


def test_an_empty_response_is_refused() -> None:
    # An empty funding response is a rate-limit body, an error page or a
    # truncated read — never a poll.  Persisting it would make a failed poll
    # indistinguishable from a successful one.
    with pytest.raises(FundingParseError, match="at least one reading"):
        parse_funding({"symbols": []})


def test_a_reading_without_a_symbol_is_refused() -> None:
    with pytest.raises(FundingParseError, match="non-empty 'symbol'"):
        parse_funding([{"funding_rate": "0.0001", "borrow_rate": "0.00003"}])


def test_a_reading_without_a_funding_rate_is_refused() -> None:
    with pytest.raises(FundingParseError, match="no 'funding_rate'"):
        parse_funding([{"symbol": "BTCUSDT", "borrow_rate": "0.00003"}])


def test_a_reading_without_a_borrow_rate_is_refused() -> None:
    with pytest.raises(FundingParseError, match="no 'borrow_rate'"):
        parse_funding([{"symbol": "BTCUSDT", "funding_rate": "0.0001"}])


def test_a_symbol_listed_twice_is_refused() -> None:
    # A duplicate makes "the borrow rate for BTCUSDT" ambiguous, and picking one
    # arbitrarily is a silent choice between two different carry adjustments.
    with pytest.raises(FundingParseError, match="listed more than once"):
        parse_funding(payload(btc_reading(), btc_reading()))


def test_a_payload_that_is_not_json_is_refused() -> None:
    with pytest.raises(FundingParseError, match="not valid JSON"):
        parse_funding(b"<html>rate limited</html>")


def test_same_rates_hash_the_same_whatever_order_they_arrive_in() -> None:
    # The content hash answers "did the rates change?", so a venue that merely
    # reordered its listing has not changed a single rate.
    forward = parse_funding(payload(btc_reading(), eth_reading()))
    reversed_ = parse_funding(payload(eth_reading(), btc_reading()))

    assert forward.source_sha256 == reversed_.source_sha256
    # ...while the persisted document keeps the venue's own order, because that
    # is what a human diffing two polls reads.
    assert forward.symbols == ("BTCUSDT", "ETHUSDT")
    assert reversed_.symbols == ("ETHUSDT", "BTCUSDT")


def test_changing_one_rate_changes_the_hash() -> None:
    before = parse_funding(payload(btc_reading(borrow_rate="0.00003")))
    after = parse_funding(payload(btc_reading(borrow_rate="0.00004")))

    assert before.source_sha256 != after.source_sha256


# -- The record log ---------------------------------------------------------


def make_store(tmp_path) -> FundingRateStore:
    return FundingRateStore(StagingArea(tmp_path / "staging"))


def test_the_first_poll_lands_as_record_one(tmp_path) -> None:
    store = make_store(tmp_path)

    record = store.record(payload(btc_reading(), eth_reading()), fetched_at=T0)

    assert isinstance(record, FundingRecord)
    assert record.sequence == 1
    assert record.reading_count == 2
    assert record.symbols == ("BTCUSDT", "ETHUSDT")
    assert record.path == tmp_path / "staging" / "funding" / "1.bin"
    assert record.path.read_bytes()  # the record is durably on disk


def test_each_poll_is_a_new_record_rather_than_an_overwrite(tmp_path) -> None:
    # The feature statement, read as the log's behaviour: each poll's rows are
    # retained permanently, one record after another.
    store = make_store(tmp_path)

    first = store.record(payload(btc_reading(borrow_rate="0.00003")), fetched_at=T0)
    second = store.record(payload(btc_reading(borrow_rate="0.00004")), fetched_at=T_PLUS_60)

    assert (first.sequence, second.sequence) == (1, 2)
    assert first.path != second.path
    # Record 1's bytes are untouched by record 2's arrival: the log is a
    # permanent history, not a slot.
    assert store.record_at(1) is not None
    assert store.record_at(1).rates("BTCUSDT") == ("0.0001", "0.00003")
    assert store.record_at(2).rates("BTCUSDT") == ("0.0001", "0.00004")


def test_an_earlier_records_bytes_are_never_rewritten(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)
    committed = (tmp_path / "staging" / "funding" / "1.bin").read_bytes()

    store.record(payload(btc_reading(borrow_rate="9.0")), fetched_at=T_PLUS_60)
    store.record(payload(eth_reading()), fetched_at=T_PLUS_120)

    assert (tmp_path / "staging" / "funding" / "1.bin").read_bytes() == committed


def test_records_are_read_back_oldest_first(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)
    store.record(payload(eth_reading()), fetched_at=T_PLUS_60)

    records = store.records()

    assert [r.sequence for r in records] == [1, 2]
    assert records[0].fetched_at == T0
    assert records[1].fetched_at == T_PLUS_60


def test_current_and_previous_name_the_comparison_point(tmp_path) -> None:
    store = make_store(tmp_path)
    assert store.current() is None  # nothing polled yet — no borrow rate to offer
    assert store.previous() is None

    store.record(payload(btc_reading()), fetched_at=T0)
    assert store.previous() is None  # a first record has nothing behind it

    store.record(payload(btc_reading(borrow_rate="0.00004")), fetched_at=T_PLUS_60)

    current, previous = store.current(), store.previous()
    assert current is not None and previous is not None
    assert (previous.sequence, current.sequence) == (1, 2)
    assert current.rates("BTCUSDT") == ("0.0001", "0.00004")
    assert store.latest_rates("BTCUSDT") == ("0.0001", "0.00004")


def test_the_log_survives_a_restart(tmp_path) -> None:
    # A fresh store over the same staging tree resumes appending past what a
    # prior run persisted — the seed-from-what-is-durable moment the resume
    # watermark gives a restarted worker, applied to the funding log.
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    restarted = FundingRateStore(StagingArea(tmp_path / "staging"))
    second = restarted.record(payload(eth_reading()), fetched_at=T_PLUS_60)

    assert second.sequence == 2
    assert [r.sequence for r in restarted.records()] == [1, 2]


def test_a_failed_parse_consumes_no_sequence(tmp_path) -> None:
    # Parse-then-write, so a rate-limit body never appears in the log as a poll
    # that happened.
    store = make_store(tmp_path)

    with pytest.raises(FundingParseError):
        store.record({"symbolData": []}, fetched_at=T0)

    assert store.records() == ()
    assert store.current() is None
    # And the next honest poll still claims sequence 1: no hole was left.
    assert store.record(payload(btc_reading()), fetched_at=T_PLUS_60).sequence == 1


def test_a_naive_fetched_at_is_refused(tmp_path) -> None:
    # The 60-second cadence is decided from elapsed wall-clock time, so a naive
    # timestamp is unsubtractable from an aware one at exactly the boundary the
    # rule turns on.
    store = make_store(tmp_path)

    with pytest.raises(ValueError, match="timezone-aware"):
        store.record(payload(btc_reading()), fetched_at=datetime(2026, 3, 1, 12, 0))


def test_fetched_at_is_normalised_to_utc(tmp_path) -> None:
    store = make_store(tmp_path)
    offset = timezone(timedelta(hours=9))

    record = store.record(
        payload(btc_reading()), fetched_at=datetime(2026, 3, 1, 21, 0, tzinfo=offset)
    )

    assert record.fetched_at == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert record.fetched_at.tzinfo is UTC


# -- StampedReading: the time-series view -----------------------------------


def test_a_record_stamps_each_reading_with_its_poll_instant(tmp_path) -> None:
    store = make_store(tmp_path)
    record = store.record(payload(btc_reading()), fetched_at=T0)

    stamped = record.reading("BTCUSDT")

    assert isinstance(stamped, StampedReading)
    assert stamped.symbol == "BTCUSDT"
    assert stamped.funding_rate == "0.0001"
    assert stamped.borrow_rate == "0.00003"
    assert stamped.reading_time == T0


def test_latest_reading_stamps_with_the_most_recent_records_instant(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)
    store.record(payload(btc_reading(borrow_rate="0.00004")), fetched_at=T_PLUS_60)

    latest = store.latest_reading("BTCUSDT")

    assert latest is not None
    assert latest.borrow_rate == "0.00004"
    assert latest.reading_time == T_PLUS_60


def test_an_absent_symbol_is_none_not_a_default(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(eth_reading()), fetched_at=T0)

    assert store.latest_reading("BTCUSDT") is None
    assert store.latest_rates("BTCUSDT") is None


# -- Damage is refused, not parsed around -----------------------------------


def test_damaged_record_bytes_are_refused(tmp_path) -> None:
    # A log the cost path trusts for its borrow rate must not hand back a
    # plausible-looking rate assembled from bytes that changed.
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    path = tmp_path / "staging" / "funding" / "1.bin"
    payload_bytes = path.read_bytes().replace(b'"0.00003"', b'"9.999"')
    assert payload_bytes != path.read_bytes()  # the tamper actually changed bytes
    path.write_bytes(payload_bytes)

    restarted = FundingRateStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(FundingCorruptError, match="not the\\s+bytes that were committed"):
        restarted.current()


def test_unreadable_record_bytes_are_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    (tmp_path / "staging" / "funding" / "1.bin").write_bytes(b"not json")

    restarted = FundingRateStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(FundingCorruptError, match="not readable as a"):
        restarted.records()


def test_a_record_file_that_disagrees_with_its_name_is_refused(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    path = tmp_path / "staging" / "funding" / "1.bin"
    path.write_bytes(path.read_bytes().replace(b'"sequence":1', b'"sequence":7'))

    restarted = FundingRateStore(StagingArea(tmp_path / "staging"))
    with pytest.raises(FundingCorruptError, match="does not describe itself"):
        restarted.records()


def test_reading_a_record_that_was_never_recorded_is_none(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    # An honest absence, distinct from the corrupt-bytes case above: a number
    # that simply never happened is not damage.
    assert store.record_at(9) is None
    with pytest.raises(ValueError, match="must be positive"):
        store.record_at(0)


# -- The 60-second cadence --------------------------------------------------


def clock_at(moment: datetime):
    return lambda: moment


def test_a_poll_is_due_immediately_on_an_empty_store(tmp_path) -> None:
    # Startup is simply the first cycle of a process whose store is empty.
    worker = FundingRateWorker(
        make_store(tmp_path), lambda: payload(btc_reading()), clock=clock_at(T0)
    )

    assert worker.last_fetched_at() is None
    assert worker.is_due() is True


def test_a_second_cycle_inside_the_window_is_not_due(tmp_path) -> None:
    worker = FundingRateWorker(
        make_store(tmp_path), lambda: payload(btc_reading()), clock=clock_at(T0)
    )
    worker.run_cycle()

    # 30 seconds later — inside the 60-second window.
    later = FundingRateWorker(
        worker.store, lambda: payload(btc_reading()), clock=clock_at(T_PLUS_30)
    )
    assert later.is_due() is False


def test_the_window_boundary_is_due_again(tmp_path) -> None:
    store = make_store(tmp_path)
    FundingRateWorker(
        store, lambda: payload(btc_reading()), clock=clock_at(T0)
    ).run_cycle()

    # Exactly 60 seconds later — the boundary, so due.
    boundary = FundingRateWorker(
        store, lambda: payload(btc_reading()), clock=clock_at(T_PLUS_60)
    )
    assert boundary.is_due() is True


def test_the_cadence_is_read_from_the_durable_log_not_memory(tmp_path) -> None:
    # A restart inside the window must not re-poll: the deployment table calls
    # ingest restart-safe, and a cadence held in process memory would poll on
    # every restart and skip a cycle whenever the process was down at the wrong
    # moment.
    FundingRateWorker(
        make_store(tmp_path), lambda: payload(btc_reading()), clock=clock_at(T0)
    ).run_cycle()

    restarted = FundingRateWorker(
        FundingRateStore(StagingArea(tmp_path / "staging")),
        lambda: payload(btc_reading()),
        clock=clock_at(T_PLUS_30),
    )

    assert restarted.last_fetched_at() == T0
    assert restarted.is_due() is False


def test_a_cycle_persists_a_record_and_reports_its_sequence(tmp_path) -> None:
    calls = []

    def fetch() -> dict:
        calls.append(1)
        return payload(btc_reading(), eth_reading())

    worker = FundingRateWorker(make_store(tmp_path), fetch, clock=clock_at(T0))

    result = worker.run_cycle()

    assert result.sequence == 1  # the record, i.e. the log's watermark
    assert result.rows_written == 2  # the readings the record carries
    assert len(calls) == 1
    assert worker.stream_class is StreamClass.FUNDING
    assert worker.store.current().sequence == 1


def test_a_not_due_cycle_polls_nothing_and_claims_no_progress(tmp_path) -> None:
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    def fetch() -> dict:
        raise AssertionError("a not-due cycle must not reach the exchange")

    worker = FundingRateWorker(store, fetch, clock=clock_at(T_PLUS_30))

    result = worker.run_cycle()

    assert result.sequence == 0
    assert result.rows_written == 0
    assert len(store.records()) == 1  # no second record was written


def test_a_failed_poll_leaves_the_log_untouched_and_raises(tmp_path) -> None:
    # The failure the supervisor converts into this stream's StreamFailure: the
    # worker raises, the boundary records it, no sequence is consumed.
    store = make_store(tmp_path)
    worker = FundingRateWorker(store, lambda: b"<html>429</html>", clock=clock_at(T0))

    with pytest.raises(FundingParseError):
        worker.run_cycle()

    assert store.records() == ()
    assert worker.is_due() is True  # still owed a poll, honestly


def test_the_worker_rejects_mis_wired_collaborators(tmp_path) -> None:
    store = make_store(tmp_path)

    with pytest.raises(TypeError, match="persists into a FundingRateStore"):
        FundingRateWorker("not a store", lambda: payload(btc_reading()))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        FundingRateWorker(store, "not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="clock must be a callable"):
        FundingRateWorker(store, lambda: payload(btc_reading()), clock=7)  # type: ignore[arg-type]


def test_the_store_rejects_something_that_is_not_a_staging_area() -> None:
    with pytest.raises(TypeError, match="writes into a StagingArea"):
        FundingRateStore("not staging")  # type: ignore[arg-type]


# -- Registration and composition -------------------------------------------


def test_the_member_registers_a_worker_for_the_funding_stream() -> None:
    # Importing the package fires the registration — the plugin convention
    # every later ingest feature follows, with no shared file edited.
    assert FUNDING_STREAM in default_worker_registry()
    assert StreamClass.FUNDING in default_worker_registry()


def test_registering_an_explicit_fetch_revises_the_same_worker(tmp_path) -> None:
    # A re-registered class is a revision of the same worker, never a second
    # worker — so a deployment that wires a client does not end up with two
    # funding workers competing for the same sequence numbers.
    registry = WorkerRegistry()
    store = make_store(tmp_path)
    register_funding_worker(
        lambda: payload(btc_reading()),
        store=store,
        clock=clock_at(T0),
        registry=registry,
    )
    # Registering the same class again replaces the factory in place.
    register_funding_worker(
        lambda: payload(eth_reading()),
        store=store,
        clock=clock_at(T0),
        registry=registry,
    )

    assert len(registry) == 1
    worker = registry.build_workers()[0]
    assert worker.run_cycle().sequence == 1
    assert store.current().symbols == ("ETHUSDT",)


def test_registering_an_explicit_fetch_does_not_pollute_the_default(tmp_path) -> None:
    # A registration is a deployment act, not a global side effect: wiring an
    # explicit fetch must not replace the auto-discovered worker for every later
    # composition in the process — which is exactly how a test would be handed a
    # worker bound to a store that has since been deleted.
    auto_discovered = default_worker_registry().build_workers()[0]
    store = make_store(tmp_path)

    factory = register_funding_worker(
        lambda: payload(btc_reading()), store=store, clock=clock_at(T0)
    )

    # The caller gets its wired worker...
    assert factory().store.staging.root == store.staging.root
    # ...while the default registry still composes the environment-resolved one,
    # untouched by the registration above.
    still_default = default_worker_registry().build_workers()[0]
    assert still_default.store.staging.root == auto_discovered.store.staging.root
    assert still_default.store.staging.root != store.staging.root


def test_registering_a_non_callable_fetch_is_refused() -> None:
    with pytest.raises(TypeError, match="fetch must be a zero-argument"):
        register_funding_worker("nope")  # type: ignore[arg-type]


def test_the_composed_worker_reports_an_unconfigured_fetch_as_a_stream_failure(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Feature 16's contract: an unconfigured stream is that stream's own failure
    # in the report and every other stream keeps ingesting — not a component
    # that fails to compose.
    from nullius_ingest import FunctionWorker, IngestSupervisor

    monkeypatch.setenv("LAKE_ROOT", str(tmp_path / "lake"))
    worker = FundingRateWorker(
        FundingRateStore(StagingArea(tmp_path / "lake" / "staging")),
        lambda: (_ for _ in ()).throw(FundingError("no fetch wired")),
    )
    supervisor = IngestSupervisor(
        [worker, FunctionWorker(StreamClass.KLINES, lambda: 12)]
    )

    report = supervisor.run_cycle()

    failure = report.outcome_for(StreamClass.FUNDING)
    assert failure is not None and not failure.ok
    assert failure.failure.error_type == "FundingError"
    assert report.outcome_for(StreamClass.KLINES).rows_written == 12


def test_records_land_where_the_seal_looks(tmp_path) -> None:
    # §4.2's snapshot layout carries a borrow/ directory: the stream's staging
    # log is what a seal copies into it, so the permanent history becomes part
    # of the sealed record rather than a sidecar a replay would have to
    # reconstruct from live requests.
    store = make_store(tmp_path)
    store.record(payload(btc_reading()), fetched_at=T0)

    assert store.root == tmp_path / "staging" / "funding"
    assert store.root.is_dir()
    assert store.staging.root == tmp_path / "staging"


def test_records_are_retained_permanently_not_expired(tmp_path) -> None:
    # The load-bearing contrast with the L2 book-diff stream, which §4.1 keeps
    # for a rolling 90 days: the funding log is written once into the staging
    # area and copied by the seal, and nothing in the system expires it.  Many
    # polls, all still readable.
    store = make_store(tmp_path)
    for i in range(10):
        when = T0 + timedelta(seconds=60 * i)
        store.record(payload(btc_reading(borrow_rate=f"0.0000{i}")), fetched_at=when)

    assert len(store.records()) == 10
    assert store.record_at(1).rates("BTCUSDT")[1] == "0.00000"
    assert store.record_at(10).rates("BTCUSDT")[1] == "0.00009"
