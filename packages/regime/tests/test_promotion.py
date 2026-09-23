"""Feature 285's act: the promotion, blocked on its target regime's coverage.

app_spec.xml, "Regime Coverage Strata", feature 285: *System rejects a
promotion when the target deployment regime has coverage below the
configured threshold.*  Feature 283 persists the counts, feature 284 reads
them back as one ledger, feature 290 makes the numbers and features 287/288
grow them; this file pins the *block* over all of that.

The sentence's four load-bearing phrases are what most of it is about.

*"**A promotion**"* — the subject is a deployment decision about to be
published, and the act is its refusal: the judgment **raises**
:class:`~regime.errors.PromotionCoverageError` rather than answering a
boolean, so the caller that calls it on its last line is stopped before the
promotion leaves the room.  The tests that check the raise *is* the
emission — the code word, the figure, the regime, the threshold, §C7, the
repair — are the ones that keep the refusal worth catching.

*"**The target deployment regime**"* — the figure is **one named stratum's**
stored-world count, and every neighbouring figure it is deliberately not is
pinned: not feature 289's ``covered`` count (a pool spread across three
strata one of which is not the target passes that sibling's claim and is
exactly this block), not ``len(ledger)`` (naming a stratum is not covering
it), and not the sum of the counts (worlds in *other* regimes are not worlds
in this one).  The suite's centrepiece is the pair of readings that separates
the two siblings.

*"**Coverage below the configured threshold**"* — the threshold is the
deployment's own number and has no default, so it is a **required keyword**
pinned from both sides (a lower threshold admits what a higher one blocks),
and the comparison is the sentence's word: *below* fails, *at* stands, no
upper edge.  A threshold that is not a count is refused rather than honoured,
zero included, because ``world_count >= 0`` admits every promotion.

*"**Coverage**"* — ``0107`` detail 1 at this seam, and the one place in the
member where collapsing it would misreport a *gate*: a target regime **named
and holding no worlds** is §C7's ``crash: 0`` — a count of zero, refused on
the *count* — while a target regime **never named** has no row, so its
coverage is unknown, and the two carry different messages in the same class
because their repairs differ.

§C7's own example ledger is the block's canonical fixture — ``{high-vol
trend: 2, low-vol chop: 14, crash: 0, …}`` — and every claim about what the
pool holds is checked **both ways**: through the judgment under test, and
through raw SQL against the table, the discipline the coverage, ledger and
diversity suites state.  The refusal-writes-nothing tests exist because a
verdict is not a persist: the table is exactly what it was whether the
promotion stands or falls.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    COVERAGE_BELOW_THRESHOLD_CODE,
    COVERAGE_TABLE,
    DEFAULT_STRATA,
    STRATUM_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageError,
    DiversityClaimError,
    PromotionCoverageError,
    RegimeCoverage,
    RegimeError,
    rejects_regime_diverse_claim,
    rejects_undercovered_promotion,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL.

    This suite's own four lines rather than a call into the member, on the
    same terms the coverage, ledger and diversity suites state: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be pinning
    an implementation detail it should be free to change.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_rows(database_url: str) -> list[tuple[object, ...]]:
    """Every row the table holds, as a reader with no code in common with
    this member would read it.

    The both-ways instrument: the judgment reads a ledger the table fed, so
    the other half of every assertion here needs the table's own word for
    what the pool holds.  Deliberately unordered — the judgment claims no
    order over rows and neither does this.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {STRATUM_COLUMN}, {WORLD_COUNT_COLUMN} FROM {COVERAGE_TABLE}"
        )
        try:
            return list(cursor.fetchall())
        finally:
            cursor.close()


def _raw_count(database_url: str, stratum: str) -> int | None:
    """One stratum's count as the table itself states it, or ``None``.

    The figure computed the raw way, so a test asserting the judgment read
    *zero* or *two* is asserting it against the table, not against the
    ledger's own lookup spelling of it.
    """
    for name, world_count in _raw_rows(database_url):
        if name == stratum:
            return world_count  # type: ignore[return-value]
    return None


# -- The feature's own sentence ----------------------------------------------------


