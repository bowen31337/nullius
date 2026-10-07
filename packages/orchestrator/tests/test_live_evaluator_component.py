"""Feature 8, the "live-evaluator" component.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 8:
*System creates a "live-evaluator" component, registered with @register in
orchestrator/__init__.py.  Its builder answers a LiveEvaluator whose
evaluate(node_id, campaign_id, depth, code) calls evaluate_node with the
loaded context, a SubtreeOracle over the "nulloracle-target-route"
component, and the "ledger" component.  It answers None when
load_evaluation_context() answers None.*  Features 2 through 7 each built
one seam; this feature is the one place they are named together, so the
suite exercises the two things only the registration can test — that the
builder resolves to the right shape from the right component name, and
that the shape it resolves to is the right thing only when called — and
reuses ``test_context.py``'s own ``live`` fixture approach rather than
re-inventing a sealed world, since the context this component loads is
exactly feature 5's.

One test per claim the feature sentence makes:

* **the component name and shape** — a scan of this member alone
  registers ``"live-evaluator"``, and the real workspace scan carries it
  too.

* **the answer, or None** — an unset ``NULLIUS_EVALUATION_CONFIG``
  answers ``None`` from the builder (and from the composed application);
  a set, valid one answers a :class:`~orchestrator.LiveEvaluator`
  wrapping exactly what :func:`~orchestrator.load_evaluation_context`
  itself would answer for the same environment.

* **a broken configuration is not softened to None** — a configured but
  invalid document raises :class:`~orchestrator.EvaluationConfigError`
  out of the builder (and therefore out of ``create_app()``), the same
  shape :func:`load_evaluation_context` itself raises.

* **the builder reads only the loader's own variables and evaluates
  nothing** — building the component calls
  :func:`~orchestrator.load_evaluation_context` and nothing else: it
  never calls :func:`~orchestrator.evaluate_node` and never resolves
  ``"nulloracle-target-route"`` or ``"ledger"``.

* **evaluate() wires the two siblings and forwards everything else** —
  :meth:`~orchestrator.LiveEvaluator.evaluate` resolves
  ``"nulloracle-target-route"`` and ``"ledger"`` from a fresh
  ``create_app()`` at call time, wraps the route in a
  :class:`~orchestrator.SubtreeOracle` bound to the loaded context's own
  ``database_url``, and calls :func:`~orchestrator.evaluate_node` with
  the node's own four arguments, the loaded context, that oracle and that
  ledger — read back from a patched ``evaluate_node`` rather than run for
  real, since the real chain is feature 7's own suite to exercise.

additions_spec_real_campaign_path.xml, "Campaign Evaluation Path", feature
4, extends the last claim above: *LiveEvaluator.evaluate builds the oracle
from the composed sidecar and that supply ... whenever the composed route
has no targets.  A composed route that does carry targets is used
unchanged.*  Two more tests, run for real (a migrated tree, a genuine
sidecar, a real sandbox spawn — the same shape
``tests/e2e/test_live_evaluation_end_to_end.py`` already proves for a
hand-wired route), exercise that extension:

* **a real node and a null node both evaluate to scored rows** when the
  composed ``"nulloracle-target-route"`` is nulloracle's own no-supply
  shape (``TargetEndpoint(sidecar, permute=...)``, no ``targets``) —
  :meth:`~orchestrator.LiveEvaluator.evaluate` answers a
  :class:`~orchestrator.NodeEvaluation` with real metrics for both, never
  the refusal that bare route would otherwise give on both branches alike.

* **the barrier holds** — asked identically (same symbols, horizon and
  date range) for the real root and the null root, the sidecar-backed
  oracle's two responses carry identical ``target_series`` keys; nothing
  about the response's shape names which branch answered it.

No test in this file opens a network connection, reads a real credential,
or writes outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import orchestrator
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from cost_model import FeeSchedule, load_cost_model
from ledger import TrialLedger
from nulloracle import (
    NullAssignment,
    NullSidecar,
    SidecarKey,
    TargetEndpoint,
    TargetRequest,
    block_indices,
)
from orchestrator import (
    EvaluationConfigError,
    EvaluationContext,
    LiveEvaluator,
    SubtreeOracle,
    load_evaluation_context,
    snapshot_forward_returns,
)
from snapshot import SnapshotService

from app.module_loader import Application, Registration, create_app

#: This member's ``src/`` — the scan root a test that wants *only* this
#: member's own registrations passes to ``create_app``, the same root
#: ``test_member.py`` derives.
MEMBER_SRC = Path(orchestrator.__file__).resolve().parent.parent

#: The component name the feature sentence names, spelled here rather
#: than read off the module, the same discipline ``test_member.py`` and
#: ``test_context.py`` hold for theirs: a name the code quietly dropped or
#: renamed is a failing test about *the feature text*.
COMPONENT_NAME = "live-evaluator"

#: The world the sealed snapshot carries — a single symbol over a short
#: span, the smallest shape ``load_evaluation_context`` will accept; this
#: suite never evaluates a node, so the world's only job is to make a
#: loadable context.
SYMBOLS = ("SYM00",)
FIRST_DAY = dt.date(2026, 9, 1)
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(8))
LOOKBACK = 4
EVALUATION_DAYS = tuple(
    day.isoformat() for day in BAR_DAYS[LOOKBACK : LOOKBACK + 2]
)
HORIZON = 1
SEED = 20261005
EPOCH = "epoch-2026-10-05-a"
ARTIFACT_DIR_NAME = "artifacts"
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32


def _close(day_index: int) -> float:
    return round(100.0 + 0.25 * day_index, 2)


def _stage_and_seal(lake_root: Path) -> Any:
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        for offset, day in enumerate(BAR_DAYS):
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
                        "close": [str(_close(offset))],
                        "volume": ["1.0"],
                    }
                ),
                partition / "part-0.parquet",
            )
    service = SnapshotService(lake_root)
    return service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))


class LiveWorld:
    """A loadable live-evaluation environment — the ``test_context.py``
    ``live`` fixture's own recipe, scaled down to the one job this suite
    needs it for: a ``NULLIUS_EVALUATION_CONFIG`` document that loads.
    """

    def __init__(self, environment: Mapping[str, str], document: Mapping[str, Any]):
        self.environment = dict(environment)
        self.document = dict(document)


@pytest.fixture
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveWorld:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _stage_and_seal(tmp_path / "lake")

    document = {
        "snapshot_mount": str(sealed.path),
        "evaluation_dates": list(EVALUATION_DAYS),
        "horizon": HORIZON,
        "seed": SEED,
        "epoch_id": EPOCH,
        "artifact_dir": str(tmp_path / ARTIFACT_DIR_NAME),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    config_path = tmp_path / "evaluation.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")

    database_url = f"sqlite:///{tmp_path / 'live-evaluator-test.db'}"
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": database_url,
        "NULLIUS_EVALUATOR_IMAGE": IMAGE,
    }
    return LiveWorld(environment, document)


def _assert_is_a_live_evaluator(component: object) -> None:
    """Pin a composed component by class name and module, not ``isinstance``.

    ``create_app`` imports this member under a synthetic module name on
    every call (``_nullius_scanned_orchestrator``), so a component it
    builds and the :class:`~orchestrator.LiveEvaluator` this file imports
    canonically are two distinct class objects — the same two-copies fact
    ``packages/canary/tests/test_component.py`` documents for its own
    component.  ``isinstance`` across the copies cannot hold, so identity
    is checked by name instead.
    """
    assert type(component).__name__ == "LiveEvaluator"
    assert type(component).__module__.endswith("orchestrator")


def _assert_raised_an_evaluation_config_error(error: BaseException) -> None:
    """The same cross-copy pin, for the exception a scanned build raises."""
    assert type(error).__name__ == "EvaluationConfigError"
    assert type(error).__module__.endswith("orchestrator._context")


def _apply_environment(
    monkeypatch: pytest.MonkeyPatch, environment: Mapping[str, str]
) -> None:
    """Point the process environment at ``environment`` — the builder's own
    source, since it calls the loader with ``env=None``.
    """
    for name in (
        "NULLIUS_EVALUATION_CONFIG",
        "DATABASE_URL",
        "NULLIUS_EVALUATOR_IMAGE",
        "NULLIUS_COST_MODEL_PATH",
        "NULLIUS_EVALUATOR_CONFIG",
    ):
        if name in environment:
            monkeypatch.setenv(name, environment[name])
        else:
            monkeypatch.delenv(name, raising=False)


# -- The component name and shape ------------------------------------------


def test_the_member_alone_registers_the_component(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_environment(monkeypatch, live.environment)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert isinstance(app, Application)
    assert COMPONENT_NAME in app
    assert COMPONENT_NAME in app.order
    _assert_is_a_live_evaluator(app.get(COMPONENT_NAME))


def test_the_full_workspace_carries_the_component() -> None:
    app = create_app()
    assert COMPONENT_NAME in app
    assert COMPONENT_NAME in app.order


# -- The answer, or None -----------------------------------------------------


def test_unconfigured_answers_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NULLIUS_EVALUATION_CONFIG", raising=False)
    assert orchestrator.build_live_evaluator() is None

    app = create_app(MEMBER_SRC, registry=Registration())
    assert COMPONENT_NAME in app
    assert app.get(COMPONENT_NAME) is None


def test_a_blank_variable_answers_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NULLIUS_EVALUATION_CONFIG", "  ")
    assert orchestrator.build_live_evaluator() is None


def test_a_configured_environment_answers_a_live_evaluator(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_environment(monkeypatch, live.environment)

    live_evaluator = orchestrator.build_live_evaluator()

    assert isinstance(live_evaluator, LiveEvaluator)
    assert isinstance(live_evaluator.context, EvaluationContext)
    # The builder's whole content is one call to the loader: the context
    # it wraps is exactly what a direct call answers for the very same
    # (process) environment.
    assert live_evaluator.context == load_evaluation_context()


# -- A broken configuration is not softened to None ---------------------------


def test_a_broken_configuration_raises_rather_than_degrading(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = dict(live.document)
    del broken["epoch_id"]
    config_path = Path(live.environment["NULLIUS_EVALUATION_CONFIG"])
    config_path.write_text(json.dumps(broken), encoding="utf-8")
    _apply_environment(monkeypatch, live.environment)

    with pytest.raises(EvaluationConfigError):
        orchestrator.build_live_evaluator()

    # create_app scans this member under a synthetic module name, so the
    # exception it raises is a distinct (but equivalently named) class —
    # pytest.raises(EvaluationConfigError) would not catch it.
    with pytest.raises(Exception) as record:
        create_app(MEMBER_SRC, registry=Registration())
    _assert_raised_an_evaluation_config_error(record.value)


# -- The builder reads only the loader's variables and evaluates nothing -----


def test_building_never_calls_evaluate_node(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_environment(monkeypatch, live.environment)

    def _must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("build_live_evaluator must evaluate nothing")

    monkeypatch.setattr(orchestrator, "evaluate_node", _must_not_run)

    live_evaluator = orchestrator.build_live_evaluator()

    assert isinstance(live_evaluator, LiveEvaluator)


def test_building_resolves_no_sibling_component(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_environment(monkeypatch, live.environment)

    def _must_not_compose(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(
            "build_live_evaluator must not resolve a sibling component"
        )

    monkeypatch.setattr("app.module_loader.create_app", _must_not_compose)

    live_evaluator = orchestrator.build_live_evaluator()

    assert isinstance(live_evaluator, LiveEvaluator)


# -- evaluate() wires the two siblings and forwards everything else ----------


class _FakeEndpoint:
    """The shape :class:`~orchestrator.SubtreeOracle` demands of an
    endpoint — a callable ``post`` — and nothing else, so wiring is
    verified by identity rather than by behaviour.
    """

    def post(self, request: Any) -> Any:  # pragma: no cover - never reached
        raise AssertionError("evaluate() must not call the endpoint directly")


def test_evaluate_resolves_siblings_at_call_time_and_forwards_to_evaluate_node(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply_environment(monkeypatch, live.environment)
    context = load_evaluation_context()
    assert context is not None
    live_evaluator = LiveEvaluator(context)

    fake_endpoint = _FakeEndpoint()
    fake_ledger = object()
    fake_app = Application(
        components={
            "nulloracle-target-route": fake_endpoint,
            "ledger": fake_ledger,
        }
    )
    monkeypatch.setattr("app.module_loader.create_app", lambda: fake_app)

    captured: dict[str, Any] = {}

    def _fake_evaluate_node(
        node_id: str,
        campaign_id: str,
        depth: int,
        code: str,
        *,
        context: EvaluationContext,
        oracle: Any,
        ledger: Any,
    ) -> str:
        captured.update(
            node_id=node_id,
            campaign_id=campaign_id,
            depth=depth,
            code=code,
            context=context,
            oracle=oracle,
            ledger=ledger,
        )
        return "sentinel"

    monkeypatch.setattr(orchestrator, "evaluate_node", _fake_evaluate_node)

    answer = live_evaluator.evaluate("node-1", "campaign-1", 2, "CODE")

    assert answer == "sentinel"
    assert captured["node_id"] == "node-1"
    assert captured["campaign_id"] == "campaign-1"
    assert captured["depth"] == 2
    assert captured["code"] == "CODE"
    assert captured["context"] is context
    assert captured["ledger"] is fake_ledger
    assert isinstance(captured["oracle"], SubtreeOracle)
    assert captured["oracle"].endpoint is fake_endpoint
    assert captured["oracle"].database_url == context.database_url


def test_evaluate_refuses_an_unconfigured_route(
    live: LiveWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Neither sibling's absence is evaluate()'s to soften: an unconfigured
    # nulloracle route answers None from the composed application, and
    # SubtreeOracle itself is what refuses a None endpoint.
    _apply_environment(monkeypatch, live.environment)
    context = load_evaluation_context()
    assert context is not None
    live_evaluator = LiveEvaluator(context)

    fake_app = Application(components={"ledger": object()})
    monkeypatch.setattr("app.module_loader.create_app", lambda: fake_app)

    from orchestrator._oracle import SubtreeOracleError

    with pytest.raises(SubtreeOracleError):
        live_evaluator.evaluate("node-1", "campaign-1", 0, "CODE")


# -- additions_spec_real_campaign_path.xml feature 4 ------------------------
# "LiveEvaluator.evaluate builds the oracle from the composed sidecar and
# that supply ... whenever the composed route has no targets."


#: Repository root, two levels above this member's own (``packages/<name>``
#: is one level above ``tests/``, the workspace root one more) — the same
#: derivation ``tests/e2e/test_live_evaluation_end_to_end.py`` makes for
#: reaching ``migrations/versions`` by path.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VERSIONS_DIR = _REPO_ROOT / "migrations" / "versions"

#: The node table's structural columns (0118), the metrics columns feature
#: 7's writer lands on it (0114), and the campaign row (0111) — the same
#: three migrations the e2e journey applies for the same reason.
_TREE_MIGRATIONS = ("0118_node_table", "0114_node_metrics", "0111_campaign_table")

#: Three symbols, a wide span of bar days — enough for a real cross-sectional
#: score and a real horizon-1 forward return. The span was widened from 3 to
#: 60 once step 10's six leakage tripwires started running for real inside
#: ``evaluate_node`` (additions_spec_tripwires_live.xml): the probes
#: standardize by √T, and at only 3 measured dates the honest momentum
#: signal below landed a false ``tripwire_fail`` by chance (label-permute)
#: — the same width ``test_evaluate.py`` pins its own momentum journey at,
#: for the same reason stated there.
_RC_SYMBOLS = ("AAA", "BBB", "CCC")
_RC_FIRST_DAY = dt.date(2026, 9, 10)
_RC_LOOKBACK = 4
_RC_SPAN = 60
_RC_HORIZON = 1
_RC_BAR_DAYS = tuple(
    _RC_FIRST_DAY + dt.timedelta(days=offset)
    for offset in range(_RC_LOOKBACK + _RC_SPAN + _RC_HORIZON)
)
_RC_EVALUATION_DATES = _RC_BAR_DAYS[_RC_LOOKBACK : _RC_LOOKBACK + _RC_SPAN]
_RC_WORLD_SEED = 20261006
_RC_EPOCH_ID = "epoch-2026-10-06-fallback-oracle"
_RC_EVALUATOR_HASH = "d4" * 32
_RC_SNAPSHOT_HASH_FALLBACK = "e5" * 32
_RC_COST_MODEL_HASH = "f6" * 32
_RC_CAMPAIGN_ID = "d00d0000-0000-4000-8000-000000000001"
_RC_REAL_ROOT = "d00d0000-0000-4000-8000-0000000000a0"
_RC_NULL_ROOT = "d00d0000-0000-4000-8000-0000000000b0"
_RC_REAL_CHILD = "d00d0000-0000-4000-8000-0000000000a1"
_RC_NULL_CHILD = "d00d0000-0000-4000-8000-0000000000b1"
_RC_KEY_HEX = "22" * 32

#: A deterministic momentum signal — the same shape
#: ``test_live_evaluation_end_to_end.py``'s own ``MOMENTUM_SIGNAL_CODE`` is,
#: scaled to this fixture's own lookback.
_RC_SIGNAL_CODE = f"""
import polars as pl

