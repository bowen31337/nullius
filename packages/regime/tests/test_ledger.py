"""Feature 284's act: the current coverage ledger, whole.

app_spec.xml, "Regime Coverage Strata", feature 284: *System returns the
current coverage ledger showing stored world counts for every named
stratum.*  Feature 283's store writes one count per stratum; this file
pins the read that answers with the ledger **as a whole**, and the
sentence's two load-bearing words are what most of it is about.

*"**Every named stratum**"* — the ledger is read from the *table*, not
from a vocabulary, and ``test_a_stratum_outside_the_default_three_is_in_the_ledger``
is the assertion that keeps :data:`DEFAULT_STRATA` a default rather than
an enumeration.  A reader that walked the three names would report
nothing about a deployment whose labeler carves five, which is the exact
blindness §C7's ledger exists to cure.

*"**The current ledger**"* — the answer is a reading of the table now,
not a memo of what this process saw earlier, and the tests that persist
through one store and read through another (a second ``RegimeCoverage``,
:func:`read_ledger`, the composed component) are what keep that honest.
The value the read returns derives every figure from its rows on demand,
so nothing in it can go stale.

The other half of the file is ``0107`` detail 1, holding on the read side
the distinction it argues on the write side: a stratum **named and
empty** is a row with a zero in it, and a stratum **never named** is
absent from the ledger — different facts, kept apart by two different
types (:class:`~regime.coverage.CoverageCount` and
:class:`~regime.ledger.CoverageHole`) because feature 286's
``empty_stratum`` warning fires on the first and must not fire on the
second.

Every claim about what the ledger holds is checked **both ways**: through
the read under test, and through raw SQL against the table, the
discipline the member's coverage suite states — a test that only read the
store's own answer would be pinning the store against itself.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    COVERAGE_TABLE,
    DATABASE_URL_ENV,
    DEFAULT_STRATA,
    STRATUM_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageCount,
    CoverageError,
    CoverageHole,
    CoverageLedger,
    RegimeCoverage,
    persist_coverage,
    read_ledger,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL.

    This suite's own four lines rather than a call into the member, on the
    same terms the coverage suite states: the store's ``_sqlite_path`` is
    private, and a test reaching into it would be pinning an
    implementation detail it should be free to change.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_ledger(database_url: str) -> list[tuple[object, ...]]:
    """Every row the table holds, as a reader with no code in common with
    this member would read it — the whole-table instrument.

    The read under test is a ``SELECT`` over this table; the other half of
    every assertion here needs the *table's* word for what it holds, which
    is what this returns.  Deliberately unordered by stratum: the read
    claims an order, and a helper that pre-sorted would be making the
    claim for it.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN} FROM {COVERAGE_TABLE}"
        )
        try:
            return list(cursor.fetchall())
        finally:
            cursor.close()


