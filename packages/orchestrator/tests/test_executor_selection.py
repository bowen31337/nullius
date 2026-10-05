"""Feature 7 (Executor Selection): the signal executor, from the context.

additions_spec_gvisor_executor.xml, "Executor Selection", feature 7:
*System creates the signal executor from the evaluation context:
orchestrator._context.signal_sandbox(context) answers a GVisorSandbox for
sandbox_runtime "gvisor", or a HardenedSubprocessSandbox for "unisolated".*

One test per claim the feature sentence makes:

* **the type the runtime chooses** — ``signal_sandbox`` answers a
  :class:`~orchestrator._gvisor.GVisorSandbox` for ``"gvisor"`` (wired to
  the context's own ``gvisor_runtime_root``, ``gvisor_state_root`` and
  ``lake_roots``) or a
  :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox` for
  ``"unisolated"``.

* **the three extra keys "gvisor" needs** — ``gvisor_runtime_root``,
  ``gvisor_state_root`` and ``lake_roots`` are read from the evaluation
  configuration, and a document missing one of them refuses with
  :class:`~orchestrator._context.EvaluationConfigError` naming the key —
  checked, like the gate itself, before the snapshot or the cost model is
  ever touched.

* **``evaluate_node`` always passes ``signal_sandbox(context)`` to
  ``execute_signal``** — the evaluator's own default
  :class:`~evaluator.SignalSandbox` is never constructed for agent code.

* **the executor's own last result survives** — :class:`~evaluator.RawScoreVector`
  carries no ``fail_class`` or ``detail``, so a specific reported class
  (``"timeout"`` here) replaces the generic ``SandboxExecutionError`` name
  on ``NodeEvaluation.fail_class``; the one class the executor itself
  defines as a catch-all (``"crash"``) still maps to the generic name, the
  same literal string every existing orchestrator test (feature 7 of
  additions_spec_live_evaluation.xml) already pins for a signal that raises.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contract.window import MarketWindow
from cost_model import FeeSchedule, load_cost_model
from evaluator import SandboxResult, SignalSandbox
from ledger import TrialLedger
from orchestrator import _evaluate as evaluate_mod
from orchestrator._context import (
    GVISOR_RUNTIME_ROOT_KEY,
    GVISOR_STATE_ROOT_KEY,
    LAKE_ROOTS_KEY,
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
    signal_sandbox,
)
from orchestrator._evaluate import SandboxExecutionError, evaluate_node
from orchestrator._gvisor import GVisorSandbox
from orchestrator._hardened_sandbox import HardenedSubprocessSandbox
from orchestrator._oci_bundle import CHILD_BOOTSTRAP_PATH
from snapshot import SnapshotService

#: The marker for "this key is absent" — test_context.py's own idiom, local
#: here since this file builds its own, much smaller documents.
_OMIT = object()


# -- The three extra keys: refused by name, before the gate reads anything -----


def _gvisor_document(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """One ``"gvisor"`` configuration document — every required key present,
    with placeholder values for everything but ``sandbox_runtime`` and the
    three gVisor-only keys, since a missing-key refusal (the thing under
    test here) fires before any of the placeholders is ever read.
    """
    document: dict[str, Any] = {
        "snapshot_mount": str(tmp_path / "unreachable-snapshot"),
        "evaluation_dates": ["2026-01-01"],
        "horizon": 1,
        "seed": 1,
        "epoch_id": "epoch-placeholder",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "gvisor",
        GVISOR_RUNTIME_ROOT_KEY: str(tmp_path / "gvisor-runtime"),
        GVISOR_STATE_ROOT_KEY: str(tmp_path / "gvisor-state"),
        LAKE_ROOTS_KEY: [],
    }
    for key, value in overrides.items():
        if value is _OMIT:
            document.pop(key, None)
        else:
            document[key] = value
    return document


def _write_config(tmp_path: Path, document: dict[str, Any]) -> Path:
    path = tmp_path / f"evaluation-{abs(id(document))}.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _fake_runsc_dir(tmp_path: Path) -> Path:
    """A scratch directory holding an executable ``runsc`` — never a real,
    provisioned gVisor install (the same stand-in test_context.py's own
    ``live.runsc_path`` fixture uses), just enough for the gate's
    ``shutil.which`` check to succeed.
    """
    runsc_dir = tmp_path / "bin"
    runsc_dir.mkdir(exist_ok=True)
    runsc = runsc_dir / "runsc"
    runsc.write_text("#!/bin/sh\n", encoding="utf-8")
    runsc.chmod(0o755)
    return runsc_dir


@pytest.mark.parametrize(
    "key", [GVISOR_RUNTIME_ROOT_KEY, GVISOR_STATE_ROOT_KEY, LAKE_ROOTS_KEY]
)
def test_gvisor_refuses_a_missing_extra_key_by_name(
    tmp_path: Path, key: str
) -> None:
    runsc_dir = _fake_runsc_dir(tmp_path)
    config_path = _write_config(tmp_path, _gvisor_document(tmp_path, **{key: _OMIT}))
    environment = {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "PATH": str(runsc_dir),
    }

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(environment)

    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert key in message


def test_unisolated_needs_none_of_the_three_extra_keys(tmp_path: Path) -> None:
    # The conditional shape: "unisolated" builds no gVisor executor, so it
    # reads none of the three keys this feature adds — a document that
    # carries none of them (beyond the acknowledgement feature 5 already
    # requires) still loads past the gate, refusing only on the next thing
    # it is actually missing (DATABASE_URL, read right after), never on a
    # gVisor key that "unisolated" has no use for.
    document = _gvisor_document(tmp_path)
    for key in (GVISOR_RUNTIME_ROOT_KEY, GVISOR_STATE_ROOT_KEY, LAKE_ROOTS_KEY):
        document.pop(key, None)
    document["sandbox_runtime"] = "unisolated"
    document["acknowledge_unisolated"] = True
    config_path = _write_config(tmp_path, document)

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context({"NULLIUS_EVALUATION_CONFIG": str(config_path)})

    message = str(record.value)
    assert "DATABASE_URL" in message
    for key in (GVISOR_RUNTIME_ROOT_KEY, GVISOR_STATE_ROOT_KEY, LAKE_ROOTS_KEY):
        assert key not in message


# -- The type the runtime chooses -----------------------------------------------


def _bare_context(**overrides: Any) -> EvaluationContext:
    """An :class:`EvaluationContext` with placeholder values everywhere
    ``signal_sandbox`` does not look — it reads only ``sandbox_runtime``,
    ``gvisor_runtime_root``, ``gvisor_state_root`` and ``lake_roots``, so
    every other field here is a value never dereferenced by the function
    under test.
    """
    base: dict[str, Any] = {
        "snapshot": object(),
        "closes": {},
        "cost_model": None,
        "cost_schedule": None,
        "evaluator_hash": "ab" * 32,
        "snapshot_hash": "cd" * 32,
        "cost_model_hash": "ef" * 32,
        "epoch_id": "epoch-bare",
        "database_url": "sqlite:///:memory:",
        "artifact_dir": Path("/tmp/executor-selection-bare"),
        "seed": 1,
        "horizon": 1,
        "evaluation_dates": (dt.date(2026, 1, 1),),
        "sandbox_runtime": "unisolated",
    }
    base.update(overrides)
    return EvaluationContext(**base)


def test_signal_sandbox_answers_hardened_subprocess_sandbox_for_unisolated() -> None:
    executor = signal_sandbox(_bare_context(sandbox_runtime="unisolated"))
    assert isinstance(executor, HardenedSubprocessSandbox)
    assert executor.last_result is None


def test_signal_sandbox_answers_gvisor_sandbox_for_gvisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runsc_dir = _fake_runsc_dir(tmp_path)
    monkeypatch.setenv("PATH", str(runsc_dir))
    runtime_root = tmp_path / "runtime-root"
    state_root = tmp_path / "state-root"
    lake_root = tmp_path / "lake"

    # bug_spec_gvisor_bind_boot.xml: GVisorSandbox now verifies at
    # construction that the runtime root already carries the child
    # bootstrap baked in (never bind-mounted) — a stub file is enough here,
    # since this test never actually runs a signal through it.
    child_path = runtime_root / CHILD_BOOTSTRAP_PATH.lstrip("/")
    child_path.parent.mkdir(parents=True, exist_ok=True)
    child_path.write_text("", encoding="utf-8")

    context = _bare_context(
        sandbox_runtime="gvisor",
        gvisor_runtime_root=runtime_root,
        gvisor_state_root=state_root,
        lake_roots=(lake_root,),
    )
    executor = signal_sandbox(context)

    assert isinstance(executor, GVisorSandbox)
    assert executor.runtime_root == runtime_root
    assert executor.state_root == state_root.resolve()
    assert executor.lake_roots == (lake_root,)
    assert executor.last_result is None


# -- The executor's own last result, read past what RawScoreVector drops -------

_UNIVERSE = ("AAA", "BBB")


def _window(universe: tuple[str, ...] = _UNIVERSE) -> MarketWindow:
    t = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    frames = {"bars": pa.table({sym: [1.0] for sym in universe})}
    return MarketWindow(t, universe=universe, frames=frames)


_BENIGN_SIGNAL_CODE = """
import polars as pl