class TestTheBlock:
    """*System rejects a promotion* — the act itself."""

    def test_a_promotion_into_an_uncovered_regime_is_refused(
        self, store, database_url
    ) -> None:
        # §C7 states the rule as an action taken at the door — *"Block
        # promotion when the regime being deployed into has coverage below
        # threshold"* — and this is that action.  The message carries
        # everything an operator needs: the code word, the regime, the
        # figure, the threshold, §C7, and the repair.
        store.record("high-volatility trend", 1)
        store.record("low-volatility chop", 14)
        store.record("crash", 0)

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )

        message = str(raised.value)
        assert message.startswith(
            f"{COVERAGE_BELOW_THRESHOLD_CODE}: the target deployment regime "
            "'crash' holds 0 stored worlds"
        )
        assert "threshold of 1" in message
        assert "§C7" in message
        assert "feature 290" in message
        assert "feature 287" in message
        # Both ways: the table's own word for the figure the judgment read.
        assert _raw_count(database_url, "crash") == 0

    def test_a_promotion_into_a_covered_regime_stands(
        self, store, database_url
    ) -> None:
        # The other half of the sentence: a regime the pool covers clears
        # the block and the deployment proceeds — and the judgment answers
        # ``None`` rather than a truthy verdict, so the caller's last line
        # is a call that either returns or stops it.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        assert (
            rejects_undercovered_promotion(
                store.ledger(), regime="low-volatility chop", threshold=14
            )
            is None
        )
        assert _raw_count(database_url, "low-volatility chop") == 14

    def test_the_figure_is_the_targets_own_count(self, store) -> None:
        # Worlds in *other* regimes are not worlds in this one: the pool
        # holds fourteen in low-volatility chop and one in high-volatility
        # trend, and a promotion into the crash regime is uncovered
        # regardless of how many worlds the rest of the pool holds.
        store.record("high-volatility trend", 1)
        store.record("low-volatility chop", 14)
        store.record("crash", 2)
        ledger = store.ledger()
        assert rejects_undercovered_promotion(
            ledger, regime="crash", threshold=2
        ) is None
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(ledger, regime="crash", threshold=3)
        assert "holds 2 stored worlds" in str(raised.value)

    def test_the_figure_is_not_the_sum_of_the_counts(self, store) -> None:
        # §C7's opening sentence made flesh: fourteen worlds in one regime
        # is the one-regime pool, and a deployment into a regime holding
        # none of them is not covered by the other fourteen.  A judgment
        # that summed the ledger would admit this promotion.
        store.record("low-volatility chop", 14)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )

    def test_the_figure_is_not_the_number_of_named_strata(self, store) -> None:
        # Naming a stratum is not covering it, and it is certainly not
        # covering *this* one: three strata named, all three empty, and a
        # promotion into any of them is blocked on the count.
        for name in DEFAULT_STRATA:
            store.name_stratum(name)
        ledger = store.ledger()
        assert len(ledger) == 3
        for name in DEFAULT_STRATA:
            with pytest.raises(PromotionCoverageError):
                rejects_undercovered_promotion(ledger, regime=name, threshold=1)

    def test_the_sentence_boundary_is_below_not_at(self, store) -> None:
        # The sentence's own comparison: rejected when coverage falls
        # *below* the configured threshold, so at exactly the threshold the
        # promotion stands.  Meeting a threshold is enough — there is no
        # band — and the asymmetry has no upper edge: more worlds in the
        # target regime only strengthen the case for deploying into it.
        for count in (1, 2, 5):
            store.record("crash", count)
            assert (
                rejects_undercovered_promotion(
                    store.ledger(), regime="crash", threshold=count
                )
                is None
            )
            with pytest.raises(PromotionCoverageError):
                rejects_undercovered_promotion(
                    store.ledger(), regime="crash", threshold=count + 1
                )

    def test_an_empty_ledger_blocks_every_promotion(self, store) -> None:
        # A database where no census has run is a real answer about a real
        # pool — an empty one, uncategorized and uncounted — and every
        # deployment into it is uncovered, on the *absence* rather than on
        # a count: no stratum is named, so none has been counted.
        ledger = store.ledger()
        assert len(ledger) == 0
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(ledger, regime="crash", threshold=1)
        assert "is not named by the ledger" in str(raised.value)

    def test_the_verdict_rules_on_the_reading_it_was_handed(self, store) -> None:
        # A value is a reading: the judgment does not re-read the table
        # behind the ledger's back.  A promotion judged over a reading that
        # has gone stale gets that reading's verdict, and the caller
        # deploying *now* reads again — both halves, because a judgment
        # that silently refreshed would be answering a question the caller
        # did not ask.
        store.record("crash", 1)
        store.record("low-volatility chop", 14)
        stale = store.ledger()

        store.record("crash", 90)  # the pool moved under the reading

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(stale, regime="crash", threshold=50)
        assert "holds 1 stored world" in str(raised.value)  # singular, and stale
        assert (
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=50
            )
            is None
        )