def _raw_ledger_ordered(database_url: str) -> list[tuple[object, ...]]:
    """The table's rows in the order the read claims — stratum order."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN} "
            f"FROM {COVERAGE_TABLE} ORDER BY {STRATUM_COLUMN}"
        )
        try:
            return list(cursor.fetchall())
        finally:
            cursor.close()


def _write_raw_row(
    database_url: str, stratum: str, world_count: object, *, store=None
) -> None:
    """Land a row through raw SQL, past the store's own validation.

    SQLite's columns are dynamically typed, so this is how the *corrupt
    row* states are reached: a value the writer would have refused is
    exactly the value another tool can still put in the table, and the
    read's job is to refuse it rather than report a count nobody wrote.

    ``store`` is asked for one unrelated read first, because a raw write
    is a *reader's* tool here and this suite's databases start with no
    table at all — the store's idempotent ``CREATE TABLE`` is what brings
    one, and a raw ``INSERT`` against a database nobody has opened would
    fail on the table rather than on the value the test is about.
    """
    if store is not None:
        store.ledger()  # the store's own creator, so the table exists
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        connection.execute(
            f"INSERT INTO {COVERAGE_TABLE} ({STRATUM_COLUMN}, "
            f"{WORLD_COUNT_COLUMN}) VALUES (?, ?)",
            (stratum, world_count),
        )
        connection.commit()


def _raw_row(database_url: str, stratum: str) -> tuple[object, ...] | None:
    """One stratum's row as the table holds it, or ``None`` when absent."""
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN} "
            f"FROM {COVERAGE_TABLE} WHERE {STRATUM_COLUMN} = ?",
            (stratum,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()


# -- The feature's own sentence ----------------------------------------------------


class TestTheLedger:
    """*System returns the current coverage ledger* — the act itself."""

    def test_returns_every_named_stratum_with_its_count(
        self, store, database_url
    ) -> None:
        # Feature 284's sentence, end to end: §C7's own example ledger —
        # the 2, the 14 and the 0 — read back as one object, checked
        # against the table rather than against the store's own answers.
        asked = {
            "high-volatility trend": 2,
            "low-volatility chop": 14,
            "crash": 0,
        }
        for stratum, world_count in asked.items():
            store.record(stratum, world_count)

        ledger = store.ledger()

        assert ledger.counts == asked
        assert [row.stratum for row in ledger.rows] == sorted(asked)
        # The table's word for the same thing: same pairs, same counts.
        assert sorted(_raw_ledger(database_url)) == sorted(asked.items())

    def test_the_ledger_is_the_tables_current_content(self, store) -> None:
        # *Current*: a count written after one read is in the next one.
        # The value carries no cache of its own, and the store holds none
        # of the rows it wrote — a memo in either place would make this
        # question about the process rather than about the pool.
        store.record("crash", 1)
        assert store.ledger().counts == {"crash": 1}
        store.record("crash", 7)
        assert store.ledger().counts == {"crash": 7}

    def test_a_stratum_outside_the_default_three_is_in_the_ledger(self, store) -> None:
        # *Every named stratum* — the sentence's word, and the reason the
        # read goes to the table rather than to DEFAULT_STRATA.  The set
        # is open (0107 stores whatever names the plugin writes, because
        # the day the stratum set changes is a configuration change in
        # the labeler), so a deployment whose labeler carves five strata
        # has five rows, and a reader that walked the default three would
        # report nothing about the fourth and fifth.
        store.record("momentum ignition", 5)
        store.record("volatility crush", 1)
        for name in DEFAULT_STRATA:
            store.record(name, 0)

        counts = store.ledger().counts

        assert counts["momentum ignition"] == 5
        assert counts["volatility crush"] == 1
        assert len(counts) == 5  # the default three and the two beyond them

    def test_an_empty_ledger_is_an_answer_not_an_error(
        self, store, database_url
    ) -> None:
        # A database where no census has run yet names no stratum.  That
        # is a state, not a fault: the read answers, and the answer is
        # empty.  (The store's first open creates the table idempotently,
        # so the table may not even exist before this call — which is the
        # other half of what "the same write path" means for a reader.)
        ledger = store.ledger()
        assert ledger.rows == ()
        assert ledger.counts == {}
        assert len(ledger) == 0
        assert ledger.empty == ()
        assert ledger.covered == ()
        assert [hole.stratum for hole in ledger.holes()] == list(DEFAULT_STRATA)
        assert _raw_ledger(database_url) == []

    def test_the_read_is_a_second_reader_over_the_same_table(
        self, store, database_url
    ) -> None:
        # The read through the store and the read through the module-level
        # spelling are one reading of one table: a count persisted through
        # ``persist_coverage`` shows up in ``store.ledger()``, and the
        # other way round.  They are the same seam from the two sides.
        store.record("crash", 4)
        persist_coverage("low-volatility chop", 11, database_url=database_url)
        assert read_ledger(database_url=database_url).counts == {
            "crash": 4,
            "low-volatility chop": 11,
        }

    def test_another_stores_write_is_visible_immediately(self, database_url) -> None:
        # The reader and the writer are different objects, and the answer
        # comes from the table rather than from the reader's history: a
        # second store's persist lands in the first store's next read.
        writer, reader = RegimeCoverage(database_url), RegimeCoverage(database_url)
        writer.record("crash", 3)
        assert reader.ledger().counts == {"crash": 3}

    def test_rows_are_sorted_by_stratum(self, store, database_url) -> None:
        # The order is the *name's*: a rowid table's default order is the
        # order rows happened to be written, which would make the ledger's
        # display churn whenever a count crossed zero between censuses,
        # and an operator diffing two readings would see movement where
        # nothing about the pool changed.
        for name in ("momentum", "crash", "alpha regime", "zulu regime"):
            store.record(name, 1)

        ledger = store.ledger()

        assert [row.stratum for row in ledger.rows] == sorted(
            ["momentum", "crash", "alpha regime", "zulu regime"]
        )
        # The same order the SQL clause asks the database for — the two
        # cannot disagree, and this is the assertion that says so.
        assert [
            (row.stratum, row.world_count) for row in ledger.rows
        ] == _raw_ledger_ordered(database_url)

    def test_the_answer_is_read_back_not_reassembled(self, store, database_url) -> None:
        # The vintage each row carries is the table's own stamp, not a
        # value built from the arguments: compared against the raw row,
        # column for column.  The ledger is the rows the table holds.
        store.record("crash", 8)
        row = store.ledger().rows[0]
        with closing(sqlite3.connect(_path_of(database_url))) as connection:
            cursor = connection.execute(
                f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN}, "
                "updated_at FROM regime_coverage WHERE stratum = ?",
                ("crash",),
            )
            try:
                assert (row.stratum, row.world_count, row.updated_at) == (
                    cursor.fetchone()
                )
            finally:
                cursor.close()

    def test_a_count_of_zero_is_a_row_and_not_an_absence(self, store) -> None:
        # §C7's example ledger writes ``crash: 0``.  The row exists, the
        # read reports it, and — the distinction the next class is about —
        # it is a *count* rather than a hole.
        store.record("crash", 0)
        ledger = store.ledger()
        assert len(ledger) == 1
        assert ledger["crash"].world_count == 0
        assert "crash" in ledger
        assert [hole.stratum for hole in ledger.holes()] == [
            "high-volatility trend",
            "low-volatility chop",
        ]

    def test_a_lower_count_is_reported_not_hidden(self, store) -> None:
        # §C6's tripwires excise worlds from the pool, so the pool is not
        # monotone in worlds either; the ledger reports what is true now.
        # A read that only ever reported growth would be legislating a
        # monotonicity the system does not have.
        store.record("crash", 9)
        store.record("crash", 2)
        assert store.ledger().counts == {"crash": 2}

    def test_a_named_stratum_with_no_count_asserted_is_a_row(self, store) -> None:
        # ``name_stratum`` lands the named-empty row without asserting a
        # count — 0107 detail 1's one-column insert.  The ledger holds it
        # as a row with a zero, which is exactly the state feature 286's
        # ``empty_stratum`` warning reads.
        store.name_stratum("crash")
        ledger = store.ledger()
        assert ledger["crash"].world_count == 0
        assert ledger["crash"].empty is True


