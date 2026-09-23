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

import datetime as dt
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
    HoldoutRecordError,
    PairedComparisonError,
    TransferStoreError,
    pool_commitment,
    pooled_family_transfer,
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


class TestTheSplitSeam:
    """The split's membership read, pinned against the owners' own census.

    Feature 278 restates one law it does not own — *what a world of the pool
    is* — the same way it restates the pool's table names: spelled here, never
    imported, because no member in this workspace imports another.  The law
    is the union — ``bootstrap_world``'s rows plus ``replay_score``'s distinct
    worlds, a world once whichever half names it — and feature 186 already
    states it from the other side of the member boundary
    (:func:`bootstrap.world_census`, whose ``n_financial`` is the distinct
    score worlds the bootstrap pool does not hold).  The tests below stand a
    pool up through both owners' own entry points and pin the two spellings
    against each other: the split's enumeration, the census's two figures,
    and one shared world that both halves name, counted once.
    """

    def _owners_pool(self, tmp_path: Path) -> str:
        """A pool both owners built: migrated by ``0109``, authored by 188.

        The same stand-up ``TestTheSeam`` spells, returned as a URL so a test
        can read it through this member and through the bootstrap pool with
        no second construction.  The store's 40-50 band is its own floor, so
        forty worlds is the smallest pool this helper can honestly author.
        """
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        bootstrap = pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )

        migration = _load_migration(
            "m0109_split", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'split-seam.db'}"
        migration.apply(database_url)
        bootstrap.BootstrapPool(database_url).persist_worlds(40)
        return database_url

    def _write_scores(self, url: str, financial_ids: tuple[str, ...]) -> str:
        """Score rows over the given financial worlds and one shared world.

        Writes through ``0109``'s own eight columns, raw — the replay member's
        writer is not this member's to drive — and deliberately names one
        *bootstrap* world too, because an authored world that has been
        replayed is the honest shape of a dreaming pool and the one row that
        makes the union law do work: both halves name that world, and every
        read below must still hold it once.  Returns the shared world's id.
        """
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            shared = connection.execute(
                f"SELECT world_id FROM {WORLD_TABLE} LIMIT 1"
            ).fetchone()[0]
            for world_id in (*financial_ids, shared):
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-{world_id}",
                        "pi-0",
                        world_id,
                        0.0,
                        1.0,
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )
        return shared

    def test_the_enumeration_is_the_census(self, tmp_path: Path) -> None:
        """One law, two members, one figure: 40 authored + 3 financial = 43.

        The split's ``pool_worlds`` and feature 186's ``world_census`` each
        spell the pool's membership without importing the other, so the pin
        is the only thing that keeps them one law: a census that grew a third
        figure, or an enumeration that started counting score rows, breaks
        this test the moment it drifts.
        """
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )
        from bootstrap import BootstrapPool, world_census

        url = self._owners_pool(tmp_path)
        self._write_scores(url, ("world-fin-1", "world-fin-2", "world-fin-3"))

        worlds = dreaming.pool_worlds(sqlite_path(url))
        census = world_census(BootstrapPool(url))

        assert len(worlds) == 43
        assert census.n_bootstrap == 40
        assert census.n_financial == 3  # the shared world is not financial
        assert len(worlds) == census.n_bootstrap + census.n_financial

    def test_a_world_both_halves_name_is_held_once(self, tmp_path: Path) -> None:
        """The row that makes the union do work: one world, two tables, once.

        The shared world is in ``bootstrap_world`` *and* in
        ``replay_score`` — the census counts it as bootstrap and not
        financial, and the split's enumeration must count it once, in id
        order with the rest, rather than twice or once per score row.
        """
        url = self._owners_pool(tmp_path)
        shared = self._write_scores(url, ("world-fin-1",))

        worlds = dreaming.pool_worlds(sqlite_path(url))

        assert worlds.count(shared) == 1
        assert worlds == tuple(sorted(worlds))
        assert shared in worlds and "world-fin-1" in worlds

    def test_the_owners_pool_splits(self, tmp_path: Path) -> None:
        """The feature's own call over a pool this member did not build.

        43 worlds split 30/13 — the odd world's remainder (0.9 against 0.1)
        outbids for the holdout — and every world the owners put in the pool
        lands on exactly one side, which is the disjointness the paired
        statistic (feature 281) and the bar (feature 280) stand on.
        """
        url = self._owners_pool(tmp_path)
        self._write_scores(url, ("world-fin-1", "world-fin-2", "world-fin-3"))

        split = dreaming.split_replay_pool(database_url=url)

        assert len(split.train) == 30
        assert len(split.holdout) == 13
        assert not (set(split.train) & set(split.holdout))
        assert set(split.train) | set(split.holdout) == set(
            dreaming.pool_worlds(sqlite_path(url))
        )


