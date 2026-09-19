"""Gap detection on reconnect — a gap_detected event naming the stream.

These tests are the feature statement for app_spec.xml feature 25 —
*"System detects a websocket sequence-number gap on reconnect, which
emits a gap_detected event naming the affected stream"* — read as
behaviour of the gap module:

* a stream's sequences are watched per stream; the first message after a
  reconnect that jumps the expected sequence emits one ``gap_detected``
  event naming that stream and the inclusive range it skipped;
* what is not a gap stays silent: a first-ever observation (no
  baseline), a contiguous tail after reconnect (nothing was lost), and a
  duplicate or replayed message (no forward hole);
* the event is emitted, not raised: the sink wired at construction
  receives it, the caller is returned it, and the log that records it is
  the seam feature 26's backfill reads — while under the supervisor the
  detecting cycle is a *success* (§15's recovery for a gap is REST
  backfill, not a halt), and every other stream keeps ingesting.
"""

from __future__ import annotations

import threading

import pytest

from nullius_ingest import (
    GAP_DETECTED_EVENT,
    CycleResult,
    FunctionWorker,
    GapDetected,
    GapDetector,
    GapEventLog,
    StreamClass,
    WorkerRegistry,
)
from nullius_ingest.registry import build_supervisor


def feed(
    detector: GapDetector, stream: StreamClass | str, *sequences: int
) -> list[GapDetected]:
    """Observe ``sequences`` in order; return the events they emitted."""
    return [
        event
        for event in (detector.observe(stream, s) for s in sequences)
        if event is not None
    ]


# -- The event ---------------------------------------------------------------


def test_the_event_kind_is_gap_detected() -> None:
    # The spelling the feature statement fixes: logs, alerts and the
    # feature 26 backfill match on this string, so the constant and the
    # default agree with it.
    assert GAP_DETECTED_EVENT == "gap_detected"
    event = GapDetected(
        stream=StreamClass.AGG_TRADES, first_missing=4, last_missing=6
    )
    assert event.event == "gap_detected"


def test_an_event_names_the_affected_stream() -> None:
    # The event coerces its stream, so a worker wiring from configuration
    # can pass the string spelling — and only that stream is named.
    event = GapDetected(
        stream="aggTrades",  # type: ignore[arg-type]
        first_missing=8,
        last_missing=9,
    )
    assert event.stream is StreamClass.AGG_TRADES
    assert event.render().startswith("gap_detected: aggTrades")


def test_missing_count_is_the_inclusive_range_size() -> None:
    event = GapDetected(stream=StreamClass.KLINES, first_missing=4, last_missing=6)
    assert event.missing_count == 3
    single = GapDetected(stream=StreamClass.KLINES, first_missing=4, last_missing=4)
    assert single.missing_count == 1


def test_an_event_renders_where_the_gap_opened() -> None:
    # One line naming the stream, the hole, its size, and where it
    # opened — the facts §15 pairs with a recovery action.
    on_reconnect = GapDetected(
        stream=StreamClass.AGG_TRADES, first_missing=4, last_missing=6,
        on_reconnect=True,
    )
    assert "aggTrades" in on_reconnect.render()
    assert "4..6" in on_reconnect.render()
    assert "3 messages" in on_reconnect.render()
    assert "on reconnect" in on_reconnect.render()

    mid_feed = GapDetected(stream=StreamClass.BOOK_DIFFS, first_missing=11, last_missing=11)
    assert "within an open connection" in mid_feed.render()


def test_an_inverted_missing_range_is_refused_at_construction() -> None:
    # Our own record, our own wiring bug: an inverted range is a lie a
    # backfiller cannot even name, refused before anything logs it.
    with pytest.raises(ValueError, match="cannot be inverted"):
        GapDetected(
            stream=StreamClass.KLINES, first_missing=9, last_missing=4
        )


# -- Detection on reconnect ----------------------------------------------------


def test_a_streams_first_observation_is_not_a_gap() -> None:
    # No baseline, no gap: whatever came before the worker started is
    # backfill territory, not a detected hole.
    detector = GapDetector()
    assert feed(detector, StreamClass.AGG_TRADES, 500) == []