# -- The two absences --------------------------------------------------------------


class TestTheNamedEmptyVersusTheNeverNamed:
    """``0107`` detail 1, held on the read side.

    A named stratum holding no worlds is a row with a zero; a stratum
    nobody named is absent from the ledger.  A whole-ledger read is the
    one place the two would collapse — *"it is not in the ledger"* is a
    tempting way to write "zero" — so these tests exist to keep them
    apart in the read's own output.
    """

    def test_a_named_empty_stratum_is_a_row_and_a_hole_is_not(self, store) -> None:
        # The whole distinction in one assertion: ``crash`` is recorded as
        # zero and appears as a row; ``low-volatility chop`` is never
        # named and appears only as a hole.  The two hold the same number
        # of stored worlds — none — and are different facts.
        store.record("crash", 0)

        ledger = store.ledger()

        assert [row.stratum for row in ledger.empty] == ["crash"]
        # Vocabulary order, not sorted order: DEFAULT_STRATA lists the
        # trend name first, and the holes follow the list that was asked.
        assert [hole.stratum for hole in ledger.holes()] == [
            "high-volatility trend",
            "low-volatility chop",
        ]
        assert "crash" in ledger
        assert "low-volatility chop" not in ledger

    def test_empty_is_the_named_empty_set_not_the_missing_one(self, store) -> None:
        # ``empty`` is a fact about rows the ledger *holds*; ``holes`` is a
        # question asked of a vocabulary.  A ledger naming nothing at all
        # has no empty strata and three holes, and a ledger naming three
        # empty strata has three of each — the figures agree there and
        # mean different things, which is why the read reports both.
        assert store.ledger().empty == ()
        for name in DEFAULT_STRATA:
            store.name_stratum(name)
        ledger = store.ledger()
        assert [row.stratum for row in ledger.empty] == sorted(DEFAULT_STRATA)
        assert ledger.holes() == ()
        assert ledger.covered == ()

    def test_a_hole_carries_no_count_to_be_mistaken_for(self) -> None:
        # The type *is* the distinction: a hole has no ``world_count``
        # attribute to read a zero out of, so a caller cannot reach for
        # the obvious field and silently get "the pool holds none" where
        # the truth is "nobody ever binned a world into this stratum".
        hole = CoverageHole(stratum="crash")
        assert hole.stratum == "crash"
        assert not hasattr(hole, "world_count")
        assert not hasattr(hole, "empty")
        # And it is not the record type: a caller that wants one has to
        # name the stratum first, which is the honest repair.
        assert not isinstance(hole, CoverageCount)

    def test_a_holes_row_is_the_name_alone(self) -> None:
        # One key, because no row exists to have carried the other two —
        # and the key is the table's own column name.
        assert CoverageHole(stratum="crash").row() == {STRATUM_COLUMN: "crash"}

    def test_holes_come_back_in_the_vocabularys_order(self, store) -> None:
        # The caller's order is part of what it asked: a worklist of
        # strata still to be covered reads in the order the caller listed
        # them, and sorting it here would reorder the caller's own list
        # behind its back.
        vocabulary = ("zulu", "crash", "alpha", "momentum")
        store.record("crash", 2)
        store.record("alpha", 9)
        assert [hole.stratum for hole in store.ledger().holes(vocabulary)] == [
            "zulu",
            "momentum",
        ]

    def test_the_vocabulary_is_the_callers_and_stays_open(self, store) -> None:
        # The default is a default, not a law: a vocabulary sharing no
        # name with the default three is asked and answered normally, and
        # nothing refuses it.  The stratum set is the labeler's
        # configuration (0107's words).
        store.record("crash", 1)
        assert store.ledger().holes(("crash", "invented regime")) == (
            CoverageHole(stratum="invented regime"),
        )

    def test_the_ledger_may_hold_names_the_vocabulary_does_not(self, store) -> None:
        # The other direction, and not a hole: a ledger holding more
        # strata than the vocabulary names is over-covered, not deficient.
        # Read off ``rows`` by anyone who wants it, never reported as a
        # hole — a hole is a name the caller expected and the ledger
        # lacked.
        store.record("momentum ignition", 4)
        ledger = store.ledger()
        assert [hole.stratum for hole in ledger.holes(DEFAULT_STRATA)] == list(
            DEFAULT_STRATA
        )
        assert ledger.counts == {"momentum ignition": 4}

    def test_an_empty_vocabulary_names_nothing_to_be_missing(self, store) -> None:
        store.record("crash", 1)
        assert store.ledger().holes(()) == ()


