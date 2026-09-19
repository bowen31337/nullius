"""Gap backfill over REST, and the seal gate that refuses to seal over a hole.

These tests are the feature statement for app_spec.xml feature 26 —
*"System backfills a detected websocket gap over REST before the next
snapshot seals, which rejects a seal attempt while any gap stays open"* —
read as behaviour of the backfill module:

* the backfiller reads the gaps feature 25's detector logged, and fills each
  open one — the hole's inclusive range fetched over an injected REST call and
  written into the stream's staging log;
* a gap is filled by exactly the sequences it named: a short or out-of-range
  fetch leaves the gap open and raises, so the seal is never gated on a fill
  that did not fill;
* a filled gap is not re-filled, so a retry over the same log does not
  re-fetch;
* the seal gate wraps the sealing service and refuses a seal while any gap
  stays open — naming the stream and the hole — and lets the seal through once
  the backfiller has filled them.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from nullius_ingest import (
    GAP_FILLED_EVENT,
    GapBackfiller,
    GapDetected,
    GapDetector,
    GapEventLog,
    GapFilled,
    GapNotFilledError,
    SealGate,
    StagingArea,
    StreamClass,
)

AT = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)


# -- Fixtures: a detector that logs, a backfiller over a fake REST + staging --


def detector_and_log() -> tuple[GapDetector, GapEventLog]:
    """A detector wired to a log — feature 25's composition, feature 26's input."""
    log = GapEventLog()
    return GapDetector(on_event=log.record), log


def make_backfiller(
    log: GapEventLog,
    staging: StagingArea,
    fetch,
    serialize=lambda stream, rows, first, last: b"|".join(rows),
) -> GapBackfiller:
    return GapBackfiller(
        log=log,
        staging=staging,
        fetch=fetch,
        serialize=serialize,
    )


def fake_fetch(rows_by_range: dict[tuple[int, int], list[bytes]]):
    """A REST stand-in returning the rows registered for a (first, last) range."""
    calls: list[tuple[StreamClass, int, int]] = []

    def _fetch(stream: StreamClass, first: int, last: int) -> list[bytes]:
        calls.append((stream, first, last))
        return list(rows_by_range.get((first, last), []))

    _fetch.calls = calls  # type: ignore[attr-defined]
    return _fetch


# -- The open-gap query --------------------------------------------------------


def test_open_gaps_reports_every_detected_gap_in_emission_order() -> None:
    # Before any fill, every gap the log holds is open, in the order the
    # detector emitted them — the query the seal gate reads.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({}))

        detector.observe(StreamClass.AGG_TRADES, 1)
        detector.reconnect(StreamClass.AGG_TRADES)
        detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4
        detector.observe(StreamClass.KLINES, 10)
        detector.reconnect(StreamClass.KLINES)
        detector.observe(StreamClass.KLINES, 13)  # gap 11..12

        open_gaps = backfiller.open_gaps()
        assert [g.stream for g in open_gaps] == [
            StreamClass.AGG_TRADES,
            StreamClass.KLINES,
        ]
        assert (open_gaps[0].first_missing, open_gaps[0].last_missing) == (2, 4)
        assert (open_gaps[1].first_missing, open_gaps[1].last_missing) == (11, 12)


def test_a_filled_gap_drops_out_of_open_gaps() -> None:
    # Filling a gap clears it from the open set: the query reflects the fill,
    # so the gate's next check sees one fewer hole.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4
    detector.observe(StreamClass.AGG_TRADES, 6)  # contiguous after 5
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 9)  # gap 7..8

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(
            log, staging, fake_fetch({(2, 4): [b"a", b"b", b"c"]})
        )
        assert len(backfiller.open_gaps()) == 2

        backfiller.fill_gap(GapDetected(StreamClass.AGG_TRADES, 2, 4))

        open_gaps = backfiller.open_gaps()
        assert len(open_gaps) == 1
        assert (open_gaps[0].first_missing, open_gaps[0].last_missing) == (7, 8)


def test_is_open_tracks_a_single_gap() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.FUNDING, 1)
    detector.reconnect(StreamClass.FUNDING)
    detector.observe(StreamClass.FUNDING, 4)  # gap 2..3
    gap = GapDetected(StreamClass.FUNDING, 2, 3)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(
            log, staging, fake_fetch({(2, 3): [b"x", b"y"]})
        )
        assert backfiller.is_open(gap) is True
        backfiller.fill_gap(gap)
        assert backfiller.is_open(gap) is False


# -- Filling a gap -------------------------------------------------------------


def test_fill_gap_fetches_the_range_and_appends_one_batch() -> None:
    # The fill asks the REST client for the gap's exact range, serialises the
    # rows, and appends them to the stream's staging log as the next batch —
    # the same append-only area a live-feed cycle writes into.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4
    gap = GapDetected(StreamClass.AGG_TRADES, 2, 4)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(2, 4): [b"a", b"b", b"c"]})
        backfiller = make_backfiller(log, staging, fetch)

        filled = backfiller.fill_gap(gap)

        assert isinstance(filled, GapFilled)
        assert filled.gap is gap
        assert filled.batch_sequence == 1
        assert filled.event == GAP_FILLED_EVENT
        assert filled.first == 2 and filled.last == 4
        staged = staging.staged(StreamClass.AGG_TRADES)
        assert len(staged) == 1
        assert staged[0].sequence == 1
        assert staged[0].rows == 3


def test_fill_gap_calls_fetch_and_serialize_with_the_range() -> None:
    # The injected REST fetch and row serialiser are called with exactly the
    # gap's range — the seam the stream workers fill.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.KLINES, 100)
    detector.reconnect(StreamClass.KLINES)
    detector.observe(StreamClass.KLINES, 103)  # gap 101..102
    gap = GapDetected(StreamClass.KLINES, 101, 102)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(101, 102): [b"r1", b"r2"]})

        def serialize(stream, rows, first, last):
            assert stream is StreamClass.KLINES
            assert (first, last) == (101, 102)
            assert rows == [b"r1", b"r2"]
            return b"payload"

        backfiller = make_backfiller(log, staging, fetch, serialize)
        backfiller.fill_gap(gap)

        assert fetch.calls == [(StreamClass.KLINES, 101, 102)]
        assert staging.staged(StreamClass.KLINES)[0].payload == b"payload"


def test_fill_stream_fills_gaps_in_ascending_range_order() -> None:
    # A stream with several holes fills them low-to-high, so its backfill
    # batches land in the order the holes opened.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.BOOK_DIFFS, 1)
    detector.observe(StreamClass.BOOK_DIFFS, 9)   # gap 2..8
    detector.observe(StreamClass.BOOK_DIFFS, 12)  # gap 10..11
    detector.observe(StreamClass.BOOK_DIFFS, 30)  # gap 13..29

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch(
            {
                (2, 8): [b"x"] * 7,
                (10, 11): [b"y", b"y"],
                (13, 29): [b"z"] * 17,
            }
        )
        backfiller = make_backfiller(log, staging, fetch)

        filled = backfiller.fill_stream(StreamClass.BOOK_DIFFS)

        assert [f.first for f in filled] == [2, 10, 13]
        assert [f.batch_sequence for f in filled] == [1, 2, 3]
        assert len(staging.staged(StreamClass.BOOK_DIFFS)) == 3


def test_fill_stream_only_touches_the_named_stream() -> None:
    # Two streams each with a gap; filling one leaves the other's gap open —
    # the per-stream isolation feature 16 enforces everywhere.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3
    detector.observe(StreamClass.KLINES, 1)
    detector.reconnect(StreamClass.KLINES)
    detector.observe(StreamClass.KLINES, 3)  # gap 2..2

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(2, 3): [b"a", b"b"], (2, 2): [b"k"]})
        backfiller = make_backfiller(log, staging, fetch)

        filled = backfiller.fill_stream(StreamClass.AGG_TRADES)

        assert len(filled) == 1
        assert filled[0].gap.stream is StreamClass.AGG_TRADES
        # klines' gap is still open.
        assert len(backfiller.open_gaps()) == 1
        assert backfiller.open_gaps()[0].stream is StreamClass.KLINES


# -- A fill must cover the gap exactly -----------------------------------------


def test_a_short_fetch_leaves_the_gap_open_and_raises() -> None:
    # Fewer rows than the hole, and the hole is still open: the fill refuses
    # rather than appending a partial fill the seal would trust.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4
    gap = GapDetected(StreamClass.AGG_TRADES, 2, 4)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(
            log, staging, fake_fetch({(2, 4): [b"a", b"b"]})  # only 2 of 3
        )

        with pytest.raises(GapNotFilledError) as exc:
            backfiller.fill_gap(gap)

        assert exc.value.gap is gap
        # Nothing was appended: the short fill never reached staging.
        assert staging.staged(StreamClass.AGG_TRADES) == ()
        # And the gap is still open.
        assert backfiller.is_open(gap) is True


def test_an_empty_fetch_is_not_a_fill() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.FUNDING, 1)
    detector.reconnect(StreamClass.FUNDING)
    detector.observe(StreamClass.FUNDING, 3)  # gap 2..2
    gap = GapDetected(StreamClass.FUNDING, 2, 2)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({(2, 2): []}))

        with pytest.raises(GapNotFilledError):
            backfiller.fill_gap(gap)
        assert staging.staged(StreamClass.FUNDING) == ()


def test_an_over_range_fetch_is_refused() -> None:
    # More rows than the hole is a different range than the event named:
    # silently accepting it would let a fetch rewrite the hole's meaning.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3
    gap = GapDetected(StreamClass.AGG_TRADES, 2, 3)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(
            log, staging, fake_fetch({(2, 3): [b"a", b"b", b"c"]})  # 3 for a 2-hole
        )

        with pytest.raises(GapNotFilledError):
            backfiller.fill_gap(gap)
        assert staging.staged(StreamClass.AGG_TRADES) == ()


def test_the_error_names_the_gap_and_what_the_fetch_covered() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.KLINES, 10)
    detector.reconnect(StreamClass.KLINES)
    detector.observe(StreamClass.KLINES, 20)  # gap 11..19
    gap = GapDetected(StreamClass.KLINES, 11, 19)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(
            log, staging, fake_fetch({(11, 19): [b"x"] * 5})  # covers 11..15
        )
        with pytest.raises(GapNotFilledError) as exc:
            backfiller.fill_gap(gap)
        assert exc.value.covered_first == 11
        assert exc.value.covered_last == 15
        assert "11..19" in str(exc.value)


# -- Idempotency ---------------------------------------------------------------


def test_a_filled_gap_is_not_refilled_on_retry() -> None:
    # Filling records the gap as filled; a second fill_gap for the same range
    # is refused (not re-fetched), so a retry over the same log does not write
    # a second batch.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3
    gap = GapDetected(StreamClass.AGG_TRADES, 2, 3)

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(2, 3): [b"a", b"b"]})
        backfiller = make_backfiller(log, staging, fetch)

        backfiller.fill_gap(gap)
        with pytest.raises(ValueError, match="already filled"):
            backfiller.fill_gap(gap)

        assert len(fetch.calls) == 1  # fetched once, not twice
        assert len(staging.staged(StreamClass.AGG_TRADES)) == 1


def test_fill_stream_is_idempotent_across_a_second_call() -> None:
    # A second fill_stream over the same log fills nothing new.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(2, 3): [b"a", b"b"]})
        backfiller = make_backfiller(log, staging, fetch)

        assert len(backfiller.fill_stream(StreamClass.AGG_TRADES)) == 1
        assert backfiller.fill_stream(StreamClass.AGG_TRADES) == ()
        assert len(staging.staged(StreamClass.AGG_TRADES)) == 1


# -- Construction guards -------------------------------------------------------


def test_a_non_callable_fetch_is_refused() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        with pytest.raises(TypeError, match="fetch must be a callable"):
            GapBackfiller(log=log, staging=staging, fetch="rest.get", serialize=lambda *a: b"")  # type: ignore[arg-type]


def test_a_non_callable_serialize_is_refused() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        with pytest.raises(TypeError, match="serialize must be a callable"):
            GapBackfiller(log=log, staging=staging, fetch=lambda *a: [], serialize=12)  # type: ignore[arg-type]


def test_a_wrong_log_or_staging_is_refused() -> None:
    import pathlib
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        with pytest.raises(TypeError, match="reads a GapEventLog"):
            GapBackfiller(log=[], staging=staging, fetch=lambda *a: [], serialize=lambda *a: b"")  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="writes to a StagingArea"):
            GapBackfiller(log=GapEventLog(), staging={}, fetch=lambda *a: [], serialize=lambda *a: b"")  # type: ignore[arg-type]


# -- The seal gate -------------------------------------------------------------


class _FakeService:
    """A sealing-service stand-in: records seals, honours snapshot_hash=."""

    def __init__(self) -> None:
        self.sealed: list[tuple[object, dict]] = []

    def seal(self, source=None, **kwargs):  # noqa: ANN001
        self.sealed.append((source, kwargs))
        return object()


def _gate_with_service(backfiller, service=None):
    gate = SealGate.__new__(SealGate)  # bypass the snapshot import in __init__
    gate._service = service if service is not None else _FakeService()
    gate._backfiller = backfiller
    gate._SnapshotError = RuntimeError
    return gate


def test_the_gate_refuses_a_seal_while_a_gap_is_open() -> None:
    # Feature 26's second half: with a gap still open, the gate refuses the
    # seal and names the stream and the hole — the service is never asked.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({}))
        service = _FakeService()
        gate = _gate_with_service(backfiller, service)

        with pytest.raises(RuntimeError) as exc:
            gate.seal("staging")

        assert "2..4" in str(exc.value)
        assert "aggTrades" in str(exc.value)
        assert service.sealed == []  # never sealed


def test_the_gate_lets_a_seal_through_once_the_gaps_are_filled() -> None:
    # Backfill the gaps, then the same gate lets the seal through — the fill
    # cleared the open set the gate reads.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 5)  # gap 2..4

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({(2, 4): [b"a", b"b", b"c"]}))
        service = _FakeService()
        gate = _gate_with_service(backfiller, service)

        backfiller.fill_stream(StreamClass.AGG_TRADES)
        result = gate.seal("staging", sealed_at=AT)

        assert result is not None
        assert len(service.sealed) == 1
        assert service.sealed[0][0] == "staging"


def test_the_gate_names_every_open_gap() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3
    detector.observe(StreamClass.KLINES, 1)
    detector.reconnect(StreamClass.KLINES)
    detector.observe(StreamClass.KLINES, 3)  # gap 2..2

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({}))
        service = _FakeService()
        gate = _gate_with_service(backfiller, service)

        with pytest.raises(RuntimeError) as exc:
            gate.seal("staging")

        message = str(exc.value)
        assert "aggTrades 2..3" in message
        assert "klines 2..2" in message
        assert "2 websocket gap" in message


def test_a_gate_without_a_backfiller_never_blocks() -> None:
    # The honest "no gap tracking wired" default: a gate with no backfiller
    # forwards unconditionally, so the seal path works before feature 25's
    # detector is in the loop.
    service = _FakeService()
    gate = _gate_with_service(None, service)
    assert gate.open_gaps() == ()
    gate.seal("staging")
    assert len(service.sealed) == 1


def test_the_gate_forwards_seal_arguments_unchanged() -> None:
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({}))
        service = _FakeService()
        gate = _gate_with_service(backfiller, service)

        gate.seal("staging", sealed_at=AT, snapshot_hash="a" * 64, universe={"x": 1})

        _, kwargs = service.sealed[0]
        assert kwargs == {"sealed_at": AT, "snapshot_hash": "a" * 64, "universe": {"x": 1}}


# -- End to end: detect, backfill, seal ----------------------------------------


def test_detect_backfill_then_seal_the_full_chain() -> None:
    # The feature end to end through the feature-16 boundary: a gapped
    # reconnect is detected into the log, the backfiller fills it over the
    # injected REST fetch into staging, and only then does the gate let the
    # seal through — a snapshot never sealed over a hole.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.observe(StreamClass.AGG_TRADES, 2)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 6)  # gap 3..5

    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        fetch = fake_fetch({(3, 5): [b"r3", b"r4", b"r5"]})
        backfiller = make_backfiller(log, staging, fetch)
        service = _FakeService()
        gate = _gate_with_service(backfiller, service)

        # Before backfill: the seal is refused.
        with pytest.raises(RuntimeError, match="3..5"):
            gate.seal("staging")

        # Backfill fills the hole.
        filled = backfiller.fill_stream(StreamClass.AGG_TRADES)
        assert len(filled) == 1
        assert filled[0].render().startswith("gap_filled: aggTrades")

        # Now the seal goes through, carrying the now-complete stream.
        gate.seal("staging", sealed_at=AT)
        assert len(service.sealed) == 1
        assert len(staging.staged(StreamClass.AGG_TRADES)) == 1


# -- Integration: the real sealing service behind the gate ---------------------


def test_the_gate_with_a_real_snapshot_service(tmp_path) -> None:
    # The real end to end with the actual sealing service (not a stand-in):
    # a real SnapshotService bound to the same lake the StagingArea writes,
    # so the gate's lazy import, isinstance check and forwarded seal are all
    # exercised — and the refusal is the service's own SnapshotError.
    from snapshot import SnapshotError, SnapshotService

    detector, log = detector_and_log()
    detector.observe(StreamClass.AGG_TRADES, 1)
    detector.reconnect(StreamClass.AGG_TRADES)
    detector.observe(StreamClass.AGG_TRADES, 4)  # gap 2..3

    # The StagingArea is the lake's staging directory — the same path the
    # sealing service seals from by default — so a default seal reads it.
    staging = StagingArea(tmp_path / "staging")
    fetch = fake_fetch({(2, 3): [b"r2", b"r3"]})
    backfiller = make_backfiller(log, staging, fetch)
    service = SnapshotService(tmp_path)
    gate = SealGate(service=service, backfiller=backfiller)

    # With the gap open, the real service is never asked and the seal raises
    # the service's own error type.
    with pytest.raises(SnapshotError) as exc:
        gate.seal()
    assert "2..3" in str(exc.value)
    assert service.sealed() == []  # nothing published

    # Backfill the hole, then the seal publishes a real snapshot.
    backfiller.fill_stream(StreamClass.AGG_TRADES)
    record = gate.seal(sealed_at=AT)
    assert record.sealed_at == AT
    assert record.path.name.startswith("2026-09-19")
    assert len(staging.staged(StreamClass.AGG_TRADES)) == 1
    # The sealed snapshot carries the backfill batch's bytes.
    assert len(record.files) == 1


def test_the_gate_rejects_a_wrong_service() -> None:
    # The gate wraps a SnapshotService; anything else is a wiring bug.
    import pathlib
    import tempfile

    detector, log = detector_and_log()
    with tempfile.TemporaryDirectory() as d:
        staging = StagingArea(pathlib.Path(d))
        backfiller = make_backfiller(log, staging, fake_fetch({}))
        with pytest.raises(TypeError, match="wraps a SnapshotService"):
            SealGate(service=object(), backfiller=backfiller)  # type: ignore[arg-type]
