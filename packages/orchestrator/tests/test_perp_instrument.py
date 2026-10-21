"""additions_spec_research_book_v2.xml, the perp instrument feature.

System evaluates signals as a book of USD-M perpetuals when the evaluation
config says ``"instrument": "perp"``, so that node and close-out figures
return perp price returns net of funding carry and perp fees.

Over one tmp sealed snapshot carrying ``bars``, ``futbars`` and ``funding``
for three "funded" symbols (AAAUSDT, BBBUSDT, CCCUSDT — each with a sealed
perpetual) and one "no-perp" symbol (DDDUSDT — bars only, no futures
contract at all), this suite covers:

* the config key is optional (``"spot"`` default, ``"perp"`` opt-in) and
  closed (a third spelling is refused);
* with ``"perp"``, ``context.closes`` is served from ``futbars``'
  ``fut_close`` — never the bars ``close`` — keyed by the same spot symbol;
* the funding carry :func:`orchestrator._evaluate._funding_carry` computes
  is the sum of ``funding_rate_sum`` over the holding window ``D+1``
  through ``D+h``, excluding the settlement row keyed to ``D`` itself and
  counting a missing row as zero, with the sign that makes a long pay
  positive funding and a short receive it (bug_spec_null_carry_leak moved
  where that carry is charged — into the target seam,
  :func:`orchestrator._targets.snapshot_forward_returns` — but
  ``_funding_carry`` itself, and this window rule, are unchanged);
* a scored symbol with no perp close at a date is dropped from the score
  vector before alignment, never refused;
* a "perp" instrument whose cost-model schedule does not price a USD-M
  venue (a venue not ending ``_usdm``) is refused, naming both;
* a live node evaluated with ``"perp"`` evaluates to completion over a
  world that mixes funded and un-funded symbols.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across another, so the suite is
safe under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

import cost_model
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import TAKER
from evaluator import (
    HORIZONS,
    GatedTargets,
    RawScoreVector,
    SignalExecution,
    TargetSeries,
    align_targets,
    apply_costs,
)
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import (
    PERP_INSTRUMENT,
    SPOT_INSTRUMENT,
    EvaluationConfigError,
    load_evaluation_context,
)
from orchestrator._evaluate import (
    _cost_schedule_from_context,
    _drop_unpriced_symbols,
    _funding_carry,
    evaluate_node,
)
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

CODE_WORD = "evaluation_config"
USDM_PATH = Path(cost_model.__file__).with_name("binance_usdm.yaml")

_TS = pa.timestamp("us", tz="UTC")

FUNDED_SYMBOLS = ("AAAUSDT", "BBBUSDT", "CCCUSDT")
NOPERP_SYMBOL = "DDDUSDT"
ALL_SYMBOLS = FUNDED_SYMBOLS + (NOPERP_SYMBOL,)

FIRST_DAY = dt.date(2026, 1, 1)
ALL_DAYS = tuple(FIRST_DAY + dt.timedelta(days=i) for i in range(30))

#: The funding-window test's own three days: D, D+1 and D+2 — entirely
#: outside EVAL_DATES, so the sentinel and the deliberately missing row
#: never touch the full-node evaluation below.
WINDOW_DAY = ALL_DAYS[5]
WINDOW_DAY_PLUS_1 = ALL_DAYS[6]
WINDOW_DAY_PLUS_2 = ALL_DAYS[7]

#: AAAUSDT's own day-D funding settlement — deliberately huge, so including
#: it in a window sum would be unmistakable; the window the spec names
#: starts strictly after the entry, at D+1, and must never reach this row.
SENTINEL_FUNDING = "9.00000000"
#: AAAUSDT's D+1 settlement — the one row the two-day window must sum.
WINDOW_FUNDING = "0.00030000"
#: Every other day (every symbol, and AAAUSDT outside the window test's own
#: three days) — uniform, so nothing outside the window test depends on it.
UNIFORM_FUNDING = "0.00040000"

EVAL_DATES = ALL_DAYS[15:25]


def _spot_close(symbol_index: int, day_index: int) -> float:
    # The rank order among symbols rotates with the day (period
    # len(FUNDED_SYMBOLS)) rather than staying fixed: the full-node test
    # below scores symbols by their latest close directly, and a signal
    # whose relative ranking never changed across dates would give
    # compute_node_metrics a constant per-date information coefficient —
    # refused as an undefined t-statistic (zero variance), not the
    # perp-instrument defect this suite is testing for.
    phase = (symbol_index + day_index) % len(FUNDED_SYMBOLS)
    return round(100.0 + 10.0 * phase + 0.05 * day_index, 4)


def _fut_close(symbol_index: int, day_index: int) -> float:
    return round(_spot_close(symbol_index, day_index) + 5.0, 4)


def _stamp(day: dt.date) -> Any:
    return dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)


def _write_bars(staging: Path, symbol: str, day: dt.date, close: float) -> None:
    partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "open_time": pa.array([_stamp(day)], type=_TS),
                "close": [str(close)],
                "volume": ["10.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_futbars(staging: Path, symbol: str, day: dt.date, fut_close: float) -> None:
    partition = staging / "futbars" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "fut_close": [str(fut_close)],
                "fut_volume": ["1000.0"],
                "taker_buy_volume": ["400.0"],
                "quote_volume": ["100000.0"],
            }
        ),
        partition / "part-0.parquet",
    )


def _write_funding(staging: Path, symbol: str, day: dt.date, funding_rate_sum: str) -> None:
    partition = staging / "funding" / f"symbol={symbol}" / f"date={day.isoformat()}"
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": [symbol],
                "date": pa.array([_stamp(day)], type=_TS),
                "funding_rate_sum": [funding_rate_sum],
                "funding_rate_last": [funding_rate_sum],
                "n_settlements": pa.array([3], type=pa.int64()),
            }
        ),
        partition / "part-0.parquet",
    )


def _funding_for(symbol: str, day: dt.date) -> str | None:
    """``None`` means "write no row at all" — AAAUSDT's deliberate gap at
    :data:`WINDOW_DAY_PLUS_2`, the missing-row-counts-zero case.
    """
    if symbol != "AAAUSDT":
        return UNIFORM_FUNDING
    if day == WINDOW_DAY:
        return SENTINEL_FUNDING
    if day == WINDOW_DAY_PLUS_1:
        return WINDOW_FUNDING
    if day == WINDOW_DAY_PLUS_2:
        return None
    return UNIFORM_FUNDING


def _seal_world(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for index, symbol in enumerate(ALL_SYMBOLS):
        for day_index, day in enumerate(ALL_DAYS):
            _write_bars(staging, symbol, day, _spot_close(index, day_index))
    for index, symbol in enumerate(FUNDED_SYMBOLS):
        for day_index, day in enumerate(ALL_DAYS):
            _write_futbars(staging, symbol, day, _fut_close(index, day_index))
            funding = _funding_for(symbol, day)
            if funding is not None:
                _write_funding(staging, symbol, day, funding)
    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed


@pytest.fixture(scope="module")
def sealed_world(tmp_path_factory: pytest.TempPathFactory) -> Any:
    workdir = tmp_path_factory.mktemp("perp-instrument-world")
    return _seal_world(workdir / "lake")


# -- Loading a context over the sealed world ------------------------------------


def _bwrap_dir(tmp_path: Path) -> Path:
    bwrap_dir = tmp_path / "bin"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return bwrap_dir


def _document(
    sealed_path: Path,
    tmp_path: Path,
    *,
    evaluation_dates: tuple[dt.date, ...],
    instrument: str | None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "snapshot_mount": str(sealed_path),
        "evaluation_dates": [day.isoformat() for day in evaluation_dates],
        "horizon": 1,
        "seed": 20261014,
        "epoch_id": "epoch-perp-instrument-test",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    if instrument is not None:
        document["instrument"] = instrument
    return document


def _environment(
    tmp_path: Path, document: dict[str, Any], *, name: str, cost_model_path: Path | None
) -> dict[str, str]:
    config_path = tmp_path / f"evaluation-{name}.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / f'{name}.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "PATH": str(_bwrap_dir(tmp_path)),
    }
    if cost_model_path is not None:
        environment["NULLIUS_COST_MODEL_PATH"] = str(cost_model_path)
    return environment


def _load(
    sealed_path: Path,
    tmp_path: Path,
    *,
    name: str,
    evaluation_dates: tuple[dt.date, ...] = EVAL_DATES,
    instrument: str | None = None,
    cost_model_path: Path | None = None,
) -> Any:
    document = _document(
        sealed_path, tmp_path, evaluation_dates=evaluation_dates, instrument=instrument
    )
    environment = _environment(
        tmp_path, document, name=name, cost_model_path=cost_model_path
    )
    return load_evaluation_context(environment)


# -- The config: optional, closed, and the venue gate ---------------------------


def test_spot_is_the_unchanged_default(sealed_world: Any, tmp_path: Path) -> None:
    _service, sealed = sealed_world
    context = _load(sealed.path, tmp_path, name="spot-default")

    assert context is not None
    assert context.instrument == SPOT_INSTRUMENT
    assert context.funding is None
    day = ALL_DAYS[16]
    assert context.closes["AAAUSDT"][day] == _spot_close(0, 16)


def test_instrument_refuses_an_unknown_value(sealed_world: Any, tmp_path: Path) -> None:
    _service, sealed = sealed_world
    with pytest.raises(EvaluationConfigError) as record:
        _load(sealed.path, tmp_path, name="instrument-unknown", instrument="margin")

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert "instrument" in message
    assert "margin" in message


def test_perp_refuses_a_cost_model_whose_venue_is_not_usdm(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    # No cost_model_path: the shipped default (venue "binance_spot") is what
    # loads, and it does not end in "_usdm".
    with pytest.raises(EvaluationConfigError) as record:
        _load(sealed.path, tmp_path, name="perp-mismatched-venue", instrument="perp")

    message = str(record.value)
    assert message.startswith(f"{CODE_WORD}:")
    assert "perp" in message
    assert "binance_spot" in message


# -- The perp closes: fut_close, never the bars close ---------------------------


def test_perp_closes_come_from_fut_close_not_bars_close(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _load(
        sealed.path,
        tmp_path,
        name="perp-closes",
        instrument="perp",
        cost_model_path=USDM_PATH,
    )

    assert context is not None
    assert context.instrument == PERP_INSTRUMENT
    day = ALL_DAYS[16]
    assert context.closes["AAAUSDT"][day] == _fut_close(0, 16)
    assert context.closes["AAAUSDT"][day] != _spot_close(0, 16)
    # DDDUSDT has bars but never a futures contract: a perp context carries
    # no closes for it at all.
    assert NOPERP_SYMBOL not in context.closes


# -- The funding carry: the window, a missing row, and the sign -----------------


def _gated_with(
    values: dict[dt.date, dict[str, float]], *, horizon: int, snapshot_name: str
) -> GatedTargets:
    """A hand-built, step-5 bundle whose ``horizon`` series carries
    ``values`` verbatim and every other horizon is the empty series feature
    75's shape promise requires — the same helper
    ``test_cost_pit_cross_section.py`` already proved for exercising
    :func:`evaluator.apply_costs` directly, parametrized by horizon here
    since the funding window's length is the horizon itself.
    """
    dates = tuple(sorted(values))
    series = {
        h: TargetSeries(
            horizon=h, snapshot_name=snapshot_name, values=values if h == horizon else {}
        )
        for h in HORIZONS
    }
    return GatedTargets(
        snapshot_name=snapshot_name,
        rebalance_dates=dates,
        series=series,
        charges_budget=False,
    )


def test_funding_carry_sums_d_plus_1_through_d_plus_h_excluding_d_itself(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _load(
        sealed.path,
        tmp_path,
        name="perp-funding-window",
        instrument="perp",
        cost_model_path=USDM_PATH,
    )
    assert context is not None

    # WINDOW_FUNDING (D+1) is summed; WINDOW_DAY_PLUS_2's missing row counts
    # zero; WINDOW_DAY's own SENTINEL_FUNDING is excluded entirely — if it
    # had leaked in, the carry would be off by nearly 9.0. _funding_carry is
    # the one definition of this window rule (bug_spec_null_carry_leak kept
    # its signature and semantics; only its caller moved), so this still
    # exercises the window math against a real, sealed-snapshot-backed
    # context's own parsed funding partitions.
    expected_carry = float(WINDOW_FUNDING) + 0.0
    assert _funding_carry(context, "AAAUSDT", WINDOW_DAY, 2) == pytest.approx(expected_carry)

    # bug_spec_null_carry_leak moved the carry out of charges() and into the
    # target seam (orchestrator._targets.snapshot_forward_returns, so that a
    # planted null's permutation carries it along); charges() now quotes the
    # uniform fee alone, with no trace of the carry.
    gross_return = 0.05
    gated = _gated_with(
        {WINDOW_DAY: {"AAAUSDT": gross_return}},
        horizon=2,
        snapshot_name="snap_funding_window_test",
    )
    charges = _cost_schedule_from_context(context)
    priced = apply_costs(
        gated, charges, node_id="node-funding-window", cost_model=context.cost_model
    )

    fee = context.cost_schedule.fee_fraction(TAKER)
    assert priced.charges(2)[WINDOW_DAY]["AAAUSDT"] == pytest.approx(fee)

    post_cost_return = priced.returns(2)[WINDOW_DAY]["AAAUSDT"]
    assert post_cost_return == pytest.approx(gross_return - fee)


def test_a_long_earns_less_than_its_price_return_and_a_short_earns_more(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _load(
        sealed.path,
        tmp_path,
        name="perp-funding-sign",
        instrument="perp",
        cost_model_path=USDM_PATH,
    )
    assert context is not None

    gross_return = 0.05
    gated = _gated_with(
        {WINDOW_DAY: {"AAAUSDT": gross_return}},
        horizon=2,
        snapshot_name="snap_funding_sign_test",
    )
    charges = _cost_schedule_from_context(context)
    priced = apply_costs(
        gated, charges, node_id="node-funding-sign", cost_model=context.cost_model
    )
    post_cost_return = priced.returns(2)[WINDOW_DAY]["AAAUSDT"]

    # Sigma w (r - c): a fully long book (w=+1) pays the charge, a fully
    # short book (w=-1) receives it back — the fee alone already does this,
    # but a uniform fee cancels in a dollar-neutral book; the funding carry
    # does not, since it is not uniform across symbols.
    long_book_return = 1.0 * post_cost_return
    short_book_return = -1.0 * post_cost_return

    assert long_book_return < gross_return
    assert short_book_return > -gross_return


# -- The scoring universe: a no-perp symbol is dropped, not refused ------------


def test_a_no_perp_symbol_is_dropped_from_the_score_vector_not_refused(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _load(
        sealed.path,
        tmp_path,
        name="perp-drop",
        instrument="perp",
        cost_model_path=USDM_PATH,
    )
    assert context is not None

    days = EVAL_DATES[:2]
    vectors: dict[dt.date, RawScoreVector] = {}
    for day in days:
        universe = ("AAAUSDT", NOPERP_SYMBOL)
        vectors[day] = RawScoreVector(
            rebalance_date=day,
            decision_time=dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC),
            universe=universe,
            seed=1,
            contract_version="1",
            scores=pl.Series([1.0, -1.0]),
            problems=[],
        )
    execution = SignalExecution(
        snapshot_name="snap_drop_test", code_hash="a" * 64, seed=1, vectors=vectors
    )

    filtered, dropped = _drop_unpriced_symbols(execution, context)

    assert dropped == len(days)
    for day in days:
        vector = filtered.vector(day)
        assert vector.universe == ("AAAUSDT",)
        assert vector.scores.to_list() == [1.0]

    # The replaced refusal: align_targets no longer sees the dropped symbol,
    # so it never raises EvaluatorAlignmentError for it.
    alignment = align_targets(filtered, context.closes)
    assert alignment is not None


# -- A live node: evaluates to completion with a no-perp symbol dropped --------


NODE_SIGNAL_CODE = """
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) == 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    latest = {}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        latest[symbol] = float(series[-1]["c"][0])
    return pl.Series([latest[symbol] for symbol in ctx.universe])