# -- The views ---------------------------------------------------------------------


class TestTheDerivedViews:
    """The figures the category's later features read off the ledger."""

    def test_counts_is_c7s_own_shape(self, store) -> None:
        # §C7 draws the ledger as ``{high-vol trend: 2, low-vol chop: 14,
        # crash: 0, …}``, and the spec's API summary writes the endpoint
        # (feature 343) in the same shape: a mapping of name to count.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        store.record("crash", 0)
        assert store.ledger().counts == {
            "high-volatility trend": 2,
            "low-volatility chop": 14,
            "crash": 0,
        }

    def test_counts_is_a_fresh_mapping_per_call(self, store) -> None:
        # A caller cannot mutate this value's answer: the view is built
        # from the rows on demand, so a caller that edits the dict it was
        # handed leaves the ledger — and the next caller — untouched.
        store.record("crash", 1)
        ledger = store.ledger()
        handed = ledger.counts
        handed["crash"] = 999
        handed["invented"] = 5
        assert ledger.counts == {"crash": 1}

    def test_covered_is_the_complement_of_empty(self, store) -> None:
        # Feature 289 refuses a regime-diverse claim while fewer than
        # three strata hold stored worlds, so *which* strata hold worlds
        # is a figure its own, named once here rather than recomputed at
        # every call site.
        store.record("crash", 0)
        store.record("low-volatility chop", 3)
        store.record("high-volatility trend", 1)
        ledger = store.ledger()
        assert [row.stratum for row in ledger.covered] == [
            "high-volatility trend",
            "low-volatility chop",
        ]
        assert [row.stratum for row in ledger.empty] == ["crash"]
        assert len(ledger.covered) + len(ledger.empty) == len(ledger)

    def test_the_views_are_derived_not_stored(self, store) -> None:
        # Nothing in the value is a second copy of the content: the rows
        # are the only state, and every other answer is computed from
        # them.  Asserted structurally — the dataclass has one field — so
        # a future edit that added a memo would have to delete this test
        # to land.
        fields = [field.name for field in dataclasses.fields(CoverageLedger)]
        assert fields == ["rows"]

    def test_two_ledgers_with_the_same_rows_are_the_same_ledger(self, store) -> None:
        # The lookup index is not part of the value: equality is over the
        # rows, so a read and a hand-built ledger that hold the same
        # content are equal — which is what makes a reading worth
        # comparing against an earlier one.
        store.record("crash", 2)
        read = store.ledger()
        hand_built = CoverageLedger(rows=read.rows)
        assert read == hand_built
        assert read.counts == hand_built.counts
        assert read.holes() == hand_built.holes()

    def test_a_hand_built_ledger_is_canonicalized(self) -> None:
        # The value sorts its own rows, so a ledger assembled out of order
        # answers in the same order a read does — the SQL clause keeps the
        # database's answer stable, the sort keeps the value's answer
        # stable, and the two cannot disagree.
        rows = (
            CoverageCount(stratum="zulu", world_count=1, updated_at="t"),
            CoverageCount(stratum="alpha", world_count=2, updated_at="t"),
        )
        ledger = CoverageLedger(rows=rows)
        assert [row.stratum for row in ledger.rows] == ["alpha", "zulu"]
        assert list(ledger) == ["alpha", "zulu"]