# -- The two siblings, and the readings that separate them -------------------------


class TestTheTwoSiblings:
    """285's figure is one stratum; 289's is how many hold worlds."""

    def test_the_readings_that_separate_the_two_judgements(self, store) -> None:
        # The suite's centrepiece, and the reason this feature is not a face
        # of feature 289.  A pool covered across the whole default
        # vocabulary, with the regime being deployed into holding none of
        # it: 289's claim — *is the pool spread across regimes?* — **stands**
        # on three covered strata, and a deployment into the fourth is
        # exactly what §C7 says to block.
        for name in DEFAULT_STRATA:
            store.record(name, 5)
        store.record("momentum ignition", 0)
        ledger = store.ledger()

        assert rejects_regime_diverse_claim(ledger) is None  # three covered
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                ledger, regime="momentum ignition", threshold=1
            )
        assert "'momentum ignition' holds 0 stored worlds" in str(raised.value)

    def test_the_narrower_reading_is_not_a_substitute(self, store) -> None:
        # The other direction, so neither sibling is read as the stronger
        # one: three names in the default vocabulary with only the *target*
        # covered.  The promotion stands — the one regime it deploys into
        # holds worlds — while 289's spread claim falls on its own figure.
        store.record("crash", 4)
        ledger = store.ledger()

        assert (
            rejects_undercovered_promotion(ledger, regime="crash", threshold=4)
            is None
        )
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(ledger)

    def test_the_block_is_not_a_diversity_refusal(self, store) -> None:
        # One ``except`` for both would put two findings — and two repairs
        # — behind one clause: the diversity refusal says *withdraw the
        # claim or spread the pool*, while this one says *grow this regime
        # or deploy elsewhere*.  Pinned as the classes the caller catches.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        try:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        except DiversityClaimError:
            raise AssertionError("a promotion block is not a claim's refusal")
        except PromotionCoverageError:
            pass


# -- The threshold -----------------------------------------------------------------


class TestTheThreshold:
    """*The configured threshold* — required, validated, and the deployment's."""

    def test_the_threshold_is_required(self, store) -> None:
        # The sentence names the figure as *"the configured threshold"* and
        # spells no number, so the number belongs to the deployment and this
        # module deliberately ships no default: a default here would be a
        # coverage floor nobody configured, which is §C7's blindness
        # legislated back in through the configuration.  Pinned as the
        # ``TypeError`` a caller omitting it gets, so the omission is a
        # loud failure rather than a silently wrong gate.
        store.record("crash", 1)
        with pytest.raises(TypeError):
            rejects_undercovered_promotion(  # type: ignore[call-arg]
                store.ledger(), regime="crash"
            )

    def test_a_lower_threshold_admits_what_a_higher_one_blocks(self, store) -> None:
        # The threshold is the deployment's own figure and the comparison
        # moves with it: the same reading, two configurations, two verdicts.
        store.record("crash", 3)
        ledger = store.ledger()
        assert (
            rejects_undercovered_promotion(ledger, regime="crash", threshold=3)
            is None
        )
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(ledger, regime="crash", threshold=4)
        assert "threshold of 4" in str(raised.value)

    def test_a_threshold_of_one_still_blocks_an_uncovered_regime(self, store) -> None:
        # Degenerate but honest: ``world_count >= 1`` still refuses a regime
        # holding no worlds, so it is the caller's to set and not this
        # module's to second-guess.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )

    def test_a_threshold_of_zero_is_refused(self, store) -> None:
        # A threshold of zero is ``world_count >= 0``, true of every count a
        # ledger can hold, so it admits every promotion — including one into
        # a regime holding no worlds at all.  That is the exact block §C7
        # asks for legislated away through the configuration, refused as an
        # ask before the reading is judged.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=0
            )
        assert "at least one stored world" in str(raised.value)

    def test_a_negative_threshold_is_refused(self, store) -> None:
        store.record("crash", 1)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=-5
            )

    def test_a_boolean_threshold_is_refused(self, store) -> None:
        # ``True`` is ``1`` in Python, so a flag where a threshold belongs
        # would read as the weakest possible coverage bar — refused for the
        # reason every count validator in this workspace refuses a bool.
        store.record("crash", 1)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=True
            )
        assert "count of stored worlds" in str(raised.value)

    def test_a_non_integer_threshold_is_refused(self, store) -> None:
        store.record("crash", 1)
        for malformed in ("1", 2.5, None):
            with pytest.raises(PromotionCoverageError):
                rejects_undercovered_promotion(
                    store.ledger(), regime="crash", threshold=malformed
                )


