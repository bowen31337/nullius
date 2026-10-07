"""PIT-1 — every rebalance date must be scored over *its own* universe.

bug_spec_pit_universe.xml, bug 1: *"Every rebalance date is scored over the
universe of the last evaluation date, so a symbol listed late in the window
breaks alignment for every signal."*  ``orchestrator._evaluate`` resolved the
window once at ``decision_time = evaluation_dates[-1]`` and then tagged
*every* rebalance date's :class:`~contract.window.MarketWindow` with
``resolution.universe`` — the symbols alive on the *last* date — so a symbol
listed partway through the evaluation grid (the reproduction's ``HYPEUSDT``,
first bar 2026-09-24) was scored on dates before it had a single bar, and
:func:`evaluator.align_targets` refused the whole node with
``EvaluatorAlignmentError``.  :func:`evaluator._execute._materialize_default`
carried the identical bug.

The fix is one helper, :func:`evaluator._execute.pit_universe`, applied by
both materializers: feature 72's admission rule — a symbol is tradable on a
day exactly when its sealed bars carry a partition dated that day — read per
rebalance date from the one resolution's own ``slices`` (no second snapshot
read), rather than once from the resolution's own decision date.

One test per claim this fix makes:

* **a late listing** — a symbol is absent from the window's universe before
  its first bar and present from it on, and a live evaluation over a world
  that includes one still aligns and scores (the reproduction, reversed).
* **a delisting** — a symbol stays in the universe on the earlier dates its
  bars cover and drops out after, without reviving as of the final date
  (survivorship is not reintroduced).
* **the rule, restated** — the per-date universe this fix computes agrees
  with :func:`evaluator.resolve_window` called fresh at that date — the same
  admission rule, read from the one resolution two different ways.
* **no extra reads** — across a whole evaluation's rebalance dates, the
  production materializer never re-reads a partition it already cached,
  never reads one dated after the day it is materializing, and never asks
  the mount for a fresh partition listing — the per-date question is
  answered entirely from the resolution already in hand.
* **a thin cross-section is absent, not a refusal** — a date whose per-date
  universe holds fewer than two symbols (normalize's own floor) scores
  nothing for that date rather than failing the node, the same treatment
  align_targets already gives a date it cannot align.

A note on scope: ``evaluator.apply_costs`` (step 7, unrelated to this bug and
to every file this fix touches) assumes a dense panel — the same symbol set
on every date a horizon covers — which a genuine listing or delisting
necessarily breaks downstream of alignment.  That is a separate, pre-existing
gap in step 7, not this bug, and nothing in ``touches_files`` licenses fixing
it here, so the "aligns and scores" claims below are checked at the layer
this bug actually broke — ``execute_signal`` and ``evaluator.align_targets``
(and, for the null gate's own exact-support certification, ``gate_targets``)
— rather than by asserting a full ``evaluate_node`` success that would
require step 7 to tolerate a varying cross-section too.

No test opens a network connection or writes outside a pytest temporary
directory, and none shares mutable state across tests, so the suite is safe
under pytest-xdist (the existing ``test_evaluate.py`` is this file's model
for both).
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
from cost_model import FeeSchedule, load_cost_model
from evaluator import (
    EvaluatorNormalizeError,
    align_targets,
    execute_signal,
    gate_targets,
    normalize_scores,
    resolve_window,
)
from evaluator._execute import pit_universe
from ledger import TrialLedger
from nulloracle.target import OK, TargetResponse
from orchestrator._context import BARS_STREAM, EvaluationContext
from orchestrator._evaluate import _materialize_from_context, evaluate_node
from orchestrator._oracle import SubtreeOracle
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
NODE_TABLE_MIGRATIONS = ("0118_node_table", "0114_node_metrics")

WORLD_SEED = 73737373
AUTOCORRELATION = 0.5
HORIZON = 1
EPOCH_ID = "epoch-2026-10-07-pit"
EVALUATOR_HASH = "11" * 32
SNAPSHOT_HASH_FALLBACK = "22" * 32
COST_MODEL_HASH = "33" * 32
CAMPAIGN_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeef"

#: The listing-and-delisting world: two symbols span every bar day, one
#: ("GONE") is delisted a third of the way through, and one ("LATE") is not
#: listed until two thirds of the way through — the reproduction's shape
#: (``HYPEUSDT``, listed partway through a snapshot sealed months earlier),
#: with a delisting folded into the same world so both of feature 72's
#: transitions are covered without a second sealed snapshot.
_LMD_FIRST_DAY = dt.date(2026, 9, 1)
_LMD_ALL_DAYS = tuple(_LMD_FIRST_DAY + dt.timedelta(days=i) for i in range(12))
_LMD_GONE_LAST_INDEX = 4  # GONE's bars: days 0..4
_LMD_LATE_FIRST_INDEX = 7  # LATE's bars: days 7..11
LMD_SYMBOL_DAYS: dict[str, tuple[dt.date, ...]] = {
    "ALWAYS1": _LMD_ALL_DAYS,
    "ALWAYS2": _LMD_ALL_DAYS,
    "GONE": _LMD_ALL_DAYS[: _LMD_GONE_LAST_INDEX + 1],
    "LATE": _LMD_ALL_DAYS[_LMD_LATE_FIRST_INDEX:],
}
LMD_GONE_LAST_DAY = _LMD_ALL_DAYS[_LMD_GONE_LAST_INDEX]
LMD_LATE_FIRST_DAY = _LMD_ALL_DAYS[_LMD_LATE_FIRST_INDEX]
#: Rebalance dates days 2..9 — inside GONE's live window at the start, inside
#: LATE's at the end, and inside neither in the middle (days 5..6, where only
#: the two always-present symbols remain) — so a single evaluation crosses
#: both transitions.
LMD_EVALUATION_DATES = _LMD_ALL_DAYS[2:10]

#: The thin-cross-section world: one symbol spans every bar day, a second is
#: listed only for the back half — so the evaluation's first few rebalance
#: dates have a one-symbol universe (normalize's own floor is two) and the
#: rest have two.
_DEGEN_FIRST_DAY = dt.date(2026, 9, 1)
_DEGEN_ALL_DAYS = tuple(_DEGEN_FIRST_DAY + dt.timedelta(days=i) for i in range(10))
_DEGEN_PAIR_FIRST_INDEX = 5
DEGEN_SYMBOL_DAYS: dict[str, tuple[dt.date, ...]] = {
    "SOLO": _DEGEN_ALL_DAYS,
    "PAIR": _DEGEN_ALL_DAYS[_DEGEN_PAIR_FIRST_INDEX:],
}
#: Days 1..8: four one-symbol dates (SOLO alone) followed by four two-symbol
#: dates (SOLO and PAIR both) — enough non-degenerate dates for
#: ``compute_node_metrics``'s own floor (at least two measured dates).
DEGEN_EVALUATION_DATES = _DEGEN_ALL_DAYS[1:9]

#: The score is simply the symbol's latest available close — no lookback
#: dependency, so a symbol with a single bar (the day it is listed, or the
#: day before it is delisted) scores exactly as well as one with a long
#: history.  ``ctx.universe`` is the window's own per-date admission list, so
#: a symbol iterated here is guaranteed at least one bar at or before the
#: decision time (feature 72's rule) — the fix this suite is for.
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
        if len(series) == 0:
            raise ValueError(f"{symbol} is in ctx.universe but has no bar")
        latest[symbol] = float(series[-1]["c"][0])
    return pl.Series([latest[symbol] for symbol in ctx.universe])
"""