# -- The value's own protocol ------------------------------------------------------


class TestTheLedgerValue:
    """The ledger as a value: lookup, membership, length."""

    def test_one_stratum_can_be_looked_up(self, store) -> None:
        store.record("crash", 6)
        assert store.ledger()["crash"].world_count == 6

    def test_looking_up_a_name_the_ledger_lacks_is_a_key_error(self, store) -> None:
        # The Mapping protocol's own answer, and deliberately not a
        # CoverageError: a name the ledger does not hold is not a fault of
        # the ledger or of the ask — it is the *never named* fact, and a
        # caller that needs it spelled as something it can hold wants
        # ``holes`` or the store's ``get``.
        store.record("crash", 1)
        with pytest.raises(KeyError):
            store.ledger()["low-volatility chop"]

    def test_get_answers_none_for_a_name_the_ledger_lacks(self, store) -> None:
        store.record("crash", 1)
        ledger = store.ledger()
        assert ledger.get("crash").world_count == 1
        assert ledger.get("low-volatility chop") is None
        assert ledger.get("low-volatility chop", "absent") == "absent"

    def test_get_does_not_reread_the_table(self, store, database_url) -> None:
        # A value is a *reading*: something written after it was taken is
        # not in it.  The store's ``get`` asks the table and would see the
        # new count; the ledger's ``get`` asks the ledger in hand.  The
        # two are spelled the same way on purpose, and the difference is
        # what "current" means for each.
        store.record("crash", 1)
        ledger = store.ledger()
        store.record("crash", 99)
        assert ledger.get("crash").world_count == 1
        assert store.get("crash").world_count == 99

    def test_membership_is_total(self, store) -> None:
        # ``in`` is a question, and a question about a non-stratum has the
        # answer *no* rather than a refusal — the refusal belongs on the
        # paths that would otherwise act on the value.  Feature 286's
        # warning, and any caller asking "was this stratum ever named?",
        # must not have to guard the question.
        store.record("crash", 1)
        ledger = store.ledger()
        assert "crash" in ledger
        assert "Crash" not in ledger  # nothing is normalised, on either side
        assert "low-volatility chop" not in ledger
        assert "" not in ledger
        assert None not in ledger
        assert 7 not in ledger

    def test_looking_up_a_name_that_cannot_be_a_stratum_is_refused(self, store) -> None:
        # A blank name is not a stratum the ledger failed to hold — it is
        # not a stratum at all, so no ledger could ever hold it and the
        # honest answer is the ask's refusal rather than a KeyError.
        store.record("crash", 1)
        with pytest.raises(CoverageError):
            store.ledger()[""]

    def test_len_counts_strata_not_worlds(self, store) -> None:
        # §C7's ledger drawn as a set of keys: three names are three names
        # whether they hold two worlds between them or two million.  The
        # two questions are ``len(ledger)`` and ``ledger.counts``.
        store.record("crash", 0)
        store.record("low-volatility chop", 5)
        store.record("high-volatility trend", 5000)
        assert len(store.ledger()) == 3
        assert sum(store.ledger().counts.values()) == 5005

    def test_an_empty_ledger_answers_every_protocol_question(self) -> None:
        ledger = CoverageLedger(rows=())
        assert len(ledger) == 0
        assert list(ledger) == []
        assert ledger.counts == {}
        assert ledger.get("crash") is None
        assert "crash" not in ledger
        assert ledger.empty == ()
        assert ledger.covered == ()
        with pytest.raises(KeyError):
            ledger["crash"]


