"""Feature 289's act: the diversity claim, refused while the pool is thin.

app_spec.xml, "Regime Coverage Strata", feature 289: *System rejects a
regime-diverse claim while fewer than three strata hold stored worlds.*
Feature 283 persists the counts, feature 284 reads them back as one
ledger, feature 290 makes the numbers and features 287/288 grow them;
this file pins the verdict over all of that — and the sentence's three
load-bearing phrases are what most of it is about.

*"**Regime-diverse claim**"* — the subject is a claim, a report a caller
is about to publish, and the act is its refusal: the judgment **raises**
:class:`~regime.errors.DiversityClaimError` rather than answering a
boolean, so the caller that calls it on its last line is stopped before
the claim leaves the room.  The tests that check the raise *is* the
emission — the code word, the figure, the names, the floor, §C7, the
repair — are the ones that keep the refusal worth catching.

*"**Fewer than three**"* — the boundary is the sentence's own word.  At
exactly three covered strata the claim stands; at two it falls; there is
no upper edge.  The floor is the default vocabulary's size pinned from
both sides (``REGIME_DIVERSITY_FLOOR == len(DEFAULT_STRATA) == 3``), and
a deployment with a wider vocabulary judges with its own figure through
the ``floor`` keyword.

*"**Strata hold stored worlds**"* — the figure is the *covered* count,
and the neighbouring figures it is deliberately not are each pinned:
not ``len(ledger)`` (naming a stratum is not covering it), not the sum
of the counts (worlds are not strata — fourteen worlds in low-vol chop
is §C7's one-regime pool entire), and the named-empty row and the
never-named absence, different facts everywhere else in this member,
are the same *non-figure* here.

§C7's own example ledger is the refusal's canonical fixture —
``{high-vol trend: 2, low-vol chop: 14, crash: 0, …}`` is two covered
strata beside a zero nobody acted on — and every claim about what the
pool holds is checked **both ways**: through the judgment under test,
and through raw SQL against the table, the discipline the coverage and
ledger suites state.  The refusal-writes-nothing tests exist because a
verdict is not a persist: the table is exactly what it was whether the
claim stands or falls.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from regime import (
    COVERAGE_TABLE,
    DEFAULT_STRATA,
    NOT_REGIME_DIVERSE_CODE,
    REGIME_DIVERSITY_FLOOR,
    STRATUM_COLUMN,
    WORLD_COUNT_COLUMN,
    CoverageError,
    DiversityClaimError,
    RegimeCoverage,
    RegimeError,
    rejects_regime_diverse_claim,
)


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for raw SQL.

    This suite's own four lines rather than a call into the member, on
    the same terms the coverage and ledger suites state: the store's
    ``_sqlite_path`` is private, and a test reaching into it would be
    pinning an implementation detail it should be free to change.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _raw_rows(database_url: str) -> list[tuple[object, ...]]:
    """Every row the table holds, as a reader with no code in common with
    this member would read it.

    The both-ways instrument: the judgment reads a ledger the table
    fed, so the other half of every assertion here needs the table's
    own word for what the pool holds.  Deliberately unordered — the
    judgment claims no order over rows and neither does this.
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
    asserting the judgment read *two* is asserting it against the table,
    not against the ledger's own ``covered`` view spelling of two.
    """
    return sorted(
        stratum
        for stratum, world_count in _raw_rows(database_url)
        if world_count  # SQLite affinity has left a number here or the
        # read would have refused; the truthiness of a count is its sign
    )


# -- The feature's own sentence ----------------------------------------------------


class TestTheVerdict:
    """*System rejects a regime-diverse claim* — the act itself."""

    def test_c7s_own_example_ledger_is_refused(self, store, database_url) -> None:
        # §C7 draws its example ledger as ``{high-vol trend: 2, low-vol
        # chop: 14, crash: 0, …}`` — and that pool is the claim's worst
        # case: two strata holding worlds beside a named and empty crash
        # nobody acted on.  The refusal is the acting, and the message
        # carries everything an operator needs: the code word, the
        # figure, both covered strata, and the floor.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        store.record("crash", 0)

        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger())

        message = str(raised.value)
        assert message.startswith(f"{NOT_REGIME_DIVERSE_CODE}: 2 strata hold")
        assert "'high-volatility trend'" in message
        assert "'low-volatility chop'" in message
        assert "'crash'" not in message  # named, empty, and not coverage
        assert "floor of 3" in message
        assert "§C7" in message
        # Both ways: the table's own word for the figure the judgment read.
        assert _covered_names(database_url) == [
            "high-volatility trend",
            "low-volatility chop",
        ]

    def test_the_one_regime_pool_is_refused(self, store) -> None:
        # Fourteen worlds in one stratum is §C7's opening sentence made
        # flesh — the pool that grew in low-vol chop and is low-vol chop.
        # Worlds are not strata, and no count of worlds in one regime
        # buys the claim the sentence refuses.
        store.record("low-volatility chop", 14)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger())
        assert "1 stratum holds" in str(raised.value)  # the singular verb

    def test_a_pool_whose_named_strata_all_hold_none_is_refused(self, store) -> None:
        # Three strata named, three named-empty rows landed, zero worlds
        # stored: ``len(ledger)`` is three and the figure is zero, which
        # is the whole difference between naming a stratum and covering
        # one.  Feature 286's warning fires on exactly this state; the
        # claim still does not survive it.
        for name in DEFAULT_STRATA:
            store.name_stratum(name)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger())
        assert "no stratum holds a stored world" in str(raised.value)

    def test_an_empty_ledger_is_refused(self, store) -> None:
        # A database where no census has run is a real answer about a
        # real pool — an empty one, uncategorized and uncounted — and a
        # regime-diverse claim over it is refused on the figure, not on
        # the emptiness: the state is admissible, the claim is not.
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger())

    def test_a_claim_at_exactly_the_floor_stands(self, store, database_url) -> None:
        # The sentence's own boundary: rejected *while fewer than* three,
        # so at three the claim stands.  Meeting a floor is enough —
        # there is no band — and the worlds per stratum are beside the
        # point entirely.
        for name, count in zip(DEFAULT_STRATA, (1, 1, 5000)):
            store.record(name, count)
        assert _covered_names(database_url) == sorted(DEFAULT_STRATA)
        assert rejects_regime_diverse_claim(store.ledger()) is None

    def test_a_claim_above_the_floor_stands(self, store) -> None:
        # No upper edge: more strata holding worlds only strengthens a
        # diversity claim, the asymmetry a floor has.
        for name in ("alpha regime", "crash", "low-volatility chop",
                     "momentum ignition", "zulu regime"):
            store.record(name, 1)
        assert rejects_regime_diverse_claim(store.ledger()) is None

    def test_the_figure_is_covered_strata_not_named_ones(self, store) -> None:
        # A deployment whose labeler carves five, two of which hold
        # nothing: the default floor counts three covered and the claim
        # stands, while the deployment's own five-name question refuses
        # it — the openness ``floor`` is a keyword for, the same
        # openness ``holes()``'s vocabulary argument states.
        for name in ("alpha regime", "crash", "low-volatility chop",
                     "momentum ignition", "zulu regime"):
            store.record(name, 1)
        store.record("momentum ignition", 0)
        store.record("zulu regime", 0)
        ledger = store.ledger()
        assert len(ledger) == 5  # five named
        assert rejects_regime_diverse_claim(ledger) is None  # three covered
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(ledger, floor=5)
        assert "floor of 5" in str(raised.value)

    def test_named_empty_and_never_named_are_the_same_non_figure(
        self, tmp_path: Path
    ) -> None:
        # ``0107`` detail 1 at this seam: a stratum named and empty (a
        # row with a zero) and a stratum never named (no row at all) are
        # different facts the member keeps apart everywhere — and they
        # are the same *non-figure* here, because neither holds a stored
        # world.  Two ledgers, one carrying ``crash: 0`` and one never
        # naming crash, refuse the claim identically.
        named_empty = RegimeCoverage(f"sqlite:///{tmp_path / 'named-empty.db'}")
        never_named = RegimeCoverage(f"sqlite:///{tmp_path / 'never-named.db'}")
        for store in (named_empty, never_named):
            store.record("high-volatility trend", 2)
            store.record("low-volatility chop", 14)
        named_empty.record("crash", 0)

        refusals = []
        for store in (named_empty, never_named):
            with pytest.raises(DiversityClaimError) as raised:
                rejects_regime_diverse_claim(store.ledger())
            refusals.append(str(raised.value).split(";", 1)[0])
        assert refusals[0].startswith(f"{NOT_REGIME_DIVERSE_CODE}: 2 strata hold")
        assert refusals[0] == refusals[1]  # the same finding either way

    def test_the_verdict_rules_on_the_reading_it_was_handed(self, store) -> None:
        # A value is a reading: the judgment does not re-read the table
        # behind the ledger's back.  A claim judged over a reading that
        # has gone stale gets that reading's verdict, and the caller
        # claiming diversity *now* reads again — both halves, because a
        # judgment that silently refreshed would be answering a question
        # the caller did not ask.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        stale = store.ledger()

        store.record("crash", 1)  # the pool moved under the reading

        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(stale)
        assert rejects_regime_diverse_claim(store.ledger()) is None


# -- The floor ---------------------------------------------------------------------


class TestTheFloor:
    """The sentence's *three* — a default, a keyword, and a boundary."""

    def test_the_default_floor_is_the_default_vocabularys_size(self) -> None:
        # The sentence's own number and the default vocabulary's own
        # size in one: DEFAULT_STRATA names three, the labeler's DEFAULT_K
        # carves three (the cross-member suite's pin), and a claim
        # diverse in fewer than the vocabulary's own count of regimes is
        # diverse in a minority of what the deployment counts.  Pinning
        # the equality means a future edit that widens the vocabulary
        # has to look at the floor too.
        assert REGIME_DIVERSITY_FLOOR == len(DEFAULT_STRATA) == 3

    def test_a_wider_floor_refuses_a_claim_the_default_admits(self, store) -> None:
        store.record("crash", 1)
        store.record("high-volatility trend", 1)
        store.record("low-volatility chop", 1)
        assert rejects_regime_diverse_claim(store.ledger()) is None
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger(), floor=4)
        assert "floor of 4" in str(raised.value)

    def test_a_narrower_floor_admits_a_thinner_pool(self, store) -> None:
        store.record("crash", 3)
        store.record("low-volatility chop", 4)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger())
        assert rejects_regime_diverse_claim(store.ledger(), floor=2) is None

    def test_a_floor_of_one_still_refuses_an_empty_pool(self, store) -> None:
        # Degenerate but honest: ``covered >= 1`` is a floor that still
        # refuses an empty pool's claim, so it is the caller's to set
        # and not this module's to second-guess.
        store.record("crash", 0)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger(), floor=1)

    def test_a_floor_below_one_is_refused(self, store) -> None:
        # A diversity floor of zero admits every claim — including one
        # over a pool no stratum of which holds a single world — which
        # is the blindness §C7's ledger exists to cure, legislated back
        # in through the configuration.  Refused as an ask, before the
        # reading is judged.
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger(), floor=0)
        assert "at least one stratum" in str(raised.value)

    def test_a_negative_floor_is_refused(self, store) -> None:
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger(), floor=-3)

    def test_a_boolean_floor_is_refused(self, store) -> None:
        # ``True`` is ``1`` in Python, so a flag where a floor belongs
        # would name one covered stratum as diverse enough — refused
        # for the reason every count validator in this workspace
        # refuses a bool.
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger(), floor=True)
        assert "count of strata" in str(raised.value)

    def test_a_non_integer_floor_is_refused(self, store) -> None:
        store.record("crash", 1)
        for malformed in ("3", 2.5, None):
            with pytest.raises(DiversityClaimError):
                rejects_regime_diverse_claim(store.ledger(), floor=malformed)