def signal(ctx, seed):
    bars = ctx.bars("1d")
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")
    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = frame.filter(pl.col("symbol") == symbol).sort("open_time")
        if len(series) < {_RC_LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[0]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


def _rc_closes() -> dict[str, dict[dt.date, float]]:
    """A random-walk world, the same AR(1) shape
    ``test_live_evaluation_end_to_end.py`` seals its own in — never a pure
    linear trend, whose day-to-day information coefficient would be
    identical on every date and leave ``ic_tstat`` dividing zero by zero.
    """
    import random

    generator = random.Random(_RC_WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol_index, symbol in enumerate(_RC_SYMBOLS):
        price = 100.0 + 10.0 * symbol_index
        path: dict[dt.date, float] = {}
        for day in _RC_BAR_DAYS:
            price = max(1.0, price * (1.0 + generator.gauss(0.0, 0.03)))
            path[day] = round(price, 2)
        closes[symbol] = path
    return closes


def _rc_load_migration(revision: str) -> ModuleType:
    path = _VERSIONS_DIR / f"{revision}.py"
    assert path.is_file(), path
    spec = importlib.util.spec_from_file_location(
        f"_live_evaluator_component_{revision}", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _rc_path_of(database_url: str) -> Path:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _rc_migrate(database_url: str) -> None:
    for revision in _TREE_MIGRATIONS:
        _rc_load_migration(revision).apply(database_url)


def _rc_plant_campaign(database_url: str) -> None:
    with closing(sqlite3.connect(_rc_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO campaign (id, campaign_type, workspace_count, null_fraction) "
            "VALUES (?, ?, ?, ?)",
            (_RC_CAMPAIGN_ID, "Type-R", 2, 0.5),
        )


def _rc_plant_node(
    database_url: str, *, node_id: str, parent_id: str | None, depth: int
) -> None:
    with closing(sqlite3.connect(_rc_path_of(database_url))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, parent_id, _RC_CAMPAIGN_ID, "macro", depth),
        )


def _rc_seal_the_world(workdir: Path) -> tuple[Any, dict[str, dict[dt.date, float]]]:
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    closes = _rc_closes()

    for symbol in _RC_SYMBOLS:
        for day in _RC_BAR_DAYS:
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
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 2, tzinfo=dt.UTC))
    mount = service.mount(sealed.name)
    return mount, closes


def _rc_permute(series: Any, *, seed: Any, block_days: Any) -> dict[Any, dict[str, float]]:
    """Feature 115's mechanism at the panel's grain, over the public primitive —
    the same reconciliation :func:`orchestrator._sidecar_backed_endpoint`
    makes internally, rebuilt here so this test depends on no private name.
    """
    days = list(series)
    rows = [series[day] for day in days]
    order = block_indices(range(len(days)), seed=seed, block_days=block_days)
    return {days[position]: dict(rows[order[position]]) for position in range(len(days))}


class _FallbackWorld:
    def __init__(
        self,
        *,
        context: EvaluationContext,
        sidecar: NullSidecar,
        ledger: TrialLedger,
        real_root: str,
        null_root: str,
        real_child: str,
        null_child: str,
    ) -> None:
        self.context = context
        self.sidecar = sidecar
        self.ledger = ledger
        self.real_root = real_root
        self.null_root = null_root
        self.real_child = real_child
        self.null_child = null_child


@pytest.fixture(scope="module")
def fallback_world(tmp_path_factory: pytest.TempPathFactory) -> _FallbackWorld:
    """A real tree, a real sidecar and a real sealed snapshot — no stand-ins.

    One campaign, two roots planted directly (never drawn by
    :class:`nulloracle.TypeRSelection`, so this fixture controls which root
    is null without depending on a seeded draw), one child each.  The
    sidecar is written once, directly, with both assignments — the same
    ``NullSidecar``/``NullAssignment`` seam
    ``tests/nulloracle/test_sidecar_persistence.py`` exercises.
    """
    workdir = tmp_path_factory.mktemp("fallback-oracle-world")
    mount, closes = _rc_seal_the_world(workdir)

    config = load_cost_model()
    schedule = FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)
    database_url = f"sqlite:///{workdir / 'fallback-oracle.db'}"
    _rc_migrate(database_url)

    context = EvaluationContext(
        snapshot=mount,
        closes=closes,
        cost_model=config,
        cost_schedule=schedule,
        evaluator_hash=_RC_EVALUATOR_HASH,
        snapshot_hash=_RC_SNAPSHOT_HASH_FALLBACK,
        cost_model_hash=_RC_COST_MODEL_HASH,
        epoch_id=_RC_EPOCH_ID,
        database_url=database_url,
        artifact_dir=workdir / "artifacts",
        seed=_RC_WORLD_SEED,
        horizon=_RC_HORIZON,
        evaluation_dates=_RC_EVALUATION_DATES,
        sandbox_runtime="unisolated",
    )
    ledger = TrialLedger(database_url)
    sidecar = NullSidecar(workdir / "null" / "sidecar.enc", SidecarKey.from_hex(_RC_KEY_HEX))
    sidecar.write(
        {
            _RC_REAL_ROOT: NullAssignment(
                node_id=_RC_REAL_ROOT, is_null=False, perm_seed=11, block_days=20
            ),
            _RC_NULL_ROOT: NullAssignment(
                node_id=_RC_NULL_ROOT, is_null=True, perm_seed=22, block_days=20
            ),
        }
    )

    _rc_plant_campaign(database_url)
    _rc_plant_node(database_url, node_id=_RC_REAL_ROOT, parent_id=None, depth=0)
    _rc_plant_node(database_url, node_id=_RC_NULL_ROOT, parent_id=None, depth=0)
    _rc_plant_node(
        database_url, node_id=_RC_REAL_CHILD, parent_id=_RC_REAL_ROOT, depth=1
    )
    _rc_plant_node(
        database_url, node_id=_RC_NULL_CHILD, parent_id=_RC_NULL_ROOT, depth=1
    )

    return _FallbackWorld(
        context=context,
        sidecar=sidecar,
        ledger=ledger,
        real_root=_RC_REAL_ROOT,
        null_root=_RC_NULL_ROOT,
        real_child=_RC_REAL_CHILD,
        null_child=_RC_NULL_CHILD,
    )


