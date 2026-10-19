"""One-pass panel reads: the evaluation chain stops reading per (date, symbol, day).

The lake stores one Parquet file per symbol-day, and the evaluation chain used
to read strictly per day: ``_evaluate._materialize_from_context`` built each
rebalance date's window by looping every symbol's trailing partitions, so a
60-date out-of-sample evaluation on the 239-symbol wide snapshot made
1,385,448 ``pyarrow.parquet.read_table`` calls (each ``mount.select`` listing
the directory and sorting it) and took 3.5 to 27 minutes, almost none of it in
the sandbox.  ``_context._LazySymbolCloses._read_close`` read one file per day
on top of that — 331,369 reads for one snapshot's futures closes — and the
funding reader beside it did the same.

The fix reads each ``(stream, symbol)``'s whole partition table **once**:

* ``_evaluate``'s ``_PanelCache`` — one instance per evaluation call, never at
  module level, dropped when the call returns — reads every partition of a
  symbol in a single ``read_table`` and answers each date's window as a
  bisect slice of that table.  The frame handed onward is byte-identical to
  the previous per-file path's, so the sandbox sees exactly what it saw.
* ``_context._LazySymbolCloses`` (and ``_LazySymbolFunding``) read all of a
  symbol's partitions in one pass on first access, answering the identical
  ``{day: close}`` mapping.

One test per claim the fix makes:

* **the materialized frames are byte-identical** to the frames the previous
  per-file path produces — that path is pinned here as
  :func:`_previous_per_file_window`, swapped in for the cache — for every date
  of the grid, including a date whose window starts before a symbol's first
  partition and a symbol missing on some days;
* **the read count is O(symbols), not O(dates x symbols x window)** — asserted
  with a counting wrapper over ``pyarrow.parquet.read_table``;
* **``_LazySymbolCloses`` answers the same mapping** a per-day reader produces
  for a fixture symbol, reading each symbol once;
* **the cache never survives the call** — a second evaluation over the same
  snapshot reads the partitions again rather than reusing a module-level
  cache.

No test opens a network connection or writes outside a pytest temporary
directory, and no test carries state across another, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import bisect
import datetime as dt
import random
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contract.bars import bars_frame_name
from evaluator import resolve_window
from orchestrator._evaluate import _materialize_from_context
from snapshot import SnapshotService

#: Two symbols every day, one delisted partway through, one listed partway
#: through — so the grid crosses a listing and a delisting and the materialized
#: frames have to keep every symbol's own truncated range straight.
FIRST_DAY = dt.date(2026, 9, 1)
ALL_DAYS: tuple[dt.date, ...] = tuple(
    FIRST_DAY + dt.timedelta(days=i) for i in range(40)
)
GONE_LAST_INDEX = 18
LATE_FIRST_INDEX = 24
SYMBOL_DAYS: dict[str, tuple[dt.date, ...]] = {
    "ALWAYS": ALL_DAYS,
    "OTHER1": ALL_DAYS,
    "GONE": ALL_DAYS[: GONE_LAST_INDEX + 1],
    "LATE": ALL_DAYS[LATE_FIRST_INDEX:],
}

#: Rebalance dates from the middle on: inside GONE's live window at the start,
#: inside LATE's at the end, and inside neither in between.
GRID: tuple[dt.date, ...] = ALL_DAYS[12:32]

#: The window depth the materializer caps at, in days.  Small so a date's
#: window starts before a symbol's own first partition (``GONE`` on a date
#: after its delisting, ``LATE`` on an early date).
MAX_HISTORY_DAYS = 6
WORLD_SEED = 20261019

BARS_FRAME = bars_frame_name("1d")


#: One pinned funding_rate_sum per (symbol, day) — a negative rate on
#: alternate days, since a short-pays-long settlement is legitimate.
def _funding(symbol: str, day: dt.date) -> float:
    return round(0.0003 + 0.0001 * ((day - FIRST_DAY).days % 3) - 0.0002, 8)


def _seal_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """Seal a snapshot whose symbols cover different day ranges.

    The AR(1) recipe the evaluator suites share, generalized to a per-symbol
    day range — the shape a late listing and a delisting both need.  A
    matching ``funding`` stream is staged beside the bars, so the funding
    reader's own one-pass read is exercised over the same sealed mount.
    """
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol, days in SYMBOL_DAYS.items():
        price = 100.0 + generator.uniform(-20.0, 20.0)
        path: dict[dt.date, float] = {}
        previous = 0.0
        for day in days:
            previous = 0.5 * previous + 0.5 * generator.gauss(0.0, 0.02)
            price = max(1.0, price * (1.0 + previous))
            path[day] = round(price, 2)
        closes[symbol] = path

    for symbol, days in SYMBOL_DAYS.items():
        for day in days:
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [f"{closes[symbol][day]:.2f}"],
                        "volume": ["12.5"],
                    }
                ),
                partition / "part-0.parquet",
            )
            funding_part = (
                staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            funding_part.mkdir(parents=True)
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "date": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "funding_rate_sum": [f"{_funding(symbol, day):.8f}"],
                        "funding_rate_last": ["0.00010000"],
                        "n_settlements": pa.array([3], type=pa.int64()),
                    }
                ),
                funding_part / "part-0.parquet",
            )

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name), closes


def _previous_per_file_window(
    mount: Any,
    resolution: Any,
    stream: str,
    symbol: str,
    earliest_date: dt.date,
    decision_date: dt.date,
) -> Any:
    """One window, built the way the previous per-file path built it.

    This is the pre-fix code, pinned verbatim as the reference reader: every
    one of the symbol's admitted partitions up to ``decision_date`` read on
    its own — ``pq.read_table(str(paths[0]))``, the day's first part, an empty
    table skipped — each row tagged with its partition's ``date=`` day, the
    rows concatenated in that order, and the window ``(earliest_date,
    decision_date]`` taken as a bisect slice of the concatenation.

    The cached path must answer the identical frame: same rows, same order,
    same columns and dtypes.  Only the *reading* changes — one call for the
    whole symbol instead of one call per day.
    """
    row_days: list[dt.date] = []
    parts: list[Any] = []
    for iso in sorted(resolution.dates(stream, symbol)):
        row_day = dt.date.fromisoformat(iso)
        if row_day > decision_date:
            continue
        paths = list(mount.select(stream, symbol, iso))
        if not paths:
            continue
        one = pq.read_table(str(paths[0]))
        if one.num_rows == 0:
            continue
        row_days.extend([row_day] * one.num_rows)
        parts.append(one)
    if not parts:
        return None
    table = pa.concat_tables(parts).combine_chunks()
    lo = bisect.bisect_right(row_days, earliest_date)
    hi = bisect.bisect_right(row_days, decision_date)
    return table.slice(lo, hi - lo) if hi > lo else None


class _PreviousPerFileCache:
    """A stand-in for ``_PanelCache`` that reads one file per (symbol, day).

    ``_materialize_from_context`` reads each date's windows through
    ``panels.window``; swapping this in makes the whole frame builder —
    truncation, renaming, feature frames, the empty-frame shape — run exactly
    as it does in production, over windows assembled by the previous path.
    The frames it produces are therefore the pre-fix ones, byte for byte.
    """

    def __init__(self, mount: Any, resolution: Any) -> None:
        self._mount = mount
        self._resolution = resolution

    def window(
        self, stream: str, symbol: str, earliest_date: dt.date, decision_date: dt.date
    ) -> Any:
        return _previous_per_file_window(
            self._mount,
            self._resolution,
            stream,
            symbol,
            earliest_date,
            decision_date,
        )


def _materialize(mount: Any) -> Any:
    """The production materializer over the sealed mount."""
    return _materialize_from_context(
        SimpleNamespace(snapshot=mount, max_history_days=MAX_HISTORY_DAYS)
    )


def _frame(materialize: Any, resolution: Any, day: dt.date) -> Any:
    window = materialize(
        resolution, dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
    )
    return window.frames[BARS_FRAME]


def _frames(
    mount: Any, resolution: Any, days: Sequence[dt.date], *, per_file: bool = False
) -> dict[dt.date, Any]:
    """Each date's materialized frame, over the cache or the previous path.

    The materializer resolves its panel cache lazily, on the first date it is
    asked for, so the previous path is swapped in — and the whole grid
    consumed — inside the patch window rather than only around construction.
    """
    from orchestrator import _evaluate

    real = _evaluate._PanelCache
    if per_file:
        _evaluate._PanelCache = _PreviousPerFileCache
    try:
        materialize = _materialize(mount)
        return {day: _frame(materialize, resolution, day) for day in days}
    finally:
        _evaluate._PanelCache = real


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("panel-cache-world")
    return _seal_world(workdir)


@pytest.fixture
def resolution(world: tuple[Any, dict]) -> Any:
    mount, _ = world
    decision_time = dt.datetime.combine(GRID[-1], dt.time(23, 59), tzinfo=dt.UTC)
    return resolve_window(mount, decision_time)


class _CountingReadTable:
    """Counts every ``pyarrow.parquet.read_table`` a block makes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.count = 0
        real = pq.read_table

        def counting(*args: Any, **kwargs: Any) -> Any:
            self.count += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(pq, "read_table", counting)


