"""bug_spec_smoke_campaign_hang.xml's example-config regression.

The shipped ``deploy/campaign/*.example.json`` files each opened with a
``_comment`` key — a note for the operator copying them, per
``.env.campaign.tpl.example``'s instructions. Neither loader's key
vocabulary admits it: ``providers.load_authoring_config`` and
``orchestrator.load_evaluation_context`` both refuse any key outside their
own closed set, so an operator who copied an example verbatim and pointed
``NULLIUS_AUTHORING_CONFIG`` / ``NULLIUS_EVALUATION_CONFIG`` at the copy got
a refusal naming ``_comment`` before the campaign ever started.

This test loads both examples through the real loaders — the authoring one
as shipped (its pins and knobs name no filesystem path), and the evaluation
one with ``snapshot_mount`` and ``artifact_dir`` redirected to a tmp sealed
snapshot, since the shipped paths (``/opt/nullius/...``) are placeholders
for a real deployment, not a path this suite may read or write.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orchestrator._context import EvaluationContext, load_evaluation_context
from providers import AuthoringConfig, load_authoring_config
from snapshot import SnapshotService

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHORING_EXAMPLE = REPO_ROOT / "deploy" / "campaign" / "authoring-config.example.json"
EVALUATION_EXAMPLE = (
    REPO_ROOT / "deploy" / "campaign" / "evaluation-config.example.json"
)

#: A digest-pinned reference — the only spelling the evaluator member's own
#: identity accepts (never a tag).
IMAGE = "ghcr.io/nullius/evaluator@sha256:" + "ab" * 32


def test_authoring_example_is_valid_input_to_its_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NULLIUS_AUTHORING_CONFIG", str(AUTHORING_EXAMPLE))
    config = load_authoring_config()
    assert isinstance(config, AuthoringConfig)
    # The 5.x pins in the shipped example take 'effort', not 'temperature' —
    # the no-sampling models' own vocabulary (providers._anthropic).
    assert config.temperature is None
    assert config.effort == "high"


def test_evaluation_example_is_valid_input_to_its_loader(
    tmp_path: Path, lake_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partition = (
        lake_root / "staging" / "bars" / "symbol=SYM00" / "date=2026-09-01"
    )
    partition.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "symbol": ["SYM00"],
                "open_time": [dt.datetime(2026, 9, 1, tzinfo=dt.UTC)],
                "close": ["100.0"],
                "volume": ["1.0"],
            }
        ),
        partition / "part-0.parquet",
    )
    sealed = SnapshotService(lake_root).seal(
        sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC)
    )

    document = json.loads(EVALUATION_EXAMPLE.read_text(encoding="utf-8"))
    document["snapshot_mount"] = str(sealed.path)
    document["artifact_dir"] = str(tmp_path / "artifacts")
    config_path = tmp_path / "evaluation-config.json"
    config_path.write_text(json.dumps(document), encoding="utf-8")

    # The shipped example names sandbox_runtime: "gvisor", which the gate
    # accepts only with a real runsc binary on PATH — a scratch stub stands
    # in for a deployment's gVisor install, the same way test_context.py's
    # own fixtures do.
    runsc_dir = tmp_path / "bin"
    runsc_dir.mkdir()
    runsc = runsc_dir / "runsc"
    runsc.write_text("#! /bin/sh\n", encoding="utf-8")
    runsc.chmod(0o755)

    monkeypatch.setenv("NULLIUS_EVALUATION_CONFIG", str(config_path))
    monkeypatch.setenv("NULLIUS_EVALUATOR_IMAGE", IMAGE)
    monkeypatch.setenv("PATH", str(runsc_dir))

    context = load_evaluation_context()
    assert isinstance(context, EvaluationContext)
    assert context.sandbox_runtime == "gvisor"