class TestTheComparisonSeam:
    """The paired statistic's read, pinned against ``0109``'s own built table.

    Feature 281 reads two columns of a table it does not own — ``world_id``,
    which is what makes two readings *pair*, and ``score``, which is the
    out-of-sample IR §11.0 compares — and the read is the feature's whole
    claim: §10.3.1's *"same policy pair on the same worlds"* is true here only
    because both arms come out of one table keyed by world, so a world only one
    arm was replayed against is **refused** rather than silently dropped.

    The tests below stand a pool up through ``0109``'s **real** ``apply()`` —
    not this member's stand-in DDL, which the member's own suite uses — and
    compare over it.  That is the same discipline the classes above apply to
    the restatement, turned on the read: what makes the pairing a fact about
    the store rather than about this member's opinion of it is that the
    *owner's* table is the one the arms are read from.
    """

    def _migrated_pool(self, tmp_path: Path) -> str:
        """A database ``0109`` built, holding two arms over three shared worlds.

        The arms differ by more than a constant on purpose: a pair whose every
        world moved by the same amount is refused by the statistic itself (a
        standard error of exactly zero), so a fixture that wrote ``pi-0`` and
        ``pi-1`` as one figure shifted would exercise the refusal rather than
        the comparison.
        """
        migration = _load_migration(
            "m0109_paired", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'paired-seam.db'}"
        migration.apply(database_url)

        baselines = {"world-a": 0.10, "world-b": 0.20, "world-c": 0.30}
        candidate = {"world-a": 0.40, "world-b": 0.65, "world-c": 0.50}
        with closing(sqlite3.connect(sqlite_path(database_url))) as connection, connection:
            for policy, readings in (("pi-0", baselines), ("pi-1", candidate)):
                for world_id, score in readings.items():
                    connection.execute(
                        f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                        "world_id, beta, score, committed_pick, is_holdout, "
                        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"score-{policy}-{world_id}",
                            policy,
                            world_id,
                            0.0,
                            score,
                            None,
                            0,
                            "2026-01-01T00:00:00Z",
                        ),
                    )
        return database_url

    def test_the_arms_are_read_from_the_owners_own_table(self, tmp_path: Path) -> None:
        """The feature's call over a pool the migration built, not this member's stand-in.

        The comparison's two numbers — the mean paired difference and the
        worlds it was taken over — are computed here independently from the
        figures written above, so the agreement is about the *read* and not
        about the statistic agreeing with itself.
        """
        url = self._migrated_pool(tmp_path)

        record = dreaming.paired_pool_difference(
            "pi-1", "pi-0", database_url=url
        )

        differences = (0.30, 0.45, 0.20)
        assert record.paired_worlds == 3
        assert record.mean_difference == pytest.approx(sum(differences) / 3)
        assert set(dict(record.differences)) == {"world-a", "world-b", "world-c"}

    def test_a_world_only_one_arm_was_replayed_against_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The unpaired case, over the owner's table rather than a hand-built one.

        A partially-replayed pool is the ordinary way this state arrives, and
        dropping the unshared world is the tempting edit that would turn
        §10.3.1's paired comparison into the unpaired one §11.0 rejects.  The
        refusal has to come from the store read as well as from a caller
        holding two dicts, which is what this pins.
        """
        url = self._migrated_pool(tmp_path)
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            connection.execute(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                "world_id, beta, score, committed_pick, is_holdout, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "score-pi-1-world-d",
                    "pi-1",
                    "world-d",
                    0.0,
                    0.9,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )

        with pytest.raises(dreaming.PairedComparisonError) as refusal:
            dreaming.paired_pool_difference("pi-1", "pi-0", database_url=url)

        assert "world-d" in str(refusal.value)

    def test_a_third_policys_rows_are_not_paired_in(self, tmp_path: Path) -> None:
        """The read selects the two arms it was asked for, and no others.

        ``replay_score`` holds every policy the pool has ever replayed, so a
        read without its ``policy_version`` predicate would pair a candidate
        against whichever rows happened to sort last — and the figures would
        look like a comparison of two named arms.  This is the store-side
        version of the same discipline the module's single-``policy_version``
        read states in its docstring, pinned by putting a third arm in the
        table and checking it changes nothing.

        The claim is deliberately narrow because ``0109`` alone builds one
        table: the split's agreement (feature 278's own cross-member class
        names feature 281 as the consumer of its disjointness) needs
        ``bootstrap_world`` too, which the bootstrap member authors, and is
        pinned from that side rather than restated here.
        """
        url = self._migrated_pool(tmp_path)
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            connection.execute(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                "world_id, beta, score, committed_pick, is_holdout, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "score-pi-2-world-a",
                    "pi-2",
                    "world-a",
                    0.0,
                    99.0,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )

        record = dreaming.paired_pool_difference("pi-1", "pi-0", database_url=url)

        assert record.paired_worlds == 3
        assert record.mean_difference == pytest.approx((0.30 + 0.45 + 0.20) / 3)
        # The third arm's 99.0 reading is in the table and not in the comparison.
        assert max(abs(value) for _, value in record.differences) < 1.0


class TestTheTransferSeam:
    """The family holdout's reads, pinned against the owners' own pool.

    Feature 282 reads the pool through two laws it does not own: the
    membership (:func:`dreaming.pool_worlds`'s union, feature 278's
    restatement) and the arms (:func:`dreaming.paired._pool_arm`, feature
    281's read).  The family census itself is the caller's fact — no column
    of either table carries it — so what this class pins is the seam over
    the *owners'* tables: a pool built by ``0109`` and feature 188's store,
    both arms read from the owner's own ``replay_score``, and the transfer
    taken over a family the caller declares.  The same discipline the split
    and the comparison seams above apply, turned on the family-shaped
    holdout: what makes the held-out family a fact about one pool rather
    than about this member's opinion of it is that the owner's tables are
    what the figure was read from.
    """

    #: The financial family's worlds — the roots a dreaming pool's replayed
    #: half carries.  Deliberately not a theme of feature 241's default set
    #: for the retained root: this seam tests the *read*, not the config, and
    #: a slug the legal set happens to carry would suggest the set was
    #: consulted here when no member may consult another's.
    FINANCIAL_ROOT = "momentum"
    AUTHORED_ROOT = "hpo"

    def _owners_pool(self, tmp_path: Path) -> str:
        """A pool both owners built: migrated by ``0109``, authored by 188."""
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        bootstrap = pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )

        migration = _load_migration(
            "m0109_transfer", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'transfer-seam.db'}"
        migration.apply(database_url)
        bootstrap.BootstrapPool(database_url).persist_worlds(40)
        return database_url

    def _write_two_arms(self, url: str) -> tuple[dict[str, float], dict[str, float]]:
        """Both arms' readings over the financial worlds and one authored one.

        Written through ``0109``'s own eight columns, raw — the replay
        member's writer is not this member's to drive.  The authored world is
        named on purpose: a world that is in ``bootstrap_world`` *and* scored
        is the honest shape of a dreaming pool, and holding the financial
        family out must leave that world retained — the restriction is by
        family, not by replay presence.  Returns the two arms in
        (candidate, baseline) order for the independent arithmetic below.
        """
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            authored = connection.execute(
                f"SELECT world_id FROM {WORLD_TABLE} LIMIT 1"
            ).fetchone()[0]
            for world_id in ("world-fin-1", "world-fin-2", "world-fin-3", authored):
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-pi-0-{world_id}",
                        "pi-0",
                        world_id,
                        0.0,
                        {"world-fin-1": 0.10, "world-fin-2": 0.20, "world-fin-3": 0.30}.get(world_id, 0.15),
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-pi-1-{world_id}",
                        "pi-1",
                        world_id,
                        0.0,
                        {"world-fin-1": 0.40, "world-fin-2": 0.55, "world-fin-3": 0.50}.get(world_id, 0.45),
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )
        return (
            {"world-fin-1": 0.40, "world-fin-2": 0.55, "world-fin-3": 0.50},
            {"world-fin-1": 0.10, "world-fin-2": 0.20, "world-fin-3": 0.30},
        )

    def _census(self, url: str, *, extra: dict[str, str] | None = None) -> dict[str, str]:
        """The pool's families, as the caller holds them: authored ``hpo``,
        financial ``momentum``."""
        with closing(sqlite3.connect(sqlite_path(url))) as connection:
            authored = [
                row[0]
                for row in connection.execute(f"SELECT world_id FROM {WORLD_TABLE}")
            ]
        census = {world: self.AUTHORED_ROOT for world in authored}
        census.update(
            {
                "world-fin-1": self.FINANCIAL_ROOT,
                "world-fin-2": self.FINANCIAL_ROOT,
                "world-fin-3": self.FINANCIAL_ROOT,
            }
        )
        if extra:
            census.update(extra)
        return census

    def test_the_transfer_is_taken_over_the_owners_own_pool(
        self, tmp_path: Path
    ) -> None:
        """§11.1's ``lofo_delta_ir`` line, run over tables this member did not build.

        The three figures are computed independently from the rows this test
        wrote: the delta is the mean of the financial family's per-world
        differences, the held-out half is exactly that family, and the
        retained count is the forty worlds feature 188 authored — the
        authored world that was also replayed stays retained, because the
        restriction is by family and not by replay presence.
        """
        url = self._owners_pool(tmp_path)
        candidate, baseline = self._write_two_arms(url)

        transfer = pooled_family_transfer(
            "pi-1",
            "pi-0",
            themes=self._census(url),
            theme=self.FINANCIAL_ROOT,
            database_url=url,
        )

        differences = [
            candidate[world] - baseline[world]
            for world in ("world-fin-1", "world-fin-2", "world-fin-3")
        ]
        assert transfer.delta_ir == pytest.approx(sum(differences) / 3)
        assert transfer.held_out == ("world-fin-1", "world-fin-2", "world-fin-3")
        assert transfer.retained_worlds == 40
        # The authored-and-replayed world has rows under both arms and is
        # still not in the comparison: its family was not asked out.
        assert transfer.difference.paired_worlds == 3
        assert dict(transfer.difference.differences).keys() == {
            "world-fin-1",
            "world-fin-2",
            "world-fin-3",
        }

    def test_a_census_that_disagrees_with_the_owners_pool_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The pool is ground truth at this seam, in either direction.

        A census that misses authored worlds would leave them in no family —
        invisible to a partition claiming to be *of* the pool — and one that
        invents a world grounds the figure on a world the owners never put
        in.  Both are the store's refusal, with the disagreement named.
        """
        url = self._owners_pool(tmp_path)
        self._write_two_arms(url)
        short = self._census(url)
        dropped = sorted(short)[:1][0]
        del short[dropped]

        with pytest.raises(TransferStoreError) as missing:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=short,
                theme=self.FINANCIAL_ROOT,
                database_url=url,
            )

        assert repr(dropped) in str(missing.value)

        padded = self._census(url, extra={"world-phantom": self.FINANCIAL_ROOT})
        with pytest.raises(TransferStoreError) as phantom:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=padded,
                theme=self.FINANCIAL_ROOT,
                database_url=url,
            )

        assert "'world-phantom'" in str(phantom.value)

    def test_a_family_world_only_one_arm_was_replayed_against_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The delegated pairing law, over the owner's own table."""
        url = self._owners_pool(tmp_path)
        self._write_two_arms(url)
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            connection.execute(
                f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                "world_id, beta, score, committed_pick, is_holdout, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "score-pi-1-world-fin-4",
                    "pi-1",
                    "world-fin-4",
                    0.0,
                    0.9,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )

        with pytest.raises(PairedComparisonError) as refusal:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes=self._census(url, extra={"world-fin-4": self.FINANCIAL_ROOT}),
                theme=self.FINANCIAL_ROOT,
                database_url=url,
            )

        assert "world-fin-4" in str(refusal.value)

    def test_a_0109_only_database_holds_no_pool_to_hold_a_family_out_of(
        self, tmp_path: Path
    ) -> None:
        """``0109`` makes the score table and not the world table (pinned two
        classes up), so the membership read refuses — translated into this
        feature's store class, never re-raised as the split's."""
        migration = _load_migration(
            "m0109_transfer_alone", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'transfer-alone.db'}"
        migration.apply(database_url)

        with pytest.raises(TransferStoreError) as refusal:
            pooled_family_transfer(
                "pi-1",
                "pi-0",
                themes={
                    "world-fin-1": self.FINANCIAL_ROOT,
                    **{f"w{i:03d}": self.AUTHORED_ROOT for i in range(20)},
                },
                theme=self.FINANCIAL_ROOT,
                database_url=database_url,
            )

        assert "no pool" in str(refusal.value)