# -- The target regime, and the absence that is not a zero -------------------------


class TestTheTargetRegime:
    """*The target deployment regime* — a name, and the two ways it is missing."""

    def test_a_target_that_is_not_a_name_is_refused(self, store) -> None:
        store.record("crash", 1)
        for malformed in (None, "", "   ", 7, ["crash"]):
            with pytest.raises(PromotionCoverageError) as raised:
                rejects_undercovered_promotion(
                    store.ledger(), regime=malformed, threshold=1
                )
            assert "is a stratum name" in str(raised.value)

    def test_a_blank_target_is_not_answered_as_an_absence(self, store) -> None:
        # A name that cannot be a stratum is a malformed ask, not a stratum
        # the ledger failed to hold — the distinction feature 283's own
        # validator draws, honored here rather than smoothed over: an empty
        # name is not a stratum at all.
        store.record("crash", 1)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="   ", threshold=1
            )
        assert "is not named by the ledger" not in str(raised.value)

    def test_a_named_empty_regime_is_refused_on_the_count(self, store) -> None:
        # §C7's ``crash: 0`` — a row, a count of zero, and a coverage
        # finding.  The promotion is blocked on the *figure*, and the
        # message states it.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        message = str(raised.value)
        assert "holds 0 stored worlds" in message
        assert "is not named by the ledger" not in message

    def test_a_never_named_regime_is_refused_on_the_absence(self, store) -> None:
        # The other side of ``0107`` detail 1, and the one place in this
        # member where collapsing it would invent a finding: a regime with
        # no row has never been counted, so its coverage is **unknown**
        # rather than zero, and reporting an unknown as a zero would be a
        # figure the pool never produced.  Refused separately, with the
        # repair the caller actually needs — *name and count it*.
        store.record("high-volatility trend", 1)
        store.record("low-volatility chop", 2)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        message = str(raised.value)
        assert "is not named by the ledger" in message
        assert "never been counted" in message
        assert "Name the stratum and count it" in message
        # And the table has no row to have carried a count, so the "unknown"
        # is the table's own state rather than the ledger's opinion.
        assert _raw_count(_path_to_url(store), "crash") is None

    def test_named_empty_and_never_named_are_different_refusals(
        self, tmp_path: Path
    ) -> None:
        # The pair, side by side: the same figure would be reported by a
        # judgment that read an absent row as a zero, and the two messages
        # differ because the two repairs do — one needs *worlds in this
        # regime*, the other needs the stratum *counted*.
        named_empty = RegimeCoverage(f"sqlite:///{tmp_path / 'named-empty.db'}")
        never_named = RegimeCoverage(f"sqlite:///{tmp_path / 'never-named.db'}")
        for store in (named_empty, never_named):
            store.record("high-volatility trend", 1)
        named_empty.record("crash", 0)

        refusals = []
        for store in (named_empty, never_named):
            with pytest.raises(PromotionCoverageError) as raised:
                rejects_undercovered_promotion(
                    store.ledger(), regime="crash", threshold=1
                )
            refusals.append(str(raised.value))
        assert "holds 0 stored worlds" in refusals[0]
        assert "is not named by the ledger" in refusals[1]
        assert refusals[0] != refusals[1]

    def test_the_targets_name_is_normalized_by_feature_283s_validator(
        self, store
    ) -> None:
        # The name goes through the writer's own validator, imported rather
        # than re-written, so the gate cannot drift from the table on what a
        # stratum is: the strip the store applies on write applies here too,
        # and an indented or newline-terminated target reaches the row it
        # names.
        store.record("crash", 3)
        assert (
            rejects_undercovered_promotion(
                store.ledger(), regime="  crash\n", threshold=3
            )
            is None
        )


# -- The ask is refused ------------------------------------------------------------