# -- Migrations and raw-SQL planting, exactly test_evaluate.py's own recipe ----


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_pit_test_{revision}", path
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


# -- Sealing a world whose symbols cover different day ranges ------------------


def _seal_world(
    workdir: Path,
    symbol_days: dict[str, tuple[dt.date, ...]],
    *,
    seed: int,
) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    """Seal a snapshot where each symbol's bars span its own day range.

    The momentum e2e journey's own AR(1) recipe (also ``test_evaluate.py``'s
    ``_seal_the_world``), generalized to accept a *per-symbol* day range
    rather than one shared range — the one new ingredient a late listing and
    a delisting both need.
    """
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


# -- The oracle stand-in: the real-branch targets, computed the same way ------
# -- align_targets computes them, so the gate's own exact-support certify  ----
# -- (per date *and* per symbol, §7.2) passes over a world whose per-date  ----
# -- universe varies — the one thing test_evaluate.py's dense, gapless     ----
# -- world never needed, because its universe was every symbol, every day. ----


class RecordingEndpoint:
    """A fake ``TargetEndpoint`` answering the real (non-null) branch's targets.

    ``gate_targets`` certifies that an answer lives on *exactly* the aligned
    support, per date and per symbol (§7.2) — true of a real deployment's
    endpoint because it and ``align_targets`` both compute the same forward
    return from the same sealed closes.  This stand-in does the same: given
    the evaluation's own ``closes`` and its one ``resolution``, it rebuilds
    ``align_targets``' own market grid (the sorted union of every symbol's
    close dates) and steps ``horizon`` positions forward on it, filling a
    date's row only for the symbols :func:`evaluator._execute.pit_universe`
    admits *that date* — never the request's full, horizon-wide symbol
    union, which a world with a late listing or a delisting never has on
    every date at once.
    """

    def __init__(
        self,
        *,
        closes: dict[str, dict[dt.date, float]],
        resolution: Any,
        charges_budget: bool = True,
    ) -> None:
        self._closes = closes
        self._resolution = resolution
        self.charges_budget = charges_budget
        self.requests: list[Any] = []
        self._grid = sorted({day for series in closes.values() for day in series})
        self._position = {day: index for index, day in enumerate(self._grid)}

    def post(self, request: Any) -> TargetResponse:
        self.requests.append(request)
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


