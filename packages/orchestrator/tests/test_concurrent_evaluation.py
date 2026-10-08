"""bug_spec_evaluation_throughput.xml, bug 2 — nodes evaluate concurrently.

A campaign used to evaluate every node one at a time — a plain serial
``for`` loop over the planted roots, and a round's children answered
through ``discovery.run_batch`` at a concurrency bound (``width``) that is
the campaign's own exploration-batch size, not a hardware fact. A 32-root
campaign on a 16-core host ran one gVisor sandbox at a time, at about 6%
CPU, because nothing bounded (or raised) the concurrency to the host's own
capacity.

The fix is an optional configuration key,
``orchestrator._context.EVALUATION_WORKERS_KEY`` (an int from 1 to 16,
default :data:`orchestrator._context.DEFAULT_EVALUATION_WORKERS`):
``orchestrator._campaign`` now evaluates every root, and dispatches a
round's children, on a thread pool bounded by this many concurrent slots —
each node still in its own sandbox (a fresh executor per
``evaluator.evaluate`` call, unaffected by this fix). Results are buffered
and released in the order a serial run would have produced them, not
completion order, so every persisted row and every emitted event is
identical regardless of how many slots actually ran.

One test per claim the fix makes:

* **evaluation_workers 1 and 4 produce identical persisted rows and
  identical event order** — the same proposal/score pairs and the same
  ``node_evaluated`` sequence, for the same eight roots, regardless of
  concurrency.
* **a round's child evaluations also release in deterministic (batch)
  order** — the same claim, one level down, where completion order would
  otherwise be reversed relative to submission order without the fix.
* **4 workers are at least 2.5x faster on 8 nodes with a sleeping stub
  executor** — the throughput claim the bug's own reproduction measured.
* **a raising node leaves its siblings evaluated** — every sibling already
  running when one node's evaluation raises is still persisted and
  emitted; only the raising node itself is dropped, and the exception
  still reaches the caller once every sibling has been handled.
* **two campaigns run concurrently never interleave their events** — each
  campaign's own emitted events name only its own campaign id.
* **out-of-range values are refused at config load** — evaluation_workers
  outside 1..16 (or not an int) raises
  :class:`orchestrator._context.EvaluationConfigError`, naming the key,
  both at the private validator and through the public
  :func:`orchestrator._context.load_evaluation_context` door.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory. Each test takes a fresh SQLite file
(never ``sqlite://`` in-memory) and no state is shared across tests or
threads except through the stub executor each test builds for itself, so
the suite is safe under pytest-xdist.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import discovery
import ledger
import providers
import pytest
import signal_agent
from orchestrator._campaign import (
    STOP_ROUND_CAP,
    CampaignResult,
    run_campaign,
)
from orchestrator._context import (
    DEFAULT_EVALUATION_WORKERS,
    EvaluationConfigError,
    _evaluation_workers,
    load_evaluation_context,
)
from policy_runtime import UNBOUNDED_BUDGET

# conftest-less suite: this file is under packages/orchestrator/tests, same
# resolution test_campaign.py uses for the repository root and migrations.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

CAMPAIGN_MIGRATION = "0111_campaign_table"
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
    "0114_node_metrics",
)

SOURCE = "def signal(ctx):\n    return ctx.close.pct_change(20)\n"
PROPOSAL = "Mechanism: fades crowded carry.\n```python\n" + SOURCE + "```\n"

ROOT_PIN = providers.ModelPin("deepseek", "deepseek-v4-flash", "20260910")
DEPTH_PIN = providers.ModelPin("anthropic", "claude-opus-5", "20260401")
SAMPLING = providers.AgentSampling(temperature=0.4, seed=7)
USAGE = providers.Usage(input_tokens=1_000, output_tokens=200)

#: A single-member frontier tier naming exactly ROOT_PIN's own family — the
#: same reasoning test_campaign.py's own ROOT_TIER gives: a tier of one
#: member is always assigned to itself, so every root in this suite records
#: cleanly regardless of the hash ``rotation_index`` draws.
ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the campaign and "
            "node tables' own migrations rather than hand-writing their DDL"
        )
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_concurrent_evaluation_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migrated_database(tmp_path: Path, label: str) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / f'{label}.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


def _prewarm_fail_class_column(database_url: str) -> None:
    """Add ``node.fail_class`` up front, serially, before any concurrent
    round-loop dispatch runs against this database.

    No migration declares this column — ``discovery.persist.AttemptLog``
    adds it lazily, itself, on its own first write
    (``_ensure_fail_class_column``'s own probe-then-``ALTER TABLE``). That
    probe has no guard against two threads both seeing the column absent
    at once: dispatching more than one first-ever ``AttemptLog.record``
    concurrently races two ``ALTER TABLE ... ADD COLUMN`` statements, and
    the loser raises ``sqlite3.OperationalError: duplicate column name``
    — a real, pre-existing concurrency defect in ``discovery.persist``,
    outside this bug's own file-claim scope
    (``packages/orchestrator/src/orchestrator/_campaign.py``,
    ``_context.py`` and this test file only) to fix.  Running the
    identical, idempotent ``ALTER TABLE`` here once, before this test's own
    concurrent dispatch starts, is what lets a round-loop test actually
    exercise this bug's own concurrency fix rather than tripping over an
    unrelated race in a module this bug does not touch.
    """
    import sqlite3
    from contextlib import closing

    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(node)")}
        if "fail_class" not in columns:
            with connection:
                connection.execute("ALTER TABLE node ADD COLUMN fail_class TEXT")


class _Context:
    """The subset of ``orchestrator._context.EvaluationContext`` this suite
    reads — ``test_campaign.py``'s own ``_Context``, plus
    ``evaluation_workers``, the one new attribute this bug's fix reads off
    it (``getattr``, so a context built without it still defaults — see
    ``test_campaign.py``'s own fakes, which never carry it either).
    """

    def __init__(
        self, database_url: str, artifact_dir: Path, *, evaluation_workers: int
    ) -> None:
        import hashlib

        self.database_url = database_url
        self.evaluator_hash = hashlib.sha256(b"evaluator").hexdigest()
        self.snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
        self.cost_model_hash = hashlib.sha256(b"cost-model").hexdigest()
        self.artifact_dir = artifact_dir
        self.evaluation_dates = (1,)  # live_question reads only len(); never a real date
        self.evaluation_workers = evaluation_workers


class RootAuthor:
    """``author.author_root`` for planting, ``author(workspace)`` for round-loop
    expansion — ``test_campaign.py``'s own ``SequenceAuthor``, restated here
    (this file's own self-contained-suite convention) since this bug's test
    also needs round-loop expansion, not root planting alone.
    """

    def __init__(self) -> None:
        self.root_calls: list[tuple[str, str, str]] = []
        self.expand_calls: list[Any] = []

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
        record = providers.AuthoringRecord(
            node_id=str(root_id),
            campaign_id=campaign_id,
            depth=0,
            role="root",
            pin=ROOT_PIN,
            sampling=SAMPLING,
            usage=USAGE,
            served_model=ROOT_PIN.model,
            tier=ROOT_TIER,
        )
        return SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )

    def __call__(self, workspace: Any) -> Any:
        self.expand_calls.append(workspace)
        child_id = discovery.refined_node_id(workspace.node_id)
        record = providers.AuthoringRecord(
            node_id=child_id,
            campaign_id=workspace.campaign_id,
            depth=workspace.depth + 1,
            role="depth",
            pin=DEPTH_PIN,
            sampling=SAMPLING,
            usage=USAGE,
            served_model=DEPTH_PIN.model,
        )
        return SimpleNamespace(
            code=SOURCE,
            stated_mechanism="Fades crowded carry.",
            proposal=PROPOSAL,
            record=record,
        )

    @property
    def root_ids(self) -> list[str]:
        return [call[2] for call in self.root_calls]


class FakeSidecarSelection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def persist(self, campaign_id: str) -> None:
        self.calls.append(campaign_id)


class EmptyBatchPolicy:
    """``policy.select`` is never asked when ``rounds=0`` — this is only a
    shape the signature needs, never actually called in that case."""

    def select(self, prefix_view: Any) -> list[str]:
        return []


class StagedPolicy:
    """Answers one pre-built batch per round — ``test_campaign.py``'s own,
    restated for the same self-contained-suite reason.
    """

    def __init__(self, stages: list[Callable[[], list[str]]]) -> None:
        self._stages = list(stages)
        self.calls = 0

    def select(self, prefix_view: Any) -> list[str]:
        batch = self._stages[self.calls]() if self.calls < len(self._stages) else []
        self.calls += 1
        return list(batch)


def _recording_emit() -> tuple[list[dict[str, Any]], Callable[[dict[str, Any]], None]]:
    events: list[dict[str, Any]] = []
    return events, events.append


class RecordingEvaluator:
    """A thread-safe stub ``evaluator`` — the stand-in this whole suite
    dispatches concurrently instead of a real sandbox.

    Each call appends to ``calls`` under a lock (so the list itself is
    never corrupted by concurrent appends) and tracks ``max_concurrent``,
    the highest number of calls ever in flight at once — the one figure
    that actually proves real parallelism rather than merely a working
    API. ``sleep_seconds`` may be a fixed float or a ``node_id -> float``
    callable, for a test that needs different nodes to finish in a
    different order than they were submitted. A ``node_id`` named in
    ``raising`` raises :class:`RuntimeError` instead of answering — every
    other node still answers normally.
    """

    def __init__(
        self,
        *,
        sleep_seconds: float | Callable[[str], float] = 0.0,
        raising: frozenset[str] = frozenset(),
    ) -> None:
        self._sleep = sleep_seconds
        self._raising = raising
        self._lock = threading.Lock()
        self.calls: list[tuple[Any, Any, Any, Any]] = []
        self._in_flight = 0
        self.max_concurrent = 0

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        with self._lock:
            self.calls.append((node_id, campaign_id, depth, code))
            self._in_flight += 1
            self.max_concurrent = max(self.max_concurrent, self._in_flight)
        try:
            duration = self._sleep(node_id) if callable(self._sleep) else self._sleep
            if duration:
                time.sleep(duration)
            if node_id in self._raising:
                raise RuntimeError(f"evaluation blew up for {node_id!r}")
            return SimpleNamespace(
                node_id=node_id,
                fail_class=None,
                score=signal_agent.ScoreRecord(ic_mean=0.1, ic_tstat=2.0, fail_class=None),
                charges_budget=True,
            )
        finally:
            with self._lock:
                self._in_flight -= 1


def _node_proposal_rows(database_url: str) -> dict[str, str]:
    """``{node_id: score_json}`` for every persisted proposal — a direct
    read of ``node_proposal`` (the table ``signal_agent.ProposalStore``
    writes), since that store answers no public reader of its own.
    """
    import sqlite3
    from contextlib import closing

    path = database_url.removeprefix("sqlite:///")
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute("SELECT node_id, score FROM node_proposal").fetchall()
    return dict(rows)


def _run_roots_only(
    tmp_path: Path,
    label: str,
    *,
    workspaces: int,
    evaluation_workers: int,
    evaluator: Any,
) -> tuple[CampaignResult, list[dict[str, Any]], RootAuthor, str]:
    """Plant ``workspaces`` roots and evaluate them — no round loop at all
    (``rounds=0``), so the only concurrency this exercises is the root
    evaluation this bug's fix adds.
    """
    database_url = _migrated_database(tmp_path, label)
    context = _Context(
        database_url, tmp_path / "artifacts", evaluation_workers=evaluation_workers
    )
    author = RootAuthor()
    events, emit = _recording_emit()
    result = run_campaign(
        campaign_type="Type-D",
        workspaces=workspaces,
        rounds=0,
        width=1,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=evaluator,
        policy=EmptyBatchPolicy(),
        context=context,
        sidecar_selection=FakeSidecarSelection(),
        emit=emit,
    )
    return result, events, author, database_url


def _normalized_events(events: list[dict[str, Any]], root_ids: list[str]) -> list[dict[str, Any]]:
    """Strip the one-off identities (``campaign_id``, the minted root ids)
    out of an event list, replacing a root id with its own planting
    position — the fact two separately-run campaigns can actually agree
    on, since ``uuid.uuid4()`` mints a fresh id every run.

    The ``summary`` event (whole-result restatement: ``roots``, ``nodes``,
    the manifest's own ``campaign_id``) is excluded rather than normalized
    — it carries nothing the ``result``-level assertions beside this helper
    do not already check directly, and normalizing its nested identities
    would just restate those same checks a second, more fragile way.
    """
    positions = {node_id: f"root-{index}" for index, node_id in enumerate(root_ids)}
    normalized = []
    for event in events:
        if event.get("event") == "summary":
            continue
        copy = dict(event)
        copy.pop("campaign_id", None)
        if copy.get("node_id") in positions:
            copy["node_id"] = positions[copy["node_id"]]
        normalized.append(copy)
    return normalized


# -- evaluation_workers 1 vs 4: identical persisted rows and event order --------


def test_evaluation_workers_one_and_four_produce_identical_results(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    # A small sleep gives the thread pool a measurable window to actually
    # overlap calls — without it, a near-instant stub could serialize by
    # scheduling luck alone and the max_concurrent assertion below would be
    # proving nothing.
    serial_evaluator = RecordingEvaluator(sleep_seconds=0.05)
    parallel_evaluator = RecordingEvaluator(sleep_seconds=0.05)

    result_1, events_1, author_1, db_1 = _run_roots_only(
        tmp_path_factory.mktemp("workers-1"),
        "workers-1",
        workspaces=8,
        evaluation_workers=1,
        evaluator=serial_evaluator,
    )
    result_4, events_4, author_4, db_4 = _run_roots_only(
        tmp_path_factory.mktemp("workers-4"),
        "workers-4",
        workspaces=8,
        evaluation_workers=4,
        evaluator=parallel_evaluator,
    )

    # Real concurrency actually happened at workers=4 and not at workers=1 —
    # otherwise the rest of this test would hold trivially for the wrong
    # reason (a pool that never actually overlapped two calls).
    assert serial_evaluator.max_concurrent == 1
    assert parallel_evaluator.max_concurrent > 1

    assert result_1.stop_reason == result_4.stop_reason == STOP_ROUND_CAP
    assert len(result_1.roots) == len(result_4.roots) == 8
    assert result_1.nodes == result_4.nodes == ()

    assert _normalized_events(events_1, author_1.root_ids) == _normalized_events(
        events_4, author_4.root_ids
    )

    # The proposal/score pairs this module itself writes (through
    # history_store.persist, under its own write lock) — set-equal by
    # planting position, since the node ids themselves differ between runs.
    rows_1 = _node_proposal_rows(db_1)
    rows_4 = _node_proposal_rows(db_4)
    assert len(rows_1) == len(rows_4) == 8
    by_position_1 = {
        f"root-{author_1.root_ids.index(node_id)}": score
        for node_id, score in rows_1.items()
    }
    by_position_4 = {
        f"root-{author_4.root_ids.index(node_id)}": score
        for node_id, score in rows_4.items()
    }
    assert by_position_1 == by_position_4

    # Neither run touched the ledger (this stub evaluator never debits
    # one) — set-equal, trivially, both empty.
    assert ledger.TrialLedger(db_1).rows() == ()
    assert ledger.TrialLedger(db_4).rows() == ()


# -- A round's child evaluations also release in deterministic order ------------


def test_a_rounds_child_evaluations_release_in_deterministic_batch_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Root ids are minted by run_campaign itself (uuid.uuid4()); pinned here
    # so the four children's own ids (a pure function of their parent's) are
    # known before the call, which is what lets the sleeping stub target a
    # specific child rather than a specific completion-order position.
    fixed_root_ids = [str(uuid.UUID(int=index + 1)) for index in range(4)]
    sequence = iter(fixed_root_ids)
    real_uuid4 = uuid.uuid4
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(next(sequence, str(real_uuid4()))))

    child_ids = [discovery.refined_node_id(root_id) for root_id in fixed_root_ids]
    # The first-submitted child sleeps longest, the last-submitted sleeps
    # almost nothing — without the deterministic-release fix, completion
    # order (and so event order) would come out reversed.
    durations = {child_ids[i]: 0.2 - (i * 0.04) for i in range(len(child_ids))}

    database_url = _migrated_database(tmp_path, "round-order")
    _prewarm_fail_class_column(database_url)
    context = _Context(database_url, tmp_path / "artifacts", evaluation_workers=4)
    author = RootAuthor()
    policy = StagedPolicy([lambda: list(fixed_root_ids)])
    events, emit = _recording_emit()

    result = run_campaign(
        campaign_type="Type-D",
        workspaces=4,
        rounds=1,
        width=4,
        allowance=UNBOUNDED_BUDGET,
        author=author,
        evaluator=RecordingEvaluator(sleep_seconds=lambda node_id: durations.get(node_id, 0.0)),
        policy=policy,
        context=context,
        sidecar_selection=FakeSidecarSelection(),
        emit=emit,
    )

    assert result.roots == tuple(fixed_root_ids)
    assert result.nodes == tuple(child_ids)
    assert result.stop_reason == STOP_ROUND_CAP

    node_events = [e for e in events if e["event"] == "node_evaluated"]
    child_events = [e for e in node_events if e["depth"] == 1]
    assert [e["node_id"] for e in child_events] == child_ids


# -- Throughput: 4 workers are at least 2.5x faster on 8 nodes ------------------


def test_four_workers_are_at_least_two_point_five_times_faster_on_eight_nodes(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    sleep_seconds = 0.25
    # Migrated once, outside the timed region: applying five migrations is
    # a fixed cost that has nothing to do with evaluation concurrency, and
    # timing it would dilute the speedup this test is actually measuring.
    # The two timed calls below each create their own fresh campaign (and
    # plant their own eight roots) against this one already-migrated file.
    tmp_path = tmp_path_factory.mktemp("perf")
    database_url = _migrated_database(tmp_path, "perf")

    def _timed(evaluation_workers: int) -> float:
        context = _Context(
            database_url, tmp_path / "artifacts", evaluation_workers=evaluation_workers
        )
        started = time.perf_counter()
        run_campaign(
            campaign_type="Type-D",
            workspaces=8,
            rounds=0,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=RootAuthor(),
            evaluator=RecordingEvaluator(sleep_seconds=sleep_seconds),
            policy=EmptyBatchPolicy(),
            context=context,
            sidecar_selection=FakeSidecarSelection(),
            emit=lambda _event: None,
        )
        return time.perf_counter() - started

    serial_seconds = _timed(1)
    parallel_seconds = _timed(4)

    assert serial_seconds / parallel_seconds >= 2.5, (
        f"serial={serial_seconds:.3f}s parallel={parallel_seconds:.3f}s: "
        "4 workers must be at least 2.5x faster than 1 on 8 sleeping nodes"
    )


# -- A raising node leaves its siblings evaluated --------------------------------


def test_a_raising_root_leaves_its_siblings_evaluated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_root_ids = [str(uuid.UUID(int=index + 1)) for index in range(8)]
    sequence = iter(fixed_root_ids)
    real_uuid4 = uuid.uuid4
    monkeypatch.setattr(uuid, "uuid4", lambda: uuid.UUID(next(sequence, str(real_uuid4()))))

    raising_id = fixed_root_ids[2]
    database_url = _migrated_database(tmp_path, "raising-root")
    context = _Context(database_url, tmp_path / "artifacts", evaluation_workers=4)
    author = RootAuthor()
    evaluator = RecordingEvaluator(raising=frozenset({raising_id}))
    events, emit = _recording_emit()

    with pytest.raises(RuntimeError, match=raising_id):
        run_campaign(
            campaign_type="Type-D",
            workspaces=8,
            rounds=0,
            width=1,
            allowance=UNBOUNDED_BUDGET,
            author=author,
            evaluator=evaluator,
            policy=EmptyBatchPolicy(),
            context=context,
            sidecar_selection=FakeSidecarSelection(),
            emit=emit,
        )

    # The pool had already started every sibling concurrently before the
    # raising root's own result was even read back, so every one of the
    # eight roots was actually evaluated — the raising root never cancelled
    # the seven dispatched alongside it.
    assert len(evaluator.calls) == 8
    assert {call[0] for call in evaluator.calls} == set(fixed_root_ids)

    # Every sibling on both sides of the raising root in planting order was
    # still persisted and emitted; only the raising root itself was
    # dropped.
    node_events = [e for e in events if e["event"] == "node_evaluated"]
    evaluated_ids = {e["node_id"] for e in node_events}
    assert evaluated_ids == set(fixed_root_ids) - {raising_id}
    assert raising_id not in evaluated_ids

    rows = _node_proposal_rows(database_url)
    assert set(rows) == set(fixed_root_ids) - {raising_id}


# -- Two concurrent campaigns never interleave their events ----------------------


def test_two_concurrent_campaigns_never_interleave_their_events(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    outcomes: dict[str, tuple[CampaignResult, list[dict[str, Any]]]] = {}
    # tmp_path_factory.mktemp is not meant to be called from more than one
    # thread at once (its own numbered-dir bookkeeping races under xdist) —
    # both directories are made here, serially, in the main thread, and
    # only handed to the background threads afterward.
    tmp_paths = {label: tmp_path_factory.mktemp(f"interleave-{label}") for label in ("a", "b")}

    def _run(label: str) -> None:
        result, events, _author, _db = _run_roots_only(
            tmp_paths[label],
            f"interleave-{label}",
            workspaces=4,
            evaluation_workers=4,
            evaluator=RecordingEvaluator(sleep_seconds=0.05),
        )
        outcomes[label] = (result, events)

    threads = [threading.Thread(target=_run, args=(label,)) for label in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    result_a, events_a = outcomes["a"]
    result_b, events_b = outcomes["b"]

    assert result_a.campaign_id != result_b.campaign_id
    assert len(result_a.roots) == len(result_b.roots) == 4

    campaign_ids_a = {event["campaign_id"] for event in events_a if "campaign_id" in event}
    campaign_ids_b = {event["campaign_id"] for event in events_b if "campaign_id" in event}
    assert campaign_ids_a == {result_a.campaign_id}
    assert campaign_ids_b == {result_b.campaign_id}


# -- The config: a default, and a refusal outside 1..16 -------------------------


def test_evaluation_workers_default_is_four_when_absent() -> None:
    assert _evaluation_workers({}, "x") == DEFAULT_EVALUATION_WORKERS
    assert DEFAULT_EVALUATION_WORKERS == 4


@pytest.mark.parametrize("value", [1, 16])
def test_evaluation_workers_boundary_values_are_accepted(value: int) -> None:
    # "an int from 1 to 16" names an inclusive range — both ends must be
    # accepted, not merely the values strictly between them.
    assert _evaluation_workers({"evaluation_workers": value}, "x") == value


@pytest.mark.parametrize("value", [0, -1, 17, 100, 1.5, "4", True, False])
def test_out_of_range_evaluation_workers_is_refused(value: Any) -> None:
    with pytest.raises(EvaluationConfigError) as record:
        _evaluation_workers({"evaluation_workers": value}, "x")
    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert "evaluation_workers" in message


def _minimal_document(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "snapshot_mount": str(tmp_path / "not-a-real-snapshot"),
        "evaluation_dates": ["2026-01-02"],
        "horizon": 1,
        "seed": 7,
        "epoch_id": "epoch-concurrent-eval",
        "artifact_dir": str(tmp_path / "artifacts"),
        "sandbox_runtime": "unisolated",
        "acknowledge_unisolated": True,
    }
    document.update(overrides)
    return document


def _environment(tmp_path: Path, document: dict[str, Any]) -> dict[str, str]:
    config_path = tmp_path / "evaluation-config.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")
    bwrap_dir = tmp_path / "bwrap-path"
    bwrap_dir.mkdir(exist_ok=True)
    bwrap = bwrap_dir / "bwrap"
    if not bwrap.exists():
        bwrap.write_text("#! /bin/sh\n", encoding="utf-8")
        bwrap.chmod(0o755)
    return {
        "NULLIUS_EVALUATION_CONFIG": str(config_path),
        "DATABASE_URL": f"sqlite:///{tmp_path / 'concurrent-eval.db'}",
        "NULLIUS_EVALUATOR_IMAGE": "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32,
        "PATH": str(bwrap_dir),
    }


def test_an_out_of_range_evaluation_workers_is_refused_through_config_load(
    tmp_path: Path,
) -> None:
    # evaluation_workers is read (and so refused, when out of range) before
    # the snapshot is ever mounted — snapshot_mount names a path that does
    # not exist, and the test still reaches the refusal this bug's fix
    # adds, never snapshot_mount's own.
    document = _minimal_document(tmp_path, evaluation_workers=32)

    with pytest.raises(EvaluationConfigError) as record:
        load_evaluation_context(_environment(tmp_path, document))

    message = str(record.value)
    assert message.startswith("evaluation_config:")
    assert "evaluation_workers" in message