# -- The ask is refused ------------------------------------------------------------


class TestTheAskIsRefused:
    """A ledger carrying no readable figure is refused, and named."""

    def test_nothing_handed_in_is_refused(self) -> None:
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(None)
        assert "carries no ``covered``" in str(raised.value)

    def test_a_string_is_refused(self) -> None:
        # A string is not a reading of anything; it is refused as an ask
        # rather than iterated into characters the way a vocabulary
        # helper would refuse one.
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim("crash")

    def test_a_store_where_the_reading_belongs_is_refused_with_its_repair(
        self, store
    ) -> None:
        # The easy mistake: the judgment takes the reading, and a caller
        # holding the store hands the store.  The refusal names the
        # repair — call ``ledger()`` on it first — rather than leaving
        # the caller to guess why a store "carries no covered figure".
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store)
        message = str(raised.value)
        assert "is the store" in message
        assert "``ledger()``" in message
        assert "feature 284" in message

    def test_a_covered_view_that_cannot_be_counted_is_refused(self) -> None:
        class _NotSized:
            covered = 7

        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(_NotSized())
        assert "cannot be counted" in str(raised.value)

    def test_a_covered_row_without_a_usable_name_is_refused(self) -> None:
        # The seam validates what it reads: a covered row carrying no
        # stratum name cannot be named in the refusal, and a refusal
        # that could not say what the claim leaned on would be a finding
        # about nothing.
        class _Row:
            pass

        class _Ledger:
            covered = (_Row(),)

        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(_Ledger())
        assert "could not be read as a stratum" in str(raised.value)

    def test_the_seam_translates_the_count_vocabulary(self) -> None:
        # The name check is feature 283's own validator, imported rather
        # than re-written — and its refusal is *translated* into this
        # module's class at the seam, so a caller's ``except
        # DiversityClaimError`` is never defeated by the count-persist
        # vocabulary for an act that persisted nothing.
        class _Row:
            stratum = "   "

        class _Ledger:
            covered = (_Row(),)

        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(_Ledger())
        assert NOT_REGIME_DIVERSE_CODE in str(raised.value)
        # And the count-persist class does not catch it — the translation
        # at the seam is the whole point, spelled the direct way:
        try:
            rejects_regime_diverse_claim(_Ledger())
        except CoverageError:
            raise AssertionError("a blank name is not a persist's refusal")
        except DiversityClaimError:
            pass