class TestTheAskIsRefused:
    """A ledger carrying no readable reading is refused, and named."""

    def test_nothing_handed_in_is_refused(self) -> None:
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(None, regime="crash", threshold=1)
        assert "cannot be asked for one stratum's row" in str(raised.value)

    def test_a_string_is_refused(self) -> None:
        # A string is not a reading of anything; it is refused as an ask
        # rather than indexed into characters.
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion("crash", regime="crash", threshold=1)
        assert "a string is not a reading" in str(raised.value)

    def test_a_store_where_the_reading_belongs_is_refused_with_its_repair(
        self, store
    ) -> None:
        # The easy mistake, and the one this seam has to get right in a
        # particular order: feature 283's store carries a *one-stratum* read
        # of its own (``get``, for a caller holding a name), so a judgment
        # that looked for a lookup before looking for the read verb would
        # accept a live store here and then ask it a two-argument question
        # it does not answer — a ``TypeError`` where a refusal belongs.  The
        # store is identified by the verb it alone carries and refused with
        # its repair named.
        store.record("crash", 1)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(store, regime="crash", threshold=1)
        message = str(raised.value)
        assert "is the store" in message
        assert "``ledger()``" in message
        assert "feature 284" in message

    def test_an_object_with_neither_reading_nor_store_is_refused(self) -> None:
        class _Nothing:
            pass

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                _Nothing(), regime="crash", threshold=1
            )
        assert "cannot be asked for one stratum's row" in str(raised.value)

    def test_a_row_carrying_a_corrupt_count_is_refused(self) -> None:
        # SQLite's columns are dynamically typed, so a raw ``INSERT`` from
        # another tool can land anything in ``world_count``; a gate that
        # compared it would admit or block a deployment on a number nobody
        # wrote.  The refusal is this module's class, and it names the row.
        class _Row:
            stratum = "crash"
            world_count = "many"

        class _Ledger:
            def get(self, stratum: str, default: object = None) -> object:
                return _Row() if stratum == "crash" else default

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                _Ledger(), regime="crash", threshold=1
            )
        message = str(raised.value)
        assert "'crash'" in message
        assert "could not be read as a coverage count" in message

    def test_a_negative_stored_count_is_refused(self) -> None:
        # A negative number of worlds is not a number of worlds, and a
        # comparison against it would be meaningless in either direction.
        class _Row:
            stratum = "crash"
            world_count = -3

        class _Ledger:
            def get(self, stratum: str, default: object = None) -> object:
                return _Row() if stratum == "crash" else default

        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                _Ledger(), regime="crash", threshold=1
            )

    def test_the_seam_translates_the_count_vocabulary(self) -> None:
        # The name and count checks are feature 283's own validators,
        # imported rather than re-written — and their refusals are
        # *translated* into this module's class at the seam, so a caller's
        # ``except PromotionCoverageError`` is never defeated by the
        # count-persist vocabulary for an act that persisted nothing.
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(None, regime="   ", threshold=1)
        try:
            rejects_undercovered_promotion(None, regime="   ", threshold=1)
        except CoverageError:
            raise AssertionError("a blank target is not a persist's refusal")
        except PromotionCoverageError:
            pass

    def test_the_threshold_is_checked_before_the_reading_is_looked_up(
        self, store
    ) -> None:
        # The refusal order is stated and pinned: the reading's shape first,
        # then the target's name, then the threshold, and only then the
        # lookup.  A malformed threshold over a reading that names nothing
        # is therefore refused as a *threshold* — the caller's fix is the
        # number it configured, not the pool.
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=0
            )
        assert "at least one stored world" in str(raised.value)
        # And with a threshold that is fine, the same call reports the
        # absence instead.
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        assert "is not named by the ledger" in str(raised.value)


# -- The refusal's class -----------------------------------------------------------