# -- The ask is refused ------------------------------------------------------------


class TestTheAskIsRefused:
    """A malformed ask is refused, and refused in feature 283's vocabulary."""

    def test_a_vocabulary_that_cannot_be_one_is_refused(self, store) -> None:
        # A single string is a sequence of its characters, which is not a
        # set of strata — the trap worth naming, because ``"crash"``
        # iterates happily and would report five holes named ``c``, ``r``
        # and so on.
        store.record("crash", 1)
        with pytest.raises(CoverageError) as raised:
            store.ledger().holes("crash")
        assert "vocabulary" in str(raised.value)

    def test_a_vocabulary_with_a_blank_name_is_refused(self, store) -> None:
        # A blank name is not a stratum the ledger is missing; it is a
        # malformed ask, and the refusal is feature 283's own validator —
        # imported rather than re-written, so the reader and the writer
        # cannot drift on what a name is.
        store.record("crash", 1)
        with pytest.raises(CoverageError):
            store.ledger().holes(("crash", "   "))

    def test_a_vocabulary_naming_one_stratum_twice_is_refused(self, store) -> None:
        # A duplicate would report one missing stratum twice.  Refused
        # rather than deduplicated: silently repairing it would hide the
        # caller's bug behind a clean-looking answer.
        store.record("crash", 1)
        with pytest.raises(CoverageError) as raised:
            store.ledger().holes(("momentum", "momentum"))
        assert "twice" in str(raised.value)

    def test_a_vocabulary_the_ledger_cannot_be_asked_of_is_refused(self) -> None:
        with pytest.raises(CoverageError):
            CoverageLedger(rows=()).holes(7)

    def test_a_ledger_of_rows_that_is_not_a_collection_is_refused(self) -> None:
        with pytest.raises(CoverageError) as raised:
            CoverageLedger(rows="crash")
        assert "iterable" in str(raised.value)

    def test_a_refused_ask_leaves_the_ledger_alone(self, store, database_url) -> None:
        # The refusals are about the ask rather than about the data: the
        # read is a read, and a refused question writes nothing.
        store.record("crash", 1)
        before = _raw_ledger(database_url)
        with pytest.raises(CoverageError):
            store.ledger().holes(("crash", "crash"))
        assert _raw_ledger(database_url) == before


# -- The data is validated ---------------------------------------------------------