# -- The refusal's class -----------------------------------------------------------


class TestTheRefusalsClass:
    """The sibling seat :mod:`regime.errors` reserved for this feature."""

    def test_the_verdict_is_not_a_coverage_error(self, store) -> None:
        # The reservation's reason, pinned: a well-formed ask that runs
        # into a judged threshold is not a malformed one, and a caller
        # catching :class:`CoverageError` for a refused persist must not
        # find a refused *claim* behind the same ``except`` — the
        # repairs differ (a corrected re-ask versus a decision about
        # evidence).
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger())
        try:
            rejects_regime_diverse_claim(store.ledger())
        except CoverageError:
            raise AssertionError("the claim's refusal is not a persist's")
        except DiversityClaimError:
            pass

    def test_the_refusal_is_catchable_as_the_members_base(self, store) -> None:
        # One ``except RegimeError`` still catches every failure of the
        # member's path — the point of the shared base.
        store.record("crash", 1)
        with pytest.raises(RegimeError):
            rejects_regime_diverse_claim(store.ledger())

    def test_the_code_word_opens_the_verdict(self, store) -> None:
        # Greppable by the one word that names the finding, in the
        # family ``pool_too_thin``, ``full_history_fit`` and
        # ``no_origin`` already establish — an operator greps the log,
        # not the traceback.
        store.record("crash", 1)
        store.record("low-volatility chop", 2)
        with pytest.raises(DiversityClaimError, match=NOT_REGIME_DIVERSE_CODE):
            rejects_regime_diverse_claim(store.ledger())

    def test_the_message_names_the_way_out(self, store) -> None:
        # A gate whose message does not name the door out is a dead end
        # rather than a finding: withdraw the claim, or raise the figure
        # — the census (feature 290) and the backfill (feature 287)
        # being the acts that do.
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(store.ledger())
        message = str(raised.value)
        assert "Withdraw the claim" in message
        assert "feature 290" in message
        assert "feature 287" in message