class TestTheRefusalsClass:
    """One class for every face, because the caller is a gate."""

    def test_every_face_is_the_one_class(self, store) -> None:
        # The gathering, pinned across all five faces: a caller guarding
        # its promotion path with a single ``except`` must not have any of
        # them slip past, because the promotion would then proceed through
        # the hole.  That is the whole argument for one class here where
        # feature 289 splits its two.
        store.record("crash", 0)
        ledger = store.ledger()
        for call in (
            lambda: rejects_undercovered_promotion(None, regime="crash", threshold=1),
            lambda: rejects_undercovered_promotion(store, regime="crash", threshold=1),
            lambda: rejects_undercovered_promotion(ledger, regime="", threshold=1),
            lambda: rejects_undercovered_promotion(ledger, regime="crash", threshold=0),
            lambda: rejects_undercovered_promotion(ledger, regime="crash", threshold=1),
            lambda: rejects_undercovered_promotion(
                ledger, regime="momentum ignition", threshold=1
            ),
        ):
            with pytest.raises(PromotionCoverageError):
                call()

    def test_the_block_is_not_a_coverage_error(self, store) -> None:
        # Nothing failed to persist here: the repairs differ (a corrected
        # re-ask versus a decision about evidence), and folding the two
        # would put them behind one ``except``.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        try:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        except CoverageError:
            raise AssertionError("the block's refusal is not a persist's")
        except PromotionCoverageError:
            pass

    def test_the_refusal_is_catchable_as_the_members_base(self, store) -> None:
        # One ``except RegimeError`` still catches every failure of the
        # member's path — the point of the shared base.
        store.record("crash", 0)
        with pytest.raises(RegimeError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )

    def test_the_code_word_opens_every_verdict(self, store) -> None:
        # Greppable by the one word that names the finding, in the family
        # ``pool_too_thin``, ``full_history_fit``, ``no_origin``,
        # ``not_regime_diverse`` and ``empty_stratum`` already establish —
        # an operator greps the log, not the traceback.  And the word is
        # the whole cross-member seam: the promotion plugin's own features
        # (291–300) restate this literal rather than import it.
        store.record("crash", 0)
        with pytest.raises(
            PromotionCoverageError, match=COVERAGE_BELOW_THRESHOLD_CODE
        ):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        assert COVERAGE_BELOW_THRESHOLD_CODE == "coverage_below_threshold"

    def test_the_message_names_the_regime_the_figure_and_the_threshold(
        self, store
    ) -> None:
        # A gate's message is what an operator reads *instead of* being
        # stopped, so it has to say which regime was being deployed into,
        # what the pool held there, and what bar it missed.
        store.record("high-volatility trend", 4)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="high-volatility trend", threshold=40
            )
        message = str(raised.value)
        assert "'high-volatility trend'" in message
        assert "holds 4 stored worlds" in message
        assert "threshold of 40" in message

    def test_the_message_names_the_way_out(self, store) -> None:
        # A gate whose message does not name the door out is a dead end
        # rather than a finding: grow the coverage in the regime being
        # deployed into, or deploy into a regime the pool covers — the
        # census (feature 290) and the backfill (feature 287) being the
        # acts that do the first.
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        message = str(raised.value)
        assert "Grow the coverage" in message
        assert "deploy into a regime the pool does cover" in message
        assert "feature 290" in message
        assert "feature 287" in message


# -- The seam ----------------------------------------------------------------------