def test_evaluate_scores_both_a_real_and_a_null_node_when_the_route_has_no_targets(
    fallback_world: _FallbackWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nulloracle's own no-supply shape: TargetEndpoint(sidecar, permute=...),
    # no targets= — exactly what nulloracle.build_target_route always
    # builds, and the one the composed application always carries since
    # that member resolves no step-4 series of its own.
    bare_route = TargetEndpoint(fallback_world.sidecar, permute=_rc_permute)
    fake_app = Application(
        components={
            "nulloracle-target-route": bare_route,
            "nulloracle": fallback_world.sidecar,
            "ledger": fallback_world.ledger,
        }
    )
    monkeypatch.setattr("app.module_loader.create_app", lambda: fake_app)

    live_evaluator = LiveEvaluator(fallback_world.context)

    real_answer = live_evaluator.evaluate(
        fallback_world.real_child, _RC_CAMPAIGN_ID, 1, _RC_SIGNAL_CODE
    )
    null_answer = live_evaluator.evaluate(
        fallback_world.null_child, _RC_CAMPAIGN_ID, 1, _RC_SIGNAL_CODE
    )

    # A scored node, not a refusal — for both.
    assert real_answer.fail_class is None
    assert real_answer.metrics is not None
    assert null_answer.fail_class is None
    assert null_answer.metrics is not None


def test_the_sidecar_backed_oracles_responses_have_identical_keys(
    fallback_world: _FallbackWorld,
) -> None:
    # The barrier (PRD §4.2): asked identically for a real root and a null
    # root, the oracle's two responses carry the same shape — nothing in
    # the response could tell a caller which branch answered it.
    endpoint = TargetEndpoint(
        fallback_world.sidecar,
        targets=snapshot_forward_returns(fallback_world.context),
        permute=_rc_permute,
    )
    span = (_RC_EVALUATION_DATES[0], _RC_BAR_DAYS[-1])

    real_response = endpoint.post(
        TargetRequest(
            node_id=fallback_world.real_root,
            campaign_id=_RC_CAMPAIGN_ID,
            depth=0,
            horizon=_RC_HORIZON,
            symbols=_RC_SYMBOLS,
            date_range=span,
        )
    )
    null_response = endpoint.post(
        TargetRequest(
            node_id=fallback_world.null_root,
            campaign_id=_RC_CAMPAIGN_ID,
            depth=0,
            horizon=_RC_HORIZON,
            symbols=_RC_SYMBOLS,
            date_range=span,
        )
    )

    assert real_response.status == null_response.status
    assert real_response.target_series.keys() == null_response.target_series.keys()
    assert real_response.charges_budget is True
    assert null_response.charges_budget is False


# -- The module's surface -----------------------------------------------------


def test_the_module_s_surface() -> None:
    # The feature sentence's own list, exactly: the twelve names feature
    # 8 gathers from features 2 through 7, plus LiveEvaluator itself, plus
    # additions_spec_real_campaign_path.xml feature 4's forward-return
    # supply.
    expected = {
        "evaluate_node",
        "NodeEvaluation",
        "LiveEvaluator",
        "SubtreeOracle",
        "OracleTargetError",
        "NodeMetricsWriter",
        "ArtifactStoreWriter",
        "load_evaluation_context",
        "EvaluationContext",
        "EvaluationConfigError",
        "charge_node",
        "charge_failed_node",
        "snapshot_forward_returns",
    }
    assert set(orchestrator.__all__) == expected
    assert len(orchestrator.__all__) == len(set(orchestrator.__all__))
    for name in expected:
        assert hasattr(orchestrator, name), name
