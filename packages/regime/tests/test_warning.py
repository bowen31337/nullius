"""Feature 286's act: the ``empty_stratum`` warning, emitted not raised.

app_spec.xml, "Regime Coverage Strata", feature 286: *System emits an
``empty_stratum`` warning when any named regime stratum holds 0 stored
worlds.*  Feature 283 persists the counts, feature 284 reads them back as
one ledger, and this file pins the category's *report* over that reading —
the spec's one emission that is a **warning** rather than an *alert*, and
the sentence's two load-bearing phrases are what most of it is about.

*"**Emits**"* — the act is :func:`warnings.warn`, never a raise: a named
stratum holding no worlds is §C7's own ``crash: 0``, a by-design state the
census writes (zeros included) and the warning *reports*, so the caller
proceeds while the finding lands where Python's warning machinery puts it.
The tests that check the warning is *emitted* — the category, the code
word, the names, §C7, the repair — and that the caller is **not** stopped,
are the ones that keep the emission worth catching.

*"**Named** regime stratum"* — ``0107`` detail 1 at this seam, and the
whole design: a stratum *named and holding no worlds* is a row with
``world_count = 0`` (feature 286's warning fires on exactly that state),
while a stratum *nobody named* is the absence of a row — a different fact
the warning must never fire on.  The warning reads the reading's own
:attr:`~regime.ledger.CoverageLedger.empty` view and never consults a
vocabulary, so it fires on §C7's ``crash: 0`` and never on a stratum
nobody configured.

Every claim about what the pool holds is checked **both ways**: through
the warning over a reading, and through raw SQL against the table, the
discipline the coverage, ledger and diversity suites state.  The
emission-writes-nothing tests exist because a report is not a persist: the
table is exactly what it was whether the warning fired or not.
"""

from __future__ import annotations