# -- A mount proxy that counts, rather than mocks, the structural surface -----


class _CountingMount:
    """Wraps a real :class:`snapshot.SnapshotMount`, counting its own calls.

    Exposes exactly the structural surface :func:`evaluator.resolve_window`
    and the materializer read (``name``, ``partitions``, ``dates``,
    ``select``) and forwards every call to the real mount, so the sealed
    bytes it answers are the genuine ones — only the call counts are new.
    ``current_day`` is set by the test immediately before each
    per-rebalance-date ``materialize`` call, so every recorded ``select``
    call can be checked against the day it was made for (no look-ahead) as
    well as deduplicated across the whole grid (no re-read).
    """

    def __init__(self, mount: Any) -> None:
        self._mount = mount
        self.current_day: dt.date | None = None
        self.calls: list[tuple[dt.date, str, str, str]] = []
        self.partitions_calls = 0
        self.dates_calls = 0

    @property
    def name(self) -> str:
        return self._mount.name

    def partitions(self, stream: str) -> tuple[str, ...]:
        self.partitions_calls += 1
        return self._mount.partitions(stream)

    def dates(self, stream: str, symbol: str) -> tuple[str, ...]:
        self.dates_calls += 1
        return self._mount.dates(stream, symbol)

    def select(self, stream: str, symbol: str, date: str) -> tuple[Any, ...]:
        assert self.current_day is not None, "set current_day before materializing"
        self.calls.append((self.current_day, stream, symbol, date))
        return self._mount.select(stream, symbol, date)


# -- Fixtures: the listing-and-delisting world ---------------------------------


@pytest.fixture(scope="module")
def lmd_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("pit-universe-lmd-world")
    return _seal_world(workdir, LMD_SYMBOL_DAYS, seed=WORLD_SEED)


@pytest.fixture
def lmd_resolution(lmd_world: tuple[Any, dict]) -> Any:
    """The one resolution a live evaluation builds — at the grid's last date."""
    mount, _ = lmd_world
    decision_time = dt.datetime.combine(
        LMD_EVALUATION_DATES[-1], dt.time(23, 59, tzinfo=dt.UTC)
    )
    return resolve_window(mount, decision_time)


@pytest.fixture
def lmd_context(tmp_path: Path, lmd_world: tuple[Any, dict]) -> EvaluationContext:
    mount, closes = lmd_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'pit-lmd.db'}"
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
        evaluation_dates=LMD_EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


# -- A late listing: absent before its first bar, present after ---------------


def test_a_late_listed_symbol_is_absent_before_its_first_bar_and_present_after(
    lmd_resolution: Any,
) -> None:
    for day in LMD_EVALUATION_DATES:
        universe = pit_universe(lmd_resolution, day)
        if day < LMD_LATE_FIRST_DAY:
            assert "LATE" not in universe, (
                f"LATE has no bar on {day.isoformat()} (its first is "
                f"{LMD_LATE_FIRST_DAY.isoformat()}) and must be absent"
            )
        else:
            assert "LATE" in universe, (
                f"LATE has a bar on {day.isoformat()} and must be admitted"
            )
    # Sanity: the transition genuinely happens inside the evaluated grid, or
    # this test would pass vacuously.
    assert LMD_EVALUATION_DATES[0] < LMD_LATE_FIRST_DAY < LMD_EVALUATION_DATES[-1]


# -- A delisting: present before its last bar, absent after, never revived ----


