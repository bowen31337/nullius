"""additions_spec_derivatives_inputs.xml, "Snapshot and Window" feature 3.

*System serves the derivative streams in every node's window as
point-in-time feature frames, so that a signal returns funding, basis,
taker-flow and open-interest features through ctx.feature(name, version).*

``orchestrator._evaluate._materialize_from_context`` used to build only the
``bars:1d`` frame. It now also reads the ``funding``, ``futbars`` and
``metrics`` streams :data:`evaluator.SLICED_STREAMS` now slices beside bars,
through the same per-(stream, symbol) panel and the same no-look-ahead
discipline, and turns them into four served feature frames:

* ``feature:funding_1d:v1`` — ``symbol``, ``open_time`` (``D`` 00:00 UTC),
  ``funding_rate_sum``, ``funding_rate_last`` and ``n_settlements``, carried
  verbatim from the sealed ``funding`` stream.
* ``feature:basis_1d:v1`` — ``symbol``, ``open_time`` and ``basis =
  fut_close/spot_close - 1``, computed host-side as a string, present only
  on a day both the spot bar and the futures bar exist.
* ``feature:taker_flow_1d:v1`` — ``symbol``, ``open_time`` and
  ``taker_buy_ratio = taker_buy_volume/fut_volume``, needing only the
  ``futbars`` stream.
* ``feature:metrics_1d:v1`` — the metrics stream's own six columns, present
  only when that (opt-in at backfill time) stream is sealed at all.

One test per claim the feature makes:

* each frame's own columns, in the order the spec's sentence names them;
* the per-date point-in-time cut — no frame ever carries a row dated after
  the decision time, checked over a grid of decision dates;
* the trailing ``max_history_days`` cap applies to a derivative frame
  exactly as it already does to bars;
* ``basis_1d`` is present only where *both* the spot close and the futures
  close exist for a day — checked both ways (a day with a futures close but
  no spot bar, and a day with a spot bar but no futures close) — while
  ``taker_flow_1d``, needing only the futures side, still carries that same
  day;
* a symbol with no perpetual (no row under any derivative stream) is simply
  absent from every derivative frame, never zero-filled, though it still
  carries bars and sits in ``ctx.universe``;
* a frame is altogether absent from ``window.frames`` — not merely
  empty — when its own underlying stream was never sealed at all, checked
  for each of the three derivative streams in turn;
* a stub signal reading ``ctx.feature("funding_1d", "v1")`` through
  :func:`evaluator.execute_signal` sees exactly the rows the materializer
  built, distinguishing a symbol that has them from one that does not.

Bars are rebuilt through the same per-symbol slice-then-concatenate
sequence :mod:`test_window_history_cap` already pins row for row; nothing
here changes what a bars frame carries.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across another, so the suite is
safe under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contract.bars import bars_frame_name
from contract.features import feature_frame_name
from evaluator import execute_signal, resolve_window
from orchestrator._evaluate import _materialize_from_context
from snapshot import SnapshotService

ALPHA = "ALPHAUSDT"
BETA = "BETAUSDT"

FIRST_DAY = dt.date(2026, 1, 1)
ALL_DAYS: tuple[dt.date, ...] = tuple(FIRST_DAY + dt.timedelta(days=i) for i in range(10))

#: ALPHA carries a spot bar every day but no futures row (funding, futbars or
#: metrics) on this one — the "futures missing" half of the basis claim, and
#: also what makes funding_1d/taker_flow_1d skip a day entirely (the archive
#: rule: "rows exist only on days with at least one settlement").
FUTURES_GAP_DAY = ALL_DAYS[2]

#: ALPHA carries a futures row every day but no spot bar on this one — the
#: "spot missing" half of the basis claim.
BARS_GAP_DAY = ALL_DAYS[1]

#: Small on purpose, the same stance test_window_history_cap.py takes: the
#: claim under test is the boundary arithmetic, not the shipped default.
MAX_HISTORY_DAYS = 4

_TS = pa.timestamp("us", tz="UTC")

#: ALPHA's own spot and futures closes, as exact Decimal strings — fixed
#: per day rather than computed from a float, so the expected basis string
#: this suite asserts can be derived with the identical formula the
#: materializer uses and compared exactly, with no floating-point rounding
#: in either direction.
ALPHA_SPOT_CLOSE: dict[dt.date, str] = {
    day: str(Decimal("100.00") + Decimal(index)) for index, day in enumerate(ALL_DAYS)
}
ALPHA_FUT_CLOSE: dict[dt.date, str] = {
    day: str(Decimal(close) + Decimal("1.00")) for day, close in ALPHA_SPOT_CLOSE.items()
}
TAKER_BUY_VOLUME = "400.0"
FUT_VOLUME = "1000.0"
EXPECTED_TAKER_RATIO = format(Decimal(TAKER_BUY_VOLUME) / Decimal(FUT_VOLUME), "f")

FUNDING_FRAME = feature_frame_name("funding_1d", "v1")
BASIS_FRAME = feature_frame_name("basis_1d", "v1")
TAKER_FLOW_FRAME = feature_frame_name("taker_flow_1d", "v1")
METRICS_FRAME = feature_frame_name("metrics_1d", "v1")
DERIVATIVE_FRAMES = (FUNDING_FRAME, BASIS_FRAME, TAKER_FLOW_FRAME, METRICS_FRAME)


# -- Staging one partition at a time, matching ingest.derivs_backfill's own ---
# -- column names and types exactly --------------------------------------------


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date, close: str) -> None:
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=_TS),
                "close": [close],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "funding_rate_sum": ["0.00030000"],
                "funding_rate_last": ["0.00010000"],
                "n_settlements": pa.array([3], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(staging: Path, symbol: str, day: dt.date, *, fut_close: str) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [fut_close],
                "fut_volume": [FUT_VOLUME],
                "taker_buy_volume": [TAKER_BUY_VOLUME],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_metrics(staging: Path, symbol: str, day: dt.date) -> None:
    partition = staging / "metrics" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "sum_open_interest": ["1234.5"],
                "sum_open_interest_value": ["987654.3"],
                "count_toptrader_long_short_ratio": ["1.2"],
                "sum_toptrader_long_short_ratio": ["1.5"],
                "count_long_short_ratio": ["1.1"],
                "sum_taker_long_short_vol_ratio": ["0.9"],
            }
        ),
        partition / "part-0.parquet",
    )


def _seal_world(
    lake_root: Path,
    *,
    days: Sequence[dt.date] = ALL_DAYS,
    include_funding: bool = True,
    include_futbars: bool = True,
    include_metrics: bool = True,
) -> Any:
    """Seal ALPHA (bars + futures) and BETA (bars only — "no perpetual").

    ALPHA's futures rows (funding, futbars and, when included, metrics) are
    written for every day except :data:`FUTURES_GAP_DAY`; its spot bar is
    written for every day except :data:`BARS_GAP_DAY`.  BETA carries a spot
    bar every day and never a futures row, the fixture for "a symbol with no
    perpetual is absent".  ``include_funding``/``include_futbars``/
    ``include_metrics`` gate whether that stream is staged *at all*, for the
    "a frame is absent when its stream is not sealed" claim.
    """
    staging = lake_root / "staging"
    (lake_root / "snapshots").mkdir(parents=True)

    for day in days:
        if day != BARS_GAP_DAY:
            _write_bars(staging, ALPHA, day, ALPHA_SPOT_CLOSE[day])
        _write_bars(staging, BETA, day, "50.00")

        if day == FUTURES_GAP_DAY:
            continue
        if include_funding:
            _write_funding(staging, ALPHA, day)
        if include_futbars:
            _write_futbars(staging, ALPHA, day, fut_close=ALPHA_FUT_CLOSE[day])
        if include_metrics:
            _write_metrics(staging, ALPHA, day)

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name)


def _materialized(
    mount: Any, decision_day: dt.date, *, max_history_days: int = MAX_HISTORY_DAYS
) -> tuple[Any, Any]:
    decision_time = dt.datetime.combine(decision_day, dt.time(23, 59, tzinfo=dt.UTC))
    resolution = resolve_window(mount, decision_time)
    materialize = _materialize_from_context(
        SimpleNamespace(snapshot=mount, max_history_days=max_history_days)
    )
    return materialize(resolution, decision_time), decision_time


def _rows(frame: Any) -> list[dict[str, Any]]:
    return frame.to_pylist()


# -- The full world: every stream sealed, both gap days present ----------------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    workdir = tmp_path_factory.mktemp("derivs-features-world")
    return _seal_world(workdir / "lake")


# -- Each frame's own columns ---------------------------------------------------


def test_funding_frame_columns(world: Any) -> None:
    window, _ = _materialized(world, ALL_DAYS[-1])
    frame = window.frames[FUNDING_FRAME]
    assert frame.column_names == [
        "symbol",
        "open_time",
        "funding_rate_sum",
        "funding_rate_last",
        "n_settlements",
    ]


def test_basis_frame_columns(world: Any) -> None:
    window, _ = _materialized(world, ALL_DAYS[-1])
    frame = window.frames[BASIS_FRAME]
    assert frame.column_names == ["symbol", "open_time", "basis"]


def test_taker_flow_frame_columns(world: Any) -> None:
    window, _ = _materialized(world, ALL_DAYS[-1])
    frame = window.frames[TAKER_FLOW_FRAME]
    assert frame.column_names == ["symbol", "open_time", "taker_buy_ratio"]


def test_metrics_frame_columns(world: Any) -> None:
    window, _ = _materialized(world, ALL_DAYS[-1])
    frame = window.frames[METRICS_FRAME]
    assert frame.column_names == [
        "symbol",
        "open_time",
        "sum_open_interest",
        "sum_open_interest_value",
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    ]


# -- The per-date point-in-time cut, over a grid of decision dates -------------


@pytest.mark.parametrize("decision_day", ALL_DAYS)
def test_no_frame_ever_carries_a_row_dated_after_the_decision_time(
    world: Any, decision_day: dt.date
) -> None:
    window, decision_time = _materialized(world, decision_day)
    for name in (bars_frame_name("1d"), *DERIVATIVE_FRAMES):
        frame = window.frames[name]
        if frame.num_rows == 0:
            continue
        for value in frame.column("open_time").to_pylist():
            assert value <= decision_time, (name, value, decision_time)


# -- The history cap applies to a derivative frame exactly as it does to bars --


def test_funding_frame_respects_the_history_cap(world: Any) -> None:
    decision_day = ALL_DAYS[-1]
    window, _ = _materialized(world, decision_day)
    frame = window.frames[FUNDING_FRAME]
    dates = {row["open_time"].date() for row in _rows(frame)}
    # (decision_date - MAX_HISTORY_DAYS, decision_date] over the trailing
    # four days; none of them is FUTURES_GAP_DAY, so the cap boundary itself
    # is the only thing under test here.
    expected = set(ALL_DAYS[len(ALL_DAYS) - MAX_HISTORY_DAYS :])
    assert FUTURES_GAP_DAY not in expected, "fixture sanity"
    assert dates == expected


def test_an_early_decision_date_carries_everything_available(world: Any) -> None:
    # FUTURES_GAP_DAY is not BARS_GAP_DAY, so ALPHA is still in the per-date
    # universe here; only two days of its funding history stand behind this
    # decision date (day 0, and BARS_GAP_DAY — which has no spot bar but
    # does have funding) — fewer than MAX_HISTORY_DAYS — so the cap must not
    # remove anything genuinely there.
    decision_day = FUTURES_GAP_DAY
    window, _ = _materialized(world, decision_day)
    frame = window.frames[FUNDING_FRAME]
    dates = {row["open_time"].date() for row in _rows(frame)}
    assert dates == {ALL_DAYS[0], BARS_GAP_DAY}


# -- basis_1d exists only where both closes do; taker_flow_1d needs only futbars --


def test_basis_is_present_only_where_both_closes_exist(world: Any) -> None:
    # The tradable roster is bars-derived, so a decision date materializes
    # ALPHA at all only when ALPHA itself has a bars partition that day —
    # FUTURES_GAP_DAY qualifies (only BARS_GAP_DAY does not). By this date
    # ALPHA's futures panel holds two rows: day 0 (a spot close exists) and
    # BARS_GAP_DAY (no spot close at all, by construction) — basis must
    # survive on exactly the first.
    decision_day = FUTURES_GAP_DAY
    window, _ = _materialized(world, decision_day, max_history_days=30)
    basis_rows = {row["open_time"].date(): row for row in _rows(window.frames[BASIS_FRAME])}
    assert set(basis_rows) == {ALL_DAYS[0]}
    expected_basis = format(
        Decimal(ALPHA_FUT_CLOSE[ALL_DAYS[0]]) / Decimal(ALPHA_SPOT_CLOSE[ALL_DAYS[0]])
        - Decimal(1),
        "f",
    )
    assert basis_rows[ALL_DAYS[0]]["basis"] == expected_basis
    assert all(row["symbol"] == ALPHA for row in basis_rows.values())


def test_taker_flow_needs_only_the_futures_close(world: Any) -> None:
    # Materialized as of FUTURES_GAP_DAY (not BARS_GAP_DAY itself, which
    # would drop ALPHA from the per-date universe entirely, since the
    # roster is bars-derived). BARS_GAP_DAY has no spot bar at all, yet
    # futbars exists for it — taker_flow_1d does not consult bars, so it
    # must still carry a row for that day once ALPHA is back in the
    # universe.
    decision_day = FUTURES_GAP_DAY
    window, _ = _materialized(world, decision_day, max_history_days=30)
    taker_rows = {
        row["open_time"].date(): row for row in _rows(window.frames[TAKER_FLOW_FRAME])
    }
    assert BARS_GAP_DAY in taker_rows
    assert taker_rows[BARS_GAP_DAY]["taker_buy_ratio"] == EXPECTED_TAKER_RATIO


# -- A symbol with no perpetual never appears in a derivative frame -----------


def test_a_symbol_with_no_perpetual_is_absent_from_every_derivative_frame(
    world: Any,
) -> None:
    decision_day = ALL_DAYS[-1]
    window, _ = _materialized(world, decision_day)
    for name in DERIVATIVE_FRAMES:
        symbols = {row["symbol"] for row in _rows(window.frames[name])}
        assert BETA not in symbols
    # BETA still trades and still carries bars — only the derivative frames
    # are blind to it.
    assert BETA in window.universe
    bars_symbols = {row["symbol"] for row in _rows(window.frames[bars_frame_name("1d")])}
    assert BETA in bars_symbols


# -- A frame is wholly absent when its own stream was never sealed -----------


@pytest.mark.parametrize(
    ("missing", "absent_frames"),
    [
        ("include_funding", (FUNDING_FRAME,)),
        ("include_futbars", (BASIS_FRAME, TAKER_FLOW_FRAME)),
        ("include_metrics", (METRICS_FRAME,)),
    ],
)
def test_a_frame_is_absent_when_its_own_stream_is_not_sealed(
    tmp_path: Path, missing: str, absent_frames: tuple[str, ...]
) -> None:
    kwargs = {"include_funding": True, "include_futbars": True, "include_metrics": True}
    kwargs[missing] = False
    mount = _seal_world(tmp_path / "lake", days=ALL_DAYS[:3], **kwargs)
    window, _ = _materialized(mount, ALL_DAYS[2], max_history_days=30)
    for name in absent_frames:
        assert name not in window.frames
    for name in set(DERIVATIVE_FRAMES) - set(absent_frames):
        assert name in window.frames


# -- A stub signal reading ctx.feature("funding_1d", "v1") gets the rows ------

FUNDING_STUB_SIGNAL_CODE = """
import polars as pl