# -- The frames are byte-identical to the previous per-file path ---------------


def test_the_cached_frames_equal_the_per_file_reference_for_every_date(
    world: tuple[Any, dict], resolution: Any
) -> None:
    mount, _ = world
    cached = _frames(mount, resolution, GRID)
    reference = _frames(mount, resolution, GRID, per_file=True)

    for day in GRID:
        frame = cached[day]
        expected = reference[day]
        assert frame.equals(expected), day
        # Same columns and dtypes, not merely the same values.
        assert frame.schema.equals(expected.schema), day
        # Same row order and same row count: the concatenation is
        # symbol-major, oldest first, and each symbol keeps its own range.
        assert frame.column("symbol").to_pylist() == expected.column(
            "symbol"
        ).to_pylist(), day
        assert frame.column("open_time").to_pylist() == expected.column(
            "open_time"
        ).to_pylist(), day


def test_a_window_starting_before_a_symbols_first_partition_is_identical(
    world: tuple[Any, dict], resolution: Any
) -> None:
    # LATE is listed on LATE_FIRST_INDEX.  On the grid's early dates it is not
    # yet in the universe; on its listing date its window reaches back before
    # its first partition, so its slice must carry exactly the one bar it has.
    mount, _ = world
    cached = _frames(mount, resolution, GRID)
    reference = _frames(mount, resolution, GRID, per_file=True)
    late_first = SYMBOL_DAYS["LATE"][0]
    early = [day for day in GRID if day < late_first]
    assert early, "fixture sanity: the grid must start before LATE is listed"

    for day in early:
        frame = cached[day]
        assert frame.equals(reference[day]), day
        # Not listed yet: absent from the universe, and so absent from the
        # frame even though the cache holds its later partitions.
        assert "LATE" not in frame.column("symbol").to_pylist(), day

    frame = cached[late_first]
    assert frame.equals(reference[late_first]), late_first
    late_days = [
        value.date()
        for value, symbol in zip(
            frame.column("open_time").to_pylist(),
            frame.column("symbol").to_pylist(),
        )
        if symbol == "LATE"
    ]
    assert late_days == [late_first], late_first