def signal(ctx, seed):
    return pl.Series([0.0 for _ in ctx.universe])
"""


def test_signal_sandbox_remembers_its_own_last_result() -> None:
    # RawScoreVector drops fail_class/detail entirely; this attribute is
    # the one place either survives past execute_signal returning.
    executor = signal_sandbox(_bare_context(sandbox_runtime="unisolated"))
    assert executor.last_result is None

    result = executor.run(_BENIGN_SIGNAL_CODE, _window(), seed=1)

    assert isinstance(result, SandboxResult)
    assert executor.last_result is result
    assert result.fail_class is None


# -- evaluate_node always uses it, and reads its last result -------------------

DAY = dt.date(2026, 9, 1)


def _seal_minimal_snapshot(tmp_path: Path) -> Any:
    """The smallest sealed snapshot ``resolve_window`` will resolve: one bar,
    one symbol, on the only day this suite's contexts ever evaluate.
    """
    lake_root = tmp_path / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    partition = (
        lake_root / "staging" / "bars" / "symbol=AAA" / f"date={DAY.isoformat()}"
    )
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["AAA"],
                "open_time": [dt.datetime.combine(DAY, dt.time(0), tzinfo=dt.UTC)],
                "close": ["100.0"],
                "volume": ["1.0"],
            }
        ),
        partition / "part-0.parquet",
    )
    service = SnapshotService(lake_root)
    sealed = service.seal(
        sealed_at=dt.datetime.combine(DAY, dt.time(12), tzinfo=dt.UTC)
    )
    return service.mount(sealed.name)


@pytest.fixture
def context(tmp_path: Path) -> EvaluationContext:
    mount = _seal_minimal_snapshot(tmp_path)
    cost_model = load_cost_model()
    cost_schedule = FeeSchedule(venue=cost_model.venue, taker_bps=10.0, maker_bps=10.0)
    return EvaluationContext(
        snapshot=mount,
        closes={},
        cost_model=cost_model,
        cost_schedule=cost_schedule,
        evaluator_hash="ab" * 32,
        snapshot_hash="cd" * 32,
        cost_model_hash="ef" * 32,
        epoch_id="epoch-executor-selection",
        database_url=f"sqlite:///{tmp_path / 'executor-selection.db'}",
        artifact_dir=tmp_path / "artifacts",
        seed=1,
        horizon=1,
        evaluation_dates=(DAY,),
        sandbox_runtime="unisolated",
    )


@pytest.fixture
def ledger(context: EvaluationContext) -> TrialLedger:
    return TrialLedger(context.database_url)


@dataclass
class _FakeExecutor:
    """A duck-typed stand-in for ``signal_sandbox(context)``'s own answer:
    the same ``run(code, window, *, seed)`` shape, a canned
    :class:`~evaluator.SandboxResult`, and the ``last_result`` attribute
    :func:`orchestrator._context.signal_sandbox` always attaches.
    """

    fail_class: str
    detail: str
    calls: int = 0
    last_result: SandboxResult | None = None

    def run(self, code: str, window: object, *, seed: int) -> SandboxResult:
        self.calls += 1
        result = SandboxResult(
            scores=None,
            problems=[],
            fail_class=self.fail_class,
            detail=self.detail,
            seed=seed,
            contract_version="",
        )
        self.last_result = result
        return result


#: A signal with no imports and no behaviour: the fake executor's run()
#: ignores both code and window, so all this needs to do is pass the import
#: screen that runs before any executor is even built.
_NEUTRAL_CODE = "def signal(ctx, seed):\n    pass\n"


def test_evaluate_node_always_passes_signal_sandbox_to_execute_signal(
    context: EvaluationContext, ledger: TrialLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeExecutor(fail_class="timeout", detail="wall-clock exceeded")
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: fake)

    captured: dict[str, Any] = {}
    real_execute_signal = evaluate_mod.execute_signal

    def spy(*args: Any, **kwargs: Any) -> Any:
        captured["sandbox"] = kwargs.get("sandbox")
        return real_execute_signal(*args, **kwargs)

    monkeypatch.setattr(evaluate_mod, "execute_signal", spy)

    def _refuse_construction(self: Any, *args: Any, **kwargs: Any) -> None:
        raise AssertionError(
            "evaluator.SignalSandbox must never be constructed for agent code"
        )

    monkeypatch.setattr(SignalSandbox, "__init__", _refuse_construction)

    evaluate_node(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=None,
        ledger=ledger,
    )

    assert fake.calls == 1
    assert captured["sandbox"] is fake


def test_evaluate_node_reads_fail_class_from_the_executor_s_last_result(
    context: EvaluationContext, ledger: TrialLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _FakeExecutor(
        fail_class="timeout", detail="signal exceeded the wall-clock limit"
    )
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: fake)

    answer = evaluate_node(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=None,
        ledger=ledger,
    )

    assert answer.fail_class == "timeout"
    assert answer.score.fail_class == "timeout"
    assert answer.metrics is None
    assert answer.persistence is None
    assert answer.debit.appended is True


def test_evaluate_node_keeps_the_generic_class_for_a_crash(
    context: EvaluationContext, ledger: TrialLedger, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "crash" is the executor's own catch-all ("the signal raised or the
    # child died to a limit") — exactly the shape the generic
    # SandboxExecutionError name already covers, so it is not narrowed; the
    # same literal string feature 7 of additions_spec_live_evaluation.xml
    # already pins for a signal that raises.
    fake = _FakeExecutor(fail_class="crash", detail="signal raised: boom")
    monkeypatch.setattr(evaluate_mod, "signal_sandbox", lambda ctx: fake)

    answer = evaluate_node(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        0,
        _NEUTRAL_CODE,
        context=context,
        oracle=None,
        ledger=ledger,
    )

    assert answer.fail_class == SandboxExecutionError.__name__