def test_a_delisted_symbol_stays_present_on_earlier_dates_and_drops_after(
    lmd_resolution: Any,
) -> None:
    for day in LMD_EVALUATION_DATES:
        universe = pit_universe(lmd_resolution, day)
        if day <= LMD_GONE_LAST_DAY:
            assert "GONE" in universe, (
                f"GONE has a bar on {day.isoformat()} (history is context, "
                "not pruned ahead of a later delisting) and must be admitted"
            )
        else:
            assert "GONE" not in universe, (
                f"GONE has no bar on {day.isoformat()} and must be absent — "
                "survivorship is not reintroduced by the resolution's own "
                "later decision date"
            )
    assert LMD_EVALUATION_DATES[0] <= LMD_GONE_LAST_DAY < LMD_EVALUATION_DATES[-1]
    # The resolution's own single decision date is the grid's last — GONE is
    # long delisted by then, so a bug that fell back to ``resolution.universe``
    # for every date would never admit GONE at all, on any date.
    assert "GONE" not in lmd_resolution.universe


# -- The rule, restated: pit_universe agrees with resolve_window itself -------


def test_the_per_date_universe_equals_feature_72s_admission_rule(
    lmd_world: tuple[Any, dict], lmd_resolution: Any
) -> None:
    # feature 72's rule is already proven by evaluator._window's own suite;
    # this asserts the two routes to it — resolving fresh at a date, and
    # reading pit_universe off the one resolution already sliced at the
    # grid's last date — never disagree.
    mount, _ = lmd_world
    for day in LMD_EVALUATION_DATES:
        fresh = resolve_window(
            mount, dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
        )
        assert pit_universe(lmd_resolution, day) == fresh.universe


# -- The node aligns and scores despite both transitions -----------------------


def test_execute_signal_and_align_targets_succeed_across_a_listing_and_a_delisting(
    lmd_world: tuple[Any, dict], lmd_context: EvaluationContext, lmd_resolution: Any
) -> None:
    # The reproduction, reversed: before the fix this raised
    # EvaluatorAlignmentError naming the late-listed symbol on the grid's
    # first date.  With the per-date universe, every rebalance date is
    # scored over exactly the symbols that have a bar that day, so alignment
    # never sees a symbol it has no close for.  Checked at the layer the bug
    # actually broke (execute_signal, align_targets, and the null gate's own
    # exact-support certification) rather than through a full evaluate_node
    # — see the module docstring's scope note on step 7's own, unrelated
    # dense-panel assumption.
    execution = execute_signal(
        lmd_resolution,
        LATEST_CLOSE_SIGNAL_CODE,
        seed=lmd_context.seed,
        rebalance_dates=LMD_EVALUATION_DATES,
        materialize=_materialize_from_context(lmd_context),
    )
    assert execution.dates() == LMD_EVALUATION_DATES
    for day in execution.dates():
        vector = execution.vector(day)
        assert vector.conforming, (day, vector.problems)
        assert vector.universe == pit_universe(lmd_resolution, day)

    alignment = align_targets(execution, lmd_context.closes)

    # gate_targets asks an evaluator.Oracle (OracleRequest in, OracleResponse
    # out); SubtreeOracle is feature 2's adapter from the nulloracle wire
    # shape to that seam, and it needs the node's row to walk to a root.
    node_id = str(uuid.uuid4())
    _plant_root(lmd_context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID)
    endpoint = RecordingEndpoint(closes=lmd_context.closes, resolution=lmd_resolution)
    oracle = SubtreeOracle(endpoint, database_url=lmd_context.database_url)
    gated = gate_targets(
        alignment,
        oracle,
        node_id=node_id,
        campaign_id=CAMPAIGN_ID,
        depth=0,
    )
    assert gated.charges_budget is True


# -- No extra reads: cached, never ahead of the day, resolution-only lookups --


def test_the_materializer_reads_no_partition_twice_or_ahead_of_its_day(
    lmd_world: tuple[Any, dict], lmd_resolution: Any
) -> None:
    mount, _ = lmd_world
    counting = _CountingMount(mount)
    materialize = _materialize_from_context(SimpleNamespace(snapshot=counting))

    for day in LMD_EVALUATION_DATES:
        counting.current_day = day
        decision_time = dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
        window = materialize(lmd_resolution, decision_time)
        assert window.universe == pit_universe(lmd_resolution, day)

    # No look-ahead: every select names a partition dated at or before the
    # day it was read for.
    for day, _stream, _symbol, iso in counting.calls:
        assert dt.date.fromisoformat(iso) <= day

    # No re-read: the same (stream, symbol, date) partition is never fetched
    # twice across the whole grid — the per-partition cache holds across
    # rebalance dates.
    pairs = [(stream, symbol, iso) for _, stream, symbol, iso in counting.calls]
    assert len(pairs) == len(set(pairs))

    # Correctness tied to the same efficiency: a symbol is never even asked
    # for outside the window its own bars admit it in.
    late_days = {day for day, _, symbol, _ in counting.calls if symbol == "LATE"}
    assert all(day >= LMD_LATE_FIRST_DAY for day in late_days)
    gone_days = {day for day, _, symbol, _ in counting.calls if symbol == "GONE"}
    assert all(day <= LMD_GONE_LAST_DAY for day in gone_days)

    # No extra snapshot read: the per-date question is answered entirely
    # from the resolution already in hand — the mount is never asked to
    # relist a stream's partitions or a symbol's dates.
    assert counting.partitions_calls == 0
    assert counting.dates_calls == 0
    assert BARS_STREAM == "bars"  # the stream every call above names