def test_a_reconnect_before_the_first_observation_still_emits_nothing() -> None:
    detector = GapDetector()
    detector.reconnect(StreamClass.AGG_TRADES)
    assert feed(detector, StreamClass.AGG_TRADES, 500) == []


def test_a_sequence_jump_on_reconnect_emits_gap_detected_naming_the_stream() -> None:
    # The feature statement, exactly: a live tail, a reconnect, and a
    # first message past the expected sequence — one event, naming the
    # affected stream and what it skipped.
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 1, 2, 3)

    detector.reconnect(StreamClass.AGG_TRADES)
    events = feed(detector, StreamClass.AGG_TRADES, 7)

    assert len(events) == 1
    event = events[0]
    assert event.event == GAP_DETECTED_EVENT
    assert event.stream is StreamClass.AGG_TRADES
    assert (event.first_missing, event.last_missing) == (4, 6)
    assert event.on_reconnect is True


def test_a_contiguous_tail_after_reconnect_emits_nothing() -> None:
    # The reconnection lost nothing: the first post-reconnect message is
    # exactly the owed sequence, and the boundary is consumed silently.
    detector = GapDetector()
    feed(detector, StreamClass.KLINES, 1, 2, 3)

    detector.reconnect(StreamClass.KLINES)
    assert feed(detector, StreamClass.KLINES, 4, 5) == []


def test_a_detected_gap_advances_the_watermark_past_the_hole() -> None:
    # The messages after the hole are real data: the tail continues from
    # the observed sequence without re-detecting the same hole, and the
    # hole lives on in the event, not in a stalled tail.
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 3)
    detector.reconnect(StreamClass.AGG_TRADES)

    assert len(feed(detector, StreamClass.AGG_TRADES, 7)) == 1
    assert feed(detector, StreamClass.AGG_TRADES, 8, 9) == []
    assert detector.last_sequence(StreamClass.AGG_TRADES) == 9


def test_a_jump_within_an_open_connection_is_detected_too() -> None:
    # A hole is a hole wherever it opened — the feed skipping mid-message
    # lost exactly what a reconnect skip lost, and the backfill does not
    # care where.  The flag records which kind it was.
    detector = GapDetector()
    events = feed(detector, StreamClass.BOOK_DIFFS, 10, 11, 15)

    assert len(events) == 1
    assert events[0].stream is StreamClass.BOOK_DIFFS
    assert (events[0].first_missing, events[0].last_missing) == (12, 14)
    assert events[0].on_reconnect is False


def test_a_duplicate_or_replayed_message_is_not_a_gap() -> None:
    # A sequence at or below the watermark carries no information about
    # the forward tail, and the watermark never regresses on one.
    detector = GapDetector()
    feed(detector, StreamClass.FUNDING, 5, 6)

    assert feed(detector, StreamClass.FUNDING, 6, 5, 1) == []
    assert detector.last_sequence(StreamClass.FUNDING) == 6


def test_a_stale_message_does_not_consume_the_reconnect_boundary() -> None:
    # Only a sequence that advances the feed decides continuity: a replay
    # arriving right after the reconnect leaves the boundary armed for
    # the message that actually continues the stream.
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 3)
    detector.reconnect(StreamClass.AGG_TRADES)

    assert feed(detector, StreamClass.AGG_TRADES, 3) == []
    events = feed(detector, StreamClass.AGG_TRADES, 8)

    assert len(events) == 1
    assert events[0].on_reconnect is True


def test_two_reconnects_without_a_message_collapse_into_one_boundary() -> None:
    # However often the socket bounces before a message arrives, the
    # boundary is decided once — by the first sequence that advances.
    detector = GapDetector()
    feed(detector, StreamClass.KLINES, 2)

    detector.reconnect(StreamClass.KLINES)
    detector.reconnect(StreamClass.KLINES)
    events = feed(detector, StreamClass.KLINES, 5)

    assert len(events) == 1
    assert events[0].on_reconnect is True


# -- Per-stream isolation ------------------------------------------------------