# -- The seam ----------------------------------------------------------------------


class TestTheSeam:
    """The judgment over readings the member's other spellings answer."""

    def test_a_hand_built_duck_ledger_is_judged(self) -> None:
        # No ``isinstance`` gate: the module loader imports this member
        # under a synthetic name, so the reading a composed store hands
        # back is structurally identical to a direct import's without
        # being the same class object — and a judgment that gated on the
        # class would refuse the very reading composition serves.  A
        # hand-built duck with the one attribute the judgment reads is
        # judged identically, which is what keeps that true.

        class Row:
            def __init__(self, stratum: str) -> None:
                self.stratum = stratum

        class DuckLedger:
            def __init__(self, *names: str) -> None:
                self.covered = tuple(Row(name) for name in names)

        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(DuckLedger("crash", "chop"))
        assert rejects_regime_diverse_claim(
            DuckLedger("crash", "chop", "trend")
        ) is None

    def test_the_module_level_read_judges_too(self, database_url) -> None:
        # Feature 284's two spellings reach the same reading, and the
        # judgment is over the reading: a count persisted through the
        # store, judged through ``read_ledger``'s answer.
        from regime import persist_coverage, read_ledger

        persist_coverage("crash", 1, database_url=database_url)
        persist_coverage("low-volatility chop", 2, database_url=database_url)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(read_ledger(database_url=database_url))
        persist_coverage("high-volatility trend", 1, database_url=database_url)
        assert rejects_regime_diverse_claim(
            read_ledger(database_url=database_url)
        ) is None

    def test_the_composed_stores_reading_judges(self, monkeypatch, tmp_path: Path) -> None:
        # The promise the member's ``__init__`` makes — the diversity
        # refusal judges *counts read out of the composed store* — pinned
        # through the real factory.  The loader's copies make
        # ``isinstance`` unusable, so the assertions are on behaviour:
        # the composed reading judges exactly as a direct import's does.
        from app.module_loader import create_app

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
        composed = create_app().get("regime")
        assert composed is not None
        composed.record("high-volatility trend", 2)
        composed.record("low-volatility chop", 14)

        with pytest.raises(DiversityClaimError) as raised:
            rejects_regime_diverse_claim(composed.ledger())
        assert type(raised.value).__name__ == "DiversityClaimError"

        composed.record("crash", 1)
        assert rejects_regime_diverse_claim(composed.ledger()) is None

    def test_the_verdict_writes_nothing(self, store, database_url) -> None:
        # A verdict is not a persist: the refusal's whole act is a
        # reading and a ruling, and the table is byte for byte what it
        # was whether the claim stands or falls — checked against the
        # table, not against the store's own answers.
        store.record("high-volatility trend", 2)
        store.record("low-volatility chop", 14)
        before = _raw_rows(database_url)

        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger())
        store.record("crash", 1)  # now admitted, and still no verdict write
        rejects_regime_diverse_claim(store.ledger())

        assert sorted(_raw_rows(database_url)) == sorted(
            before + [("crash", 1)]
        )  # the persist's row, and the verdict's nothing