import sqlite3
import warnings
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    COVERAGE_TABLE,
    DEFAULT_STRATA,
    EMPTY_STRATUM_CODE,
    STRATUM_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageCount,
    CoverageError,
    EmptyStratumWarning,
    EmptyStratumWarningError,
    RegimeCoverage,
    RegimeError,
    emit_empty_stratum_warning,
    empty_stratum_warning,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL.

    This suite's own four lines rather than a call into the member, on the
    same terms the coverage, ledger and diversity suites state: the
    store's ``_sqlite_path`` is private, and a test reaching into it would
    be pinning an implementation detail it should be free to change.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_rows(database_url: str) -> list[tuple[object, ...]]:
    """Every row the table holds, as a reader with no code in common with
    this member would read it.

    The both-ways instrument: the warning is read off a ledger the table
    fed, so the other half of every assertion here needs the table's own
    word for what the pool holds.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN} FROM {COVERAGE_TABLE}"
        )
        try:
            return list(cursor.fetchall())
        finally:
            cursor.close()


def _covered_names(database_url: str) -> list[str]:
    """The strata the table itself says hold stored worlds, sorted.

    The figure computed the raw way — ``world_count > 0`` — so a test
    asserting the reading carried *two* covered strata is asserting it
    against the table, not against the ledger's own ``covered`` view.
    """
    return sorted(
        stratum
        for stratum, world_count in _raw_rows(database_url)
        if world_count
    )


# -- The feature's own sentence ----------------------------------------------------


class TestTheEmission:
    """*System emits an ``empty_stratum`` warning* — the act itself."""

    def test_c7s_own_example_ledger_emits_the_warning(self, store, database_url) -> None:
        # §C7 draws its example ledger as ``{high-vol trend: 2, low-vol
        # chop: 14, crash: 0, …}`` — two strata holding worlds beside a
        # named and empty crash nobody acted on.  The warning is the
        # report, and the message carries everything an operator needs:
        # the code word, the count, the named stratum, §C7 and the repair.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        store.record("crash", 0)

        with pytest.warns(EmptyStratumWarning) as warned:
            emitted = emit_empty_stratum_warning(store.ledger())

        record = warned[0].message
        message = str(record)
        assert message.startswith(f"{EMPTY_STRATUM_CODE}: 1 named stratum holds")
        assert "'crash'" in message
        assert "§C7" in message
        assert "feature 290" in message  # the census, one way out
        assert "feature 287" in message  # the backfill, the other
        # The record carries the names, so catching by type still leaves them.
        assert record.strata == ("crash",)
        assert emitted is record
        # Both ways: the table's own word for the figure the reading carried.
        assert _covered_names(database_url) == [
            "high-volatility trend",
            "low-volatility chop",
        ]

    def test_the_emission_does_not_stop_the_caller(self, store) -> None:
        # The warning is non-fatal by construction: the call returns the
        # warning, and the caller proceeds past it — the promotion gate
        # (feature 285) and the diversity verdict (289) are the callers
        # that stop, on their own sentences.
        store.record("crash", 0)
        with pytest.warns(EmptyStratumWarning):
            emitted = emit_empty_stratum_warning(store.ledger())
        assert emitted is not None  # returned, not raised

    def test_two_empty_strata_are_named_in_reading_order(self, store) -> None:
        # The ledger's rows are name-ordered, so the warning names the
        # empties in the order an operator reading the ledger would — and
        # the plural verb.
        store.record("crash", 0)
        store.record("high-volatility trend", 0)
        with pytest.warns(EmptyStratumWarning) as warned:
            emit_empty_stratum_warning(store.ledger())
        assert warned[0].message.strata == ("crash", "high-volatility trend")
        assert "2 named strata hold no stored worlds" in str(warned[0].message)

    def test_a_ledger_whose_named_strata_all_hold_none_warns(self, store) -> None:
        # Three named-empty rows, zero worlds stored: ``len(ledger)`` is
        # three and every one is empty.  Feature 286's warning fires on
        # exactly this state; the diversity verdict refuses a claim over
        # it, but this module only reports it.
        for name in DEFAULT_STRATA:
            store.name_stratum(name)
        with pytest.warns(EmptyStratumWarning) as warned:
            emit_empty_stratum_warning(store.ledger())
        assert set(warned[0].message.strata) == set(DEFAULT_STRATA)

    def test_no_warning_when_every_named_stratum_holds_worlds(self, store) -> None:
        # The finding's absence: every named stratum holds a stored world,
        # so there is nothing to report.  The emission answers ``None`` and
        # Python's warning machinery is never touched.
        for name, count in zip(DEFAULT_STRATA, (1, 1, 5000)):
            store.record(name, count)
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # any warning would fail this
            assert emit_empty_stratum_warning(store.ledger()) is None

    def test_a_ledger_naming_nothing_warns_nothing(self, store) -> None:
        # A database where no census has run names no stratum, so no
        # stratum is *named and empty* — the promotion gate's and the
        # diversity verdict's finding, not this module's.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert emit_empty_stratum_warning(store.ledger()) is None

    def test_named_empty_fires_but_never_named_does_not(self, tmp_path: Path) -> None:
        # ``0107`` detail 1 at this seam, held still: a stratum named and
        # empty (a row with a zero) fires the warning; a stratum never
        # named (no row at all) does not — different facts, and the
        # warning reads the reading's ``empty`` view, never a vocabulary.
        named_empty = RegimeCoverage(f"sqlite:///{tmp_path / 'named-empty.db'}")
        never_named = RegimeCoverage(f"sqlite:///{tmp_path / 'never-named.db'}")
        for s in (named_empty, never_named):
            s.record("high-volatility trend", 2)
        named_empty.record("crash", 0)  # named and empty

        with pytest.warns(EmptyStratumWarning):
            emit_empty_stratum_warning(named_empty.ledger())
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert emit_empty_stratum_warning(never_named.ledger()) is None


# -- The two spellings ---------------------------------------------------------------


class TestTheTwoSpellings:
    """The pure question, and the emission's own act."""

    def test_the_pure_question_builds_the_warning(self, store) -> None:
        # :func:`empty_stratum_warning` is the finding as a value, or
        # ``None`` — it emits nothing, opens no database, writes no row.
        store.record("crash", 0)
        warning = empty_stratum_warning(store.ledger())
        assert isinstance(warning, EmptyStratumWarning)
        assert warning.strata == ("crash",)

    def test_the_pure_question_answers_none_when_all_covered(self, store) -> None:
        store.record("crash", 3)
        assert empty_stratum_warning(store.ledger()) is None

    def test_the_pure_question_emits_nothing(self, store) -> None:
        # Asking for the finding is not reporting it: a caller that renders
        # the finding itself reaches for the pure question, and pays for
        # no warning.
        store.record("crash", 0)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert empty_stratum_warning(store.ledger()) is not None

    def test_the_emission_returns_what_it_emitted(self, store) -> None:
        # One value for both: a caller that logs as well as warns holds the
        # record the machinery dispatched on.
        store.record("crash", 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            returned = emit_empty_stratum_warning(store.ledger())
        assert isinstance(returned, EmptyStratumWarning)
        assert returned.strata == ("crash",)

    def test_the_emission_returns_none_when_nothing(self, store) -> None:
        store.record("crash", 1)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert emit_empty_stratum_warning(store.ledger()) is None

    def test_the_pure_question_never_warns_even_when_the_finding_exists(
        self, store
    ) -> None:
        # Keeping the two apart is what lets a caller ask for the finding
        # without paying for the report: the pure question builds the
        # warning but hands it to no machinery.
        store.record("crash", 0)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            empty_stratum_warning(store.ledger())


# -- The record --------------------------------------------------------------------


class TestTheRecord:
    """The finding as the machinery dispatches on it, and a caller catches it."""

    def test_the_record_is_the_category_and_carries_the_names(self) -> None:
        record = EmptyStratumWarning(("crash", "momentum ignition"))
        assert isinstance(record, Warning)
        assert record.strata == ("crash", "momentum ignition")
        assert str(record).startswith(
            f"{EMPTY_STRATUM_CODE}: 2 named strata hold no stored worlds"
        )

    def test_the_record_defends_its_own_consistency(self) -> None:
        # A warning naming no stratum is not a finding any reading produced,
        # and a warning naming one stratum twice reports one emptiness
        # twice — both refused.
        with pytest.raises(EmptyStratumWarningError):
            EmptyStratumWarning(())
        with pytest.raises(EmptyStratumWarningError):
            EmptyStratumWarning(("crash", "crash"))

    def test_the_record_validates_its_names(self) -> None:
        with pytest.raises(EmptyStratumWarningError):
            EmptyStratumWarning(("   ",))
        with pytest.raises(EmptyStratumWarningError):
            EmptyStratumWarning("crash")  # a single string, not an iterable of names

    def test_the_record_is_str_displayable(self) -> None:
        # The full operator message is carried in the standard ``args``, so
        # ``str()`` is display-ready and the machinery's default rendering
        # needs nothing from the class.
        record = EmptyStratumWarning(("crash",))
        assert str(record) == record.args[0]
        assert EMPTY_STRATUM_CODE in str(record)


# -- The ask is refused --------------------------------------------------------------


class TestTheAskIsRefused:
    """An emission that could not be made honestly is refused, and named."""

    def test_nothing_handed_in_is_refused(self) -> None:
        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(None)
        assert "carries no ``empty``" in str(raised.value)

    def test_a_string_is_refused(self) -> None:
        # A string is not a reading of anything; it is refused as an ask
        # rather than iterated into characters.
        with pytest.raises(EmptyStratumWarningError):
            emit_empty_stratum_warning("crash")

    def test_a_store_where_the_reading_belongs_is_refused_with_its_repair(
        self, store
    ) -> None:
        # The easy mistake: the emission takes the reading, and a caller
        # holding the store hands the store.  The refusal names the repair
        # — call ``ledger()`` on it first — rather than leaving the caller
        # to guess why a store "carries no empty view".
        store.record("crash", 0)
        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(store)
        message = str(raised.value)
        assert "is the store" in message
        assert "``ledger()``" in message
        assert "feature 284" in message

    def test_an_empty_view_that_cannot_be_read_is_refused(self) -> None:
        # The seam reads what it reads: a carrier whose ``empty`` view is
        # not an iterable of rows cannot produce a finding.
        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(EmptyStratumWarningError)  # a class, not a reading
        assert "cannot be read" in str(raised.value) or "carries no" in str(raised.value)

    def test_a_carrier_whose_view_disagrees_with_its_own_row_is_refused(
        self, store
    ) -> None:
        # Feature 253's discipline for a carrier whose flag disagrees with
        # its own state: the ``empty`` view is *defined* as the rows
        # holding no worlds, so a carrier naming as empty a row whose own
        # count says three is refused rather than believed — a phantom
        # finding an operator would chase.
        store.record("crash", 3)

        class _LyingLedger:
            empty = (CoverageCount(stratum="crash", world_count=3, updated_at="2026-01-01"),)

        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(_LyingLedger())
        assert "world_count is 3" in str(raised.value)

    def test_an_empty_row_without_a_usable_name_is_refused(self) -> None:
        # The seam validates what it reads: an empty row carrying no
        # stratum name cannot be named in the warning, and a warning that
        # could not say which stratum was empty would be a finding about
        # nothing.
        class _Row:
            world_count = 0

        class _Ledger:
            empty = (_Row(),)

        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(_Ledger())
        assert "could not be read as a stratum" in str(raised.value)

    def test_an_empty_row_without_a_usable_count_is_refused(self) -> None:
        # And the count is checked against its own row: an empty row whose
        # ``world_count`` is not a genuine count is a carrier this module
        # cannot vouch for.
        class _Row:
            stratum = "crash"
            world_count = "none"

        class _Ledger:
            empty = (_Row(),)

        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(_Ledger())
        assert "could not be read as a count" in str(raised.value)

    def test_the_seam_translates_the_count_vocabulary(self) -> None:
        # The name and count checks are feature 283's own validators,
        # imported rather than re-written — and their refusals are
        # *translated* into this module's class at the seam, so a caller's
        # ``except EmptyStratumWarningError`` is never defeated by the
        # count-persist vocabulary for an act that persisted nothing.
        class _Row:
            stratum = "   "
            world_count = 0

        class _Ledger:
            empty = (_Row(),)

        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(_Ledger())
        assert EMPTY_STRATUM_CODE in str(raised.value)
        # And the count-persist class does not catch it — the translation
        # at the seam is the whole point, spelled the direct way:
        try:
            emit_empty_stratum_warning(_Ledger())
        except CoverageError:
            raise AssertionError("a blank name is not a persist's refusal")
        except EmptyStratumWarningError:
            pass


# -- The refusals class --------------------------------------------------------------


class TestTheRefusalsClass:
    """The sibling seat :mod:`regime.errors` reserved for this feature."""

    def test_the_refusal_is_not_a_coverage_error(self) -> None:
        # The reservation's reason, pinned: an emission that could not be
        # made honestly is not a persist that failed, and a caller
        # catching :class:`CoverageError` for a refused count must not
        # find a refused emission behind the same ``except`` — the repairs
        # differ (call ``ledger()`` first versus a corrected re-ask).
        with pytest.raises(EmptyStratumWarningError):
            emit_empty_stratum_warning(None)
        try:
            emit_empty_stratum_warning(None)
        except CoverageError:
            raise AssertionError("the emission's refusal is not a persist's")
        except EmptyStratumWarningError:
            pass

    def test_the_finding_is_never_raised(self, store) -> None:
        # The feature's whole distinction from its refusing siblings: the
        # finding is *emitted*, never raised.  A named stratum holding no
        # worlds is §C7's ``crash: 0`` — warned, and the caller proceeds.
        store.record("crash", 0)
        with pytest.warns(EmptyStratumWarning) as warned:
            emitted = emit_empty_stratum_warning(store.ledger())
        # A Warning, never an error — the finding is published, not raised,
        # so the caller that forgets to catch loses nothing.  (``Warning``
        # is an ``Exception`` subclass in Python, so the distinction is
        # spelled against this member's own error class, not against
        # ``Exception``.)
        assert isinstance(emitted, EmptyStratumWarning)
        assert not isinstance(emitted, EmptyStratumWarningError)
        assert not isinstance(warned[0].message, EmptyStratumWarningError)

    def test_the_refusal_is_catchable_as_the_members_base(self) -> None:
        # One ``except RegimeError`` still catches every failure of the
        # member's path — the point of the shared base.
        with pytest.raises(RegimeError):
            emit_empty_stratum_warning(None)

    def test_the_code_word_opens_the_refusal(self) -> None:
        # Greppable by the one word that names the finding, in the family
        # ``pool_too_thin``, ``full_history_fit`` and ``no_origin`` already
        # establish — an operator greps the log, not the traceback.
        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(None)
        assert str(raised.value).startswith(f"{EMPTY_STRATUM_CODE}:")

    def test_the_refusal_names_the_way_out(self) -> None:
        # A warning that failed quietly would be read as *every stratum
        # holds worlds* — the exact blindness §C7's ledger exists to cure —
        # so the refusal names the repair: call feature 284's read first.
        with pytest.raises(EmptyStratumWarningError) as raised:
            emit_empty_stratum_warning(None)
        assert "feature 284" in str(raised.value)
        assert "``empty``" in str(raised.value)


# -- The seam ----------------------------------------------------------------------


class TestTheSeam:
    """The warning over readings the member's other spellings answer."""

    def test_a_hand_built_duck_ledger_is_warned(self) -> None:
        # No ``isinstance`` gate: the module loader imports this member
        # under a synthetic name, so the reading a composed store hands
        # back is structurally identical to a direct import's without
        # being the same class object — and a warning that gated on the
        # class would refuse the very reading composition serves.  A
        # hand-built duck with the one attribute the warning reads is
        # warned identically.

        class Row:
            def __init__(self, stratum: str) -> None:
                self.stratum = stratum
                self.world_count = 0

        class DuckLedger:
            def __init__(self, *names: str) -> None:
                self.empty = tuple(Row(name) for name in names)

        with pytest.warns(EmptyStratumWarning) as warned:
            emit_empty_stratum_warning(DuckLedger("crash", "chop"))
        assert set(warned[0].message.strata) == {"crash", "chop"}

    def test_the_module_level_read_emits_too(self, database_url) -> None:
        # Feature 284's two spellings reach the same reading, and the
        # warning is over the reading: a count persisted through the store,
        # warned over ``read_ledger``'s answer.
        from regime import persist_coverage, read_ledger

        persist_coverage("crash", 0, database_url=database_url)
        persist_coverage("low-volatility chop", 2, database_url=database_url)
        with pytest.warns(EmptyStratumWarning) as warned:
            emit_empty_stratum_warning(read_ledger(database_url=database_url))
        assert warned[0].message.strata == ("crash",)

    def test_the_composed_stores_reading_emits(self, monkeypatch, tmp_path: Path) -> None:
        # The promise the member's ``__init__`` makes — the ``empty_stratum``
        # warning is emitted over counts read out of the composed store —
        # pinned through the real factory.  The loader's copies make
        # ``isinstance`` unusable, so the assertions are on behaviour: the
        # composed reading emits exactly as a direct import's does, and the
        # warning is the composed class.
        from app.module_loader import create_app

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
        composed = create_app().get("regime")
        assert composed is not None
        composed.record("high-volatility trend", 2)
        composed.record("crash", 0)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            emitted = emit_empty_stratum_warning(composed.ledger())
        assert type(emitted).__name__ == "EmptyStratumWarning"
        assert emitted.strata == ("crash",)

    def test_the_warning_reads_the_reading_it_was_handed(self, store) -> None:
        # A value is a reading: the warning does not re-read the table
        # behind the ledger's back.  A warning emitted over a reading that
        # has gone stale reports *that reading's* pool — the stale reading
        # still names crash as empty even though the table has since
        # covered it — and the caller warning about the pool *now* reads
        # again.
        store.record("high-volatility trend", 2)
        store.record("crash", 0)
        stale = store.ledger()  # a frozen snapshot: crash empty

        store.record("crash", 5)  # the pool moved under the reading

        # The stale reading still reports crash empty — it is not refreshed.
        with pytest.warns(EmptyStratumWarning) as warned:
            emit_empty_stratum_warning(stale)
        assert warned[0].message.strata == ("crash",)
        # A fresh reading reports the truth: crash is covered now, no warning.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert empty_stratum_warning(store.ledger()) is None

    def test_the_emission_writes_nothing(self, store, database_url) -> None:
        # A report is not a persist: the emission's whole act is a reading
        # and a warning, and the table is byte for byte what it was whether
        # the warning fired or not — checked against the table, not against
        # the store's own answers.
        store.record("high-volatility trend", 2)
        store.record("crash", 0)
        before = _raw_rows(database_url)

        with pytest.warns(EmptyStratumWarning):
            emit_empty_stratum_warning(store.ledger())

        assert sorted(_raw_rows(database_url)) == sorted(before)


# -- The module's place in the member ----------------------------------------------


class TestTheModulesPlace:
    """A report beside the store, not a second seat."""

    def test_the_member_exports_the_warning_and_no_new_builder(self) -> None:
        # The member's public vocabulary grows by this feature's names —
        # and only by them: the registered surface stays feature 283's one
        # store (``build_regime_coverage`` alone), because a report over a
        # reading resolves no configuration of its own and registers
        # nothing.
        import regime

        for name in (
            "EMPTY_STRATUM_CODE",
            "EmptyStratumWarning",
            "EmptyStratumWarningError",
            "emit_empty_stratum_warning",
            "empty_stratum_warning",
        ):
            assert name in regime.__all__, name
        assert [
            built for built in dir(regime) if built.startswith("build_")
        ] == ["build_regime_coverage"]

    def test_the_composed_ledger_feeds_the_warning(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The composed coverage ledger answers one question — *what is the
        # coverage ledger?* — and the warning is a caller of its answer rather
        # than a second thing to compose: the reading the composition
        # reaches is the reading the warning is emitted over.
        from app.module_loader import create_app

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
        store = create_app().get("regime")
        assert store is not None
        store.record("crash", 0)
        with pytest.warns(EmptyStratumWarning):
            emit_empty_stratum_warning(store.ledger())