def test_each_stream_tracks_its_own_sequence() -> None:
    # One detector, many streams, no cross-talk: aggTrades gaps while
    # klines' contiguous tail emits nothing — a hole in one feed is never
    # reported against another stream's name.
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 1)
    feed(detector, StreamClass.KLINES, 1, 2)

    events = feed(detector, StreamClass.AGG_TRADES, 4)

    assert len(events) == 1
    assert events[0].stream is StreamClass.AGG_TRADES
    assert feed(detector, StreamClass.KLINES, 3) == []


def test_a_reconnect_on_one_stream_marks_only_that_stream() -> None:
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 2)
    feed(detector, StreamClass.KLINES, 2)

    detector.reconnect(StreamClass.AGG_TRADES)
    klines_events = feed(detector, StreamClass.KLINES, 9)
    agg_events = feed(detector, StreamClass.AGG_TRADES, 9)

    assert len(klines_events) == 1
    assert klines_events[0].on_reconnect is False
    assert len(agg_events) == 1
    assert agg_events[0].on_reconnect is True


# -- Emission ------------------------------------------------------------------


def test_the_event_is_returned_to_the_immediate_caller() -> None:
    detector = GapDetector()
    feed(detector, StreamClass.AGG_TRADES, 1)

    event = detector.observe(StreamClass.AGG_TRADES, 3)

    assert event is not None
    assert (event.first_missing, event.last_missing) == (2, 2)


def test_a_wired_sink_receives_every_event() -> None:
    # Emission, not just a return value: the sink wired at construction
    # is handed each event as it is detected, in detection order.
    sink: list[GapDetected] = []
    detector = GapDetector(on_event=sink.append)

    feed(detector, StreamClass.BOOK_DIFFS, 1, 5, 6, 20)

    assert [e.first_missing for e in sink] == [2, 7]
    assert sink[0].stream is StreamClass.BOOK_DIFFS


def test_the_log_is_the_standard_sink() -> None:
    # The composition feature 26 builds on: every event the detector
    # emits lands in the log in emission order, nameable by stream.
    log = GapEventLog()
    detector = GapDetector(on_event=log.record)

    feed(detector, StreamClass.AGG_TRADES, 1, 2)
    detector.reconnect(StreamClass.AGG_TRADES)
    feed(detector, StreamClass.AGG_TRADES, 6)
    feed(detector, StreamClass.KLINES, 1, 2)

    assert len(log) == 1
    recorded = log.events(StreamClass.AGG_TRADES)
    assert len(recorded) == 1
    assert recorded[0].on_reconnect is True
    assert (recorded[0].first_missing, recorded[0].last_missing) == (3, 5)
    assert log.events(StreamClass.KLINES) == ()


def test_a_non_callable_sink_is_refused_at_construction() -> None:
    with pytest.raises(TypeError, match="on_event must be callable"):
        GapDetector(on_event="log.record")  # type: ignore[arg-type]