class TestTheSeam:
    """The judgment over readings the member's other spellings answer."""

    def test_a_hand_built_duck_ledger_is_judged(self) -> None:
        # No ``isinstance`` gate: the module loader imports this member
        # under a synthetic name, so the reading a composed store hands
        # back is structurally identical to a direct import's without being
        # the same class object — and a judgment that gated on the class
        # would refuse the very reading composition serves.  A hand-built
        # duck carrying the one lookup the judgment reads is judged
        # identically, which is what keeps that true.

        class Row:
            def __init__(self, world_count: int) -> None:
                self.world_count = world_count

        class DuckLedger:
            def __init__(self, counts: dict[str, int]) -> None:
                self._counts = {name: Row(n) for name, n in counts.items()}

            def get(self, stratum: str, default: object = None) -> object:
                return self._counts.get(stratum, default)

        duck = DuckLedger({"crash": 7})
        assert (
            rejects_undercovered_promotion(duck, regime="crash", threshold=7)
            is None
        )
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(duck, regime="crash", threshold=8)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(duck, regime="chop", threshold=1)

    def test_a_reading_whose_lookup_takes_only_a_name_is_judged(self) -> None:
        # Feature 283's own store carries a *one-argument* one-stratum read
        # (``get(stratum)``, the write's read-back for a caller holding a
        # name), so a duck reading with that same signature is a shape the
        # gate has to serve rather than crash on.  Asking it a two-argument
        # question would raise an untyped ``TypeError`` straight through
        # this gate — the one outcome a gate must not have, because the
        # caller's single ``except PromotionCoverageError`` would not catch
        # it and the promotion would proceed through the hole.
        class Row:
            def __init__(self, world_count: int) -> None:
                self.world_count = world_count

        class OneArgLedger:
            def __init__(self, counts: dict[str, int]) -> None:
                self._counts = {name: Row(n) for name, n in counts.items()}

            def get(self, stratum: str) -> object:
                return self._counts.get(stratum)

        ledger = OneArgLedger({"crash": 3})
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(ledger, regime="crash", threshold=5)
        assert "holds 3 stored worlds" in str(raised.value)
        # And its own *no row* answer (``None``) is the absence, not a zero.
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(ledger, regime="chop", threshold=1)
        assert "is not named by the ledger" in str(raised.value)
        assert (
            rejects_undercovered_promotion(ledger, regime="crash", threshold=3)
            is None
        )

    def test_no_untyped_error_escapes_the_gate(self, store) -> None:
        # The gathering argument, pinned as behaviour rather than as prose:
        # a caller guarding its promotion path with one ``except
        # PromotionCoverageError`` must see *every* refusal of this
        # judgment, however oddly shaped the thing it was handed.  Anything
        # that escapes as a bare ``TypeError``/``AttributeError`` is a hole
        # the promotion walks through, so a spread of malformed readings
        # and asks is driven through the gate and each must arrive typed.
        store.record("crash", 1)

        class _OneArg:
            def get(self, stratum: str) -> object:
                return None

        class _SubscriptRaises:
            def __getitem__(self, stratum: str) -> object:
                raise KeyError(stratum)

        class _GetRaisesKeyError:
            def get(self, stratum: str, default: object = None) -> object:
                raise KeyError(stratum)

        class _NoLookup:
            pass

        for ledger in (
            None,
            "crash",
            b"crash",
            _NoLookup(),
            _OneArg(),
            _SubscriptRaises(),
            _GetRaisesKeyError(),
            store,  # the store itself, in every face's position
        ):
            try:
                rejects_undercovered_promotion(ledger, regime="crash", threshold=1)
            except PromotionCoverageError:
                pass
            except Exception as exc:  # noqa: BLE001 - the probe *is* the assertion
                raise AssertionError(
                    f"{ledger!r} escaped the gate as an untyped "
                    f"{type(exc).__name__}: {exc}"
                )

    def test_a_reading_that_explodes_propagates_rather_than_being_swallowed(
        self, store
    ) -> None:
        # The boundary of the gathering above, stated rather than left to
        # be discovered: the gate translates every refusal *about the ask
        # or the pool* into its own class, and deliberately does **not**
        # swallow an error the reading raises out of its own internals — a
        # broken connection, a bug in a labeler, a property that raises.
        # Laundering those into ``PromotionCoverageError`` would be the
        # same silence one layer down: a caller would read *the promotion
        # was blocked* where the truth is *the ledger could not be read*,
        # and that is a wiring fault whose repair is not a decision about
        # evidence.  The member's other seams draw the line in the same
        # place — they catch their own vocabulary, not ``Exception``.
        class _Exploding:
            def get(self, stratum: str, default: object = None) -> object:
                raise ValueError("the connection is gone")

        with pytest.raises(ValueError, match="the connection is gone"):
            rejects_undercovered_promotion(
                _Exploding(), regime="crash", threshold=1
            )

    def test_a_subscript_only_reading_is_judged(self) -> None:
        # A reading that answers by subscript rather than by ``get`` is
        # still a reading — the same question, with ``KeyError`` as the
        # mapping protocol's own spelling of *no row for that name*.
        class Row:
            def __init__(self, world_count: int) -> None:
                self.world_count = world_count

        class MappingLedger:
            def __init__(self, counts: dict[str, int]) -> None:
                self._counts = {name: Row(n) for name, n in counts.items()}

            def __getitem__(self, stratum: str) -> object:
                return self._counts[stratum]

        mapping = MappingLedger({"crash": 2})
        assert (
            rejects_undercovered_promotion(mapping, regime="crash", threshold=2)
            is None
        )
        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(mapping, regime="chop", threshold=1)
        assert "is not named by the ledger" in str(raised.value)

    def test_the_module_level_read_blocks_too(self, database_url) -> None:
        # Feature 284's two spellings reach the same reading, and the
        # judgment is over the reading: counts persisted through the store,
        # judged through ``read_ledger``'s answer.
        from regime import persist_coverage, read_ledger

        persist_coverage("crash", 1, database_url=database_url)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                read_ledger(database_url=database_url), regime="crash", threshold=2
            )
        persist_coverage("crash", 5, database_url=database_url)
        assert (
            rejects_undercovered_promotion(
                read_ledger(database_url=database_url),
                regime="crash",
                threshold=2,
            )
            is None
        )

    def test_the_composed_stores_reading_blocks(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The promise the member's ``__init__`` makes — the promotion block
        # judges *counts read out of the composed store* — pinned through
        # the real factory.  The loader's copies make ``isinstance``
        # unusable, so the assertions are on behaviour: the composed
        # reading blocks exactly as a direct import's does.
        from app.module_loader import create_app

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
        composed = create_app().get("regime")
        assert composed is not None
        composed.record("crash", 0)
        composed.record("low-volatility chop", 3)

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                composed.ledger(), regime="crash", threshold=1
            )
        assert type(raised.value).__name__ == "PromotionCoverageError"

        with pytest.raises(PromotionCoverageError) as raised:
            rejects_undercovered_promotion(
                composed.ledger(), regime="momentum ignition", threshold=1
            )
        assert "is not named by the ledger" in str(raised.value)

        assert (
            rejects_undercovered_promotion(
                composed.ledger(), regime="low-volatility chop", threshold=2
            )
            is None
        )

    def test_the_verdict_writes_nothing(self, store, database_url) -> None:
        # A verdict is not a persist: the refusal's whole act is a reading
        # and a ruling, and the table is byte for byte what it was whether
        # the promotion stands or falls — checked against the table, not
        # against the store's own answers.
        store.record("crash", 0)
        store.record("low-volatility chop", 3)
        before = _raw_rows(database_url)

        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )
        # A wider-than-the-pool threshold on an *absent* regime, and a
        # standing promotion on a covered one: neither writes anything.
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="momentum ignition", threshold=1
            )
        rejects_undercovered_promotion(
            store.ledger(), regime="low-volatility chop", threshold=3
        )

        assert sorted(_raw_rows(database_url)) == sorted(before)


