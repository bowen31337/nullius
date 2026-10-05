"""Feature 2, root planting — a campaign's opening signal, as the tree's
depth-0 row.

additions_spec_campaign_driver.xml, "Roots", feature 2: *System persists a
planted root as a depth-0 node row with orchestrator._roots.plant_root(
campaign_id, theme_root, authored, *, context, artifact_store), and it
answers the root's node id.*  Every test here runs the real seam: a
throwaway SQLite database migrated with the node table's own migrations
(``0118`` creates the table; ``0115``-``0117`` add the three trios this
feature writes), and a real :class:`artifacts.ArtifactStore` over a
``tmp_path`` directory — the spec's own sentence, taken literally, the same
way the tree-writer and artifact-writer suites beside this one take it.

One test per claim the feature sentence makes:

* **the row** — every column the spec names (the five structural facts, the
  identity pair, the provenance trio, the authoring trio) lands exactly as
  the sentence describes, and the code is readable back through the
  artifact store at the ``artifact_uri`` the row carries.

* **idempotent by value, and the second plant writes nothing** — replanting
  the same root with identical inputs answers the same id and touches
  neither the database nor the artifact store a second time.

* **a conflicting replant is refused** — a node id the tree already holds,
  asked to be planted again with a different value, raises
  :class:`~orchestrator._roots.RootPlantError` (code word ``root_plant``)
  naming the disagreement, and neither store is touched.

* **depth is checked before anything else** — an authored record whose
  depth is not ``0`` is refused the same way, before the node id, the code
  hash or either store is read.

* **the wiring refusals** — a blank ``campaign_id`` or ``theme_root``, and a
  database the node migration has not reached, are refused by name rather
  than surfacing a raw ``sqlite3`` or ``TypeError`` failure.

* **the module's surface** — ``__all__`` names the error, its code word and
  the one function.

No test opens a network connection, reads a real credential, or writes
outside a pytest temporary directory.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from artifacts import ArtifactStore, artifact_uri
from orchestrator._roots import ROOT_PLANT_CODE, RootPlantError, plant_root
from providers import AgentSampling, AuthoringRecord, ModelPin, Usage
from signal_agent import AuthoredSignal

# conftest-less suite: this file is under packages/orchestrator/tests, so the
# repository root is four parents up — tests -> orchestrator -> packages ->
# repo root — and the migrations live beside it under migrations/versions.
REPO_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"

#: The node table migrations this feature's columns depend on: ``0118``
#: creates the table, and ``0115``-``0117`` add the three trios ``plant_root``
#: writes (the authoring, provenance and identity columns). Run with the
#: table first, because each of the other three is an ``ALTER`` against it.
NODE_TABLE_MIGRATIONS = (
    "0118_node_table",
    "0117_identity_trio",
    "0116_provenance_trio",
    "0115_agent_model_trio",
)

#: A real, pinned model triple — the exact literal the providers member's
#: own suite uses (``packages/providers/tests/test_authoring_store.py``),
#: because :class:`~providers.ModelPin` refuses a rolling alias.
ROOT_PIN = "deepseek/deepseek-v4-flash/20260910"


def _load_migration(revision: str) -> ModuleType:
    """Import a migration by file path, as the schema's owner."""
    path = VERSIONS_DIR / f"{revision}.py"
    if not path.is_file():
        raise AssertionError(
            f"{revision} is not at {path}; this suite runs the node table's "
            "own migrations rather than hand-writing its DDL, so it needs "
            "the schema's owner to be where the tree keeps it"
        )
    spec = importlib.util.spec_from_file_location(f"_orchestrator_test_{revision}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree_database(tmp_path: Path) -> str:
    """A ``sqlite:///`` URL for a throwaway database, migrated to the tree."""
    url = f"sqlite:///{tmp_path / 'tree-test.db'}"
    for revision in NODE_TABLE_MIGRATIONS:
        _load_migration(revision).apply(url)
    return url


class _Context:
    """A lightweight stand-in for the four attributes ``plant_root`` reads
    off ``context`` — the provenance trio and the database URL — rather
    than a full :class:`orchestrator._context.EvaluationContext`, which
    needs a mounted snapshot and a cost model this feature never touches.
    """

    def __init__(self, database_url: str, **hashes: str) -> None:
        self.database_url = database_url
        self.evaluator_hash = hashes.get("evaluator_hash", "e" * 64)
        self.snapshot_hash = hashes.get("snapshot_hash", "s" * 64)
        self.cost_model_hash = hashes.get("cost_model_hash", "c" * 64)


@pytest.fixture
def context(tree_database: str) -> _Context:
    return _Context(tree_database)


class _CountingStore:
    """Wraps a real :class:`artifacts.ArtifactStore`, counting writes.

    ``plant_root``'s claim is that an identical replant and a refused
    conflict touch the artifact store *not at all* — a claim a plain
    ``ArtifactStore`` cannot answer for itself. Every other attribute
    (``root``, ``read``, ``has_node``, ...) delegates straight through, so
    :func:`artifacts.artifact_uri` and this suite's own read-backs see the
    real store underneath.
    """

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store
        self.write_calls = 0
        self.commit_calls = 0
        self.discard_calls = 0

    def write(self, *args: Any, **kwargs: Any) -> Any:
        self.write_calls += 1
        return self._store.write(*args, **kwargs)

    def commit(self, *args: Any, **kwargs: Any) -> Any:
        self.commit_calls += 1
        return self._store.commit(*args, **kwargs)

    def discard(self, *args: Any, **kwargs: Any) -> Any:
        self.discard_calls += 1
        return self._store.discard(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


@pytest.fixture
def store(tmp_path: Path) -> _CountingStore:
    return _CountingStore(ArtifactStore(tmp_path / "artifacts"))


def _authored(
    *,
    node_id: str | None = None,
    campaign_id: str | None = None,
    depth: int = 0,
    code: str = "def construct():\n    return 1\n",
    stated_mechanism: str | None = "a plausible economic story",
    temperature: float = 0.4,
) -> AuthoredSignal:
    """A real :class:`~signal_agent.AuthoredSignal` over a real authoring
    record — the exact shape feature 1's ``author_root`` answers, built
    directly here because that feature is dispatched in parallel.
    """
    record = AuthoringRecord(
        node_id=node_id or str(uuid.uuid4()),
        campaign_id=campaign_id or str(uuid.uuid4()),
        depth=depth,
        role="root",
        pin=ModelPin(*ROOT_PIN.split("/")),
        sampling=AgentSampling(temperature=temperature, seed=7),
        usage=Usage(input_tokens=1_000, output_tokens=200),
        served_model="deepseek-v4-flash",
    )
    return AuthoredSignal(
        code=code,
        stated_mechanism=stated_mechanism,
        proposal=f"```python\n{code}```\nMechanism: {stated_mechanism}\n",
        record=record,
    )


def _raw_row(database_url: str, node_id: str) -> dict[str, Any] | None:
    """The node's row, read back with raw SQL — the suite's own read side,
    independent of anything ``plant_root`` itself computes.
    """
    path = Path(database_url.removeprefix("sqlite:///"))
    columns = (
        "id",
        "parent_id",
        "campaign_id",
        "theme_root",
        "depth",
        "code_hash",
        "stated_mechanism",
        "artifact_uri",
        "evaluator_hash",
        "snapshot_hash",
        "cost_model_hash",
        "agent_model_id",
        "agent_ckpt_hash",
        "agent_sampling",
    )
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            f"SELECT {', '.join(columns)} FROM node WHERE id = ?", (node_id,)
        ).fetchone()
    return dict(zip(columns, row)) if row is not None else None


# -- The row --------------------------------------------------------------------


def test_plants_a_root_row_with_every_column(
    context: _Context, store: _CountingStore
) -> None:
    campaign_id = str(uuid.uuid4())
    theme_root = "momentum"
    authored = _authored(campaign_id=campaign_id)

    node_id = plant_root(
        campaign_id, theme_root, authored, context=context, artifact_store=store
    )

    assert node_id == authored.record.node_id
    row = _raw_row(context.database_url, node_id)
    assert row is not None
    assert row["parent_id"] is None
    assert row["campaign_id"] == campaign_id
    assert row["theme_root"] == theme_root
    assert row["depth"] == 0
    assert row["code_hash"] == hashlib.sha256(authored.code.encode()).hexdigest()
    assert row["stated_mechanism"] == authored.stated_mechanism
    assert row["artifact_uri"] == artifact_uri(store, campaign_id, node_id)
    assert row["evaluator_hash"] == context.evaluator_hash
    assert row["snapshot_hash"] == context.snapshot_hash
    assert row["cost_model_hash"] == context.cost_model_hash
    assert row["agent_model_id"] == ROOT_PIN
    assert row["agent_ckpt_hash"] is None
    assert json.loads(row["agent_sampling"]) == {
        "temperature": 0.4,
        "top_p": 1.0,
        "thinking": False,
        "seed": 7,
    }

    # The code landed through the ArtifactStore, at the row's own address.
    assert store.read(campaign_id, node_id, "code.py") == authored.code.encode()
    assert store.write_calls == 1
    assert store.commit_calls == 1


def test_stated_mechanism_may_be_none(
    context: _Context, store: _CountingStore
) -> None:
    campaign_id = str(uuid.uuid4())
    authored = _authored(campaign_id=campaign_id, stated_mechanism=None)

    node_id = plant_root(
        campaign_id, "momentum", authored, context=context, artifact_store=store
    )

    row = _raw_row(context.database_url, node_id)
    assert row is not None
    assert row["stated_mechanism"] is None


# -- Idempotence and conflict -----------------------------------------------------


def test_replanting_identically_answers_the_same_id_and_writes_nothing(
    context: _Context, store: _CountingStore
) -> None:
    campaign_id = str(uuid.uuid4())
    theme_root = "momentum"
    authored = _authored(campaign_id=campaign_id)

    first = plant_root(
        campaign_id, theme_root, authored, context=context, artifact_store=store
    )
    before = _raw_row(context.database_url, first)
    assert store.write_calls == 1 and store.commit_calls == 1
    discards_after_first_plant = store.discard_calls

    second = plant_root(
        campaign_id, theme_root, authored, context=context, artifact_store=store
    )

    assert second == first
    assert _raw_row(context.database_url, first) == before
    # No second write, commit or discard touched the artifact store at all.
    assert store.write_calls == 1
    assert store.commit_calls == 1
    assert store.discard_calls == discards_after_first_plant


def test_conflicting_replant_raises_root_plant_error(
    context: _Context, store: _CountingStore
) -> None:
    campaign_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    authored = _authored(node_id=node_id, campaign_id=campaign_id)
    plant_root(
        campaign_id, "momentum", authored, context=context, artifact_store=store
    )
    before = _raw_row(context.database_url, node_id)

    conflicting = _authored(node_id=node_id, campaign_id=campaign_id, code="def construct():\n    return 2\n")

    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            campaign_id,
            "momentum",
            conflicting,
            context=context,
            artifact_store=store,
        )

    # The standing row and the artifact store are untouched by the refusal.
    assert _raw_row(context.database_url, node_id) == before
    assert store.write_calls == 1
    assert store.commit_calls == 1


