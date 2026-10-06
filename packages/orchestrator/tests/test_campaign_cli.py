"""Feature 7, the campaign CLI — ``python -m orchestrator.campaign``.

additions_spec_campaign_driver.xml, "Campaign Loop" category, feature 7:
*System runs a campaign from* ``python -m orchestrator.campaign --type TYPE
--workspaces W --rounds R [--width N] [--allowance UNITS]`` *and prints one
JSON line per emitted event, followed by the summary line.*  This suite
drives :func:`orchestrator.campaign.main` directly (the injectable seam the
feature names), never a real subprocess, and never a real
:func:`~app.module_loader.create_app` — every test hands ``main`` its own
``app`` (a real :class:`~app.module_loader.Application` built from fakes), so
no test reads an environment variable the host happens to carry or opens a
network connection.

Also "Campaign Close-out" category, feature 14: *System closes out every
campaign the campaign CLI finishes.*  Every test below this module's own
happy-path tests stubs :func:`orchestrator.closeout.main` the same way the
earlier tests in this file stub ``run_campaign`` — ``monkeypatch.setattr``
on the name :mod:`orchestrator.campaign` imported it under — rather than
standing up a real sidecar and scorer: this suite's job is the CLI's own
wiring (which campaign id close-out is called with, which exit code its own
answer becomes, and the skip this command takes for ``--no-closeout``), not
close-out's own calibration math, which :mod:`test_closeout_cli` already
covers.

One test per claim the feature sentence makes:

* **the three components are resolved from ``app`` and the policy is
  loaded** — a happy-path run over a throwaway, fully migrated SQLite
  database (the same fixture :mod:`test_campaign` uses) proves the CLI
  wires ``signal-author``, ``live-evaluator`` and
  ``nulloracle-type-r-selection`` into a real
  ``orchestrator._campaign.run_campaign`` call, with ``context`` read off
  the live-evaluator's own ``.context`` rather than loaded a second time.
* **a missing component refuses with exit 2 and one stderr line naming
  it** — each of the three, checked in the order the sentence names them.
* **a policy that cannot load refuses with exit 2** —
  ``NULLIUS_EXPLORATION_POLICY`` naming an unreadable file.
* **bad arguments exit 2 through argparse's own door** — a missing
  required flag.
* **a refusal raised mid-campaign exits 1, with its code word on
  stderr** — a root's authoring refusal, which feature 6 documents as
  propagating out of ``run_campaign`` uncaught.
* **every line is JSON, and the last is the summary ``run_campaign``
  itself emits** — exit 0 regardless of which ``stop_reason`` fired.
* **no credential is ever printed** — a stray secret riding in ``env``
  never reaches a line this command prints.
* **close-out runs after the summary line, on the finished campaign id,
  and its JSON line reaches the caller** — feature 14's own sentence.
* **a close-out refusal prints one stderr line and exits 1, with the
  campaign still recorded** — feature 14's named cause: the operator
  reruns ``python -m orchestrator.closeout`` once it is fixed.
* **a VOID verdict exits 3**.
* **``--no-closeout`` skips the step and says so on stderr**, without
  ever calling close-out.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import nulloracle
import providers
import pytest
import signal_agent
from orchestrator._policy import DEFAULT_BASELINE_WIDTH
from orchestrator.campaign import (
    CAMPAIGN_CLI_CODE,
    EXIT_CONFIG,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_VOID,
    LIVE_EVALUATOR_COMPONENT_NAME,
    main,
)
from orchestrator.closeout import EXIT_OK as CLOSEOUT_EXIT_OK
from orchestrator.closeout import EXIT_REFUSED as CLOSEOUT_EXIT_REFUSED
from orchestrator.closeout import EXIT_VOID as CLOSEOUT_EXIT_VOID
from policy_runtime import UNBOUNDED_BUDGET

from app.module_loader import Application

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is three parents up — the same resolution test_campaign.py,
# test_worker.py and test_roots.py use.
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
ROOT_TIER = providers.FrontierTier(
    providers=(providers.FrontierProvider(ROOT_PIN.provider, ROOT_PIN.model),)
)


def _load_migration(revision: str) -> ModuleType:
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(f"{revision} is not at {path}")
    spec = importlib.util.spec_from_file_location(
        f"_orchestrator_test_campaign_cli_{revision}", path
    )
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, fully migrated."""
    url = f"sqlite:///{tmp_path / 'campaign-cli-test.db'}"
    _load_migration(CAMPAIGN_MIGRATION).apply(url)
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


