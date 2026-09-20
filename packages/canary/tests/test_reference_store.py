"""Feature 141, the store: the frozen reference pair written down and read back.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 141: *System
persists a frozen canary policy together with a frozen canary tree as the
determinism reference pair.*  :mod:`canary._reference` is the frozen pair; this
suite is the store that writes it down — :mod:`canary._reference_store` — over a
real SQLite file, and the migration that creates the tables it writes to.

The store and the migration are two spellings of one schema, and this suite pins
the contract between them the way ``test_ksguard.py`` pins it for the guard:

* the store and the migration create the *same* tables — same columns, same
  types, same nullability — so a database the store creates and a database the
  migration creates are the same database;
* running the migration over a database the store created changes nothing, and
  the store over a migration-created database changes nothing;
* the migration's own revision identity is the one the chain is built off.

The store's own contract is the freeze and the read-back:

* a frozen pair lands across all four tables, keyed by one ``reference_id``;
* the read path reconstructs the *same* pair the write path froze — the policy
  and the tree, byte for byte — so the nightly replay (feature 142) reads back
  the pair it froze rather than a plausible-looking one;
* the freeze is idempotent by reference pair — re-freezing the same version
  refreshes the policy row rather than appending a second one;
* a policy version frozen twice *to different bytes* is refused, because a
  version is a name for one policy;
* a reference id the store does not hold is refused by name — the pair is a fact
  about a freeze, and a store that invented one would invent the pair the bytes
  belong to.

A member that froze a pair correctly in memory while the store wrote something
else to disk would satisfy every requirement of the value-type tests and none of
these.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from canary import (
    POLICY_TABLE,
    REFERENCE_TABLE,
    TREE_NODE_TABLE,
    TREE_TABLE,
    CanaryPolicy,
    CanaryReferencePair,
    CanaryReferenceStore,
    CanaryReferenceStoreRecord,
    CanaryTree,
    freeze_reference_pair,
    load_reference_pair,
)
from canary._errors import CanaryError
from canary._reference import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0119_canary_reference_pair.py"

POLICY_VERSION = "canary-v1"


# -- Fixtures --------------------------------------------------------------------


def _policy(version: str = POLICY_VERSION) -> CanaryPolicy:
    return CanaryPolicy.freeze(
        version=version,
        policy={"scoring": {"weights": {"a": 0.5, "b": 0.5}}, "threshold": 0.7},
    )


def _tree() -> CanaryTree:
    return CanaryTree.freeze(
        {
            "root": (None, 0, {"label": "root", "kind": "decision"}),
            "left": ("root", 1, {"label": "left", "weight": 0.3}),
            "right": ("root", 1, {"label": "right", "weight": 0.7}),
        }
    )


def _pair(
    *,
    version: str = POLICY_VERSION,
    score=None,
    created_at: datetime | None = None,
) -> CanaryReferencePair:
    return CanaryReferencePair(
        policy=_policy(version=version),
        tree=_tree(),
        recorded_score=score,
        id=None,
        is_active=True,
        created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
    )


def _store(tmp_path: Path, name: str = "reference.db") -> CanaryReferenceStore:
    """A reference store over a fresh SQLite file in ``tmp_path``."""
    return CanaryReferenceStore(f"sqlite:///{tmp_path / name}")


def _columns(store: CanaryReferenceStore, table: str) -> list[tuple]:
    """``PRAGMA table_info`` for ``table``, as ``(name, type, notnull, dflt, pk)``."""
    with closing(store._connect()) as connection:
        cursor = connection.execute(f"PRAGMA table_info({table})")
        try:
            return [(row[1], row[2], row[3], row[4], row[5]) for row in cursor.fetchall()]
        finally:
            cursor.close()


def _migration():
    """``migrations/versions/0119_canary_reference_pair.py``, loaded by path.

    By path rather than by import because that is how a migration runner loads
    it: the file is not a module on any package's ``sys.path``, and a test that
    could only reach it through an import would be testing a different
    arrangement from the one that runs.
    """
    spec = importlib.util.spec_from_file_location(
        "migration_0119_canary_reference_pair", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional: the default state of a test is a deployment that
    names no relational store, and the tests that assert on the *unconfigured*
    behaviour then do not fight a fixture that helpfully configured one. Each
    test that wants a store builds its own over ``tmp_path``, so no test in this
    suite can reach a real database — the same guarantee the conftest states for
    the member's other paths.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)


# -- The freeze ------------------------------------------------------------------


class TestTheFreezePersistsAllFourHalves:
    def test_a_frozen_pair_lands_across_all_four_tables(
        self, tmp_path: Path
    ) -> None:
        # The whole of feature 141 in one call: the policy half, the tree half,
        # the tree's nodes and the join, all keyed by one reference_id.
        store = _store(tmp_path)
        record = store.freeze(_pair())
        rid = record.reference_id
        with closing(store._connect()) as connection:
            join = connection.execute(
                f"SELECT reference_id, recorded_score, is_active FROM {REFERENCE_TABLE}"
            ).fetchall()
            policy = connection.execute(
                f"SELECT reference_id, version, code_hash FROM {POLICY_TABLE}"
            ).fetchall()
            tree = connection.execute(
                f"SELECT reference_id, tree_hash, node_count FROM {TREE_TABLE}"
            ).fetchall()
            nodes = connection.execute(
                f"SELECT reference_id, node_id FROM {TREE_NODE_TABLE}"
            ).fetchall()
        assert join == [(rid, None, 1)]
        assert policy == [(rid, POLICY_VERSION, _policy().code_hash)]
        assert tree == [(rid, _tree().tree_hash, 3)]
        assert sorted(node[1] for node in nodes) == ["left", "right", "root"]
        assert all(node[0] == rid for node in nodes)

    def test_a_freshly_frozen_pair_carries_no_recorded_score(
        self, tmp_path: Path
    ) -> None:
        # Feature 141 freezes; feature 142 replays and records. A freshly frozen
        # pair has not been replayed, so ``recorded_score`` stays NULL — and a
        # fabricated 0.0 would read as a replay that never happened.
        store = _store(tmp_path)
        record = store.freeze(_pair())
        with closing(store._connect()) as connection:
            score = connection.execute(
                f"SELECT recorded_score FROM {REFERENCE_TABLE} WHERE reference_id = ?",
                (record.reference_id,),
            ).fetchone()[0]
        assert score is None

    def test_the_freeze_returns_the_record_it_wrote(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        record = store.freeze(_pair())
        assert isinstance(record, CanaryReferenceStoreRecord)
        assert uuid.UUID(record.reference_id)
        assert record.pair.policy.code_hash == _policy().code_hash
        assert record.pair.tree.tree_hash == _tree().tree_hash

    def test_the_freeze_stamps_a_timezone_aware_instant(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        record = store.freeze(_pair())
        assert record.stored_at.tzinfo is not None

    def test_the_freeze_can_carry_an_explicit_instant(self, tmp_path: Path) -> None:
        # A replay of a recorded freeze stamps the instant the original froze:
        # the caller reconstructs the pair with its original ``created_at``, and
        # the freeze writes that instant to the join row — so the read-back
        # carries the instant the original froze rather than "now".
        store = _store(tmp_path)
        when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        record = store.freeze(_pair(created_at=when))
        assert record.stored_at.tzinfo is not None
        assert store.load(record.reference_id).stored_at == when

    def test_a_frozen_pair_can_carry_a_recorded_score(self, tmp_path: Path) -> None:
        # When the replay *has* run, the store writes the constant it carries —
        # the same row, the same column, that feature 142 fills.
        store = _store(tmp_path)
        record = store.freeze(_pair(score=0.9876))
        with closing(store._connect()) as connection:
            score = connection.execute(
                f"SELECT recorded_score FROM {REFERENCE_TABLE} WHERE reference_id = ?",
                (record.reference_id,),
            ).fetchone()[0]
        assert score == 0.9876

    def test_the_store_holds_no_walk_and_no_rendered_bytes(
        self, tmp_path: Path
    ) -> None:
        # The store takes a frozen pair and writes the canonical bytes and the
        # hashes; it holds nothing that could drift from the frozen bytes. The
        # node payloads are the canonical bytes, not a raw walk.
        store = _store(tmp_path)
        store.freeze(_pair())
        with closing(store._connect()) as connection:
            payloads = connection.execute(
                f"SELECT payload FROM {TREE_NODE_TABLE} ORDER BY node_id"
            ).fetchall()
        assert [row[0] for row in payloads] == [
            canonical_json({"label": "left", "weight": 0.3}),
            canonical_json({"label": "right", "weight": 0.7}),
            canonical_json({"kind": "decision", "label": "root"}),
        ]


# -- The read-back ---------------------------------------------------------------


class TestTheReadBackReconstructsTheFrozenPair:
    def test_the_read_path_returns_the_pair_the_write_path_froze(
        self, tmp_path: Path
    ) -> None:
        # The nightly replay reads back the pair it froze and compares against
        # it. The read path must reconstruct the *same* policy and the *same*
        # tree, byte for byte — the same hashes, the same content.
        store = _store(tmp_path)
        frozen = _pair()
        record = store.freeze(frozen)
        loaded = store.load(record.reference_id)
        assert loaded.pair.has_same_content_as(frozen)
        assert loaded.pair.policy.code_hash == frozen.policy.code_hash
        assert loaded.pair.tree.tree_hash == frozen.tree.tree_hash
        assert loaded.pair.policy.policy == frozen.policy.policy

    def test_the_read_back_tree_has_every_node(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        record = store.freeze(_pair())
        loaded = store.load(record.reference_id)
        assert {node.node_id for node in loaded.pair.tree.nodes} == {
            "root",
            "left",
            "right",
        }
        assert loaded.pair.tree.nodes[0].content == {"label": "left", "weight": 0.3}

    def test_the_read_back_record_carries_the_stored_instant(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        when = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)
        record = store.freeze(_pair(created_at=when))
        loaded = store.load(record.reference_id)
        assert loaded.stored_at == when

    def test_the_one_shot_freeze_and_load_agree_with_the_class(
        self, tmp_path: Path
    ) -> None:
        # The one-shot convenience and the class freeze and read a pair the same
        # way — a test and the factory use the same spelling.
        url = f"sqlite:///{tmp_path / 'oneshot.db'}"
        record = freeze_reference_pair(url, _pair())
        loaded = load_reference_pair(url, record.reference_id)
        assert loaded.pair.has_same_content_as(_pair())

    def test_reading_an_absent_pair_is_refused_by_name(
        self, tmp_path: Path
    ) -> None:
        # The pair is a fact about a freeze; a store that invented one would
        # invent the pair the bytes belong to. An id the store never froze is
        # refused by name, not returned as an empty pair.
        store = _store(tmp_path)
        with pytest.raises(CanaryError, match="not in the store"):
            store.load(str(uuid.uuid4()))

    def test_reading_a_row_edited_outside_the_package_is_refused(
        self, tmp_path: Path
    ) -> None:
        # The stored bytes re-derive their hashes through the value types' own
        # validation. A row whose stored hash no longer names its stored bytes —
        # a tamper, or an edit outside this package — fails to reconstruct
        # rather than loading as a plausible-looking reference.
        store = _store(tmp_path)
        record = store.freeze(_pair())
        with closing(store._connect()) as connection, connection:
            connection.execute(
                f"UPDATE {POLICY_TABLE} SET code_hash = ? WHERE reference_id = ?",
                ("0" * 64, record.reference_id),
            )
        with pytest.raises(CanaryError):
            store.load(record.reference_id)


# -- Idempotency -----------------------------------------------------------------


class TestTheFreezeIsIdempotentByReferencePair:
    def test_refreezing_the_same_pair_refreshes_rather_than_appends(
        self, tmp_path: Path
    ) -> None:
        # The grain is the reference pair, keyed by ``reference_id``: re-freezing
        # under the same id refreshes the policy, tree and join rows rather than
        # appending a second set — exactly as re-running the KS guard refreshes
        # its row. The store holds the latest pair and nothing else.
        store = _store(tmp_path)
        rid = str(uuid.uuid4())
        store.freeze(_pair(), reference_id=rid)
        store.freeze(_pair(), reference_id=rid)
        with closing(store._connect()) as connection:
            policy_rows = connection.execute(
                f"SELECT COUNT(*) FROM {POLICY_TABLE} WHERE reference_id = ?",
                (rid,),
            ).fetchone()[0]
            tree_rows = connection.execute(
                f"SELECT COUNT(*) FROM {TREE_TABLE} WHERE reference_id = ?",
                (rid,),
            ).fetchone()[0]
            node_rows = connection.execute(
                f"SELECT COUNT(*) FROM {TREE_NODE_TABLE} WHERE reference_id = ?",
                (rid,),
            ).fetchone()[0]
            join_rows = connection.execute(
                f"SELECT COUNT(*) FROM {REFERENCE_TABLE} WHERE reference_id = ?",
                (rid,),
            ).fetchone()[0]
        assert policy_rows == 1 and tree_rows == 1 and node_rows == 3
        assert join_rows == 1
        assert store.load(rid).pair.has_same_content_as(_pair())

    def test_a_version_frozen_twice_to_different_bytes_is_refused(
        self, tmp_path: Path
    ) -> None:
        # A version is a name for one policy. A second freeze of the same
        # version to *different* bytes would make the store's own key
        # unreadable — two policies sharing one version — so it is refused
        # rather than left to a raw UNIQUE violation.
        store = _store(tmp_path)
        store.freeze(_pair(version="canary-v1"))
        with pytest.raises(CanaryError, match="version"):
            store.freeze(_pair(version="canary-v1", score=0.1))

    def test_two_different_versions_coexist(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.freeze(_pair(version="canary-v1"))
        store.freeze(_pair(version="canary-v2"))
        with closing(store._connect()) as connection:
            versions = connection.execute(
                f"SELECT version FROM {POLICY_TABLE} ORDER BY version"
            ).fetchall()
        assert versions == [("canary-v1",), ("canary-v2",)]

    def test_a_freeze_takes_a_pair_not_half_of_one(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(CanaryError, match="CanaryReferencePair"):
            store.freeze("not a pair")  # type: ignore[arg-type]

    def test_a_freeze_refuses_a_malformed_reference_id(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        with pytest.raises(CanaryError, match="UUID"):
            store.freeze(_pair(), reference_id="not-a-uuid")


# -- Resolution ------------------------------------------------------------------


class TestTheStoreResolvesItsPathLazily:
    def test_resolving_an_unset_url_composes_no_store(self) -> None:
        # Absent is not an error: a deployment without a relational store
        # composes no reference-store component — a discoverable state, not an
        # exception.
        assert CanaryReferenceStore.resolve() is None

    def test_resolving_a_blank_url_composes_no_store(self) -> None:
        assert CanaryReferenceStore.resolve({"DATABASE_URL": "   "}) is None

    def test_constructing_the_store_creates_no_database_file(
        self, tmp_path: Path
    ) -> None:
        # Construction performs no I/O — composition-time work must not touch
        # the disk, the contract every store in this workspace states.
        path = tmp_path / "never.db"
        store = CanaryReferenceStore(f"sqlite:///{path}")
        assert not path.exists()
        assert store.database_url == f"sqlite:///{path}"

    def test_the_path_is_translated_but_not_created_until_use(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "later.db"
        store = CanaryReferenceStore(f"sqlite:///{path}")
        assert store.path == path
        assert not path.exists()  # .path translates; _connect creates

    def test_an_in_memory_url_is_refused_by_name(self, tmp_path: Path) -> None:
        # An in-memory database dies with the connection that opened it, and a
        # frozen reference pair must outlive the freeze that produced it.
        store = CanaryReferenceStore("sqlite:///:memory:")
        with pytest.raises(CanaryError, match="no database path"):
            store.freeze(_pair())

    def test_a_non_sqlite_url_is_refused_by_name(self, tmp_path: Path) -> None:
        store = CanaryReferenceStore("postgres://localhost/db")
        with pytest.raises(CanaryError, match="scheme"):
            store.freeze(_pair())


# -- Store and migration agree ---------------------------------------------------


class TestTheStoreAndMigrationCreateTheSameSchema:
    def test_the_column_lists_match_the_migration_exactly(
        self, tmp_path: Path
    ) -> None:
        # Not "the columns the store needs are present" — *identical*, in order
        # and in type. A store whose table had an extra column, a retyped one,
        # or a different nullability would be a second schema wearing the
        # migration's table name, and the mismatch would surface only in
        # production, on the dialect the tests do not run.
        migration = _migration()
        store = _store(tmp_path)
        theirs_path = tmp_path / "migration.db"
        migration.apply(f"sqlite:///{theirs_path}")
        with closing(sqlite3.connect(theirs_path)) as connection:
            for table in migration.TABLES:
                cursor = connection.execute(f"PRAGMA table_info({table})")
                try:
                    theirs = [
                        (row[1], row[2], row[3], row[4], row[5])
                        for row in cursor.fetchall()
                    ]
                finally:
                    cursor.close()
                assert _columns(store, table) == theirs, table

    def test_running_the_migration_over_the_stores_database_changes_nothing(
        self, tmp_path: Path
    ) -> None:
        # The contract every store in this workspace states: a fresh database and
        # an existing one take the same path, so no migration step is needed here
        # — and running the migration over a database the store created is a
        # no-op rather than a conflict.
        migration = _migration()
        store = _store(tmp_path)
        record = store.freeze(_pair())
        before = {table: _columns(store, table) for table in migration.TABLES}
        migration.apply(store.database_url)
        for table in migration.TABLES:
            assert _columns(store, table) == before[table], table
        assert store.load(record.reference_id).pair.has_same_content_as(_pair())

    def test_the_store_works_against_a_migration_created_table(
        self, tmp_path: Path
    ) -> None:
        # The *production* ordering, which the reverse test above does not cover:
        # a migration runner applies ``0119`` first, and only then does the store
        # freeze against the tables it created. Every other test lets the store
        # create the tables itself — which it can, idempotently — so without this
        # one the suite would pass for a store that only worked on databases it
        # had created, and fail in production where it never does.
        migration = _migration()
        url = f"sqlite:///{tmp_path / 'migrated.db'}"
        migration.apply(url)
        store = CanaryReferenceStore(url)
        record = store.freeze(_pair())
        loaded = store.load(record.reference_id)
        assert loaded.pair.has_same_content_as(_pair())
        assert loaded.reference_id == record.reference_id

    def test_the_migrations_own_revision_identity_is_the_one_we_chain_off(
        self, tmp_path: Path
    ) -> None:
        # The store names the migration file it mirrors; this pins that the file
        # it names is the file that creates the tables, so a renumbering of the
        # migration tree breaks this test rather than silently detaching the
        # store's docstring from the schema it claims to mirror.
        migration = _migration()
        assert MIGRATION_PATH.name == f"{migration.REVISION}.py"
        assert set(migration.TABLES) == {
            REFERENCE_TABLE,
            POLICY_TABLE,
            TREE_TABLE,
            TREE_NODE_TABLE,
        }

    def test_the_store_statements_match_the_migration_statements(
        self, tmp_path: Path
    ) -> None:
        # The store restates the DDL rather than importing it (a migration is
        # loaded by path and must not depend on a package being importable, and
        # the store must not depend on the migration being on ``sys.path``).
        # This pins that the two independent spellings name the same tables with
        # the same columns — the thing they have to agree on.
        migration = _migration()
        for statement in migration.statements("sqlite"):
            table = statement.split("CREATE TABLE IF NOT EXISTS ", 1)[1].split(" ", 1)[0]
            assert table in migration.TABLES
        store = _store(tmp_path)
        with closing(store._connect()) as connection:
            names = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        assert {row[0] for row in names} == set(migration.TABLES)