class TestTheRowsAreValidated:
    """SQLite's columns are dynamically typed; a read validates what it reads."""

    def test_a_count_that_is_not_a_number_is_refused_naming_the_stratum(
        self, store, database_url
    ) -> None:
        # A raw INSERT from another tool can land anything in this column,
        # and a ledger read that swallowed it would report a count nobody
        # wrote.  The message names the *stratum*, because a whole-ledger
        # read's most useful failure is which row is unreadable.
        store.record("crash", 1)
        _write_raw_row(database_url, "low-volatility chop", "fourteen", store=store)
        with pytest.raises(CoverageError) as raised:
            store.ledger()
        assert "low-volatility chop" in str(raised.value)

    def test_a_negative_count_is_refused(self, store, database_url) -> None:
        # §C6's excision empties a stratum; it never owes worlds.  A
        # negative count is not a number of stored worlds.
        _write_raw_row(database_url, "crash", -3, store=store)
        with pytest.raises(CoverageError) as raised:
            store.ledger()
        assert "crash" in str(raised.value)

    def test_a_fractional_count_is_refused(self, store, database_url) -> None:
        _write_raw_row(database_url, "crash", 2.5, store=store)
        with pytest.raises(CoverageError):
            store.ledger()

    def test_a_count_in_a_stored_text_type_is_coerced_by_sqlite(
        self, store, database_url
    ) -> None:
        # The INT column affinity means a numeric *string* lands as a
        # number, which is SQLite's own rule and not this module's to
        # second-guess — recorded so the reader's behaviour against a raw
        # write of ``"7"`` is a pinned fact rather than a surprise.  What
        # the reader refuses is what is still not a count *after* the
        # column's affinity has had its say.
        _write_raw_row(database_url, "crash", "7", store=store)
        assert store.ledger().counts == {"crash": 7}

    def test_a_ledger_naming_one_stratum_twice_is_refused(self) -> None:
        # The table's primary key makes this unreachable from a read, so
        # it is a *hand-built* ledger's failure — and it is refused
        # because such a ledger's ``len``, ``counts`` and ``empty`` would
        # disagree about how many strata it holds.
        rows = (
            CoverageCount(stratum="crash", world_count=1, updated_at="t"),
            CoverageCount(stratum="crash", world_count=2, updated_at="t"),
        )
        with pytest.raises(CoverageError) as raised:
            CoverageLedger(rows=rows)
        assert "twice" in str(raised.value)

    def test_a_row_without_a_vintage_is_refused(self) -> None:
        # The table declares updated_at NOT NULL because a coverage number
        # without an instant is not evidence, so a ledger holding a row
        # without one is not a ledger this module can report.
        with pytest.raises(CoverageError) as raised:
            CoverageLedger(
                rows=(CoverageCount(stratum="crash", world_count=1, updated_at=None),)
            )
        assert "crash" in str(raised.value)

    def test_a_row_that_is_not_a_row_is_refused(self) -> None:
        with pytest.raises(CoverageError):
            CoverageLedger(rows=(("crash", 1),))


# -- The address is refused --------------------------------------------------------


class TestTheAddressIsRefused:
    """A ``DATABASE_URL`` this member cannot speak is refused by name."""

    def test_the_module_level_read_refuses_a_url_it_cannot_speak(self) -> None:
        with pytest.raises(CoverageError) as raised:
            read_ledger(database_url="postgresql://localhost/nullius")
        assert "scheme" in str(raised.value)

    def test_an_in_memory_ledger_is_refused(self) -> None:
        # The ledger must outlive the call that wrote it — the endpoint
        # and the promotion gate read these rows from another process
        # entirely, so an in-memory database has no ledger to read.
        with pytest.raises(CoverageError):
            read_ledger(database_url="sqlite:///:memory:")

    def test_the_store_path_refuses_the_same_url(self, store) -> None:
        # The store's own verb goes through the same translation, so the
        # two spellings of the read refuse identically.
        with pytest.raises(CoverageError):
            RegimeCoverage("postgresql://localhost/nullius").ledger()


# -- The module-level spelling -----------------------------------------------------


