"""The evaluation canary's real wiring -- ``python -m orchestrator.canary_cli``.

bug_spec_evaluation_canary_unwired.xml, bug 2. Feature 5 of
``additions_spec_dreaming_m3.xml`` (274b72f) added ``evaluate_node``,
``replay_policy`` and ``evaluation_config_sha256`` as seams on
:func:`canary.run.main` and had ``require_dreaming_allowed`` refuse a pass
that did not include the evaluation canary -- but nothing in the workspace
ever supplied them: ``./run.sh canary`` ran ``python -m canary.run``, whose
own ``__main__`` calls ``main()`` with none. So no canary run could ever
record ``evaluation_canary=1``, and ``./run.sh dream`` was refused forever
for a stale or missing evaluation-canary pass -- the reported defect.

This suite drives :mod:`orchestrator.canary_cli`'s ``main`` in-process over
a stub evaluation context and stub scorers -- never a real sandbox, never a
sealed snapshot, never a subprocess -- and pins what the wiring has to be:

* **both evaluators and the config sha reach** :func:`canary.run.main` --
  captured here by swapping the module's own ``canary_run`` reference, so
  the real canary is neither called nor mutated.
* **each evaluator call gets a distinct**
  :class:`orchestrator._financial_eval.FinancialEvalContext` -- the per-run
  cache's lifetime *is* the instance's, so a nightly re-evaluation that
  reused one would answer from memory instead of measuring.
* **the replay scores** ``deploy/dreaming/incumbent.m2.py``'s source over
  the campaign the evaluator was handed.
* **no evaluation config, or one with no ``oos_dates``, passes no
  evaluators** -- canary.run's own refusals and its toy-only behaviour apply
  unchanged there.

No test opens a network connection, starts a sandbox, reads a real
credential or keeps state at module scope, so the suite passes under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from canary import run as canary_run
from orchestrator import _financial_eval, canary_cli
from orchestrator._context import EVALUATION_CONFIG_ENV
from orchestrator.dream import M2_INCUMBENT_PATH

#: The fixture evaluation configuration this suite names in the environment --
#: only ever *hashed* here (the loaded context is the suite's own stub), the
#: same shape ``test_dream_financial_worlds.py`` pins the config digest with.
EVALUATION_CONFIG_BYTES = b'{"pinned": "canary-cli-fixture-config"}\n'

#: The campaign and node the frozen evaluation reference names. The node
#: evaluator is stubbed, so neither id is ever read from a store.
CAMPAIGN_ID = "canary-campaign"
NODE_ID = "canary-node"


def _config_path(tmp_path: Path) -> Path:
    path = tmp_path / "evaluation-config-archive-perp-bn.json"
    path.write_bytes(EVALUATION_CONFIG_BYTES)
    return path


def _config_sha256() -> str:
    return hashlib.sha256(EVALUATION_CONFIG_BYTES).hexdigest()


def _stub_context(oos_dates: tuple[dt.date, ...] = (dt.date(2026, 6, 1),)) -> Any:
    """A duck-typed stand-in for a loaded
    :class:`orchestrator._context.EvaluationContext`.

    ``canary_cli`` reads exactly one field off it -- ``oos_dates``, the
    presence of which decides whether the evaluation canary is wired at all
    -- and hands it to :class:`orchestrator._financial_eval.
    FinancialEvalContext`, whose own two collaborators are stubbed in every
    test here, so no other field is ever reached.
    """
    return SimpleNamespace(oos_dates=oos_dates)


def _env(url: str, config: Path | None) -> dict[str, str]:
    env = {
        canary_run.DATABASE_URL_ENV: url,
        canary_run.EVALUATION_CAMPAIGN_ID_ENV: CAMPAIGN_ID,
        canary_run.EVALUATION_NODE_ID_ENV: NODE_ID,
    }
    if config is not None:
        env[EVALUATION_CONFIG_ENV] = str(config)
    return env


def _capture_canary_main(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``canary_cli``'s ``canary_run`` with one that records its call.

    Swaps the *reference this module holds*, never ``canary.run.main``
    itself: the real canary is neither run (no store, no freeze) nor mutated
    for any test that runs afterwards.
    """
    captured: dict[str, Any] = {}

    def _main(*args: Any, **kwargs: Any) -> int:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return canary_run.EXIT_OK

    monkeypatch.setattr(canary_cli, "canary_run", SimpleNamespace(main=_main))
    return captured