def test_conflicting_theme_root_raises(
    context: _Context, store: _CountingStore
) -> None:
    campaign_id = str(uuid.uuid4())
    node_id = str(uuid.uuid4())
    authored = _authored(node_id=node_id, campaign_id=campaign_id)
    plant_root(
        campaign_id, "momentum", authored, context=context, artifact_store=store
    )

    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            campaign_id,
            "mean-reversion",
            authored,
            context=context,
            artifact_store=store,
        )


# -- Depth --------------------------------------------------------------------


def test_raises_when_the_authored_record_depth_is_not_zero(
    context: _Context, store: _CountingStore
) -> None:
    authored = _authored(depth=1)

    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            str(uuid.uuid4()),
            "momentum",
            authored,
            context=context,
            artifact_store=store,
        )

    assert store.write_calls == 0
    assert store.commit_calls == 0


# -- Wiring refusals ------------------------------------------------------------


@pytest.mark.parametrize("campaign_id", ["", "   "])
def test_raises_for_a_blank_campaign_id(
    context: _Context, store: _CountingStore, campaign_id: str
) -> None:
    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            campaign_id, "momentum", _authored(), context=context, artifact_store=store
        )


@pytest.mark.parametrize("theme_root", ["", "   "])
def test_raises_for_a_blank_theme_root(
    context: _Context, store: _CountingStore, theme_root: str
) -> None:
    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            str(uuid.uuid4()),
            theme_root,
            _authored(),
            context=context,
            artifact_store=store,
        )


def test_raises_when_the_node_table_is_missing(
    tmp_path: Path, store: _CountingStore
) -> None:
    unmigrated = _Context(f"sqlite:///{tmp_path / 'unmigrated.db'}")

    with pytest.raises(RootPlantError, match=ROOT_PLANT_CODE):
        plant_root(
            str(uuid.uuid4()),
            "momentum",
            _authored(),
            context=unmigrated,
            artifact_store=store,
        )


# -- The module's surface --------------------------------------------------------


def test_module_surface() -> None:
    import orchestrator._roots as roots

    assert set(roots.__all__) == {"ROOT_PLANT_CODE", "RootPlantError", "plant_root"}
    assert roots.ROOT_PLANT_CODE == "root_plant"
    assert issubclass(roots.RootPlantError, Exception)
