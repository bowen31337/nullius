"""bug_spec_prompt_available_streams.xml — the live prompt carries
``available_streams``, so the model never asks for a stream the evaluation's
sealed snapshot does not hold.

The root cause (bug 1's own words): "the snapshot argument added to
declaration() was never threaded through the prompt builder or the composed
author."  :meth:`~signal_agent.SignalContract.declaration` already accepts a
``snapshot`` (bug_spec_authoring_contract.xml), but
:func:`signal_agent._authoring_prompt.build_authoring_prompt` passed none,
and :class:`signal_agent._llm_author.LLMSignalAuthor` had none to hand it.
This suite pins both halves of the fix:

* :func:`build_authoring_prompt` threads a ``snapshot`` straight into
  ``declaration()`` and adds the plain-language statement that every
  accessor or frequency not listed returns an empty frame — generated from
  ``available_streams`` itself, never hard-coded to one snapshot's cadence;
* :class:`LLMSignalAuthor` resolves that snapshot once, from
  ``NULLIUS_EVALUATION_CONFIG``, at construction — so every prompt it
  builds (a root, a child, and the system message a retry replays) carries
  it, composing no config leaves the prompt unchanged, a broken
  ``snapshot_mount`` refuses composition rather than silently omitting the
  field, and composing the author over a real snapshot opens no Parquet
  file.

No network; the snapshot fixture is a handful of tiny Parquet files under
``tmp_path``, and every provider is a fake that never leaves the process.
No module-level state, so the suite is order- and worker-independent under
pytest-xdist.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from providers import ModelPin
from signal_agent import anti_convergence_gate, prompt_guidance_gate, signal_contract
from signal_agent._authoring_prompt import build_authoring_prompt
from signal_agent._llm_author import (
    EVALUATION_CONFIG_CODE,
    AuthoringPromptError,
    LLMSignalAuthor,
)

from test_llm_author import (  # isort: skip
    CAMPAIGN,
    CONFORMING_ANSWER,
    FakeHistoryStore,
    FakeProvider,
    FakeSession,
    PARENT,
    ROOT_MODEL,
    ROOT_PIN,
    UNPARSEABLE_ANSWER,
    completion,
    make_config,
    workspace,
)

#: Two symbols' worth of 1d bars — only the stream and frequency this
#: snapshot actually carries; a model told about it must have nothing else
#: to ask for.
SYMBOLS = ("AAAUSDT", "BBBUSDT")
DATES = ("2026-01-01", "2026-01-02")


def _seal_tiny_1d_bars_snapshot(lake_root: Path, *, with_interval: bool = True) -> Path:
    """Seal a real snapshot — one 1d-bars partition per symbol per day.

    The same venue-string convention (and the row-level ``interval`` column)
    ``test_contract_declaration_detail.py`` seals, trimmed to two days: this
    suite only needs ``available_streams`` to answer ``{"bars": ("1d",)}``,
    not a signal that actually scores against the bytes.
    """
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")
    snapshot = pytest.importorskip("snapshot")

    staging = lake_root / "staging"
    for symbol in SYMBOLS:
        for date in DATES:
            partition = staging / "bars" / f"symbol={symbol}" / f"date={date}"
            partition.mkdir(parents=True)
            table = pa.table(
                {
                    "symbol": [symbol],
                    "open_time": pa.array(
                        [dt.datetime.fromisoformat(f"{date}T00:00:00+00:00")],
                        type=pa.timestamp("us", tz="UTC"),
                    ),
                    "close": ["100.00"],
                    "volume": ["1.0"],
                    **({"interval": ["1d"]} if with_interval else {}),
                }
            )
            pq.write_table(table, partition / "part-0.parquet")

    service = snapshot.SnapshotService(lake_root)
    sealed = service.seal(sealed_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC))
    return sealed.path


@pytest.fixture
def sealed_snapshot_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return _seal_tiny_1d_bars_snapshot(tmp_path / "lake")


def _evaluation_config_env(snapshot_mount: Path, tmp_path: Path) -> dict[str, str]:
    """``{"NULLIUS_EVALUATION_CONFIG": "<file naming snapshot_mount>"}``.

    Only the one key this member's own reader needs — never the other six
    ``orchestrator._context.load_evaluation_context`` requires (the sandbox
    gate, the cost model, ``DATABASE_URL``), because this member does not
    import orchestrator and composes no sandbox, no cost model and no store.
    """
    config_path = tmp_path / "evaluation_config.json"
    config_path.write_text(json.dumps({"snapshot_mount": str(snapshot_mount)}))
    return {"NULLIUS_EVALUATION_CONFIG": str(config_path)}


def _build_author(*, provider, env, max_retries: int = 1) -> LLMSignalAuthor:
    pin = ModelPin.parse(ROOT_PIN)
    session = FakeSession({"root": provider}, {"root": pin})
    return LLMSignalAuthor(
        session,
        history_store=FakeHistoryStore(),
        contract=signal_contract(),
        anti_convergence=anti_convergence_gate(),
        guidance=prompt_guidance_gate(),
        config=make_config(),
        max_retries=max_retries,
        env=env,
    )


# -- build_authoring_prompt: the exact shape, unit level ----------------------


def test_build_authoring_prompt_threads_the_snapshot_into_available_streams(
    sealed_snapshot_path: Path,
) -> None:
    import snapshot as snapshot_module

    mount = snapshot_module.SnapshotMount.for_directory(sealed_snapshot_path)
    ws = SimpleNamespace(campaign_id=CAMPAIGN, theme_root="momentum", depth=0)
    parts = build_authoring_prompt(ws, (), clause="clause text", snapshot=mount)
    declared = parts.task["contract"]
    assert declared["available_streams"] == {"bars": ("1d",)}
    # The empty-frame statement lives inside the contract section itself,
    # beside the mapping it is generated from -- never a second, sibling
    # fact at the task level.
    assert "returns an empty frame" in declared["available_streams_note"]
    assert "1d" in declared["available_streams_note"]


def test_build_authoring_prompt_without_a_snapshot_carries_neither_field() -> None:
    ws = SimpleNamespace(campaign_id=CAMPAIGN, theme_root="momentum", depth=0)
    parts = build_authoring_prompt(ws, (), clause="clause text")
    assert "available_streams" not in parts.task["contract"]
    assert "available_streams_note" not in parts.task["contract"]


# -- the composed author: root, child and retry prompts all carry it --------


def test_root_prompt_carries_available_streams_and_the_empty_frame_statement(
    sealed_snapshot_path: Path, tmp_path: Path
) -> None:
    env = _evaluation_config_env(sealed_snapshot_path, tmp_path)
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = _build_author(provider=provider, env=env)
    author.author_root(CAMPAIGN, "momentum", root_id=str(uuid.uuid4()))

    system = provider.requests[0].messages[0].content
    assert '"available_streams"' in system
    assert '"1d"' in system
    assert "returns an empty frame" in system


def test_child_prompt_carries_available_streams(
    sealed_snapshot_path: Path, tmp_path: Path
) -> None:
    env = _evaluation_config_env(sealed_snapshot_path, tmp_path)
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = _build_author(provider=provider, env=env)
    # depth 0's child is depth 1, still the "root" role (§14.1: roots are
    # depth 0-1), which is all the fake session above routes.
    author(workspace(depth=0, node_id=PARENT))

    system = provider.requests[0].messages[0].content
    assert '"available_streams"' in system
    assert "returns an empty frame" in system


def test_retry_prompt_still_carries_available_streams(
    sealed_snapshot_path: Path, tmp_path: Path
) -> None:
    env = _evaluation_config_env(sealed_snapshot_path, tmp_path)
    provider = FakeProvider(
        [
            completion(UNPARSEABLE_ANSWER, model=ROOT_MODEL),
            completion(CONFORMING_ANSWER, model=ROOT_MODEL),
        ],
        model=ROOT_MODEL,
    )
    author = _build_author(provider=provider, env=env, max_retries=1)
    author.author_root(CAMPAIGN, "momentum", root_id=str(uuid.uuid4()))

    assert provider.calls == 2
    first_system = provider.requests[0].messages[0].content
    retry_system = provider.requests[1].messages[0].content
    # The system message is never rebuilt across a retry -- only the
    # assistant's answer and a defect-naming user turn are appended -- so the
    # same available_streams fact that reached the first call reaches the
    # retried one too.
    assert first_system == retry_system
    assert "returns an empty frame" in retry_system


def test_no_config_leaves_the_prompt_unchanged(tmp_path: Path) -> None:
    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = _build_author(provider=provider, env={})
    assert author._snapshot is None
    author.author_root(CAMPAIGN, "momentum", root_id=str(uuid.uuid4()))

    system = provider.requests[0].messages[0].content
    assert "available_streams" not in system


def test_broken_snapshot_path_refuses_composition(tmp_path: Path) -> None:
    # A directory that exists but does not parse as a canonical sealed
    # snapshot name -- SnapshotMount.for_directory refuses it, and that
    # refusal must surface as this member's own AuthoringPromptError rather
    # than a silently absent available_streams field.
    not_a_snapshot = tmp_path / "not-a-sealed-snapshot"
    not_a_snapshot.mkdir()
    env = _evaluation_config_env(not_a_snapshot, tmp_path)
    provider = FakeProvider([], model=ROOT_MODEL)

    with pytest.raises(AuthoringPromptError) as excinfo:
        _build_author(provider=provider, env=env)
    assert EVALUATION_CONFIG_CODE in str(excinfo.value)


def test_a_missing_snapshot_mount_key_refuses_composition(tmp_path: Path) -> None:
    config_path = tmp_path / "evaluation_config.json"
    config_path.write_text(json.dumps({}))
    env = {"NULLIUS_EVALUATION_CONFIG": str(config_path)}
    provider = FakeProvider([], model=ROOT_MODEL)

    with pytest.raises(AuthoringPromptError) as excinfo:
        _build_author(provider=provider, env=env)
    assert EVALUATION_CONFIG_CODE in str(excinfo.value)


def test_a_snapshot_with_no_readable_manifest_refuses_composition(tmp_path: Path) -> None:
    # A directory that *does* parse as a canonical sealed snapshot name (so
    # SnapshotMount.for_directory mounts it) but carries no MANIFEST.json --
    # composition reads the manifest, so this refuses too, rather than
    # silently resolving a snapshot whose available_streams nothing backs.
    snapshot_module = pytest.importorskip("snapshot")
    name = snapshot_module.snapshot_name(
        dt.datetime(2026, 1, 6, tzinfo=dt.UTC), "a" * 64
    )
    no_manifest = tmp_path / "lake-without-manifest" / name
    no_manifest.mkdir(parents=True)
    env = _evaluation_config_env(no_manifest, tmp_path)
    provider = FakeProvider([], model=ROOT_MODEL)

    with pytest.raises(AuthoringPromptError) as excinfo:
        _build_author(provider=provider, env=env)
    assert EVALUATION_CONFIG_CODE in str(excinfo.value)
    assert "MANIFEST.json" in str(excinfo.value)


# -- composition stays cheap: zero Parquet reads -----------------------------


def test_composing_the_author_reads_no_parquet_file(
    sealed_snapshot_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    env = _evaluation_config_env(sealed_snapshot_path, tmp_path)

    calls: list[object] = []
    original_read_table = pq.read_table
    original_read_schema = pq.read_schema

    def spy_read_table(*args, **kwargs):
        calls.append(("read_table", args, kwargs))
        return original_read_table(*args, **kwargs)

    def spy_read_schema(*args, **kwargs):
        calls.append(("read_schema", args, kwargs))
        return original_read_schema(*args, **kwargs)

    monkeypatch.setattr(pq, "read_table", spy_read_table)
    monkeypatch.setattr(pq, "read_schema", spy_read_schema)

    provider = FakeProvider([completion(CONFORMING_ANSWER, model=ROOT_MODEL)], model=ROOT_MODEL)
    author = _build_author(provider=provider, env=env)
    assert author._snapshot is not None
    assert calls == []


def test_the_shipped_bars_layout_without_an_interval_column_reports_1d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # nullius_ingest.bars_backfill seals symbol/open_time/close/volume with no
    # ``interval`` column -- the layout the evaluator actually reads and
    # materializes as its single ``bars:1d`` frame. Reporting () for it told
    # the model "bars exist" with no frequency, and it asked for 1h bars
    # (smoke campaign 360f6f00); the answer must be ("1d",).
    import snapshot as snapshot_module

    monkeypatch.delenv("DATABASE_URL", raising=False)
    sealed = _seal_tiny_1d_bars_snapshot(tmp_path / "lake", with_interval=False)
    mount = snapshot_module.SnapshotMount.for_directory(sealed)
    ws = SimpleNamespace(campaign_id=CAMPAIGN, theme_root="momentum", depth=0)
    parts = build_authoring_prompt(ws, (), clause="clause text", snapshot=mount)
    declared = parts.task["contract"]
    assert declared["available_streams"] == {"bars": ("1d",)}
    assert "1d" in declared["available_streams_note"]
