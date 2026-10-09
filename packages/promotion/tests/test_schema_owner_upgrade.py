"""The registry bootstrap runs owners' ``upgrade()``, not their ``statements()``.

``0118_node_table``'s own :func:`upgrade` does more than its ``statements()``
list returns: it also re-runs ``0113_node_indexes``'s :func:`upgrade` once
every node column that revision's index statements need has landed, which is
how the assembled migration chain ends up carrying
``node_campaign_id_parent_id`` on a database the chain brought up.  A
bootstrap built from ``statements()`` text alone never ran that second call,
so a store-created database diverged from a migrated one on that one index —
the gap ``test_the_store_and_the_migrations_converge_either_way_round``
(``test_promotion_pre_register.py``) catches.

This file pins the fix at :func:`promotion.schema.bootstrap_schema` directly:
its returned DDL carries the backfilled index, a second call changes nothing,
and an owner's ``upgrade`` that raises is surfaced in this member's own
refusal vocabulary rather than whatever exception class happened to come out
of the migration.
"""

from __future__ import annotations

import sqlite3

import pytest
from promotion import MIGRATION_ORDER, PromotionError, PromotionStoreError
from promotion import schema as schema_module
from promotion.schema import bootstrap_schema

#: The index ``0113_node_indexes`` can always create off the base node
#: skeleton alone — ``campaign_id`` and ``parent_id`` are both feature 97's
#: own columns, so unlike the other two indexes this one needs no column a
#: later revision adds.  It is the one a bootstrap built from 0118's
#: ``statements()`` text never carried.
BACKFILLED_INDEX = "node_campaign_id_parent_id"

#: The revision ``MIGRATION_ORDER`` names for ``node`` — the one owner whose
#: ``upgrade`` does more than its own ``statements()``.
NODE_REVISION = "0118_node_table"


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _indexes(connection: sqlite3.Connection) -> set[str]:
    return {
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }


def test_the_bootstraps_returned_ddl_carries_the_backfilled_index() -> None:
    # Not "the schema ends up right" (the convergence test already pins that)
    # but "the function says so" — the DDL the fix returns is the DDL it ran,
    # and that now includes the statement a ``statements()``-only bootstrap
    # could never produce, because no entry in :data:`MIGRATION_ORDER` names
    # ``0113_node_indexes`` by itself.
    connection = _connection()
    try:
        ran = bootstrap_schema(connection)
        assert any(BACKFILLED_INDEX in statement for statement in ran)
        assert BACKFILLED_INDEX in _indexes(connection)
    finally:
        connection.close()


def test_a_second_bootstrap_changes_no_table_and_no_index() -> None:
    # Every owner's upgrade is idempotent, and that stays true for this
    # store: the schema after a second call is the schema after the first,
    # index included — the law the earlier "left exactly as it was" test
    # pins for the tables, restated here for the index this fix adds.
    connection = _connection()
    try:
        bootstrap_schema(connection)
        before = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        bootstrap_schema(connection)
        after = connection.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
    finally:
        connection.close()
    assert before == after
    assert BACKFILLED_INDEX in {name for _kind, name, _sql in before}


def test_an_owner_upgrade_that_raises_is_a_store_refusal_naming_the_revision(
    monkeypatch,
) -> None:
    # The migration is the schema's author; this module only runs it.  When
    # the thing it runs raises, the caller must not see whatever exception
    # class a migration happens to use internally — every other way this
    # bootstrap can fail already surfaces as PromotionStoreError, and an
    # owner's upgrade failing is one more.
    owner = schema_module._load_migration(NODE_REVISION)

    def _raises(connection: object, dialect: object = None) -> tuple[str, ...]:
        raise RuntimeError("the owner's own upgrade refused")

    monkeypatch.setattr(owner, "upgrade", _raises)
    connection = _connection()
    try:
        with pytest.raises(PromotionStoreError) as raised:
            bootstrap_schema(connection)
    finally:
        connection.close()
    assert NODE_REVISION in str(raised.value)
    assert "the owner's own upgrade refused" in str(raised.value)


def test_the_revisions_own_promotion_error_is_not_rewrapped(monkeypatch) -> None:
    # A migration cannot raise this member's own vocabulary today — none
    # imports it — but a caller's standing ``except PromotionError`` must not
    # be defeated by this fix wrapping a refusal that already arrived in it,
    # the same discipline :func:`promotion.schema._load_migration` keeps for
    # a missing file.
    owner = schema_module._load_migration(NODE_REVISION)

    def _refuses(connection: object, dialect: object = None) -> tuple[str, ...]:
        raise PromotionError("a refusal already in this member's vocabulary")

    monkeypatch.setattr(owner, "upgrade", _refuses)
    connection = _connection()
    try:
        with pytest.raises(PromotionError) as raised:
            bootstrap_schema(connection)
    finally:
        connection.close()
    assert not isinstance(raised.value, PromotionStoreError)
    assert "already in this member's vocabulary" in str(raised.value)


def test_the_node_owner_is_still_0118() -> None:
    # This fix leans on :data:`MIGRATION_ORDER` naming ``0118_node_table`` for
    # ``node`` — if a later edit changed the owner, the two tests above would
    # start exercising the wrong revision's upgrade silently. Pinned here so
    # that drift fails loudly instead.
    assert dict(MIGRATION_ORDER)["node"] == NODE_REVISION