def _record_financial_contexts(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record every :class:`FinancialEvalContext` ``canary_cli`` builds.

    The real dataclass is still constructed -- only the *name* this module
    looks it up under is wrapped -- so the object a stub scorer receives is
    a genuine :class:`~orchestrator._financial_eval.FinancialEvalContext`.
    """
    built: list[Any] = []
    real = _financial_eval.FinancialEvalContext

    def _factory(*args: Any, **kwargs: Any) -> Any:
        built.append(real(*args, **kwargs))
        return built[-1]

    monkeypatch.setattr(canary_cli, "FinancialEvalContext", _factory)
    return built


def test_main_wires_both_evaluators_and_the_config_sha_into_canary_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_path(tmp_path)
    env = _env(f"sqlite:///{tmp_path / 'canary.db'}", config)
    context = _stub_context()
    monkeypatch.setattr(canary_cli, "load_evaluation_context", lambda env=None: context)

    built = _record_financial_contexts(monkeypatch)

    node_calls: list[tuple[str, str, Any]] = []

    def _oos_ir(node_id: str, *, campaign_id: str, context: Any) -> float:
        node_calls.append((node_id, campaign_id, context))
        return 0.42

    monkeypatch.setattr(canary_cli, "_oos_ir", _oos_ir)

    replay_calls: list[tuple[str, str, Any]] = []

    def _score_on_financial_world(
        source: str, campaign_id: str, *, context: Any
    ) -> Any:
        replay_calls.append((source, campaign_id, context))
        return SimpleNamespace(score=0.77)

    monkeypatch.setattr(
        canary_cli, "score_on_financial_world", _score_on_financial_world
    )

    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main(["--freeze-reference"], env=env) == canary_run.EXIT_OK

    kwargs = captured["kwargs"]
    assert kwargs["env"] is env
    assert captured["args"][0] == ["--freeze-reference"]
    assert kwargs["evaluation_config_sha256"] == _config_sha256()
    assert kwargs["evaluate_node"] is not None
    assert kwargs["replay_policy"] is not None

    # The node half: the stored node's out-of-sample IR, through _oos_ir.
    assert kwargs["evaluate_node"](CAMPAIGN_ID, NODE_ID) == 0.42
    assert node_calls[0][0] == NODE_ID
    assert node_calls[0][1] == CAMPAIGN_ID

    # The replay half: the M3 baseline's own source, over that campaign.
    assert kwargs["replay_policy"](CAMPAIGN_ID) == 0.77
    assert replay_calls[0][0] == M2_INCUMBENT_PATH.read_text(encoding="utf-8")
    assert replay_calls[0][1] == CAMPAIGN_ID

    # Every call built its own FinancialEvalContext -- the per-run cache can
    # never answer a nightly re-evaluation from memory.
    assert len(built) == 2
    assert built[0] is not built[1]
    assert built[0].evaluation is context and built[1].evaluation is context
    assert node_calls[0][2] is built[0]
    assert replay_calls[0][2] is built[1]


def test_each_call_gets_a_fresh_context_even_when_the_same_evaluator_repeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_path(tmp_path)
    env = _env(f"sqlite:///{tmp_path / 'canary.db'}", config)
    monkeypatch.setattr(
        canary_cli, "load_evaluation_context", lambda env=None: _stub_context()
    )
    built = _record_financial_contexts(monkeypatch)
    monkeypatch.setattr(
        canary_cli, "_oos_ir", lambda node_id, *, campaign_id, context: 0.5
    )
    monkeypatch.setattr(
        canary_cli,
        "score_on_financial_world",
        lambda source, campaign_id, *, context: SimpleNamespace(score=0.5),
    )
    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main([], env=env) == canary_run.EXIT_OK
    evaluate_node = captured["kwargs"]["evaluate_node"]
    replay_policy = captured["kwargs"]["replay_policy"]

    evaluate_node(CAMPAIGN_ID, NODE_ID)
    evaluate_node(CAMPAIGN_ID, NODE_ID)
    replay_policy(CAMPAIGN_ID)
    replay_policy(CAMPAIGN_ID)

    assert len(built) == 4
    assert len({id(item) for item in built}) == 4


def test_an_unset_evaluation_config_passes_no_evaluators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The unconfigured deployment: composition's state, not an error. canary.run
    # runs its toy canary exactly as it did before the evaluation canary
    # existed -- and refuses by name on its own if a frozen evaluation
    # reference is on record, which is that module's own refusal to report.
    env = _env(f"sqlite:///{tmp_path / 'canary.db'}", None)
    monkeypatch.setattr(
        canary_cli, "load_evaluation_context", lambda env=None: None
    )
    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main([], env=env) == canary_run.EXIT_OK

    kwargs = captured["kwargs"]
    assert kwargs["evaluate_node"] is None
    assert kwargs["replay_policy"] is None
    assert kwargs["evaluation_config_sha256"] is None


def test_a_context_with_no_out_of_sample_grid_passes_no_evaluators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A config with no oos_dates names no window to re-evaluate a node over,
    # so there is nothing for the evaluation canary to be deterministic about.
    config = _config_path(tmp_path)
    env = _env(f"sqlite:///{tmp_path / 'canary.db'}", config)
    monkeypatch.setattr(
        canary_cli, "load_evaluation_context", lambda env=None: _stub_context(())
    )
    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main([], env=env) == canary_run.EXIT_OK

    kwargs = captured["kwargs"]
    assert kwargs["evaluate_node"] is None
    assert kwargs["replay_policy"] is None
    assert kwargs["evaluation_config_sha256"] is None


def test_a_missing_database_url_is_left_to_canary_run_to_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # canary.run owns the "no DATABASE_URL is a configuration fault" answer
    # (its own exit code 2); this CLI must not pre-empt it with a different
    # one, so the context is never loaded without a store to load it against.
    config = _config_path(tmp_path)
    env = {EVALUATION_CONFIG_ENV: str(config)}
    called: list[Mapping[str, str] | None] = []

    def _load(env: Mapping[str, str] | None = None) -> Any:
        called.append(env)
        return _stub_context()

    monkeypatch.setattr(canary_cli, "load_evaluation_context", _load)
    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main([], env=env) == canary_run.EXIT_OK
    assert called == []
    assert captured["kwargs"]["evaluate_node"] is None


def test_a_config_that_cannot_be_read_is_refused_without_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A configured-but-broken document is a refusal, the same stance
    # orchestrator.dream takes: a canary that quietly fell back to toy-only
    # because its evaluation config was broken is the very silence this
    # fix exists to end.
    from orchestrator._context import EvaluationConfigError

    env = _env(f"sqlite:///{tmp_path / 'canary.db'}", tmp_path / "missing.json")
    env[EVALUATION_CONFIG_ENV] = str(tmp_path / "missing.json")

    def _load(env: Mapping[str, str] | None = None) -> Any:
        raise EvaluationConfigError("evaluation_config: cannot be read")

    monkeypatch.setattr(canary_cli, "load_evaluation_context", _load)
    captured = _capture_canary_main(monkeypatch)

    assert canary_cli.main([], env=env) == canary_run.EXIT_REFUSED
    assert captured == {}
    stderr = capsys.readouterr().err
    assert "evaluation_config" in stderr
    assert "Traceback" not in stderr


# -- The defect, end to end: the real canary, over a real store --------------


def test_the_real_canary_run_records_evaluation_canary_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The reported defect, closed: driving the *real* canary.run.main (no
    # swap of this module's reference) over a real store, a freeze followed
    # by a plain run records evaluation_canary=1 and leaves dreaming allowed
    # -- which is exactly what `./run.sh dream` was refused for before this
    # command existed. Only the context loader and the two expensive scorers
    # are stubbed: no sealed snapshot, no sandbox, no campaign.
    from canary import CanaryHaltStore
    from canary.run import CanaryRunStore

    url = f"sqlite:///{tmp_path / 'real-canary.db'}"
    config = _config_path(tmp_path)
    env = _env(url, config)

    monkeypatch.setattr(
        canary_cli, "load_evaluation_context", lambda env=None: _stub_context()
    )
    monkeypatch.setattr(
        canary_cli, "_oos_ir", lambda node_id, *, campaign_id, context: 0.25
    )
    monkeypatch.setattr(
        canary_cli,
        "score_on_financial_world",
        lambda source, campaign_id, *, context: SimpleNamespace(score=0.75),
    )

    freeze_lines: list[str] = []
    assert (
        canary_cli.main(["--freeze-reference"], env=env, emit=freeze_lines.append)
        == canary_run.EXIT_OK
    )
    assert freeze_lines and freeze_lines[0]

    run_lines: list[str] = []
    assert canary_cli.main([], env=env, emit=run_lines.append) == canary_run.EXIT_OK

    payload = json.loads(run_lines[0])
    assert payload["evaluation_canary"] is True
    assert payload["within_tolerance"] is True

    newest = CanaryRunStore(url).newest()
    assert newest is not None
    assert newest.evaluation_canary is True
    assert CanaryHaltStore(url).halted() is False