# -- A thin cross-section is absent, never a refusal ---------------------------


@pytest.fixture(scope="module")
def degenerate_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Any, dict]:
    workdir = tmp_path_factory.mktemp("pit-universe-degenerate-world")
    return _seal_world(workdir, DEGEN_SYMBOL_DAYS, seed=WORLD_SEED + 1)


@pytest.fixture
def degenerate_resolution(degenerate_world: tuple[Any, dict]) -> Any:
    mount, _ = degenerate_world
    decision_time = dt.datetime.combine(
        DEGEN_EVALUATION_DATES[-1], dt.time(23, 59, tzinfo=dt.UTC)
    )
    return resolve_window(mount, decision_time)


@pytest.fixture
def degenerate_context(
    tmp_path: Path, degenerate_world: tuple[Any, dict]
) -> EvaluationContext:
    mount, closes = degenerate_world
    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{tmp_path / 'pit-degenerate.db'}"
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
        seed=WORLD_SEED + 1,
        horizon=HORIZON,
        evaluation_dates=DEGEN_EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )


def test_a_date_with_fewer_than_two_symbols_is_skipped_not_refused(
    degenerate_context: EvaluationContext, degenerate_resolution: Any
) -> None:
    # The grid's first four dates have only SOLO in the per-date universe —
    # normalize_scores' own floor ("one symbol is not a cross-section").
    # Three things are checked: the floor is real (a bare call over one of
    # these thin dates' own raw scores does refuse); align_targets, which
    # never consulted that floor, does not refuse over the same dates either
    # (the bug's own wording: "never an alignment refusal for the node");
    # and evaluate_node's own fix — the scores loop this bug's companion
    # change added — never lets that refusal surface as the node's
    # fail_class (whatever evaluate_node's overall outcome, for the reason
    # the module docstring's scope note gives).
    pair_first_day = DEGEN_SYMBOL_DAYS["PAIR"][0]
    thin_dates = [d for d in DEGEN_EVALUATION_DATES if d < pair_first_day]
    scored_dates = [d for d in DEGEN_EVALUATION_DATES if d >= pair_first_day]
    assert len(thin_dates) >= 2 and len(scored_dates) >= 2, "fixture sanity"

    execution = execute_signal(
        degenerate_resolution,
        LATEST_CLOSE_SIGNAL_CODE,
        seed=degenerate_context.seed,
        rebalance_dates=DEGEN_EVALUATION_DATES,
        materialize=_materialize_from_context(degenerate_context),
    )
    thin_vector = execution.vector(thin_dates[0])
    assert thin_vector.universe == ("SOLO",)
    with pytest.raises(EvaluatorNormalizeError):
        normalize_scores(thin_vector.scores)

    # align_targets never raises over the thin dates — it has no floor on
    # cross-section size, only on there being a computable target somewhere.
    align_targets(execution, degenerate_context.closes)

    node_id = str(uuid.uuid4())
    _plant_root(
        degenerate_context.database_url, node_id=node_id, campaign_id=CAMPAIGN_ID
    )
    ledger = TrialLedger(degenerate_context.database_url)
    endpoint = RecordingEndpoint(
        closes=degenerate_context.closes, resolution=degenerate_resolution
    )
    oracle = SubtreeOracle(endpoint, database_url=degenerate_context.database_url)

    answer = evaluate_node(
        node_id,
        CAMPAIGN_ID,
        0,
        LATEST_CLOSE_SIGNAL_CODE,
        context=degenerate_context,
        oracle=oracle,
        ledger=ledger,
    )

    assert answer.fail_class not in ("EvaluatorNormalizeError", "EvaluatorAlignmentError")
