"""The DDL adapter: a member that owns no schema and still needs three tables.

Feature 291 writes one ``INSERT``, and that statement names one table whose
two columns are foreign keys — so the write is impossible until ``node``,
``epoch_ledger`` and ``promotion_registry`` all exist, and none of the three is
this member's to declare.  :mod:`promotion.schema` is the resolution:
:func:`~promotion.schema.bootstrap_schema` runs the *owning migrations'* own
``statements(dialect)`` tuples, loaded by file path, so this member authors no
DDL, spells no column and cannot drift from the schema's author.

**Why this is a suite of its own rather than four tests in the store's.**
Because its subject is a *claim about authorship*, and authorship is the kind
of claim that decays quietly: the tempting edit is one hand-written ``CREATE
TABLE IF NOT EXISTS promotion_registry`` "so the store does not have to load a
file", and it would keep every behavioural test green while putting a second
spelling of the table into the tree.  The tests here are the ones that fail
when that edit is made.

**The three migrations are deliberately not a preference.**
``0108`` declares ``REQUIRES_TABLES = ("node", "epoch_ledger")`` — it *punts*
the creation of its own foreign keys' parents to whoever runs it — so a
bootstrap that ran only ``0108`` would fail its first ``INSERT`` on SQLite
with ``no such table: main.<one of the two>`` — the parent SQLite names is its
own business, but it names one this member does not own, and one that ran them
in the wrong order would fail the same way for the same reason.  Both are
asserted here, on real connections, because both are facts about SQLite rather
than opinions about layering.

**What is *not* over-created.**  ``0108`` creates five tables besides
``promotion_registry``.  The store runs that migration's whole statement tuple
rather than lifting one statement out of it — taking one statement would be
this member editing another's schema, where running the tuple is what "the
migration is the author" means — and nothing is over-created by doing so:
every statement is ``IF NOT EXISTS``, and the extra tables (``forward_record``
among them) are where their own features' writers already expect them.  That
is asserted too, so the decision is visible rather than incidental.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import MIGRATION_REVISIONS, _load_migration
from promotion import MIGRATION_ORDER, PROMOTION_REGISTRY_TABLE
from promotion import schema as schema_module
from promotion.schema import bootstrap_schema, migrations_dir

#: The two tables ``0108``'s ``REQUIRES_TABLES`` names — the parents its own
#: ``promotion_registry`` foreign keys point at, and the reason this member has
#: a migration *order* rather than a single revision.
PARENTS = ("node", "epoch_ledger")

#: The five tables ``0108`` creates besides ``promotion_registry``.  Named here
#: so the "runs the whole tuple" decision is pinned as a fact: a later edit
#: that curated the statement list down to the tables this feature uses would
#: fail this test, and the failure would say what was lost.
NEIGHBOURS = (
    "forward_record",
    "universe_membership",
    "universe_price_history",
    "universe_survivorship_audit",
    "snapshot_manifest",
)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }


# -- The claim about authorship ----------------------------------------------------


def test_the_member_authors_no_ddl_and_the_migrations_do() -> None:
    # Both halves, because only the pair means anything: the member holds no
    # ``CREATE`` of its own, and the files it names do.  A test that asserted
    # only the first would pass for a member that shipped no schema at all.
    from conftest import code_of

    member_code = code_of(schema_module)
    assert "CREATE TABLE" not in member_code
    assert "CREATE INDEX" not in member_code
    for revision in MIGRATION_REVISIONS:
        assert "CREATE TABLE" in code_of(_load_migration(revision)), revision


def test_the_migration_order_names_one_file_per_table() -> None:
    # The pair is the point: a table name beside the file that owns it, so a
    # reader sees both that this module spells no column and which file to read
    # to learn one.  Asserted against the tree's own file list, so a rename is
    # caught here rather than at the first write against a fresh database.
    assert [table for table, _revision in MIGRATION_ORDER] == [
        "node",
        *PARENTS[1:],
        PROMOTION_REGISTRY_TABLE,
    ]
    assert [revision for _table, revision in MIGRATION_ORDER] == list(
        MIGRATION_REVISIONS
    )
    for _table, revision in MIGRATION_ORDER:
        assert (migrations_dir() / f"{revision}.py").is_file(), revision


def test_migrations_dir_is_resolved_from_the_file_not_the_cwd(monkeypatch, tmp_path: Path) -> None:
    # A store is constructed from wherever the caller happens to run — a
    # test's tmp_path, an operator's shell — so a bootstrap that depended on
    # the working directory would work in one and fail in the rest.
    monkeypatch.chdir(tmp_path)
    assert migrations_dir().is_absolute()
    assert migrations_dir().is_dir()
    assert set(MIGRATION_REVISIONS) <= {
        path.stem for path in migrations_dir().glob("*.py")
    }


def test_a_missing_owner_is_refused_in_this_members_vocabulary(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(migrations_dir, "__wrapped__", None, raising=False)
    monkeypatch.setattr(schema_module, "migrations_dir", lambda: tmp_path / "gone")
    with pytest.raises(Exception) as raised:
        bootstrap_schema(sqlite3.connect(":memory:"))
    assert type(raised.value).__name__ == "PromotionError"
    assert MIGRATION_ORDER[0][1] in str(raised.value)


# -- The statements ----------------------------------------------------------------


def test_the_statements_are_the_migrations_own_tuple_for_tuple() -> None:
    # Not "agree with" — *are*.  This is the property that makes drift
    # impossible rather than merely unlikely: there is one set of statements
    # and this runs it, where a member that restated the DDL could at best
    # claim its copy matched.
    from promotion.schema import _statements

    expected: list[str] = []
    for _table, revision in MIGRATION_ORDER:
        expected.extend(_load_migration(revision).statements("sqlite"))
    assert list(_statements("sqlite")) == expected
    assert list(_statements()) == expected  # the dialect's own default


def test_the_statements_are_idempotent() -> None:
    # Which is what lets a fresh database, a fully migrated one and one this
    # store created earlier all take the same path — and what makes running
    # the migrations over a database this store created change nothing.
    from promotion.schema import _statements

    for statement in _statements("sqlite"):
        assert "IF NOT EXISTS" in statement, statement.splitlines()[0]


def test_the_whole_of_each_named_migration_is_run() -> None:
    # Zero authored DDL means the *migrations'* tuples arrive whole, including
    # the tables this feature does not touch.  Lifting one statement out of
    # ``0108`` would be this member editing another's schema; running the tuple
    # is what "the migration is the author" means.  The extra tables are where
    # their own features' writers already expect them, and every statement is
    # ``IF NOT EXISTS``, so nothing is over-created.
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        bootstrap_schema(connection)
        present = _tables(connection)
    finally:
        connection.close()
    assert {PROMOTION_REGISTRY_TABLE, *PARENTS} <= present
    assert set(NEIGHBOURS) <= present


# -- The order, which is a fact about SQLite ---------------------------------------


def test_the_order_is_the_chains_and_sqlites_tolerance_is_not_the_reason() -> None:
    # The fact both ``0108`` and ``0110`` state, asserted rather than quoted:
    # **SQLite does not resolve a foreign key's parent until a row is
    # written**, so the three statements would be accepted in *any* order
    # there.  ``0108``'s words for that are the ones to keep — *"That is a
    # tolerance, not a licence: the dependency is real"* — so this test pins
    # the tolerance (so a later reader cannot mistake the order for a
    # requirement SQLite imposes) *and* the dependency it is not a licence to
    # ignore (the next test).
    registry_statements = [
        statement
        for statement in _load_migration(MIGRATION_REVISIONS[-1]).statements("sqlite")
        if PROMOTION_REGISTRY_TABLE in statement
    ]
    assert len(registry_statements) == 1

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        # Declared *first*, with neither parent present, and accepted.
        connection.execute(registry_statements[0])
        assert PROMOTION_REGISTRY_TABLE in _tables(connection)
        # ...and the tolerance ends the moment a row is written.  SQLite names
        # *one* of the two missing parents rather than both, and which one is
        # its own business — so the assertion is that the failure names a
        # parent this member does not own, not which of the two it chose.
        with pytest.raises(sqlite3.OperationalError) as raised:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} (node_id, epoch_id, "
                "criteria_hash, pre_registered_at) VALUES (?, ?, ?, ?)",
                ("11111111-1111-4111-8111-111111111111", "e", "0" * 64, "2026-01-01"),
            )
        assert "no such table: main." in str(raised.value)
        assert any(parent in str(raised.value) for parent in PARENTS)
    finally:
        connection.close()


def test_the_three_tables_are_a_set_because_the_insert_needs_all_three() -> None:
    # The real dependency, on the connection settings the store uses: a
    # registry table *without* its parents is a database on which every
    # pre-registration fails, naming a table this member has no business
    # creating.  That — not the ``CREATE TABLE`` order — is what makes the
    # bootstrap three tables rather than one, so it is the half asserted here.
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        for statement in _load_migration(MIGRATION_REVISIONS[-1]).statements("sqlite"):
            if PROMOTION_REGISTRY_TABLE in statement:
                connection.execute(statement)
        with pytest.raises(sqlite3.OperationalError) as raised:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} (node_id, epoch_id, "
                "criteria_hash, pre_registered_at) VALUES (?, ?, ?, ?)",
                ("11111111-1111-4111-8111-111111111111", "e", "0" * 64, "2026-01-01"),
            )
        assert "no such table: main." in str(raised.value)
        assert any(parent in str(raised.value) for parent in PARENTS)
    finally:
        connection.close()

    # And the bootstrap's whole set is what makes the write possible.
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        bootstrap_schema(connection)
        with pytest.raises(sqlite3.IntegrityError) as raised:
            # Now the parents exist and the *rows* do not: a different
            # failure, and the one the probes in the store name by hand.
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} (node_id, epoch_id, "
                "criteria_hash, pre_registered_at) VALUES (?, ?, ?, ?)",
                ("11111111-1111-4111-8111-111111111111", "e", "0" * 64, "2026-01-01"),
            )
        assert "FOREIGN KEY" in str(raised.value)
    finally:
        connection.close()


def test_the_migrations_own_requires_tables_are_the_two_this_member_runs_first() -> None:
    # The order is not this member's invention: it is ``0108``'s own declared
    # dependency, read off the file rather than assumed.  If that migration's
    # ``REQUIRES_TABLES`` ever grew, this test is where the new parent would
    # have to be answered — which is the point of reading it rather than
    # restating it.
    schedule = _load_migration(MIGRATION_REVISIONS[-1])
    assert tuple(schedule.REQUIRES_TABLES) == PARENTS
    assert [table for table, _revision in MIGRATION_ORDER][:-1] == list(PARENTS)


def test_the_owning_migration_and_this_member_agree_on_the_table_name() -> None:
    # The one string both sides must spell the same.  Read off the migration's
    # own ``TABLES`` rather than off its DDL text, so the assertion is about
    # the migration's declared surface.
    assert PROMOTION_REGISTRY_TABLE in tuple(_load_migration(MIGRATION_REVISIONS[-1]).TABLES)


# -- What the store actually builds -------------------------------------------------


def test_a_fresh_database_gets_the_schema_the_migrations_describe(
    tmp_path: Path, migrations
) -> None:
    # Both creators on two fresh files, compared as ``sqlite_master`` *text*:
    # the store's schema and the migrations' schema are one schema, and the
    # comparison is against the migrations rather than against a hand-written
    # expectation, so it cannot be satisfied by the suite and the member
    # agreeing with each other.
    from promotion import PreRegistrations

    with_store = f"sqlite:///{tmp_path / 'store.db'}"
    PreRegistrations(with_store)._connect().close()
    with_migrations = f"sqlite:///{tmp_path / 'migrations.db'}"
    for migration in migrations:
        migration.apply(with_migrations)

    def schema(url: str) -> list[tuple[str, str]]:
        connection = sqlite3.connect(url.removeprefix("sqlite:///"))
        try:
            return connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' "
                "ORDER BY name"
            ).fetchall()
        finally:
            connection.close()

    assert schema(with_store) == schema(with_migrations)
    assert len(schema(with_store)) >= len(PARENTS) + 1


def test_bootstrapping_twice_changes_nothing(tmp_path: Path) -> None:
    # Idempotent by construction, asserted rather than assumed — the store
    # calls it on every connect, so a bootstrap that re-created anything would
    # drop a populated database on the second write.
    from promotion import PreRegistrations

    url = f"sqlite:///{tmp_path / 'twice.db'}"
    store = PreRegistrations(url)
    first = store._connect()
    try:
        first.execute(
            "INSERT INTO node (id, campaign_id, theme_root, depth) VALUES (?, ?, ?, ?)",
            ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "macro", 1),
        )
        first.commit()
    finally:
        first.close()
    second = store._connect()
    try:
        assert second.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 1
    finally:
        second.close()