def test_a_symbol_missing_on_some_days_keeps_its_own_range(
    world: tuple[Any, dict], resolution: Any
) -> None:
    # GONE's last bar is GONE_LAST_INDEX; after that its window is empty, so
    # its rows must stop exactly at its delisting and never be carried forward
    # off the cached panel.
    mount, _ = world
    cached = _frames(mount, resolution, GRID)
    reference = _frames(mount, resolution, GRID, per_file=True)
    gone_last = SYMBOL_DAYS["GONE"][-1]

    for day in GRID:
        frame = cached[day]
        assert frame.equals(reference[day]), day
        gone_days = [
            value.date()
            for value, symbol in zip(
                frame.column("open_time").to_pylist(),
                frame.column("symbol").to_pylist(),
            )
            if symbol == "GONE"
        ]
        assert all(value <= gone_last for value in gone_days), day
        if day > gone_last:
            assert gone_days == [], day


# -- The read count is O(symbols), not O(dates x symbols x window) -------------


def test_one_evaluation_makes_o_of_symbols_parquet_reads(
    world: tuple[Any, dict], resolution: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    mount, _ = world
    counter = _CountingReadTable(monkeypatch)
    materialize = _materialize(mount)

    for day in GRID:
        _frame(materialize, resolution, day)

    # One read per (stream, symbol) actually asked for — never one per date,
    # per symbol and per day of the window.  The materializer reads two
    # streams (bars and funding), so the bound is symbols x streams, a number
    # that does not move with the grid; the previous path made
    # ``dates x symbols x window`` reads.
    bound = len(SYMBOL_DAYS) * 2
    assert counter.count <= bound, (
        f"{counter.count} reads for {len(GRID)} dates over "
        f"{len(SYMBOL_DAYS)} symbols — the per-(date, symbol, day) path is back"
    )
    # And the count does not grow with a longer grid: a second pass over the
    # same dates, against the same call's cache, reads nothing at all.
    counter.count = 0
    for day in GRID:
        _frame(materialize, resolution, day)
    assert counter.count == 0


def test_the_previous_path_would_scale_with_the_grid(
    world: tuple[Any, dict], resolution: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the claim: the pinned per-file reader really is the
    # O(dates x symbols x window) path, so the count above is a fixed
    # improvement and not an artefact of a cheap reference.
    mount, _ = world
    counter = _CountingReadTable(monkeypatch)
    _frames(mount, resolution, GRID, per_file=True)
    assert counter.count > len(GRID), (
        "the pinned reference reader no longer reads per (date, symbol, day) — "
        "it has stopped being the previous path"
    )


def _forget_module_level_panels() -> None:
    """Drop any process-lifetime panel cache a build might keep.

    The module-level ``_PANELS`` the fix removed was shared by every node and
    every evaluation in the process.  It is cleared here (when a build still
    has one) so the test below measures *this* call's reads rather than an
    entry an earlier evaluation in the same process already paid for.
    """
    from orchestrator import _evaluate

    stale = getattr(_evaluate, "_PANELS", None)
    if stale is not None:
        stale.clear()


def test_the_cache_is_per_call_and_never_module_level(
    world: tuple[Any, dict], resolution: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One evaluation's cache lives on that call and is dropped when it
    # returns, so a second evaluation over the same snapshot reads the
    # partitions again rather than sharing a process-lifetime cache.
    mount, _ = world
    _forget_module_level_panels()
    first = _materialize(mount)
    _frame(first, resolution, GRID[0])

    counter = _CountingReadTable(monkeypatch)
    second = _materialize(mount)
    _frame(second, resolution, GRID[0])

    assert counter.count > 0, (
        "a second evaluation reused a cache from the first — the panel cache "
        "must live on the call, never at module level"
    )


# -- _LazySymbolCloses answers the same mapping, reading each symbol once ------


def _closes_for(mount: Any, symbol: str) -> Any:
    """The mapping a context builds for one symbol, over the fixture mount."""
    from orchestrator._context import _LazySymbolCloses

    return _LazySymbolCloses(mount, mount.name, symbol)


def _reference_closes(mount: Any, symbol: str, days: Sequence[dt.date]) -> dict:
    """The previous per-day close reader, pinned: one ``_read_close`` a day."""
    from orchestrator._context import _read_close

    return {day: _read_close(mount, symbol, day) for day in days}


def _forget_close_caches() -> None:
    """Start this symbol's close reads from cold.

    Both the whole-symbol cache the fix adds and the per-(symbol, day) cache
    the lazy reader has always kept are dropped, so a read count below is this
    lookup's own reads and not a hit another test already paid for.
    """
    from orchestrator import _context

    for name in ("_SERIES_CACHE", "_CLOSE_CACHE"):
        cache = getattr(_context, name, None)
        if cache is not None:
            cache.clear()


def test_lazy_closes_answers_the_same_mapping_reads_the_symbol_once(
    world: tuple[Any, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The one-pass closes must answer the identical {day: close} mapping the
    # per-day reader built, over the symbol's own days only — and must do it
    # with one read per symbol rather than one per day.
    mount, closes = world
    symbol = "ALWAYS"
    days = sorted(closes[symbol])
    expected = _reference_closes(mount, symbol, days)

    from orchestrator import _context

    _forget_close_caches()

    calls: list[object] = []
    original = _context._read_part

    def counting(part: object, name: str) -> Any:
        calls.append(part)
        return original(part, name)

    monkeypatch.setattr(_context, "_read_part", counting)

    mapping = _closes_for(mount, symbol)
    got = {day: mapping[day] for day in days}

    assert got == expected, "the one-pass close map must match the per-day one"
    assert len(calls) == 1, (
        f"{len(calls)} reads for one {len(days)}-day symbol — the per-day "
        "close reads are back"
    )
    # Every one of the symbol's own partitions, not just the first day's.
    read = calls[0]
    assert not isinstance(read, (str, bytes)) and not hasattr(read, "__fspath__")
    assert len(list(read)) == len(days)


def test_lazy_closes_answers_a_symbol_with_a_shorter_range(
    world: tuple[Any, dict]
) -> None:
    # A delisted or late-listed symbol must map exactly its own days: the
    # one-pass read takes the symbol's partition listing as the day set, so a
    # short range must not pick up a neighbour's days nor drop one of its own.
    mount, closes = world
    for symbol in ("GONE", "LATE"):
        days = sorted(closes[symbol])
        mapping = _closes_for(mount, symbol)
        assert {day: mapping[day] for day in days} == _reference_closes(
            mount, symbol, days
        )
        assert len(mapping) == len(days)
        for day in sorted(set(ALL_DAYS) - set(days)):
            assert day not in mapping


# -- The funding reader beside the closes takes the identical one-pass read ----


def test_lazy_funding_answers_the_same_mapping_reads_the_symbol_once(
    world: tuple[Any, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The funding reader beside _LazySymbolCloses takes the identical one-pass
    # read: the same {ingest day: funding_rate_sum} map the per-day reader
    # built, with one read per symbol rather than one per day.  Funding is a
    # separate stream from bars, so its partitions are staged here.
    mount, _ = world
    symbol = "GONE"
    days = SYMBOL_DAYS[symbol]

    from orchestrator import _context

    expected = {
        day: _context._read_funding_rate_sum(mount, symbol, day) for day in days
    }

    for name in ("_FUNDING_SERIES_CACHE", "_FUNDING_CACHE"):
        cache = getattr(_context, name, None)
        if cache is not None:
            cache.clear()

    calls: list[object] = []
    original = _context._read_part

    def counting(part: object, name: str) -> Any:
        calls.append(part)
        return original(part, name)

    monkeypatch.setattr(_context, "_read_part", counting)

    mapping = _context._LazySymbolFunding(mount, mount.name, symbol)
    got = {day: mapping[day] for day in days}

    assert got == expected, "the one-pass funding map must match the per-day one"
    assert len(calls) == 1, (
        f"{len(calls)} reads for one {len(days)}-day funding symbol — the "
        "per-day funding reads are back"
    )
    read = calls[0]
    assert not isinstance(read, (str, bytes)) and not hasattr(read, "__fspath__")
    assert len(list(read)) == len(days)