"""

CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee01"


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_perp_instrument_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _migrate_tree(database_url: str) -> None:
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(database_url)


def _plant_root(database_url: str, *, node_id: str, campaign_id: str) -> None:
    with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, NULL, ?, ?, ?)",
            (node_id, campaign_id, "macro", 0),
        )


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering a dense, gapless real-branch series —
    the same stand-in ``test_book_beta_neutral.py`` already proved.
    """

    def __init__(self, *, charges_budget: bool = True) -> None:
        self.charges_budget = charges_budget

    def post(self, request: Any) -> TargetResponse:
        first, last = request.date_range
        days: list[dt.date] = []
        day = first
        while day <= last:
            days.append(day)
            day += dt.timedelta(days=1)
        symbols = sorted(request.symbols)
        series = {
            day: {
                symbol: 0.001 * (index + 1) * (1.0 + 0.1 * (day - first).days)
                for index, symbol in enumerate(symbols)
            }
            for day in days
        }
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=self.charges_budget,
        )


def test_a_perp_node_evaluates_to_completion_dropping_the_no_perp_symbol(
    sealed_world: Any, tmp_path: Path
) -> None:
    _service, sealed = sealed_world
    context = _load(
        sealed.path,
        tmp_path,
        name="perp-node",
        instrument="perp",
        cost_model_path=USDM_PATH,
    )
    assert context is not None
    _migrate_tree(context.database_url)

    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    endpoint = RecordingEndpoint()
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        NODE_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class is None, answer.fail_detail
    assert answer.metrics is not None
    assert answer.persistence is not None and answer.persistence.artifact_written is True
    # DDDUSDT is scored every date (it has bars throughout) and never has a
    # perp close, so it is dropped on every one of the evaluated dates.
    assert answer.dropped_perp_symbols == len(EVAL_DATES)
