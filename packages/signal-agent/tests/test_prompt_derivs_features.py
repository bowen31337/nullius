"""additions_spec_derivatives_inputs.xml's prompt half: the authoring
declaration names the served derivative *features*, not the raw streams.

``orchestrator._evaluate._materialize_from_context`` turns three sealed raw
streams (``funding``, ``futbars``, ``metrics``) into four feature frames a
signal reaches only through ``ctx.feature(name, version, lookback)`` --
``feature:funding_1d:v1``, ``feature:basis_1d:v1``, ``feature:taker_flow_1d
:v1`` and, when ``metrics`` is itself sealed, ``feature:metrics_1d:v1``.
There is no ``ctx.funding(...)`` or ``ctx.futbars(...)`` accessor, so a
declaration that named the raw stream (as ``available_streams`` did before
this fix, reading literal top-level directory names off the snapshot) told
an authoring agent about something it had no call to make.

This suite pins:

* ``available_streams`` and ``accessors_detail["feature"]["served"]`` name
  exactly the served frames for a snapshot -- with ``metrics_1d`` present
  only when the ``metrics`` stream is itself sealed -- and never the raw
  ``funding``/``futbars``/``metrics`` stream names;
* each served frame names itself, its version, its own declared columns,
  which of those must be cast to Float64 before arithmetic, its
  one-line-per-column meaning (including feature 3's own words for
  ``funding_rate_sum`` and ``basis``), and the point-in-time rule it is
  built under;
* ``accessors_detail["feature"]["lookback_unit"]`` states that a lookback
  counts rows across the whole returned frame, never per symbol, so a
  signal must filter or group by symbol itself;
* a second, always-present worked example
  (``accessors_detail["feature"]["example"]``) that reads ``funding_1d``
  with a per-symbol ``group_by`` and gives non-constant scores over a real
  sealed fixture;
* every other rendered section of the declaration is unaffected by any of
  the above.

No network; the snapshot fixture is a handful of tiny Parquet files under
``tmp_path``, written directly in :mod:`nullius_ingest.derivs_backfill`'s own
column shapes (the same convention ``test_window_derivs_features.py`` uses
for the materializer's own suite) rather than run through the archive
backfill. ``DATABASE_URL`` is explicitly unset, so sealing never reaches for
a relational store. No module-level state, so the suite is order- and
worker-independent under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import polars as pl
import pytest
from signal_agent import SignalContract

ALPHA = "ALPHAUSDT"
BETA = "BETAUSDT"

_FIRST_DAY = dt.date(2026, 2, 1)
_DAYS: tuple[dt.date, ...] = tuple(_FIRST_DAY + dt.timedelta(days=i) for i in range(5))

#: ALPHA's own funding rate, summed per day -- nonzero and distinct from
#: BETA's implicit 0.0 (BETA carries no perpetual, so the example scores it
#: by the honest default), which is what makes the example's scores
#: non-constant by construction rather than by chance.
_ALPHA_FUNDING_RATE_SUM = "0.00030000"
_ALPHA_FUNDING_RATE_LAST = "0.00010000"


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date, close: str) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=pa.timestamp("us", tz="UTC")),
                "close": [close],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(staging: Path, symbol: str, day: dt.date) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=pa.timestamp("us", tz="UTC")),
                "funding_rate_sum": [_ALPHA_FUNDING_RATE_SUM],
                "funding_rate_last": [_ALPHA_FUNDING_RATE_LAST],
                "n_settlements": pa.array([3], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(staging: Path, symbol: str, day: dt.date, *, fut_close: str) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=pa.timestamp("us", tz="UTC")),
                "fut_close": [fut_close],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_metrics(staging: Path, symbol: str, day: dt.date) -> None:
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    partition = staging / "metrics" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=pa.timestamp("us", tz="UTC")),
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


def _seal(lake_root: Path, *, include_metrics: bool) -> Any:
    """Seal ALPHA (bars + funding + futbars [+ metrics]) and BETA (bars only).

    BETA carries a spot bar every day and no derivative row at all -- "a
    symbol with no perpetual" -- so the example signal's honest default for
    a symbol absent from ``funding_1d`` is exercised by a real, sealed gap
    rather than an empty frame built by hand.
    """
    snapshot = pytest.importorskip("snapshot")

    staging = lake_root / "staging"
    (lake_root / "snapshots").mkdir(parents=True)
    for day in _DAYS:
        _write_bars(staging, ALPHA, day, "100.00")
        _write_bars(staging, BETA, day, "50.00")
        _write_funding(staging, ALPHA, day)
        _write_futbars(staging, ALPHA, day, fut_close="101.00")
        if include_metrics:
            _write_metrics(staging, ALPHA, day)

    service = snapshot.SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 3, 1, tzinfo=dt.UTC))
    return service.mount(sealed.name)


@pytest.fixture
def sealed_with_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return _seal(tmp_path / "lake-with-metrics", include_metrics=True)


@pytest.fixture
def sealed_without_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return _seal(tmp_path / "lake-without-metrics", include_metrics=False)


_FUNDING_RATE_SUM_MEANING = (
    "funding_rate_sum: the day's summed 8-hourly perpetual funding; "
    "positive means longs pay shorts"
)
_BASIS_MEANING = "basis: perpetual close over spot close minus 1"


# -- available_streams / served: exactly the served frames, never the raw ---
# -- stream, with and without metrics ----------------------------------------


def test_declaration_lists_exactly_the_served_frames_with_metrics(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    declared = law.declaration(snapshot=sealed_with_metrics)
    assert set(declared["available_streams"]) == {
        "bars",
        "funding_1d",
        "basis_1d",
        "taker_flow_1d",
        "metrics_1d",
    }
    served = declared["accessors_detail"]["feature"]["served"]
    assert set(served) == {"funding_1d", "basis_1d", "taker_flow_1d", "metrics_1d"}


def test_declaration_lists_exactly_the_served_frames_without_metrics(
    law: SignalContract, sealed_without_metrics: Any
) -> None:
    declared = law.declaration(snapshot=sealed_without_metrics)
    assert set(declared["available_streams"]) == {
        "bars",
        "funding_1d",
        "basis_1d",
        "taker_flow_1d",
    }
    served = declared["accessors_detail"]["feature"]["served"]
    assert set(served) == {"funding_1d", "basis_1d", "taker_flow_1d"}


def test_raw_derivative_stream_names_are_never_advertised(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    declared = law.declaration(snapshot=sealed_with_metrics)
    for raw_stream in ("funding", "futbars", "metrics"):
        assert raw_stream not in declared["available_streams"]
        assert raw_stream not in declared["stream_columns"]
        assert raw_stream not in declared["accessors_detail"]["feature"]["served"]


# -- each feature's columns, Float64 cast list and one-line meaning ---------


def test_funding_1d_detail(law: SignalContract, sealed_with_metrics: Any) -> None:
    served = law.declaration(snapshot=sealed_with_metrics)["accessors_detail"]["feature"][
        "served"
    ]
    funding = served["funding_1d"]
    assert funding["name"] == "funding_1d"
    assert funding["version"] == "v1"
    assert funding["columns"] == (
        "funding_rate_sum",
        "funding_rate_last",
        "n_settlements",
    )
    assert funding["cast_to_float64"] == ("funding_rate_sum", "funding_rate_last")
    assert "n_settlements" not in funding["cast_to_float64"]
    assert _FUNDING_RATE_SUM_MEANING in funding["meaning"]


def test_every_served_feature_names_itself_its_version_and_its_point_in_time_rule(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    served = law.declaration(snapshot=sealed_with_metrics)["accessors_detail"]["feature"][
        "served"
    ]
    assert set(served) == {"funding_1d", "basis_1d", "taker_flow_1d", "metrics_1d"}
    for name, detail in served.items():
        assert detail["name"] == name
        assert detail["version"] == "v1"
        point_in_time = detail["point_in_time"].lower()
        assert "ctx.t" in point_in_time or "decision time" in point_in_time
        assert "look-ahead" in point_in_time or "no row" in point_in_time


def test_basis_1d_detail(law: SignalContract, sealed_with_metrics: Any) -> None:
    served = law.declaration(snapshot=sealed_with_metrics)["accessors_detail"]["feature"][
        "served"
    ]
    basis = served["basis_1d"]
    assert basis["columns"] == ("basis",)
    assert basis["cast_to_float64"] == ("basis",)
    assert _BASIS_MEANING in basis["meaning"]


def test_taker_flow_1d_and_metrics_1d_detail(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    served = law.declaration(snapshot=sealed_with_metrics)["accessors_detail"]["feature"][
        "served"
    ]
    taker_flow = served["taker_flow_1d"]
    assert taker_flow["columns"] == ("taker_buy_ratio",)
    assert taker_flow["cast_to_float64"] == ("taker_buy_ratio",)
    assert len(taker_flow["meaning"]) == 1

    metrics = served["metrics_1d"]
    assert metrics["columns"] == metrics["cast_to_float64"]
    assert len(metrics["columns"]) == 6
    assert len(metrics["meaning"]) == 6


def test_stream_columns_match_each_served_frames_declared_columns(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    declared = law.declaration(snapshot=sealed_with_metrics)
    served = declared["accessors_detail"]["feature"]["served"]
    for name, detail in served.items():
        assert declared["stream_columns"][name] == ("symbol", "open_time", *detail["columns"])


# -- the lookback caveat: whole frame, never per symbol ----------------------


def test_feature_lookback_unit_warns_whole_frame_not_per_symbol(law: SignalContract) -> None:
    lookback_unit = law.declaration()["accessors_detail"]["feature"]["lookback_unit"].lower()
    assert "whole" in lookback_unit
    assert "not per symbol" in lookback_unit or "never per symbol" in lookback_unit
    assert "filter" in lookback_unit or "group by symbol" in lookback_unit


def test_served_is_absent_with_no_snapshot_configured(law: SignalContract) -> None:
    declared = law.declaration()
    assert "served" not in declared["accessors_detail"]["feature"]
    assert "available_streams" not in declared


# -- the second example: funding_1d, grouped by symbol, over a real sealed --
# -- fixture, giving non-constant scores -------------------------------------


def _materialized_window(mount: Any, decision_day: dt.date) -> Any:
    evaluator = pytest.importorskip("evaluator")
    orchestrator_evaluate = pytest.importorskip("orchestrator._evaluate")

    decision_time = dt.datetime.combine(decision_day, dt.time(23, 59), tzinfo=dt.UTC)
    resolution = evaluator.resolve_window(mount, decision_time)
    materialize = orchestrator_evaluate._materialize_from_context(
        SimpleNamespace(snapshot=mount, max_history_days=90)
    )
    return materialize(resolution, decision_time)


def test_example_funding_signal_runs_over_a_sealed_fixture_and_normalizes(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    evaluator = pytest.importorskip("evaluator")
    window = _materialized_window(sealed_with_metrics, _DAYS[-1])

    source = law.declaration()["accessors_detail"]["feature"]["example"]
    assert "group_by" in source
    assert 'ctx.feature("funding_1d"' in source

    namespace: dict[str, object] = {}
    exec(source, namespace)  # noqa: S102
    result = namespace["signal"](window, 0)

    assert isinstance(result, pl.Series)
    assert result.dtype == pl.Float64
    assert len(result) == len(window.universe)
    assert result.is_finite().all()
    # ALPHA (a real funding row every day) and BETA (no perpetual at all,
    # the honest 0.0 default) land on two different scores -- non-constant
    # by construction, the same claim test_contract_declaration_detail.py
    # makes for the bars example.
    assert len(set(result.to_list())) > 1

    normalized = evaluator.normalize_scores(result)
    assert len(normalized) == len(result)


# -- every other rendered section is unchanged -------------------------------


def test_every_other_rendered_section_is_unchanged_by_a_derivs_snapshot(
    law: SignalContract, sealed_with_metrics: Any
) -> None:
    base = law.declaration()
    with_snapshot = law.declaration(snapshot=sealed_with_metrics)

    for key in base:
        if key == "accessors_detail":
            continue
        assert with_snapshot[key] == base[key], key

    base_detail = base["accessors_detail"]
    new_detail = with_snapshot["accessors_detail"]
    for accessor in ("bars", "trades", "bookfeat", "borrow"):
        assert new_detail[accessor] == base_detail[accessor], accessor

    assert new_detail["feature"]["signature"] == base_detail["feature"]["signature"]
    assert new_detail["feature"]["lookback_unit"] == base_detail["feature"]["lookback_unit"]
    assert new_detail["feature"]["returns_notes"] == base_detail["feature"]["returns_notes"]
    assert new_detail["feature"]["example"] == base_detail["feature"]["example"]
    assert "served" not in base_detail["feature"]
    assert "served" in new_detail["feature"]
