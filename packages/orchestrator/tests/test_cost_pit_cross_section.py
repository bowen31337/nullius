"""bug_spec_pipeline_cross_section.xml, bug (A) — cost cross-section.

After bug_spec_pit_universe.xml, scores, windows and aligned targets all use
each rebalance date's own point-in-time cross-section — but step 7
(``evaluator.apply_costs``) and the orchestrator's own cost schedule closure
(``orchestrator._evaluate._cost_schedule_from_context``) still assumed a
dense panel: one fixed symbol set shared by every date a horizon covers.
Two bugs made that assumption:

* :class:`evaluator.CostRequest` required every date's gross-return row to
  equal the *same* ``symbols`` tuple exactly (``_costs.py``'s own
  ``__post_init__``), so a mid-window listing or delisting raised
  ``EvaluatorCostError`` naming the mismatch the moment the request was
  built — before any schedule was even asked.
* ``orchestrator._evaluate._cost_schedule_from_context``'s quote closure
  priced every date off ``request.symbols`` (the whole-horizon union)
  rather than that date's own ``request.gross_returns[day]``, so even a
  relaxed request would be quoted for symbols a thin date never scored.
* ``evaluator._costs.apply_costs`` itself then rebuilt each date's post-cost
  row by iterating the same whole-horizon union, which would ``KeyError`` on
  any date missing a symbol from it.

This suite proves the fix at three levels: :class:`~evaluator.CostRequest`
and :func:`~evaluator.apply_costs` now accept (and still validate) a
per-date cross-section directly; the orchestrator's own cost schedule
closure quotes each date off its own symbols; and a live node evaluated over
a world with both a mid-window listing and a mid-window delisting prices
and evaluates end to end, with no ``EvaluatorCostError``.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across tests, so the suite is safe
under pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import random
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import TAKER, FeeSchedule, load_cost_model
from evaluator import (
    HORIZONS,
    CostModelRef,
    CostQuote,
    CostRequest,
    EvaluatorCostError,
    GatedTargets,
    TargetSeries,
    apply_costs,
)
from evaluator._execute import pit_universe
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import EvaluationContext
from orchestrator._evaluate import _cost_schedule_from_context, evaluate_node
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

_VENUE = "binance_spot"
_VERSION = "2026.09.1"
_REF = CostModelRef(venue=_VENUE, version=_VERSION)
_SNAPSHOT = "snap_pit_cost_test"


# -- Part 1: evaluator._costs' own contract, per date -------------------------


def _gated_with(values: dict[dt.date, dict[str, float]]) -> GatedTargets:
    """A hand-built, step-5 bundle whose horizon-1 series carries ``values``
    verbatim and every other horizon is empty (feature 75's shape promise).
    """
    dates = tuple(sorted(values))
    series = {
        horizon: TargetSeries(
            horizon=horizon,
            snapshot_name=_SNAPSHOT,
            values=values if horizon == 1 else {},
        )
        for horizon in HORIZONS
    }
    return GatedTargets(
        snapshot_name=_SNAPSHOT,
        rebalance_dates=dates,
        series=series,
        charges_budget=False,
    )


def _flat_schedule(bps: float = 10.0):
    """A per-date-correct stub schedule: quotes exactly each date's own
    symbols, the fix this bug requires of a real cost library adapter.
    """
    rate = bps / 10_000.0

    def schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: dict.fromkeys(row, rate)
                for day, row in request.gross_returns.items()
            },
        )

    return schedule


#: day0: AAA, BBB only.  day1: CCC lists (AAA, BBB, CCC) — a mid-window
#: listing.  day2: BBB delists (AAA, CCC) — a mid-window delisting, inside
#: the same horizon's span the listing happened in.  day3: settles at
#: (AAA, CCC) — never reviving BBB.
_D0 = dt.date(2026, 9, 1)
_D1 = _D0 + dt.timedelta(days=1)
_D2 = _D0 + dt.timedelta(days=2)
_D3 = _D0 + dt.timedelta(days=3)
_LISTING_AND_DELISTING_VALUES: dict[dt.date, dict[str, float]] = {
    _D0: {"AAA": 0.01, "BBB": -0.02},
    _D1: {"AAA": 0.02, "BBB": 0.01, "CCC": 0.03},
    _D2: {"AAA": 0.015, "CCC": 0.02},
    _D3: {"AAA": 0.03, "CCC": 0.01},
}


def test_a_mid_window_listing_and_delisting_both_price_without_error() -> None:
    gated = _gated_with(_LISTING_AND_DELISTING_VALUES)
    out = apply_costs(gated, _flat_schedule(), node_id="node_1", cost_model=_REF)

    priced = out.costed(1)
    assert priced.dates() == (_D0, _D1, _D2, _D3)
    for day, expected in _LISTING_AND_DELISTING_VALUES.items():
        # The priced returns on each date cover exactly that date's own
        # cross-section — never the whole horizon's union.
        assert set(priced.at(day)) == set(expected)
        assert set(priced.charge_at(day)) == set(expected)
        for symbol, gross in expected.items():
            assert priced.at(day)[symbol] == pytest.approx(gross - 0.001)


def test_a_request_may_carry_a_different_cross_section_per_date() -> None:
    # The relaxed invariant directly: symbols is the union, every date's own
    # row may be a strict subset of it, and the union of every date
    # recovers symbols exactly.
    request = CostRequest(
        node_id="node_1",
        venue=_VENUE,
        version=_VERSION,
        horizon=1,
        symbols=("AAA", "BBB", "CCC"),
        date_range=(_D0, _D1),
        gross_returns={
            _D0: {"AAA": 0.01, "BBB": -0.02},
            _D1: {"AAA": 0.02, "CCC": 0.03},
        },
    )
    assert request.symbols == ("AAA", "BBB", "CCC")
    assert dict(request.gross_returns[_D0]) == {"AAA": 0.01, "BBB": -0.02}
    assert dict(request.gross_returns[_D1]) == {"AAA": 0.02, "CCC": 0.03}


def test_a_request_still_refuses_a_symbol_no_date_carries() -> None:
    # Deliberately mismatched: "DDD" is declared in symbols but appears on
    # no date in gross_returns — still refused, same support rule.
    with pytest.raises(EvaluatorCostError, match="same support"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA", "BBB", "DDD"),
            date_range=(_D0, _D1),
            gross_returns={
                _D0: {"AAA": 0.01, "BBB": -0.02},
                _D1: {"AAA": 0.02},
            },
        )


def test_a_request_still_refuses_a_date_naming_a_symbol_outside_its_own_set() -> None:
    # The reverse mismatch: a date names a symbol the request's own cross-
    # section never declared at all.
    with pytest.raises(EvaluatorCostError, match="same support"):
        CostRequest(
            node_id="node_1",
            venue=_VENUE,
            version=_VERSION,
            horizon=1,
            symbols=("AAA", "BBB"),
            date_range=(_D0, _D0),
            gross_returns={_D0: {"AAA": 0.01, "BBB": -0.02, "ZZZ": 0.05}},
        )


def test_apply_costs_still_refuses_a_quote_naming_the_wrong_per_date_symbols() -> None:
    # A schedule reverting to the old, buggy behaviour — pricing every date
    # off the whole-horizon union rather than that date's own symbols — is
    # still refused, per date, by apply_costs' own support check.
    gated = _gated_with(_LISTING_AND_DELISTING_VALUES)
    union = tuple(sorted({s for row in _LISTING_AND_DELISTING_VALUES.values() for s in row}))

    def dense_schedule(request: CostRequest) -> CostQuote:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={day: dict.fromkeys(union, 0.001) for day in request.gross_returns},
        )

    with pytest.raises(EvaluatorCostError, match="cross-section"):
        apply_costs(gated, dense_schedule, node_id="node_1", cost_model=_REF)


# -- Part 2: the orchestrator's own cost schedule closure, per date -----------


def test_cost_schedule_from_context_quotes_each_date_off_its_own_symbols() -> None:
    context = SimpleNamespace(
        cost_schedule=FeeSchedule(venue=_VENUE, taker_bps=12.5, maker_bps=12.5)
    )
    charges = _cost_schedule_from_context(context)

    request = CostRequest(
        node_id="node_1",
        venue=_VENUE,
        version=_VERSION,
        horizon=1,
        symbols=("AAA", "BBB", "CCC"),
        date_range=(_D0, _D1),
        gross_returns={
            _D0: {"AAA": 0.01, "BBB": -0.02},
            _D1: {"AAA": 0.02, "CCC": 0.03},
        },
    )
    quote = charges(request)

    assert set(quote.costs[_D0]) == {"AAA", "BBB"}
    assert set(quote.costs[_D1]) == {"AAA", "CCC"}
    fee = FeeSchedule(venue=_VENUE, taker_bps=12.5, maker_bps=12.5).fee_fraction(TAKER)
    assert quote.costs[_D0]["AAA"] == pytest.approx(fee)
    assert quote.costs[_D1]["CCC"] == pytest.approx(fee)


# -- Part 3: a live node, evaluated end to end over a listing and a delisting -


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_cost_pit_test_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _path_of(database_url: str) -> Path:
    from urllib.parse import unquote, urlparse

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


WORLD_SEED = 55667788
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-07-cost-pit"
EVALUATOR_HASH = "44" * 32
SNAPSHOT_HASH_FALLBACK = "55" * 32
COST_MODEL_HASH = "66" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeefa"

_FIRST_DAY = dt.date(2026, 9, 1)
_ALL_DAYS = tuple(_FIRST_DAY + dt.timedelta(days=i) for i in range(12))
_GONE_LAST_INDEX = 4
_LATE_FIRST_INDEX = 7
SYMBOL_DAYS: dict[str, tuple[dt.date, ...]] = {
    "ALWAYS1": _ALL_DAYS,
    "ALWAYS2": _ALL_DAYS,
    "GONE": _ALL_DAYS[: _GONE_LAST_INDEX + 1],
    "LATE": _ALL_DAYS[_LATE_FIRST_INDEX:],
}
#: Days 2..9 cross both transitions — inside GONE's window at the start,
#: inside LATE's at the end, and inside neither in the middle.
EVALUATION_DATES = _ALL_DAYS[2:10]

LATEST_CLOSE_SIGNAL_CODE = """
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


def _seal_world(
    workdir: Path, symbol_days: dict[str, tuple[dt.date, ...]], *, seed: int
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(seed)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol, days in symbol_days.items():
        price = 100.0 + generator.uniform(-20.0, 20.0)
        previous_return = 0.0
        path: dict[dt.date, float] = {}
        for day in days:
            shock = generator.gauss(0.0, 0.02)
            return_ = (
                AUTOCORRELATION * previous_return + (1.0 - AUTOCORRELATION) * shock
            )
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

    for symbol, days in symbol_days.items():
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

    service = SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the real branch over a varying
    per-date universe — the gate's own exact-support certification over a
    world that includes a listing and a delisting (the same stand-in
    ``test_pit_universe_per_date.py`` uses for the alignment-level claims;
    this suite drives it through to a full, priced evaluation).
    """

    def __init__(self, *, closes: dict[str, dict[dt.date, float]], resolution: Any) -> None:
        self._closes = closes
        self._resolution = resolution
        self.charges_budget = True
        self._grid = sorted({day for series in closes.values() for day in series})
        self._position = {day: index for index, day in enumerate(self._grid)}

    def post(self, request: Any) -> TargetResponse:
        first, last = request.date_range
        series: dict[dt.date, dict[str, float]] = {}
        day = first
        while day <= last:
            at = self._position.get(day)
            if at is not None:
                exit_at = at + request.horizon
                if exit_at < len(self._grid):
                    exit_day = self._grid[exit_at]
                    row = {}
                    for symbol in pit_universe(self._resolution, day):
                        if symbol not in request.symbols:
                            continue
                        entry_price = self._closes.get(symbol, {}).get(day)
                        exit_price = self._closes.get(symbol, {}).get(exit_day)
                        if entry_price is not None and exit_price is not None:
                            row[symbol] = exit_price / entry_price - 1.0
                    if row:
                        series[day] = row
            day += dt.timedelta(days=1)
        return TargetResponse(
            status=OK,
            node_id=request.node_id,
            target_series=series,
            charges_budget=self.charges_budget,
        )


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("cost-pit-world")
    return _seal_world(workdir, SYMBOL_DAYS, seed=WORLD_SEED)


@pytest.fixture
def context(tmp_path: Path, world: tuple[Any, dict]) -> EvaluationContext:
    mount, closes = world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'cost-pit.db'}"
    _migrate_tree(database_url)
    return EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=COST_MODEL_HASH,
        epoch_id=EPOCH_ID,
        database_url=database_url,
        artifact_dir=tmp_path / "artifacts",
        seed=WORLD_SEED,
        horizon=HORIZON,
        evaluation_dates=EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


def test_a_live_node_prices_and_evaluates_across_a_listing_and_a_delisting(
    world: tuple[Any, dict], context: EvaluationContext
) -> None:
    # The reproduction, reversed: before the fix this failed with
    # EvaluatorCostError naming a symbol the request's own cross-section
    # lacked on some dates (the bug evidence's own "gross_returns carries
    # ... [39 symbols, no HYPEUSDT], but the request's cross-section is
    # ... [40]").  With the per-date fix, the node prices and evaluates to
    # completion over a world with both a listing (LATE) and a delisting
    # (GONE) inside the evaluated grid.
    from evaluator import resolve_window

    mount, closes = world
    decision_time = dt.datetime.combine(
        EVALUATION_DATES[-1], dt.time(23, 59, tzinfo=dt.UTC)
    )
    resolution = resolve_window(mount, decision_time)

    node_id = str(uuid.uuid4())
    _plant_root(context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    endpoint = RecordingEndpoint(closes=closes, resolution=resolution)
    oracle = SubtreeOracle(endpoint, database_url=context.database_url)
    ledger = TrialLedger(context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        LATEST_CLOSE_SIGNAL_CODE,
        context=context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class is None, answer.fail_detail
    assert answer.metrics is not None
    assert answer.score.ic_mean is not None
    assert answer.persistence is not None and answer.persistence.artifact_written is True