def signal(ctx, seed):
    funding = ctx.feature("funding_1d", "v1")
    counts = {
        symbol: float(funding.filter(pl.col("symbol") == symbol).height)
        for symbol in ctx.universe
    }
    return pl.Series([counts[symbol] for symbol in ctx.universe])
"""


def test_a_stub_signal_reading_ctx_feature_gets_the_funding_rows(world: Any) -> None:
    decision_day = ALL_DAYS[-1]
    decision_time = dt.datetime.combine(decision_day, dt.time(23, 59, tzinfo=dt.UTC))
    resolution = resolve_window(world, decision_time)
    context = SimpleNamespace(snapshot=world, max_history_days=MAX_HISTORY_DAYS)
    execution = execute_signal(
        resolution,
        FUNDING_STUB_SIGNAL_CODE,
        seed=1,
        rebalance_dates=[decision_day],
        materialize=_materialize_from_context(context),
    )
    vector = execution.vector(decision_day)
    assert vector.conforming, vector.problems
    scores = dict(zip(vector.universe, vector.scores.to_list()))
    # ALPHA has funding rows within the window; BETA, with no perpetual, has
    # none at all — the stub's own count distinguishes them, so a signal
    # really did read the materialized rows rather than an empty stand-in.
    assert scores[ALPHA] > 0.0
    assert scores[BETA] == 0.0