# -- The module's place in the member ----------------------------------------------


class TestTheModulesPlace:
    """A block beside the store, not a second seat."""

    def test_the_member_exports_the_block_and_no_new_builder(self) -> None:
        # The member's public vocabulary grows by this feature's names —
        # and only by them: the registered surface stays feature 283's one
        # store (``build_regime_coverage`` alone), because a judgment over
        # a reading resolves no configuration of its own and registers
        # nothing.
        import regime

        for name in (
            "COVERAGE_BELOW_THRESHOLD_CODE",
            "PromotionCoverageError",
            "rejects_undercovered_promotion",
        ):
            assert name in regime.__all__, name
        assert [
            built for built in dir(regime) if built.startswith("build_")
        ] == ["build_regime_coverage"]

    def test_the_code_word_is_the_cross_member_seam(self) -> None:
        # No member imports another, so the promotion plugin's own features
        # (291–300, including 299's persisted blocking reason) reach this
        # refusal by restating one literal.  Pinned as a literal so a
        # rename here is a rename there.
        import regime

        assert regime.COVERAGE_BELOW_THRESHOLD_CODE == "coverage_below_threshold"

    def test_the_seat_is_untouched_by_the_block(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The app seat answers one question — *what is the composed
        # coverage ledger?* — and the block is a caller of its answer
        # rather than a second thing to compose: the seat still exposes
        # exactly the composition accessor, and the reading it reaches is
        # the reading the judgment takes.
        from app.modules import regime as seat

        assert set(seat.__all__) == {"COMPONENT_NAME", "regime_coverage_component"}

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'seated.db'}")
        store = seat.regime_coverage_component()
        assert store is not None
        store.record("crash", 0)
        with pytest.raises(PromotionCoverageError):
            rejects_undercovered_promotion(
                store.ledger(), regime="crash", threshold=1
            )


def _path_to_url(store: RegimeCoverage) -> str:
    """The URL a store was built with — for the raw-SQL both-ways check.

    A one-line accessor rather than a fixture, so a test that wants the
    table's own word for a row keeps reading it the raw way the rest of
    this suite does.
    """
    return store.database_url