class _Context:
    """The subset of ``orchestrator._context.EvaluationContext`` run_campaign
    reads — the same six attributes :mod:`test_campaign`'s own fake carries."""

    def __init__(self, database_url: str, artifact_dir: Path) -> None:
        self.database_url = database_url
        self.evaluator_hash = hashlib.sha256(b"evaluator").hexdigest()
        self.snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
        self.cost_model_hash = hashlib.sha256(b"cost-model").hexdigest()
        self.artifact_dir = artifact_dir
        self.evaluation_dates = (dt.date(2026, 1, 2), dt.date(2026, 1, 3))


@pytest.fixture
def context(tree_database: str, tmp_path: Path) -> _Context:
    return _Context(tree_database, tmp_path / "artifacts")


# -- The fakes the three resolved components answer -----------------------------


class SequenceAuthor:
    """``author.author_root`` for planting, ``author(workspace)`` for expansion
    — the same fake :mod:`test_campaign` drives ``run_campaign`` with directly."""

    def __init__(self) -> None:
        self.root_calls: list[tuple[str, str, str]] = []

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
        import discovery

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
    def first_root_id(self) -> str:
        return self.root_calls[0][2]


class RefusingRootAuthor(SequenceAuthor):
    """Every root authoring call is refused — feature 6's own documented
    stance: the refusal propagates out of ``run_campaign`` uncaught."""

    def author_root(self, campaign_id: str, theme_root: str, *, root_id: Any) -> Any:
        self.root_calls.append((campaign_id, theme_root, str(root_id)))
        raise signal_agent.AuthoringRefusedError(
            "authoring_refused: the model's answer was shown the defect and "
            "refused again each time"
        )


class _LiveEvaluatorDouble:
    """The ``"live-evaluator"`` component's own two faces: ``.context`` (what
    this CLI reads ``run_campaign``'s ``context`` argument from) and
    ``.evaluate(node_id, campaign_id, depth, code)``."""

    def __init__(self, context: _Context, *, fail_class: str | None = None) -> None:
        self.context = context
        self.calls: list[tuple[Any, Any, Any, Any]] = []
        self._fail_class = fail_class
        self._score = signal_agent.ScoreRecord(
            ic_mean=0.1, ic_tstat=2.0, fail_class=fail_class
        )

    def evaluate(self, node_id: Any, campaign_id: Any, depth: Any, code: Any) -> Any:
        self.calls.append((node_id, campaign_id, depth, code))
        return SimpleNamespace(
            node_id=node_id,
            fail_class=self._fail_class,
            score=self._score,
            charges_budget=True,
        )


class FakeSidecarSelection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def persist(self, campaign_id: str) -> None:
        self.calls.append(campaign_id)


def _app(
    *,
    author: Any = "_absent",
    evaluator: Any = "_absent",
    sidecar_selection: Any = "_absent",
) -> Application:
    """A real :class:`~app.module_loader.Application` carrying exactly the
    three components this command resolves — omitting one (the
    ``"_absent"`` default) is how a test proves the missing-component
    refusal, and ``Application.get`` answers ``None`` for a key that was
    never carried at all, the same as a deployment that never composed it."""

    components: dict[str, Any] = {}
    if author != "_absent":
        components[signal_agent.SIGNAL_AUTHOR_COMPONENT_NAME] = author
    if evaluator != "_absent":
        components[LIVE_EVALUATOR_COMPONENT_NAME] = evaluator
    if sidecar_selection != "_absent":
        components[nulloracle.TYPE_R_COMPONENT_NAME] = sidecar_selection
    return Application(components=components, order=tuple(sorted(components)))


# -- The happy path: plant, seal, evaluate, expand to the round cap -------------


def test_the_cli_resolves_the_three_components_and_runs_the_campaign(
    context: _Context,
) -> None:
    # No NULLIUS_EXPLORATION_POLICY, so main() loads the real baseline
    # policy (unguarded, width DEFAULT_BASELINE_WIDTH).  This fake
    # evaluator never writes a node's ic_mean (the same stance
    # test_campaign.py's own FakeEvaluator takes), so the root the policy
    # would rank is never revealed and the round loop stops at no_batch
    # — a real, exercised stop_reason, and still exit 0 ("any
    # stop_reason"), which is the one fact this test is pinning: the
    # command wires create_app()'s three components and the policy loader
    # into a real run_campaign call, start to finish.
    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)
    lines: list[str] = []

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "2", "--width", "1", "--no-closeout"],
        env={},
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_OK
    assert sidecar.calls, "the Type-R seal must have run"
    assert len(author.root_calls) == 1
    assert len(evaluator.calls) >= 1

    events = [json.loads(line) for line in lines]
    assert events[0]["event"] == "root_planted"
    assert events[-1]["event"] == "summary"
    assert events[-1]["stop_reason"] == "no_batch"
    assert events[-1]["rounds_run"] == 0
    assert "manifest" in events[-1]


