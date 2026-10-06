"""The migration tree must build a fresh database, in chain order.

Bug: 0113-0117 alter or index the ``node`` table before 0118 creates it, so
applying ``migrations/versions/0*.py`` in chain order (each file's own
``apply(database_url)``) to an empty SQLite database used to fail at 0113
with ``sqlite3.OperationalError: no such table: main.node`` — 0118, which
creates the five-column skeleton, only succeeded once it ran first by hand.

Every migration file is loaded by path (``importlib.util.spec_from_file_location``),
not by package import, the same convention the migrations themselves use (see
e.g. ``migrations/versions/0113_node_indexes.py``'s ``_sqlite_path`` docstring)
— a migration must not depend on a workspace package being importable to run.
"""

from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlparse

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations" / "versions"

#: Every migration file, in chain order — the filename's own ``NNNN`` prefix
#: numeric-sorts to the same order as the assembled ``DOWN_REVISION`` chain.
MIGRATION_FILES = sorted(MIGRATIONS_DIR.glob("0*.py"))

#: The tables the operator CLIs (``canary``, ``dream``, ``closeout``, ...) read,
#: per the bug's "Reproduce" evidence: a fresh build must create every one.
OPERATOR_TABLES = (
    "replay_score",
    "policy_revision",
    "node",
    "campaign",
    "trial_ledger",
    "canary_reference",
)


def _load_migration(path: Path) -> ModuleType:
    """Load a migration module from its file, independent of ``sys.path``."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply_tree(database_url: str) -> None:
    """Apply every migration file to ``database_url``, in chain order."""
    for path in MIGRATION_FILES:
        _load_migration(path).apply(database_url)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path (test-local copy
    of the same helper every migration file carries, so this file does not
    depend on importing one of them for it)."""
    parsed = urlparse(database_url)
    path = unquote(parsed.path).removeprefix("/")
    return Path(path)


def _connect(database_url: str) -> sqlite3.Connection:
    connection = sqlite3.connect(_sqlite_path(database_url))
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row[0] for row in rows}


def _table_info(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return connection.execute(f"PRAGMA table_info({table})").fetchall()


def _index_list(connection: sqlite3.Connection, table: str) -> list[tuple]:
    return connection.execute(f"PRAGMA index_list({table})").fetchall()


def _index_columns(connection: sqlite3.Connection, index: str) -> list[tuple]:
    return connection.execute(f"PRAGMA index_info({index})").fetchall()


def test_fresh_tree_reaches_head(test_database_url: str) -> None:
    """Every file's ``apply()`` returns normally against an empty database,
    and the chain is walked all the way to its head — the last file's own
    tables exist, not just an early file's.
    """
    _apply_tree(test_database_url)

    head = _load_migration(MIGRATION_FILES[-1])
    assert head.REVISION == "0119_canary_reference_pair"
    assert head.DOWN_REVISION == "0118_node_table"

    with _connect(test_database_url) as connection:
        names = _table_names(connection)
        assert "node" in names
        missing_head_tables = set(head.TABLES) - names
        assert not missing_head_tables, (
            f"head's own tables missing after a fresh build: {sorted(missing_head_tables)}"
        )


def test_fresh_tree_creates_the_tables_operator_clis_read(
    test_database_url: str,
) -> None:
    _apply_tree(test_database_url)

    with _connect(test_database_url) as connection:
        names = _table_names(connection)

    missing = set(OPERATOR_TABLES) - names
    assert not missing, f"operator tables missing after a fresh build: {sorted(missing)}"


def test_fresh_tree_is_idempotent(test_database_url: str) -> None:
    """Applying the whole tree twice changes nothing on the second pass."""
    _apply_tree(test_database_url)
    with _connect(test_database_url) as connection:
        before_tables = sorted(_table_names(connection))
        before_node = _table_info(connection, "node")
        before_node_indexes = _index_list(connection, "node")

    _apply_tree(test_database_url)  # must not raise

    with _connect(test_database_url) as connection:
        after_tables = sorted(_table_names(connection))
        after_node = _table_info(connection, "node")
        after_node_indexes = _index_list(connection, "node")

    assert after_tables == before_tables
    assert after_node == before_node
    assert after_node_indexes == before_node_indexes


def test_node_schema_is_the_same_whether_0118_or_0113_creates_it(
    tmp_path: Path,
) -> None:
    """0113's node skeleton (created when the table is absent) must match
    0118's — same ``CREATE TABLE IF NOT EXISTS``, same five columns, same
    self-referencing ``parent_id`` foreign key — whichever of the two actually
    creates the table on a given database.
    """
    node_table_module = _load_migration(MIGRATIONS_DIR / "0118_node_table.py")

    # A fresh database: 0113 is the first file to touch `node`, so it is the
    # one that creates the table here.
    fresh_url = f"sqlite:///{tmp_path / 'fresh.db'}"
    _apply_tree(fresh_url)

    # A database where `node` already existed before 0113 ran — the way a
    # store's own `CREATE TABLE IF NOT EXISTS` would leave it, or an older
    # chain. 0113 then finds the table already there and 0118 is the no-op.
    preexisting_url = f"sqlite:///{tmp_path / 'preexisting.db'}"
    with _connect(preexisting_url) as connection:
        node_table_module.upgrade(connection)
    _apply_tree(preexisting_url)

    with _connect(fresh_url) as fresh, _connect(preexisting_url) as preexisting:
        assert _table_info(fresh, "node") == _table_info(preexisting, "node")

        fresh_indexes = sorted(row[1] for row in _index_list(fresh, "node"))
        preexisting_indexes = sorted(
            row[1] for row in _index_list(preexisting, "node")
        )
        assert fresh_indexes == preexisting_indexes
        for index in fresh_indexes:
            assert _index_columns(fresh, index) == _index_columns(
                preexisting, index
            )