# -- The module's place in the member ----------------------------------------------


class TestTheModulesPlace:
    """A verdict beside the store, not a second seat."""

    def test_the_member_exports_the_verdict_and_no_new_builder(self) -> None:
        # The member's public vocabulary grows by this feature's names —
        # and only by them: the registered surface stays feature 283's
        # one store (``build_regime_coverage`` alone), because a
        # judgment over a reading resolves no configuration of its own
        # and registers nothing.
        import regime

        for name in (
            "DiversityClaimError",
            "NOT_REGIME_DIVERSE_CODE",
            "REGIME_DIVERSITY_FLOOR",
            "rejects_regime_diverse_claim",
        ):
            assert name in regime.__all__, name
        assert [
            built for built in dir(regime) if built.startswith("build_")
        ] == ["build_regime_coverage"]

    def test_the_composed_ledger_feeds_the_verdict(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        # The composed coverage ledger answers one question — *what is the
        # coverage ledger?* — and the judgment is a caller of its answer rather
        # than a second thing to compose: the reading the composition
        # reaches is the reading the judgment takes.
        from app.module_loader import create_app

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'composed.db'}")
        store = create_app().get("regime")
        assert store is not None
        store.record("crash", 1)
        with pytest.raises(DiversityClaimError):
            rejects_regime_diverse_claim(store.ledger())