def test_every_emitted_line_is_json_and_the_summary_is_last(context: _Context) -> None:
    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)
    lines: list[str] = []

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1", "--width", "1", "--no-closeout"],
        env={},
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_OK
    assert lines, "at least the root_planted, node_evaluated and summary lines"
    for line in lines:
        parsed = json.loads(line)  # raises if any line is not valid JSON
        assert "event" in parsed
    assert json.loads(lines[-1])["event"] == "summary"


# -- A missing component refuses with exit 2, naming it --------------------------


def test_a_missing_signal_author_refuses_with_exit_2(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=None, evaluator=evaluator, sidecar_selection=sidecar)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_CONFIG
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "signal-author" in captured.err
    assert captured.err.startswith(CAMPAIGN_CLI_CODE)


def test_a_missing_live_evaluator_refuses_with_exit_2(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    author = SequenceAuthor()
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=None, sidecar_selection=sidecar)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_CONFIG
    captured = capsys.readouterr()
    assert LIVE_EVALUATOR_COMPONENT_NAME in captured.err
    # The root author must never be asked: the evaluator was checked and
    # refused before anything was planted.
    assert author.root_calls == []


def test_a_missing_type_r_selection_refuses_with_exit_2(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    app = _app(author=author, evaluator=evaluator, sidecar_selection=None)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_CONFIG
    captured = capsys.readouterr()
    assert nulloracle.TYPE_R_COMPONENT_NAME in captured.err
    assert author.root_calls == []


def test_the_first_missing_component_is_the_one_named(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    # Every component is missing; only "signal-author" (checked first) is
    # ever named — the command refuses before reaching the other two.
    app = _app(author=None, evaluator=None, sidecar_selection=None)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "signal-author" in captured.err
    assert LIVE_EVALUATOR_COMPONENT_NAME not in captured.err
    assert nulloracle.TYPE_R_COMPONENT_NAME not in captured.err


# -- A policy that cannot load refuses with exit 2 -------------------------------


def test_an_unloadable_policy_refuses_with_exit_2(
    context: _Context, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    missing_file = tmp_path / "no-such-policy.py"
    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={"NULLIUS_EXPLORATION_POLICY": str(missing_file)},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_CONFIG
    captured = capsys.readouterr()
    assert "policy_load" in captured.err
    assert author.root_calls == []


# -- Bad arguments exit 2 through argparse's own door ----------------------------


def test_missing_required_arguments_exit_2_through_argparse(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--type", "Type-D"])  # --workspaces and --rounds are required
    assert exit_info.value.code == 2


# -- A refusal raised mid-campaign exits 1, with its code word on stderr --------


def test_a_root_authoring_refusal_exits_1_with_its_code_word_on_stderr(
    context: _Context, capsys: pytest.CaptureFixture[str]
) -> None:
    author = RefusingRootAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert "authoring_refused" in captured.err
    # Nothing was sealed: the refusal happened before the Type-R seal.
    assert sidecar.calls == []


# -- Defaults: --width and --allowance, when the caller states neither ---------


def test_default_width_and_allowance_are_the_named_constants(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orchestrator.campaign as campaign_module

    captured: dict[str, Any] = {}

    def fake_run_campaign(**kwargs: Any) -> Any:
        captured.update(kwargs)
        kwargs["emit"]({"event": "summary", "campaign_id": "x", "stop_reason": "round_cap"})
        return SimpleNamespace(stop_reason="round_cap")

    monkeypatch.setattr(campaign_module, "run_campaign", fake_run_campaign)

    author = object()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = object()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    code = main(
        ["--type", "Type-D", "--workspaces", "3", "--rounds", "4", "--no-closeout"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_OK
    assert captured["campaign_type"] == "Type-D"
    assert captured["workspaces"] == 3
    assert captured["rounds"] == 4
    assert captured["width"] == DEFAULT_BASELINE_WIDTH
    assert captured["allowance"] == UNBOUNDED_BUDGET
    assert captured["author"] is author
    assert captured["evaluator"] is evaluator
    assert captured["context"] is evaluator.context
    assert captured["sidecar_selection"] is sidecar


def test_explicit_width_and_allowance_override_the_defaults(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orchestrator.campaign as campaign_module

    captured: dict[str, Any] = {}

    def fake_run_campaign(**kwargs: Any) -> Any:
        captured.update(kwargs)
        kwargs["emit"]({"event": "summary", "campaign_id": "x", "stop_reason": "round_cap"})
        return SimpleNamespace(stop_reason="round_cap")

    monkeypatch.setattr(campaign_module, "run_campaign", fake_run_campaign)

    app = _app(
        author=object(),
        evaluator=_LiveEvaluatorDouble(context),
        sidecar_selection=object(),
    )

    code = main(
        [
            "--type", "Type-R",
            "--workspaces", "2",
            "--rounds", "1",
            "--width", "5",
            "--allowance", "12.5",
            "--no-closeout",
        ],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_OK
    assert captured["width"] == 5
    assert captured["allowance"] == 12.5


# -- No credential is ever printed -----------------------------------------------


def test_no_credential_in_env_ever_reaches_a_printed_line(
    context: _Context,
) -> None:
    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    secret = "sk-super-secret-credential-should-never-print"
    lines: list[str] = []

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "1", "--width", "1", "--no-closeout"],
        env={"NULLIUS_EXPLORATION_POLICY": "", "NULLIUS_FAKE_API_KEY": secret},
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_OK
    assert all(secret not in line for line in lines)


# -- Feature 14: every finished campaign is closed out ---------------------------
#
# Each test below stubs ``orchestrator.closeout.main`` the way the tests above
# stub ``run_campaign`` — ``monkeypatch.setattr`` on the name this module
# imported it under — so no test here stands up a real sidecar, scorer or
# second database read. close-out's own calibration math is
# :mod:`test_closeout_cli`'s job; this suite only proves the campaign CLI's
# wiring onto it.


def test_close_out_runs_after_the_summary_line_and_its_json_line_is_displayed(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orchestrator.campaign as campaign_module

    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    recorded: dict[str, Any] = {}

    def fake_run_closeout(argv: list[str], *, env: Any, emit: Any) -> int:
        recorded["argv"] = list(argv)
        recorded["env"] = env
        emit(json.dumps({"campaign_id": argv[1], "calibration_status": "ok"}))
        return CLOSEOUT_EXIT_OK

    monkeypatch.setattr(campaign_module, "run_closeout", fake_run_closeout)

    env: dict[str, str] = {}
    lines: list[str] = []

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "2", "--width", "1"],
        env=env,
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_OK
    events = [json.loads(line) for line in lines]
    # The summary line is second-to-last now: close-out's own JSON line
    # follows it, the one this command displays after the campaign finished.
    assert events[-2]["event"] == "summary"
    campaign_id = events[-2]["campaign_id"]
    assert recorded["argv"] == ["--campaign-id", campaign_id]
    assert recorded["env"] is env
    assert events[-1] == {"campaign_id": campaign_id, "calibration_status": "ok"}


def test_a_close_out_refusal_exits_1_and_the_campaign_stays_recorded(
    context: _Context, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import orchestrator.campaign as campaign_module

    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    def fake_run_closeout(argv: list[str], *, env: Any, emit: Any) -> int:
        print(
            "closeout: the sidecar holds no entry for evaluated node",
            file=sys.stderr,
        )
        return CLOSEOUT_EXIT_REFUSED

    monkeypatch.setattr(campaign_module, "run_closeout", fake_run_closeout)

    lines: list[str] = []
    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "2", "--width", "1"],
        env={},
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_REFUSED
    captured = capsys.readouterr()
    assert captured.err.strip().count("\n") == 0, "one stderr line, close-out's own"
    assert "closeout" in captured.err
    # The campaign itself is recorded: it ran and sealed its Type-R draw
    # before close-out was ever attempted.
    assert sidecar.calls, "the Type-R seal must have run before close-out was attempted"
    events = [json.loads(line) for line in lines]
    assert events[-1]["event"] == "summary"


def test_a_void_verdict_exits_3(
    context: _Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    import orchestrator.campaign as campaign_module

    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    def fake_run_closeout(argv: list[str], *, env: Any, emit: Any) -> int:
        emit(json.dumps({"campaign_id": argv[1], "calibration_status": "void"}))
        return CLOSEOUT_EXIT_VOID

    monkeypatch.setattr(campaign_module, "run_closeout", fake_run_closeout)

    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "2", "--width", "1"],
        env={},
        app=app,
        emit=lambda line: None,
    )

    assert code == EXIT_VOID


def test_no_closeout_skips_the_step_and_says_so_on_stderr(
    context: _Context, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import orchestrator.campaign as campaign_module

    author = SequenceAuthor()
    evaluator = _LiveEvaluatorDouble(context)
    sidecar = FakeSidecarSelection()
    app = _app(author=author, evaluator=evaluator, sidecar_selection=sidecar)

    def fail_if_called(argv: list[str], *, env: Any, emit: Any) -> int:
        raise AssertionError("--no-closeout must never call close-out")

    monkeypatch.setattr(campaign_module, "run_closeout", fail_if_called)

    lines: list[str] = []
    code = main(
        ["--type", "Type-D", "--workspaces", "1", "--rounds", "2", "--width", "1", "--no-closeout"],
        env={},
        app=app,
        emit=lines.append,
    )

    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "no-closeout" in captured.err
    assert captured.err.startswith(CAMPAIGN_CLI_CODE)
    # No close-out line was ever displayed: the summary stays the last line.
    events = [json.loads(line) for line in lines]
    assert events[-1]["event"] == "summary"
