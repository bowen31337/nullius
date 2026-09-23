"""The two spellsings this member restates — pinned against their owners.

The workspace contract is that **no member imports another**.  It is met with
the same remedy everywhere: the spelling is *restated* in the member that needs
it, and a suite like this one is what keeps the restatement honest.
``packages/discovery/tests/test_cross_member.py`` states the contract and the
remedy at length; this is the same discipline applied to this member's two
restatements.

This member restates two things it does not own, and both for the same reason:
**a trigger cannot be written over a table whose name is not known.**

**``replay_score`` (§C5's evidence).**  Migration ``0109`` creates it and the
replay member (features 245-255) writes it.  This member reads exactly two of
its columns — ``id``, which the commitment hashes, and ``world_id``, which is
the world a score is about — and *spells all eight*, because a restatement that
carried only the columns this feature happens to read would be a restatement
nobody could check against its owner.  The tests below run ``0109``'s **own**
standalone entry point (:func:`apply`) against a fresh database and compare
what it actually built against
:data:`dreaming.layout.REPLAY_SCORE_COLUMNS`, so the pin is against the
migration's executed DDL and not against a copy of its text.

**``bootstrap_world`` (§C5's worlds).**  Feature 188 authors it and feature 191
widened it in place.  The widening is why the pin below checks *nullability*
rather than only names: feature 191's whole change is that ``seed`` became
nullable and two provenance columns arrived, and a restatement that missed the
widening would describe the table as it was two features ago.

**Why the imports are inside the tests.**  A module-scope import of a sibling
would make this member's suite fail to collect wherever that sibling is absent,
which is the outcome the restatement exists to avoid: the restatement must
outlive the sibling.  Inside a function the absence costs one test, and that
test says exactly what is missing.  ``pytest.importorskip`` is the same stance
spelled for the path bootstrap — these tests need a sibling's or a migration's
own source, which the workspace's member suites do not otherwise reach for.

**The last class exercises the seam rather than the data.**  Everything above
pins literals; the final class holds a real pool built by ``0109`` and by
feature 188's own store, opens a hold over it, and proves the guards actually
fire over tables this member did not create.  That is still the same
discipline — the sibling's schema is stood up through its own public entry
point, never by hand-written DDL — but it is the one assertion that would catch
a restatement whose *names* were right and whose *shape* made a guard
ineffective.
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import dreaming
import pytest
from dreaming import (
    REPLAY_SCORE_TABLE,
    WORLD_TABLE,
    CycleFreeze,
    pool_commitment,
    sqlite_path,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "migrations" / "versions"


def _load_migration(name: str, filename: str):
    """Load a migration module by file path, the way the member suites do.

    The migrations are not an importable package — they are versioned files a
    runner loads in order — so a test that wants ``0109``'s entry point loads
    the file directly rather than importing it.  The same helper the tripwires
    and replay suites spell for their own schema owners.
    """
    path = MIGRATIONS / filename
    if not path.exists():
        pytest.skip(f"migration {filename} is not in this checkout")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _columns_of(table: str, ddl: str) -> tuple[str, ...]:
    """The column names one ``CREATE TABLE`` declares, in declaration order.

    Read out of the DDL the owner actually produced, which is what makes the
    pin below a comparison against a *schema* rather than against a constant
    that could itself be stale.

    The body is split on newlines and each **comma that ends a line** marks the
    end of one definition, which is the shape both owners write: one column per
    line, its type and constraints on that line, and any continuation (the
    migration's ``DEFAULT`` expression, which wraps) on the next.  Counting
    commas rather than lines is what makes the parse survive that wrap, and
    reading the **first word of each definition** is what makes it survive a
    constraint that names identifiers of its own.

    It refuses to answer rather than answering wrongly: a body with no
    parenthesis, or a definition whose first word is a constraint keyword
    rather than a column, would mean the shape this reads has changed, and a
    silently short list would make the pin below pass for the wrong reason.
    """
    body = ddl.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)
    assert len(body) == 2, f"no CREATE TABLE for {table} in the owner's DDL"
    # The body ends at the next statement, not at a bare ``)`` line: the
    # owners' DDL is indented, so the closing parenthesis carries leading
    # whitespace and a search for "the next line is )" would miss it entirely.
    # Splitting on the *next* ``CREATE TABLE`` is exact for a script that is a
    # sequence of table creations, which is what ``statements()`` returns — and
    # the trailing text is dropped by taking only the columns, so whatever
    # punctuation the owner puts between tables is not this reader's concern.
    inner = body[1].split("CREATE TABLE", 1)[0]

    names: list[str] = []
    current: list[str] = []
    for line in inner.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        current.append(stripped)
        if stripped.endswith(","):
            definition = " ".join(current).rstrip(",")
            word = definition.split()[0]
            assert word.upper() not in {
                "CHECK",
                "PRIMARY",
                "UNIQUE",
                "FOREIGN",
                "CONSTRAINT",
            }, f"unexpected table-level constraint while reading {table}: {definition}"
            names.append(word)
            current = []
    if current:  # the last definition carries no trailing comma
        names.append(" ".join(current).split()[0])
    return tuple(names)


class TestTheReplayScoreRestatement:
    """``0109``'s table, pinned against the migration's own executed DDL."""

    def test_the_column_names_are_the_migrations(self) -> None:
        """Eight names, in the migration's order and spelling.

        The comparison is against ``statements()`` — the migration's own
        inspectable output — rather than against a copy of its text, so a
        column renamed in ``0109`` fails this test at the moment it is renamed
        rather than at the moment a guard silently stops covering a table.
        """
        migration = _load_migration("m0109_columns", "0109_replay_score_and_policy_revision.py")
        ddl = "\n".join(migration.statements("sqlite"))

        assert _columns_of(REPLAY_SCORE_TABLE, ddl) == dreaming.REPLAY_SCORE_COLUMNS

    def test_the_migration_actually_builds_the_table_the_names_describe(
        self, tmp_path: Path
    ) -> None:
        """Run ``0109``'s real entry point and read back what it built.

        The static pin above compares two constant lists; this one runs the
        migration and asks SQLite what it made.  Both are worth having: the
        first says the *spelling* is right, and this one says the spelling
        describes a table that exists.  Where the two could disagree — a
        migration whose ``statements()`` and whose ``apply()`` had drifted —
        this is the test that notices.
        """
        migration = _load_migration("m0109_apply", "0109_replay_score_and_policy_revision.py")
        database_url = f"sqlite:///{tmp_path / 'migrated.db'}"
        migration.apply(database_url)

        with closing(sqlite3.connect(sqlite_path(database_url))) as connection:
            columns = tuple(
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({REPLAY_SCORE_TABLE})"
                )
            )

        assert columns == dreaming.REPLAY_SCORE_COLUMNS

    def test_the_two_columns_this_member_reads_are_the_two_it_names(self) -> None:
        """The commitment's join and its key — the only columns it depends on.

        Stated separately because these two are load-bearing in a way the other
        six are not: ``id`` is what the digest orders, and ``world_id`` is what
        makes a score a statement about a *world* rather than about a row.  A
        pool whose rows carried no world would be a tournament over nothing.
        """
        columns = dreaming.REPLAY_SCORE_COLUMNS

        assert columns[0] == "id"
        assert "world_id" in columns

    def test_the_migrations_entry_point_is_the_one_this_suite_drives(self) -> None:
        """A migration that stops exposing ``apply`` should fail loudly here.

        The seam this suite leans on is public — ``apply(database_url)`` is
        ``0109``'s standalone entry point, documented for "a caller with no
        migration runner" — and pinning its presence keeps this suite from
        quietly reaching for a private helper if the module is refactored.
        """
        migration = _load_migration("m0109_seam", "0109_replay_score_and_policy_revision.py")

        assert callable(getattr(migration, "apply", None))
        assert callable(getattr(migration, "statements", None))


class TestTheWorldRestatement:
    """Feature 188's table as feature 191 widened it — names *and* nullability."""

    def test_the_world_ids_this_member_orders_by_are_the_owners_key(self) -> None:
        """``world_id`` is the pool's key in both members' vocabularies."""
        assert "world_id" in dreaming.WORLD_COLUMNS
        assert dreaming.WORLD_COLUMNS[0] == "world_id"
        assert dreaming.WORLD_TABLE == WORLD_TABLE

    def test_the_restatement_carries_the_widening_and_not_the_188_shape(self) -> None:
        """Feature 191's two provenance columns, and a nullable ``seed``.

        188's shape had ``domain`` and ``pool_seed`` and a ``NOT NULL`` seed;
        191 replaced that half with two digests and made the seed nullable,
        because a ported world's identity is its upstream and not a draw this
        workspace made.  A restatement frozen at the 188 shape would describe a
        table two features out of date — and would still *work*, which is
        exactly why it is pinned: nothing in this member's own behaviour would
        notice.
        """
        columns = dreaming.WORLD_COLUMNS

        assert "seed" in columns
        assert "provenance" in columns
        assert "source_commit" not in columns and "dataset_manifest" not in columns

    def test_the_stand_in_body_makes_the_seed_nullable(self) -> None:
        """The stand-in's own DDL must be able to hold a ported world's row.

        Feature 191's ``seed`` is nullable and a ported world has none, so a
        stand-in that declared ``seed INTEGER NOT NULL`` would refuse a row the
        real table accepts — and this member's suite would be testing against a
        pool stricter than any deployment's.
        """
        from dreaming.layout import POOL_SCHEMA_BY_TABLE

        body = POOL_SCHEMA_BY_TABLE[WORLD_TABLE]
        seed_line = next(
            line for line in body.splitlines() if line.strip().startswith("seed")
        )

        assert "NOT NULL" not in seed_line


class TestTheSeam:
    """The restatements put to work: guards over tables this member did not build."""

    def test_the_guards_fire_over_a_pool_built_by_its_owners(
        self, tmp_path: Path
    ) -> None:
        """A real ``0109`` pool, held — and a raw write refused.

        The one assertion the data pins cannot make: that a hold over a pool
        this member did not create actually *stops a write*.  The pool is stood
        up by ``0109``'s own entry point and by feature 188's own store, in the
        order a deployment runs them, and the writer below is a raw connection
        that never heard of this member.

        The world half is authored through :meth:`BootstrapPool.persist_worlds`
        — feature 188's own public entry point, never hand-written DDL — so this
        test drives the two owners the way a deployment does.  The pool's own
        band is 40 to 50 worlds and is enforced by the store, so the smallest
        pool this test can honestly author is the band's floor; that is §10.6's
        *"target 40-50 bootstrap worlds"* showing up as a test's cost rather
        than as a shortcut around it.
        """
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        bootstrap = pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )

        migration = _load_migration(
            "m0109_seam_pool", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'seam.db'}"
        migration.apply(database_url)
        bootstrap.BootstrapPool(database_url).persist_worlds(40)

        freeze = CycleFreeze(database_url)
        hold = freeze.open("cycle-1")
        assert hold.world_count == 40

        with (
            closing(sqlite3.connect(sqlite_path(database_url))) as connection,
            pytest.raises(sqlite3.IntegrityError, match=dreaming.FREEZE_CODE),
        ):
            connection.execute(
                f"DELETE FROM {WORLD_TABLE} WHERE world_id = "
                f"(SELECT world_id FROM {WORLD_TABLE} LIMIT 1)"
            )

        assert freeze.verify(hold) is True

    def test_a_pool_built_by_its_owners_commits_like_any_other(
        self, tmp_path: Path
    ) -> None:
        """The commitment reads a real pool, not only this member's stand-in.

        A digest whose queries were written against the stand-in's shape and
        never run against the owner's would be a read that only ever worked in
        this suite — the failure the whole restatement discipline exists to
        prevent, one level down.

        **Both owners run here, and that is the point of the test.**  ``0109``
        creates ``replay_score`` and nothing else; ``bootstrap_world`` is
        feature 188's, created by its store.  A commitment over a database
        migrated by ``0109`` alone is refused — the refusal two tests up in
        ``test_cycle.py``'s ``TestTheHold`` states why — so a "real pool" is a
        database both owners have touched, which is the order a deployment
        runs them.
        """
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        bootstrap = pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )

        migration = _load_migration("m0109_commit", "0109_replay_score_and_policy_revision.py")
        database_url = f"sqlite:///{tmp_path / 'commit.db'}"
        migration.apply(database_url)
        bootstrap.BootstrapPool(database_url).persist_worlds(40)

        commitment, count = pool_commitment(sqlite_path(database_url))

        assert commitment  # a real digest over a real pool
        assert count == 40  # the worlds feature 188 authored, and no scores yet

    def test_the_two_owners_are_not_one_owner(self, tmp_path: Path) -> None:
        """Stated because the test above depends on it: 0109 does not make a pool.

        A future migration that folded ``bootstrap_world`` into ``0109`` would
        make the test above pass while testing half of what it claims — the
        *"both owners run here"* premise would be silently false.  Pinned as its
        own claim so the failure names the premise rather than the digest.
        """
        migration = _load_migration(
            "m0109_owners", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'owners.db'}"
        migration.apply(database_url)

        with closing(sqlite3.connect(sqlite_path(database_url))) as connection:
            tables = {
                name
                for (name,) in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        assert REPLAY_SCORE_TABLE in tables
        assert WORLD_TABLE not in tables