def test_a_non_integer_sequence_is_refused() -> None:
    # Floats and numeric strings that would compare equal to a sequence
    # are none: continuity is integer arithmetic or it is nothing.
    detector = GapDetector()
    with pytest.raises(TypeError, match="integer sequence number"):
        detector.observe(StreamClass.KLINES, 7.5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integer sequence number"):
        detector.observe(StreamClass.KLINES, "8")  # type: ignore[arg-type]


# -- Watermark introspection ----------------------------------------------------


def test_an_unobserved_stream_has_no_watermark() -> None:
    detector = GapDetector()
    assert detector.last_sequence(StreamClass.FUNDING) is None
    assert detector.expected_next(StreamClass.FUNDING) is None


def test_expected_next_is_one_past_the_last_sequence() -> None:
    # The debt continuity owes: last + 1, advanced past a detected hole
    # — the value whose absence the next observation names.
    detector = GapDetector()
    feed(detector, StreamClass.FUNDING, 4)
    assert detector.expected_next(StreamClass.FUNDING) == 5

    feed(detector, StreamClass.FUNDING, 12)
    assert detector.last_sequence(StreamClass.FUNDING) == 12
    assert detector.expected_next(StreamClass.FUNDING) == 13


# -- The event log ---------------------------------------------------------------


def test_the_log_records_and_replays_events_in_order() -> None:
    log = GapEventLog()
    first = GapDetected(
        stream=StreamClass.AGG_TRADES, first_missing=2, last_missing=2
    )
    second = GapDetected(
        stream=StreamClass.AGG_TRADES, first_missing=8, last_missing=9,
        on_reconnect=True,
    )

    assert log.record(first) is first
    log.record(second)

    assert list(log) == [first, second]
    assert log.events() == (first, second)


def test_events_filter_by_stream_name_only_that_stream() -> None:
    log = GapEventLog()
    log.record(
        GapDetected(
            stream=StreamClass.AGG_TRADES, first_missing=3, last_missing=4
        )
    )
    log.record(
        GapDetected(stream=StreamClass.KLINES, first_missing=7, last_missing=7)
    )

    agg = log.events(StreamClass.AGG_TRADES)

    assert len(agg) == 1
    assert agg[0].stream is StreamClass.AGG_TRADES
    assert len(log.events()) == 2


def test_the_log_refuses_a_non_event() -> None:
    # A wiring bug fails loudly rather than leaving a row a backfiller
    # would later trip over.
    log = GapEventLog()
    with pytest.raises(TypeError, match="GapDetected events"):
        log.record("gap_detected")  # type: ignore[arg-type]
    assert len(log) == 0


def test_the_log_accepts_concurrent_records_without_loss() -> None:
    # The supervisor runs one thread per worker, so a log wired as
    # several streams' sink receives events from several threads: every
    # record lands, none tears.
    log = GapEventLog()
    streams = [
        StreamClass.AGG_TRADES,
        StreamClass.KLINES,
        StreamClass.BOOK_DIFFS,
        StreamClass.FUNDING,
    ]
    per_stream = 250

    def record_range(stream: StreamClass) -> None:
        for n in range(per_stream):
            log.record(
                GapDetected(
                    stream=stream, first_missing=n + 1, last_missing=n + 1
                )
            )

    threads = [
        threading.Thread(target=record_range, args=(stream,))
        for stream in streams
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(log) == len(streams) * per_stream
    for stream in streams:
        recorded = log.events(stream)
        assert len(recorded) == per_stream
        assert [e.first_missing for e in recorded] == list(
            range(1, per_stream + 1)
        )


# -- Under the supervisor --------------------------------------------------------


def test_a_gap_detected_in_a_worker_cycle_is_data_not_a_failure() -> None:
    # End to end through the feature 16 boundary: a stream worker
    # observes a gapped reconnect mid-cycle and the cycle *succeeds* —
    # §15's recovery for a gap is REST backfill, not a halt — while the
    # event is emitted into the log naming that stream, and the healthy
    # stream keeps ingesting alongside it.
    log = GapEventLog()
    detector = GapDetector(on_event=log.record)

    def gapped_aggregates_cycle() -> CycleResult:
        feed(detector, StreamClass.AGG_TRADES, 40, 41)
        detector.reconnect(StreamClass.AGG_TRADES)
        feed(detector, StreamClass.AGG_TRADES, 45)
        return CycleResult(rows_written=3)

    registry = WorkerRegistry()
    registry.register(
        StreamClass.AGG_TRADES,
        lambda: FunctionWorker(StreamClass.AGG_TRADES, gapped_aggregates_cycle),
    )
    registry.register(
        StreamClass.KLINES,
        lambda: FunctionWorker(StreamClass.KLINES, lambda: 12),
    )

    report = build_supervisor(registry=registry).run_cycle()

    assert report.ok
    aggregates = report.outcome_for(StreamClass.AGG_TRADES)
    klines = report.outcome_for(StreamClass.KLINES)
    assert aggregates is not None and klines is not None
    assert aggregates.rows_written == 3
    assert klines.rows_written == 12
    assert len(log) == 1
    assert log.events()[0].stream is StreamClass.AGG_TRADES
    assert log.events()[0].on_reconnect is True
    assert (log.events()[0].first_missing, log.events()[0].last_missing) == (42, 44)