class TestTheModuleLevelSpelling:
    """``read_ledger`` — feature 284's sentence as one call."""

    def test_reads_the_ledger_the_database_names(self, database_url) -> None:
        persist_coverage("crash", 2, database_url=database_url)
        assert read_ledger(database_url=database_url).counts == {"crash": 2}

    def test_resolves_from_the_environment(self, monkeypatch, database_url) -> None:
        # The same seam ``persist_coverage`` resolves: a caller that
        # persists through one and reads through the other is reading the
        # rows it wrote.
        monkeypatch.setenv(DATABASE_URL_ENV, database_url)
        persist_coverage("crash", 5)
        assert read_ledger().counts == {"crash": 5}

    def test_an_explicit_url_is_preferred(self, monkeypatch, database_url) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere-else.db")
        persist_coverage("crash", 5, database_url=database_url)
        assert read_ledger(database_url=database_url).counts == {"crash": 5}

    def test_an_explicit_env_mapping_is_preferred(self, database_url) -> None:
        persist_coverage("crash", 5, database_url=database_url)
        ledger = read_ledger(env={DATABASE_URL_ENV: database_url})
        assert ledger.counts == {"crash": 5}

    def test_no_store_at_all_is_refused_by_name(self, monkeypatch) -> None:
        # Deliberately *not* an empty ledger.  An empty CoverageLedger is
        # a real answer about a real database — no census has run, so
        # nothing is named.  A deployment with no database has no ledger
        # to be empty, and answering ``()`` would report *coverage is zero
        # everywhere* about a system whose coverage was never counted —
        # a finding about the pool where the truth is a wiring fault.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        with pytest.raises(CoverageError) as raised:
            read_ledger()
        assert DATABASE_URL_ENV in str(raised.value)

    def test_a_blank_environment_value_counts_as_unset(self, monkeypatch) -> None:
        monkeypatch.setenv(DATABASE_URL_ENV, "   ")
        with pytest.raises(CoverageError):
            read_ledger()

    def test_reading_an_untouched_database_names_a_stratum_nowhere(
        self, database_url
    ) -> None:
        # The distinction the refusal above turns on, from the other side:
        # a *named* database with no census run against it is an empty
        # ledger, answered rather than refused.
        ledger = read_ledger(database_url=database_url)
        assert ledger.rows == ()
        assert [hole.stratum for hole in ledger.holes()] == list(DEFAULT_STRATA)


# -- The composition ---------------------------------------------------------------


class TestTheComposedLedger:
    """The read through the composed component — the form a reader uses."""

    def test_the_composed_store_serves_the_ledger(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The endpoint that publishes this ledger (feature 343) and the
        # promotion gate that blocks on it (285) reach the store the
        # factory composed, not a store they built.  The loader imports
        # each member under a synthetic name, so the composed store's
        # classes are structurally identical to a direct import's but not
        # the same objects — which is why the checks here are on behaviour
        # and on names rather than on isinstance.
        from app.module_loader import create_app

        url = f"sqlite:///{tmp_path / 'composed-ledger.db'}"
        monkeypatch.setenv(DATABASE_URL_ENV, url)
        composed = create_app().get("regime")
        assert composed is not None
        composed.record("crash", 4)
        composed.record("low-volatility chop", 0)

        ledger = composed.ledger()

        assert type(ledger).__name__ == "CoverageLedger"
        assert ledger.counts == {"crash": 4, "low-volatility chop": 0}
        assert [row.stratum for row in ledger.empty] == ["low-volatility chop"]
        assert [row.stratum for row in ledger.holes()] == ["high-volatility trend"]

    def test_the_composed_stores_ledger_row_is_a_count(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The composed store's CoverageCount is the loader's copy of the
        # class, so the value's own duck-typed validation is what makes a
        # composed read work at all — an isinstance check would refuse
        # every row a composed store handed back.
        from app.module_loader import create_app

        monkeypatch.setenv(DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'c.db'}")
        composed = create_app().get("regime")
        composed.record("crash", 1)
        row = composed.ledger().rows[0]
        assert type(row).__name__ == "CoverageCount"
        assert row.stratum == "crash"
        assert row.world_count == 1
        assert row.empty is False
