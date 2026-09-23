"""Feature 283's act: one regime_coverage count per named stratum, persisted.

app_spec.xml, "Regime Coverage Strata", feature 283: *System persists a
regime_coverage count per stratum such as high-volatility trend,
low-volatility chop and crash.*  docs/alpha-engine-prd.md §C7 is the
doctrine — the ledger ``{high-vol trend: 2, low-vol chop: 14, crash: 0,
…}`` that makes a regime-monotone replay pool's skew countable — and
``0107`` is the schema's voice, whose four load-bearing details these
tests pin from the writer's side:

* the **named-empty row** (detail 1): ``world_count NOT NULL DEFAULT 0``
  exists so a named stratum holding no worlds is a row with a 0 —
  feature 286's ``empty_stratum`` warning fires on exactly that state —
  while an absent row means a stratum nobody named, a different fact that
  must stay distinguishable;
* the **one-row-per-name identity** (detail 2): ``stratum`` is the whole
  primary key, so a re-issued persist is idempotent and the table never
  holds two rows for one stratum;
* the **vintage** (detail 3): ``updated_at`` is the count's evidence — a
  re-issued persist leaves it standing (the count was already true), a
  changed count re-stamps it explicitly (the writer contract the plugin
  owns, because a default does not fire on ``UPDATE``);
* the **aggregate row** (detail 4): no ``REFERENCES``, because the counted
  worlds are files in the replay pool, not rows in this database — the
  count arrives as the caller's, and the store persists it, never counts
  it.

Every write here goes through the store's public surface — ``record``,
``name_stratum``, ``get`` — and every claim about what landed is read
back through raw SQL as well, the discipline the discovery member's
campaign suite states: the row is the record, and a test that only read
the store's own answer would be pinning the store against itself.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    COVERAGE_TABLE,
    DATABASE_URL_ENV,
    DEFAULT_STRATA,
    STRATUM_COLUMN,
    UPDATED_AT_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageCount,
    CoverageError,
    RegimeCoverage,
    persist_coverage,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL.

    This suite's own four lines rather than a call into the member, on the
    same terms the discovery member's suite states: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be
    pinning an implementation detail it should be free to change.  A
    migration's URL grammar is what the store mirrors, so the translation
    is the same three steps by design.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_row(database_url: str, stratum: str) -> tuple[object, ...] | None:
    """One stratum's row as the table holds it — read as a reader with no
    code in common with this member would read it.

    The store's ``get`` is under test in half of these assertions; the
    other half need the *table's* word for what landed, which is what this
    returns.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, {UPDATED_AT_COLUMN} "
            f"FROM {COVERAGE_TABLE} WHERE {STRATUM_COLUMN} = ?",
            (stratum,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()


def _table_exists(database_url: str) -> bool:
    """Whether the ledger's table exists at all — the downgrade test's probe.

    The one question about this table that cannot be asked through SQL
    against it: after a ``DROP TABLE``, a ``SELECT`` would raise rather
    than answer, and the test's point is that the *absence* is real.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            f"AND name = '{COVERAGE_TABLE}'"
        )
        try:
            return cursor.fetchone() is not None
        finally:
            cursor.close()


def _raw_count(database_url: str) -> int:
    """How many rows the ledger holds — the one-row-per-name instrument.

    Zero when the table does not exist at all, which is the state a
    *refused* ask leaves: validation runs before the store opens
    anything, so the refusal tests measure "nothing was written" against
    a database that may have no table to count.
    """
    if not _table_exists(database_url):
        return 0
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(f"SELECT COUNT(*) FROM {COVERAGE_TABLE}")
        try:
            return int(cursor.fetchone()[0])
        finally:
            cursor.close()


# -- The feature's own sentence ----------------------------------------------------


class TestThePersist:
    """The act itself: a count per stratum, in the table, read back."""

    def test_persists_a_count_per_stratum(self, store, database_url) -> None:
        # The feature's sentence, end to end: the three strata it names,
        # each with a count, each a row.  §C7's own example ledger is
        # drawn with exactly these kinds of numbers — 2, 14 and the 0 that
        # is its own law below.
        asked = {"high-volatility trend": 2, "low-volatility chop": 14, "crash": 0}
        for stratum, world_count in asked.items():
            stored = store.record(stratum, world_count)
            assert stored.stratum == stratum
            assert stored.world_count == world_count
            assert stored.updated_at is not None  # the vintage is evidence
        for stratum, world_count in asked.items():
            row = _raw_row(database_url, stratum)
            assert row is not None, stratum
            assert row[0] == stratum
            assert row[1] == world_count
            assert row[2] is not None

    def test_the_three_names_are_the_features_own_sentence(self) -> None:
        # Verbatim, in the spec's order — the sentence's *"such as"* makes
        # them the default vocabulary rather than a gate (the openness is
        # its own test below), but the three spellings are the ledger's
        # public names, and a retyped one would make the labeler's
        # clusters and the ledger's rows disagree stratum-for-stratum.
        assert DEFAULT_STRATA == ("high-volatility trend", "low-volatility chop", "crash")

    def test_the_store_creates_the_table_on_a_fresh_database(self, store) -> None:
        # The convergence 0107 delegates: a database the migration never
        # reached takes the same write path as one it did, because the
        # store creates the table idempotently on first use.  No migration
        # has run against this database — the persist is its first act.
        assert store.record("crash", 3).world_count == 3

    def test_the_answer_is_read_back_not_assembled(self, store, database_url) -> None:
        # The vintage the answer carries is the table's own stamp, not a
        # value built from the arguments: compared against the raw row,
        # column for column, including the ``updated_at`` only the
        # database could have minted.
        stored = store.record("low-volatility chop", 9)
        raw = _raw_row(database_url, "low-volatility chop")
        assert raw is not None
        assert (stored.stratum, stored.world_count, stored.updated_at) == raw

    def test_the_table_holds_one_row_per_name(self, store, database_url) -> None:
        # The identity 0107 argues NOT NULL onto the key for: one row per
        # named stratum.  A second persist with a different count is an
        # UPDATE, never a second row.
        store.record("crash", 3)
        store.record("crash", 8)
        assert _raw_count(database_url) == 1
        assert _raw_row(database_url, "crash")[1] == 8

    def test_a_reissued_persist_lands_the_stored_row_again(
        self, store, database_url
    ) -> None:
        # Idempotent by stratum, and byte for byte: the retry answers the
        # row that was already standing — the same count and the *same*
        # vintage, pinned across a second boundary below so the equality
        # is the law's work and not the clock's.
        first = store.record("crash", 3)
        second = store.record("crash", 3)
        assert second == first
        assert _raw_count(database_url) == 1

    def test_the_vintage_moves_only_when_the_count_does(
        self, store, database_url
    ) -> None:
        # 0107 detail 3, both halves of the writer contract in one test:
        # a re-issued count leaves the vintage standing (the count was
        # already true, and *"a coverage number is only evidence while you
        # know when it was last true"* — a retry did not make it true
        # again), and a changed count re-stamps it explicitly (the default
        # does not fire on UPDATE, which is why the re-stamp is the
        # plugin's to own).  The sleep crosses the second boundary the
        # database's clock resolution draws, so each equality and each
        # difference is the law's work rather than the clock's.
        standing = store.record("crash", 3)
        time.sleep(1.1)
        retried = store.record("crash", 3)
        assert retried.updated_at == standing.updated_at  # retry: no move
        changed = store.record("crash", 4)
        assert changed.updated_at != standing.updated_at  # change: re-stamp
        assert changed.world_count == 4
        assert _raw_count(database_url) == 1

    def test_a_lower_count_is_persisted_not_refused(self, store) -> None:
        # §C6's tripwires excise a poisoned node and its subtree from the
        # replay pool, so the pool is not monotone in worlds and the
        # ledger must not legislate a monotonicity the system does not
        # have: 14 worlds of chop, then the excision takes twelve of them.
        store.record("low-volatility chop", 14)
        assert store.record("low-volatility chop", 2).world_count == 2

    def test_zero_is_persisted_as_a_row(self, store) -> None:
        # §C7's example ledger *writes the zero* — crash: 0 — so a zero
        # count is a persist like any other, landing the named-empty row.
        stored = store.record("crash", 0)
        assert stored.world_count == 0
        assert stored.empty is True  # the state; the warning is 286's

    def test_strata_outside_the_default_three_are_persisted(self, store) -> None:
        # The set is open.  The sentence's *"such as"* is the openness in
        # the spec's own words, and 0107 stores whatever names the plugin
        # writes — a deployment with five strata writes five rows.  The
        # contrast is feature 241's legal theme set, which is closed
        # because a research space is a deployment's highest-value input;
        # a stratum name is the labeler's configuration, not a space.
        assert store.record("volatility expansion", 7).world_count == 7
        assert store.get("volatility expansion").world_count == 7

    def test_case_is_not_normalised(self, store, database_url) -> None:
        # Nothing re-spells a name, on the same terms: a store that
        # case-folded would be silently renaming a stratum a deployment
        # configured.  ``"Crash"`` and ``"crash"`` are two rows, and the
        # caller that wrote both reconciles them in the configuration the
        # names came from.
        store.record("crash", 1)
        store.record("Crash", 2)
        assert _raw_count(database_url) == 2
        assert store.get("crash").world_count == 1
        assert store.get("Crash").world_count == 2

    def test_a_name_is_stripped_before_it_is_persisted(self, store) -> None:
        # The one normalisation there is: a trailing newline or an
        # indented copy would otherwise persist as a *second* row for one
        # stratum, against the key's whole identity.
        stored = store.record("  crash\n", 5)
        assert stored.stratum == "crash"
        assert store.get("crash").world_count == 5


class TestTheNamedEmptyRow:
    """0107 detail 1: naming is its own act, and it never asserts a count."""

    def test_naming_persists_a_row_whose_count_is_the_default(self, store) -> None:
        # The one-column INSERT the default buys: the name in, the count
        # from ``DEFAULT 0``, the vintage from the table's own stamp.
        # Naming a stratum asserts nothing about its count — that is what
        # makes it the right act for a deployment declaring its
        # vocabulary before the pool has anything to count.
        stored = store.name_stratum("crash")
        assert stored.stratum == "crash"
        assert stored.world_count == 0
        assert stored.updated_at is not None

    def test_the_named_empty_row_and_the_absent_one_differ(self, store) -> None:
        # The fact 0107's DEFAULT exists to keep distinguishable, held
        # still long enough to see: before any write, ``get`` answers
        # None — a stratum nobody named; after naming, it answers a row
        # holding zero — a stratum named and empty.  Feature 286's
        # ``empty_stratum`` warning fires on the second and only the
        # second.
        assert store.get("crash") is None
        assert store.name_stratum("crash").empty is True
        assert store.get("crash") is not None
        assert store.get("crash").empty is True

    def test_naming_never_zeroes_a_standing_count(self, store) -> None:
        # The stronger idempotence: a name arriving twice must not zero a
        # count the pool already holds.  The standing row is returned
        # untouched — its count and its vintage.
        standing = store.record("crash", 7)
        named = store.name_stratum("crash")
        assert named.world_count == 7
        assert named.updated_at == standing.updated_at

    def test_naming_is_idempotent(self, store, database_url) -> None:
        first = store.name_stratum("crash")
        second = store.name_stratum("crash")
        assert second == first
        assert _raw_count(database_url) == 1

    def test_recording_zero_names(self, store) -> None:
        # The two acts land the same row on a fresh stratum; they differ
        # only in what they say about one that is already named (the
        # count's authority vs the vocabulary's).
        assert store.record("crash", 0) == store.name_stratum("crash")


class TestTheRead:
    """One stratum's row back, or the honest None."""

    def test_get_reads_a_standing_row(self, store) -> None:
        stored = store.record("high-volatility trend", 2)
        assert store.get("high-volatility trend") == stored

    def test_get_answers_none_for_a_stratum_nobody_named(self, store) -> None:
        # None is *nobody named this*, not *the read failed*: an
        # unreachable database raises, so a caller can never mistake a
        # broken store for an unnamed stratum.
        assert store.get("crash") is None

    def test_a_named_stratum_reads_through_a_second_store(self, database_url) -> None:
        # The ledger outlives the store that wrote it — the reason an
        # in-memory database is refused.  A second store, pointed at the
        # same database by another process's spelling of the same URL,
        # reads what the first persisted.
        RegimeCoverage(database_url).record("crash", 6)
        assert RegimeCoverage(database_url).get("crash").world_count == 6


class TestTheRecord:
    """The read-back value: frozen, validated, store-shaped."""

    def test_the_record_is_frozen(self) -> None:
        # A count that has been read back cannot be edited into a
        # different coverage number by a caller who kept a reference —
        # the row is the record, and the value must not be able to
        # disagree with it.
        stored = CoverageCount(stratum="crash", world_count=1, updated_at="2026-01-01")
        with pytest.raises(dataclasses.FrozenInstanceError):
            stored.world_count = 2  # type: ignore[misc]

    def test_row_is_keyed_by_the_tables_own_columns(self) -> None:
        stored = CoverageCount(stratum="crash", world_count=1, updated_at="2026-01-01")
        assert set(stored.row()) == {STRATUM_COLUMN, WORLD_COUNT_COLUMN, UPDATED_AT_COLUMN}
        assert stored.row()[WORLD_COUNT_COLUMN] == 1

    def test_the_record_validates_its_own_fields(self) -> None:
        # Past the store's nose — ``dataclasses.replace`` and unpickling
        # both rebuild instances — and for the read path's sake: the
        # corrupt-row refusals below are this check, re-raised with the
        # stratum named.
        with pytest.raises(CoverageError):
            CoverageCount(stratum="", world_count=1, updated_at="x")
        with pytest.raises(CoverageError):
            CoverageCount(stratum="crash", world_count=-1, updated_at="x")
        with pytest.raises(CoverageError):
            CoverageCount(stratum="crash", world_count=1, updated_at=None)


# -- The refusals -----------------------------------------------------------------


class TestTheAskIsRefused:
    """A malformed name or count is refused before anything is opened."""

    @pytest.mark.parametrize("stratum", ["", "   ", "\n\t", None, 42, 3.0, b"crash"])
    def test_a_name_that_cannot_be_a_name(self, store, database_url, stratum) -> None:
        # One row per *named* stratum: a name that states nothing names
        # no stratum a count could be persisted for.
        with pytest.raises(CoverageError) as raised:
            store.record(stratum, 1)
        assert "stratum" in str(raised.value)
        assert _raw_count(database_url) == 0  # refused before anything was written

    @pytest.mark.parametrize("count", [True, -1, -100, 1.5, "3", None, 2.0])
    def test_a_count_that_cannot_be_a_count(self, store, database_url, count) -> None:
        # A number of stored worlds is a count: ``True`` is not a count
        # (a truthy 1 let a flag land where a number belongs), a negative
        # number is not (excision empties a stratum, it never owes
        # worlds), a fraction is not (a fractional world is not a world).
        with pytest.raises(CoverageError) as raised:
            store.record("crash", count)
        assert "world_count" in str(raised.value)
        assert _raw_count(database_url) == 0

    def test_naming_refuses_the_same_names(self, store) -> None:
        with pytest.raises(CoverageError):
            store.name_stratum("  ")
        with pytest.raises(CoverageError):
            store.get(None)


class TestTheAddressIsRefused:
    """A DATABASE_URL this member cannot speak is refused by name."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://localhost/nullius",  # a scheme this store cannot speak
            "sqlite://host/nullius.db",  # a host in a sqlite URL
            "sqlite:///",  # no path at all
            "sqlite:///:memory:",  # a ledger that dies with the connection
        ],
    )
    def test_unspeakable_urls_are_refused_by_name(self, url) -> None:
        # The construction is safe (no I/O); the first operation is where
        # the refusal lands, by name, so a misconfigured deployment
        # learns which variable to fix.
        store = RegimeCoverage(url)
        with pytest.raises(CoverageError) as raised:
            store.record("crash", 1)
        assert DATABASE_URL_ENV in str(raised.value)

    def test_the_read_path_refuses_them_too(self) -> None:
        # A caller that only reads must not be spared the diagnosis: a
        # broken address is not an unnamed stratum.
        with pytest.raises(CoverageError):
            RegimeCoverage("postgresql://localhost/nullius").get("crash")

    def test_construction_refuses_an_empty_url(self) -> None:
        # A URL that is not a non-empty string names no ledger, and a
        # store pointed at nothing would fail identically on every
        # persist — the wrong place to discover a wiring fault.
        for empty in ("", "   ", None, 42):
            with pytest.raises(CoverageError):
                RegimeCoverage(empty)  # type: ignore[arg-type]


class TestTheRowIsRefused:
    """A stored value too corrupt to be a count is refused, naming the stratum.

    SQLite's columns are dynamically typed, so a raw INSERT from another
    tool can land anything in ``world_count``; a read that swallowed it
    would report a count nobody wrote.  The repair is to the data, not to
    the call — which is why the stratum is in every message.  Each test
    brings the table into being the way a deployment does — the plugin's
    own first persist — before the raw INSERT lands beside it, which is
    the state the refusals are about.
    """

    def _corrupt(self, store, database_url: str, sql: str) -> None:
        store.name_stratum("low-volatility chop")  # the table, the plugin's way
        with closing(sqlite3.connect(_path_of(database_url))) as connection, connection:
            connection.execute(sql)

    def test_a_non_integer_count_is_refused_naming_the_stratum(
        self, store, database_url
    ) -> None:
        self._corrupt(
            store,
            database_url,
            f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, "
            f"{UPDATED_AT_COLUMN}) VALUES ('crash', 'fourteen', datetime('now'))",
        )
        with pytest.raises(CoverageError) as raised:
            store.get("crash")
        assert "crash" in str(raised.value)

    def test_a_missing_vintage_cannot_land_at_all(self, store, database_url) -> None:
        # The NULL vintage is the one corruption the schema itself
        # refuses — ``0107``'s ``NOT NULL`` is real, so the row this
        # member could not have written cannot be written by another tool
        # either.  The store-side check on the same fact is
        # ``TestTheRecord``'s validation test: a value rebuilt past the
        # store's nose (``dataclasses.replace``, a pickle) is where the
        # second line of defense earns its place.
        with pytest.raises(sqlite3.IntegrityError):
            self._corrupt(
                store,
                database_url,
                f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}, "
                f"{WORLD_COUNT_COLUMN}, {UPDATED_AT_COLUMN}) "
                "VALUES ('crash', 0, NULL)",
            )

    def test_a_corrupt_row_refuses_the_persist_too(self, store, database_url) -> None:
        # The write path reads the standing row first, so a corrupt row
        # is refused before any count lands beside it — the persist never
        # papers over a row it cannot read.
        self._corrupt(
            store,
            database_url,
            f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, "
            f"{UPDATED_AT_COLUMN}) VALUES ('crash', -3, datetime('now'))",
        )
        with pytest.raises(CoverageError) as raised:
            store.record("crash", 1)
        assert "crash" in str(raised.value)


# -- The module-level spelling -----------------------------------------------------


class TestTheModuleLevelSpelling:
    """persist_coverage: the sentence as one call."""

    def test_resolves_the_store_from_the_argument(self, database_url) -> None:
        stored = persist_coverage("crash", 4, database_url=database_url)
        assert stored.world_count == 4
        assert _raw_row(database_url, "crash") is not None

    def test_reads_the_environment_when_no_url_is_given(
        self, monkeypatch, database_url
    ) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, database_url)
        assert persist_coverage("crash", 4).world_count == 4

    def test_refuses_by_name_when_nothing_names_a_store(self, monkeypatch) -> None:
        # A persist that quietly skipped its write would leave the ledger
        # silent about exactly the strata the pool holds — the skew §C7's
        # ledger exists to make countable, discovered instead at the
        # promotion gate that reads it.  Refused by name, not skipped.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        with pytest.raises(CoverageError) as raised:
            persist_coverage("crash", 4)
        assert DATABASE_URL_ENV in str(raised.value)


# -- The two creators --------------------------------------------------------------


class TestTheConvergence:
    """The table has two creators, and whichever ran first is the winner."""

    def test_the_store_serves_a_migrated_database(self, migrated_database) -> None:
        # The migration got there first: the schema is 0107's, and the
        # plugin's writer serves it — the persist lands, the row stands.
        store = RegimeCoverage(migrated_database)
        assert store.record("crash", 5).world_count == 5
        assert store.get("crash").world_count == 5

    def test_the_migration_is_a_nothing_over_a_store_created_table(
        self, store, database_url, migrate_at
    ) -> None:
        # The store got there first: the persist creates the table
        # idempotently, and the migration — which is itself ``IF NOT
        # EXISTS`` — runs over the store-created table changing nothing.
        # Both orders converge on the same state, which is the whole of
        # 0107's convergence clause.
        store.record("crash", 5)
        migrate_at(database_url)
        assert store.get("crash").world_count == 5  # the row survived
        assert store.record("crash", 6).world_count == 6  # the writer still serves it

    def test_a_downgraded_database_is_refilled_by_the_next_persist(
        self, store, database_url, coverage_migration
    ) -> None:
        # 0107's downgrade docstring, held to: a downgraded database "is
        # refilled by the regime plugin's next persist, which creates the
        # table idempotently" — not one left broken.  The downgrade drops
        # the table and the row with it; the next persist recreates the
        # table and lands the count again.
        store.record("crash", 5)
        with closing(
            sqlite3.connect(_path_of(database_url))
        ) as connection, connection:
            coverage_migration.downgrade(connection)
        assert not _table_exists(database_url)  # the drop took table and row
        assert store.record("crash", 5).world_count == 5  # the persist refilled it


# -- The resolve seam --------------------------------------------------------------


class TestTheResolve:
    """The store's own environment seam — the builder's, spelled alone."""

    def test_resolves_from_the_environment(self, monkeypatch, database_url) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, database_url)
        resolved = RegimeCoverage.resolve()
        assert resolved is not None
        assert resolved.database_url == database_url

    def test_an_explicit_env_is_preferred(self, monkeypatch, database_url) -> None:
        # The caller that holds its own mapping (a composition, a test)
        # is not at the ambient environment's mercy.
        monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere-else.db")
        resolved = RegimeCoverage.resolve({DATABASE_URL_ENV: database_url})
        assert resolved is not None
        assert resolved.database_url == database_url

    def test_absent_is_none_not_an_error(self, monkeypatch) -> None:
        # An unconfigured deployment is a discoverable state: the builder
        # composes None rather than raising, and this is the seam that
        # answers None.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert RegimeCoverage.resolve() is None

    def test_whitespace_only_is_unset(self, monkeypatch, database_url) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        assert RegimeCoverage.resolve() is None

    def test_resolving_writes_nothing(self, monkeypatch, database_url) -> None:
        # Composition-time work must not touch the disk: resolving the
        # store leaves the database file uncreated, and the table comes
        # with the first persist.
        monkeypatch.setenv(DATABASE_URL_ENV, database_url)
        RegimeCoverage.resolve()
        assert not _path_of(database_url).exists()