class TestTheRotationSeam:
    """The holdout's rotation, pinned against the owners' own pool.

    Feature 279 reads the pool through the one law it does not own — the
    membership (:func:`dreaming.pool_worlds`'s union, feature 278's
    restatement) — and writes one row of its own beside it.  What this class
    pins is the seam over the *owners'* tables: a pool built by ``0109`` and
    feature 188's store, the cycle's holdout recorded from it, and the
    persisted half agreeing with the split taken directly through feature
    278's own seam at the same rotation — *one* split, not two that merely
    agree.  The same discipline the split, comparison and transfer seams
    above apply, turned on the sentence's second clause: *persisting which
    worlds were held out per iteration* is only a claim the store can check
    if the worlds came from the owners' tables in the first place.
    """

    def _owners_pool(self, tmp_path: Path) -> str:
        """A pool both owners built: migrated by ``0109``, authored by 188."""
        bootstrap_src = REPO_ROOT / "packages" / "bootstrap" / "src"
        if str(bootstrap_src) not in sys.path:
            sys.path.insert(0, str(bootstrap_src))
        bootstrap = pytest.importorskip(
            "bootstrap", reason="the bootstrap member is absent from this checkout"
        )

        migration = _load_migration(
            "m0109_rotation", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'rotation-seam.db'}"
        migration.apply(database_url)
        bootstrap.BootstrapPool(database_url).persist_worlds(40)
        return database_url

    def _write_scores(self, url: str, financial_ids: tuple[str, ...]) -> None:
        """Score rows over the given financial worlds and one shared world.

        Writes through ``0109``'s own eight columns, raw — the replay
        member's writer is not this member's to drive — and names one
        *bootstrap* world too, so the union law does its work before the
        rotation ever ranks a world: an authored world that was replayed is
        the honest shape of a dreaming pool, and the record's half must
        still hold it once.
        """
        with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
            shared = connection.execute(
                f"SELECT world_id FROM {WORLD_TABLE} LIMIT 1"
            ).fetchone()[0]
            for world_id in (*financial_ids, shared):
                connection.execute(
                    f"INSERT INTO {REPLAY_SCORE_TABLE} (id, policy_version, "
                    "world_id, beta, score, committed_pick, is_holdout, "
                    "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"score-rotation-{world_id}",
                        "pi-0",
                        world_id,
                        0.0,
                        1.0,
                        None,
                        0,
                        "2026-01-01T00:00:00Z",
                    ),
                )

    def test_the_persisted_holdout_is_the_split_at_the_cycles_own_rotation(
        self, tmp_path: Path
    ) -> None:
        """One spelling over the owners' pool: the row's half *is* 278's answer.

        43 worlds — forty authored, three financial, one shared — split
        30/13 at any rotation, and the row recorded for cycle 7 carries
        exactly the half ``split_replay_pool(rotation="cycle-7")`` answers,
        beside the pool's size and the exact share.  A caller marking
        ``replay_score`` rows through the split's own predicates during the
        cycle and this member recording the cycle run one split.
        """
        url = self._owners_pool(tmp_path)
        self._write_scores(url, ("world-fin-1", "world-fin-2", "world-fin-3"))

        record = dreaming.record_cycle_holdout(
            "cycle-7",
            database_url=url,
            recorded_at=dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.UTC),
        )
        direct = dreaming.split_replay_pool(database_url=url, rotation="cycle-7")

        assert record.iteration_id == "cycle-7"
        assert record.world_count == 43
        assert record.holdout == direct.holdout
        assert len(record.holdout) == 13
        assert record.fraction == dreaming.TRAIN_FRACTION
        assert set(record.holdout) | set(direct.train) == set(
            dreaming.pool_worlds(sqlite_path(url))
        )
        assert not (set(record.holdout) & set(direct.train))

    def test_the_owners_pool_rotates_cycle_by_cycle(self, tmp_path: Path) -> None:
        """§12.1's *"holdout rotated each cycle"* over tables this member did
        not build: two cycles answer two halves, and the audit read answers
        both rows oldest-first."""
        url = self._owners_pool(tmp_path)
        self._write_scores(url, ("world-fin-1", "world-fin-2", "world-fin-3"))

        first = dreaming.record_cycle_holdout(
            "cycle-1",
            database_url=url,
            recorded_at=dt.datetime(2026, 3, 1, 9, 0, 0, tzinfo=dt.UTC),
        )
        second = dreaming.record_cycle_holdout(
            "cycle-2",
            database_url=url,
            recorded_at=dt.datetime(2026, 3, 1, 10, 0, 0, tzinfo=dt.UTC),
        )

        assert first.holdout != second.holdout
        assert dreaming.cycle_holdouts(database_url=url) == (first, second)

    def test_a_0109_only_database_holds_no_pool_to_hold_worlds_out_of(
        self, tmp_path: Path
    ) -> None:
        """``0109`` makes the score table and not the world table (pinned four
        classes up), so the record's probe refuses — in this feature's own
        store class, never re-raised as the split's, and before the table is
        created so a refused record leaves no trace."""
        migration = _load_migration(
            "m0109_rotation_alone", "0109_replay_score_and_policy_revision.py"
        )
        database_url = f"sqlite:///{tmp_path / 'rotation-alone.db'}"
        migration.apply(database_url)

        with pytest.raises(HoldoutRecordError) as refusal:
            dreaming.record_cycle_holdout(
                "cycle-1",
                database_url=database_url,
                recorded_at=dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.UTC),
            )

        assert "no pool" in str(refusal.value)
        assert not isinstance(refusal.value, dreaming.SplitStoreError)
        with closing(sqlite3.connect(sqlite_path(database_url))) as connection:
            left = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name = 'cycle_holdout'"
            ).fetchone()[0]
        assert left == 0
