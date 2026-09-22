"""The two cross-member spellings this feature restates — pinned as data.

The workspace contract is that **no member imports another**.  It is stated
where it is violated by temptation and could be (`packages/artifacts/tests/
test_profiles.py`: a composed component's ``__module__`` is a submodule without
the package's exports, so a member reaching for a sibling's spelling gets a
copy it cannot compare), and it is met with the same remedy everywhere: the
spelling is *restated* in the member that needs it, and a suite like this one
is what keeps the restatement honest.  ``packages/sandbox/tests/
test_budget_law.py`` is the demonstration — it pins ``evaluator._sandbox``'s
three defaults and feature 168's runner vocabulary, importing the other member
*inside the test function* so that a sibling's absence degrades one test rather
than failing the collection of the whole suite.

This member restates two of the null-oracle member's spellings, and for two
different reasons:

**§4.1.1's clip.**  ``φ = clip(max(2/W, 0.15), 0.15, 0.35)`` is feature 117's arithmetic —
``nulloracle.null_fraction`` computes it, stores it, and refuses to *write* it
onto a campaign that does not exist.  This member’s :func:`discovery.null_fraction`
computes the same number so that the campaign row can be *created* with it (see
``campaign.py``'s module docstring for why the derivation is this feature's own
decision).  Two spellings of one formula, in two members, with no import
between them: a single edit to the clip in either place would silently give a
campaign a fraction the oracle's store then disagrees with — and the failure
mode is the worst kind here, because both numbers would be plausible fractions
and the blinding discipline would just quietly be wrong.  The tests below fail
on any of it: the two band literals, the three clip regimes, and the refusals
the count's validation produces.

**§7.3's regimes.**  ``"Type-R"`` and ``"Type-D"`` are two strings, and two
strings are exactly the kind of thing that gets retyped by hand.  Feature 122's
gate compares a tree's assignments against the campaign row's
``campaign_type``; a planner storing ``"Type R"`` would make every campaign of
its regime unreviewable.  :attr:`discovery.REGIMES` is this member's closed set
and ``nulloracle.plan.REGIMES`` is the gate's, and they must be the same two
strings in the same order.

**Why the imports are inside the tests.**  A module-scope ``import nulloracle``
would make this member's suite fail to collect wherever the null-oracle member
is absent, which is the outcome the workspace contract's remedy exists to
avoid: the restatement must outlive the sibling.  Inside a function, the
absence costs one test, and that test says exactly what is missing.  The
``pytest.importorskip`` is the same stance spelled for the path bootstrap —
these tests need the sibling's ``src/`` on ``sys.path``, which the workspace's
member suites do not otherwise do for each other.

Most of what is here is *data* — the two literals, the two regimes, the column
names and the arithmetic all of it is built on.  The last class goes one step
further and exercises the *seam*: this member creates a campaign and feature
117's store then writes a fraction onto it, against one database, in the order
a deployment runs the two.  That is still the same discipline — the oracle's
store is driven through its own public ``persist``/``load``, never a private
helper — but it is the one assertion that would catch a planner whose row is
shaped such that the oracle cannot use it.
"""

from __future__ import annotations

import sqlite3
import sys
import uuid as uuid_module
from contextlib import closing
from pathlib import Path
from urllib.parse import unquote, urlparse

import discovery
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NULLORACLE_SRC = REPO_ROOT / "packages" / "nulloracle" / "src"


def _path_of(database_url: str) -> Path:
    """The filesystem path behind a ``sqlite:///`` URL, for a raw read.

    Local rather than imported from the member, on the same terms the member's
    other suites state: what a reader of a column relies on is the URL grammar
    the migrations use, not the store's private helper.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _stored_regime(database_url: str, campaign_id: str) -> str:
    """The ``campaign_type`` a reader would find for a campaign — as SQL.

    The one column feature 122's gate selects, fetched the way a reader that
    shares no code with this member would fetch it.  Anything the planner did
    to the value on its way into the row shows up here and nowhere else.
    """
    with closing(sqlite3.connect(_path_of(database_url))) as connection:
        cursor = connection.execute(
            f"SELECT {discovery.CAMPAIGN_TYPE_COLUMN} "
            f"FROM {discovery.CAMPAIGN_TABLE} WHERE id = ?",
            (campaign_id,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    assert row is not None, campaign_id
    return row[0]


def _nulloracle():
    """The null-oracle member, imported in-function and by path if need be.

    ``importorskip`` rather than a bare import: a workspace that does not carry
    the sibling should lose these tests and nothing else.  The path insert is
    the same bootstrap every member suite performs for *itself*, applied to a
    sibling — the workspace's member suites are not installed into each other's
    environments, and the acceptance gate does not put them there either.
    """
    if str(NULLORACLE_SRC) not in sys.path:
        sys.path.insert(0, str(NULLORACLE_SRC))
    return pytest.importorskip(
        "nulloracle", reason="the null-oracle member is not in this workspace"
    )


# -- §4.1.1: the clip ------------------------------------------------------------


class TestTheClipIsOneArithmetic:
    def test_the_band_literals_agree(self) -> None:
        # Both ends, as data.  A rename or a re-clip on the oracle's side fails
        # here rather than producing a campaign whose recorded φ and whose
        # null_fraction column mean different things.
        oracle = _nulloracle()
        assert discovery.PHI_FLOOR == oracle.PHI_FLOOR
        assert discovery.PHI_CEILING == oracle.PHI_CEILING

    @pytest.mark.parametrize(
        "wells",
        # The three regimes and both boundaries between them: on the ceiling
        # (1, 2, 5), just inside it (6), through the arithmetic (7, 12, 13),
        # just under the floor (13), on it (14), and far past it (32, 1000).
        [1, 2, 5, 6, 7, 10, 12, 13, 14, 32, 1000],
    )
    def test_the_fraction_agrees_well_for_well(self, wells: int) -> None:
        oracle = _nulloracle()
        assert discovery.null_fraction(wells) == pytest.approx(
            oracle.null_fraction(wells)
        ), wells

    def test_the_oracles_own_exports_are_the_ones_this_member_restates(self) -> None:
        # Named explicitly so a *rename* on either side is a failure and not a
        # silently-skipped comparison: the attribute lookup raising is the test.
        oracle = _nulloracle()
        for name in ("PHI_FLOOR", "PHI_CEILING", "null_fraction", "REGIMES"):
            assert hasattr(oracle, name), name
        for name in ("PHI_FLOOR", "PHI_CEILING", "null_fraction", "REGIMES"):
            assert hasattr(discovery, name), name

    @pytest.mark.parametrize("bad", [0, -1, True, False, 2.5, "12", None])
    def test_both_sides_refuse_the_same_non_counts(self, bad) -> None:
        # The validation is restated alongside the arithmetic, so it is pinned
        # alongside it: a count the oracle refuses must not be a count this
        # planner accepts, because the two would then disagree about whether a
        # campaign could be planned at all.  The *error classes* differ — each
        # member raises its own, which is the workspace contract's "error
        # vocabulary at the seam" — so what is compared is that both refuse,
        # and each is named rather than caught broadly: the oracle's count
        # guard raises ``KsGuardError``, which is the class a caller reading
        # its refusal is told to repair against.
        oracle = _nulloracle()
        oracle_errors = pytest.importorskip("nulloracle.errors")
        with pytest.raises(discovery.CampaignPlanningError):
            discovery.null_fraction(bad)
        with pytest.raises(oracle_errors.KsGuardError):
            oracle.null_fraction(bad)


# -- §7.3: the two regimes -------------------------------------------------------


class TestTheRegimesAreOneClosedSet:
    def test_the_two_literals_agree(self) -> None:
        oracle = _nulloracle()
        assert discovery.TYPE_R_CAMPAIGN_TYPE == oracle.TYPE_R_CAMPAIGN_TYPE
        assert discovery.TYPE_D_CAMPAIGN_TYPE == oracle.TYPE_D_CAMPAIGN_TYPE

    def test_the_closed_sets_agree_as_sets_and_as_sequences(self) -> None:
        # Order matters as well as membership: both members build their tuple
        # as (Type-R, Type-D), and the plan value's own validation reports the
        # pair in that order in its refusal message.
        oracle = _nulloracle()
        assert set(discovery.REGIMES) == set(oracle.REGIMES)
        assert tuple(discovery.REGIMES) == tuple(oracle.REGIMES)

    def test_the_prds_two_spellings_are_the_ones_both_members_carry(self) -> None:
        # §7.3 spells the regimes as "Type-R" and "Type-D" — hyphenated, with
        # the capital T.  Asserting the literals themselves, not just the
        # agreement, is what catches the case where both members were changed
        # together to something the PRD does not say.
        assert discovery.TYPE_R_CAMPAIGN_TYPE == "Type-R"
        assert discovery.TYPE_D_CAMPAIGN_TYPE == "Type-D"
        assert discovery.REGIMES == ("Type-R", "Type-D")

    def test_the_planners_closed_set_is_the_gates(self) -> None:
        # The gate is the reader that *compares* against this column, so its
        # closed set is the one the planner has to write into.  Imported from
        # the module rather than the package because ``plan`` is where feature
        # 122 declares it (``selection`` and ``resolution`` each own one half
        # of it, which is why the re-export at the package foot is not the
        # whole story).
        _nulloracle()
        plan = pytest.importorskip("nulloracle.plan")
        assert tuple(plan.REGIMES) == tuple(discovery.REGIMES)
        assert plan.CAMPAIGN_TABLE == discovery.CAMPAIGN_TABLE
        assert plan.NODE_TABLE == discovery.NODE_TABLE
        assert plan.CAMPAIGN_TYPE_COLUMN == discovery.CAMPAIGN_TYPE_COLUMN

    def test_the_column_names_the_readers_select_by_agree(self) -> None:
        # The three columns feature 232's sentence names, as the seven readers
        # spell them.  A rename on either side would leave this planner writing
        # a column nobody selects — invisible until a reader came up empty.
        oracle = _nulloracle()
        assert discovery.CAMPAIGN_TABLE == oracle.CAMPAIGN_TABLE
        assert discovery.NODE_TABLE == oracle.NODE_TABLE
        assert discovery.CAMPAIGN_TYPE_COLUMN == oracle.CAMPAIGN_TYPE_COLUMN
        assert discovery.WORKSPACE_COUNT_COLUMN == oracle.WORKSPACE_COUNT_COLUMN
        assert discovery.NULL_FRACTION_COLUMN == oracle.NULL_FRACTION_COLUMN

    def test_both_halves_of_the_status_vocabulary_agree(self) -> None:
        # §7.4's two words, as the two members spell them.  'ok' is the
        # migration's literal default and the oracle's
        # ``CALIBRATION_STATUS_OK``; 'VOID' is feature 124's verdict, written by
        # the KS guard onto the campaign row.
        #
        # Feature 242 deliberately spelled *neither* — it read the campaign
        # row's status and carried it verbatim, and this class pinned the absence
        # so that a later feature could not drift into re-pronouncing a verdict
        # it only relays.  Feature 243 is that later feature, and it *reads* the
        # word rather than pronouncing it: its sentence turns on the value being
        # 'VOID' exactly, so the gate has to name the spelling it compares
        # against.  The pin flips from "not spelled here" to "spelled here, and
        # the same four letters" — which is the stronger assertion, because two
        # members that disagreed about the spelling would have a gate that
        # admits exactly the campaigns §7.4 voided.
        oracle = _nulloracle()
        assert discovery.CALIBRATION_STATUS_DEFAULT == oracle.CALIBRATION_STATUS_OK
        assert discovery.CALIBRATION_STATUS_DEFAULT == "ok"
        assert discovery.CALIBRATION_STATUS_OK == oracle.CALIBRATION_STATUS_OK
        assert discovery.CALIBRATION_STATUS_VOID == oracle.CALIBRATION_STATUS_VOID
        assert discovery.CALIBRATION_STATUS_VOID == "VOID"

    def test_the_store_the_oracle_declines_to_write_is_the_one_this_member_writes(
        self,
    ) -> None:
        # The seam itself, asserted rather than described: feature 117's store
        # persists a fraction onto a campaign that already exists, and refuses
        # when it does not.  This member is the writer that makes the row
        # exist.  Pinned as the *pair* of capabilities, because the whole
        # reason this member exists is that the oracle's class deliberately
        # does not have this one's.
        oracle = _nulloracle()
        fraction_store = oracle.PlantedNullFraction
        assert hasattr(fraction_store, "persist")
        assert not hasattr(fraction_store, "create")
        assert hasattr(discovery.CampaignRecords, "create")
        assert not hasattr(discovery.CampaignRecords, "persist")


class TestTheSeamActuallyOpens:
    """The whole reason this member exists, exercised across the seam.

    Every test above is about two members agreeing on *data*.  This one is
    about the *act*: feature 117's store refuses to write a fraction onto a
    campaign that does not exist, and this member is what makes one exist.  The
    two are run against one database, in the order a deployment runs them —
    plan, then plant — because a suite that only ever compared constants would
    pass for a writer that wrote a row the oracle could not then use.

    The oracle's store is driven through its own public surface
    (:meth:`PlantedNullFraction.persist`), the same call the composed path
    makes; nothing here reaches into either member's private helpers.  Its
    refusal *before* the campaign is planned is asserted too, and that
    assertion is what makes the second half meaningful: if ``persist`` never
    refused, "it works after create" would prove nothing about the seam.
    """

    def test_the_oracle_can_write_the_fraction_only_after_this_member_creates(
        self, migrated_database: str
    ) -> None:
        oracle = _nulloracle()
        errors = pytest.importorskip("nulloracle.errors")
        store = discovery.CampaignRecords(migrated_database)
        fraction_store = oracle.PlantedNullFraction(migrated_database)

        identifier = str(uuid_module.uuid4())
        # Before: the campaign does not exist, and the oracle's store will not
        # invent it — the refusal this feature is the answer to.
        with pytest.raises(errors.KsGuardError):
            fraction_store.persist(identifier, 12)

        # The planner creates it.  The fraction the oracle then writes is the
        # one this record carries, which is what makes the two spellings of
        # §4.1.1's clip one arithmetic rather than two that happen to agree.
        record = store.create(
            discovery.TYPE_R_CAMPAIGN_TYPE, 12, campaign_id=identifier
        )
        written = fraction_store.persist(identifier, 12)
        assert written == pytest.approx(record.null_fraction)
        assert fraction_store.load(identifier) == pytest.approx(record.null_fraction)

    def test_the_oracle_reads_back_the_type_and_count_the_planner_wrote(
        self, migrated_database: str
    ) -> None:
        # The three facts feature 232's sentence names, read by a reader that
        # belongs to the other member — through raw SQL, because that is all a
        # reader of a column has: the plan gate selects ``campaign_type`` from
        # this table and nothing else about the row.  If the planner's spelling
        # of a column or a regime were wrong, this is where it would show.
        store = discovery.CampaignRecords(migrated_database)
        record = store.create(discovery.TYPE_D_CAMPAIGN_TYPE, 20)
        with closing(sqlite3.connect(_path_of(migrated_database))) as connection:
            cursor = connection.execute(
                f"SELECT {discovery.CAMPAIGN_TYPE_COLUMN}, "
                f"{discovery.WORKSPACE_COUNT_COLUMN}, "
                f"{discovery.NULL_FRACTION_COLUMN} FROM {discovery.CAMPAIGN_TABLE} "
                "WHERE id = ?",
                (record.campaign_id,),
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        assert row is not None
        assert row[0] == discovery.TYPE_D_CAMPAIGN_TYPE
        assert row[1] == 20
        # W = 20 is past the floor's crossover (2/20 = 0.10 < 0.15), so the
        # clip — and therefore the *stored* value — is the floor, not 2/W's
        # unclipped answer.  An implementation that stored the raw quotient
        # would land 0.10 here and fail; the oracle's store asserts the same
        # number for the same campaign in the test above.
        assert row[2] == pytest.approx(discovery.PHI_FLOOR)

    def test_both_regimes_the_planner_writes_are_ones_the_gate_declares(
        self, migrated_database: str
    ) -> None:
        # The closed-set membership check above is about constants; this is
        # about the values that actually *land*.  A row is written for each
        # regime and its stored declaration is asserted to be a member of the
        # gate's own tuple — the comparison feature 122's review performs
        # before it says anything about a tree.  A planner that wrote a
        # normalised or prefixed spelling would pass every constant check in
        # this file and fail here.
        plan = pytest.importorskip("nulloracle.plan")
        store = discovery.CampaignRecords(migrated_database)
        written = set()
        for regime in discovery.REGIMES:
            record = store.create(regime, 12)
            stored = _stored_regime(migrated_database, record.campaign_id)
            assert stored in plan.REGIMES, stored
            written.add(stored)
        assert written == set(plan.REGIMES)


# -- Feature 240: §9.2's two orchestrator-owned filenames -------------------------


def _artifacts():
    """The artifacts member, imported in-function and by path if need be.

    The same bootstrap :func:`_nulloracle` performs, for the same reason: a
    workspace without the sibling loses these tests and nothing else.
    """
    src = REPO_ROOT / "packages" / "artifacts" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return pytest.importorskip(
        "artifacts", reason="the artifacts member is not in this workspace"
    )


def _ledger():
    """The ledger member, imported in-function and by path if need be."""
    src = REPO_ROOT / "packages" / "ledger" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return pytest.importorskip(
        "ledger", reason="the ledger member is not in this workspace"
    )


class TestTheAttemptsSeamIsOneContract:
    """Feature 240's three restatements, pinned against their owners.

    This member writes an attempt's source and trace into §9.2's layout
    and records how it ended in §9.1's ``fail_class``.  Three spellings of
    the layout and the vocabulary are therefore *shared* with two sibling
    members, and no import carries any of them across:

    * §9.2's two filenames this feature owns — ``code.py`` and
      ``exec_trace.json`` — are feature 173's contract, written by
      :func:`artifacts.persist_execution`.  A rename on either side would
      leave the layout holding two files the reader of the other side
      never looks for.
    * §9.1's four-word failure vocabulary is the **trial ledger's**
      ``outcome`` vocabulary — §8 records the same four words for a
      trial — and a member that wrote ``failed`` where the ledger writes
      ``error`` would have two names for one fact and no way to count
      either.  This is the pin that makes that drift loud.
    * the ``file:`` URI grammar: this module renders an attempt's address
      the way :func:`artifacts.artifact_uri` renders it, because both are
      one line over the *same* directory — the seam hands this member the
      path the store resolved, so the agreement is structural rather than
      coincidental, and this test is what says so out loud.
    """

    def test_the_two_files_this_feature_writes_are_the_layouts_own(self) -> None:
        artifacts = _artifacts()
        assert discovery.SOURCE_FILENAME == artifacts.SOURCE_FILENAME
        assert discovery.TRACE_FILENAME == artifacts.TRACE_FILENAME

    def test_the_layout_puts_the_two_files_where_this_feature_does(self) -> None:
        # ``code.py`` is §9.2's seventh-listed name and the trace its
        # sixth; the *values* are what a reader opens by, so the names are
        # asserted as literals too rather than only against each other —
        # two members agreeing on a misspelling would pass the check
        # above and fail a deployment.
        artifacts = _artifacts()
        assert discovery.SOURCE_FILENAME == "code.py"
        assert discovery.TRACE_FILENAME == "exec_trace.json"
        assert artifacts.SOURCE_FILENAME == "code.py"
        assert artifacts.TRACE_FILENAME == "exec_trace.json"

    def test_the_two_trace_keys_this_feature_uses_are_the_layouts(self) -> None:
        # The artifacts member's write path refuses a trace filed under a
        # node it does not fingerprint, keyed by these two names — and
        # this feature's ``Attempt.trace`` spells them from the same
        # signal the address came from, which is what makes the check
        # pass by construction.  Imported from the submodule rather than
        # the package because ``_execution`` is where feature 173
        # declares them and the package's ``__all__`` deliberately does
        # not re-export every constant of every private module.
        artifacts = _artifacts()
        execution = pytest.importorskip("artifacts._execution")
        assert execution.TRACE_NODE_KEY == "node_id"
        assert execution.TRACE_CAMPAIGN_KEY == "campaign_id"
        assert artifacts.TRACE_FILENAME == execution.TRACE_FILENAME

    def test_the_measured_five_are_the_layouts_and_the_siblings_names(self) -> None:
        # §9.2's seven files split three ways: this feature owns the pair
        # (``code.py``, ``exec_trace.json``), features 170-173 own the
        # measured five, and one directory holds all seven.  The five are
        # carried across a whole-directory commit by *name*, so a rename on
        # the artifacts side would leave this module carrying a file
        # nothing writes and dropping the one thing it was there for — the
        # exact silent loss the carry-forward exists to prevent, made loud
        # here.
        #
        # Each name is reached through the submodule that declares it
        # rather than the package root, because the constants live beside
        # the writers that stage them and the package's ``__all__``
        # re-exports only some of them.
        _artifacts()
        returns = pytest.importorskip("artifacts._returns")
        series = pytest.importorskip("artifacts._series")
        profiles = pytest.importorskip("artifacts._profiles")
        owners = (
            returns.SIGNAL_RETURNS_FILENAME,
            series.IC_SERIES_FILENAME,
            series.TURNOVER_SERIES_FILENAME,
            profiles.DECAY_PROFILE_FILENAME,
            profiles.REGIME_ATTRIBUTION_FILENAME,
        )
        assert tuple(discovery.MEASURED_FILENAMES) == owners
        # And as the doc writes them, so two members drifting together are
        # still caught.
        assert tuple(discovery.MEASURED_FILENAMES) == (
            "signal_returns.parquet",
            "ic_series.parquet",
            "turnover_series.parquet",
            "decay_profile.json",
            "regime_attribution.json",
        )

    def test_the_seven_names_are_seven_and_do_not_overlap(self) -> None:
        # The partition itself: the pair this feature stages and the five
        # it carries are disjoint, and together they are §9.2's seven.
        # An overlap would mean this module carrying forward a file it had
        # just written from a stale copy instead of from the caller.
        owned = {discovery.SOURCE_FILENAME, discovery.TRACE_FILENAME}
        measured = set(discovery.MEASURED_FILENAMES)
        assert not owned & measured
        assert len(owned) + len(measured) == 7

    def test_the_failure_vocabulary_is_the_trial_ledgers_outcome(self) -> None:
        # §9.1 annotates the ``fail_class`` column with four words and §8
        # records the same four for a trial's outcome.  The two are one
        # vocabulary because they answer one question — how did this
        # attempt end? — and a system that spelled them differently would
        # have a failure histogram per member.
        ledger = _ledger()
        assert tuple(discovery.FAIL_CLASSES) == tuple(ledger.OUTCOMES)

    def test_the_four_words_are_section_9_1s_literals(self) -> None:
        # The closed set as the architecture doc writes it, so a pair of
        # members drifting together is still caught.
        assert discovery.FAIL_CLASSES == ("ok", "timeout", "error", "tripwire_fail")

    def test_both_sides_refuse_the_same_drifted_word(self) -> None:
        # Neither side passes an unrecognised word through: the ledger's
        # :func:`ledger.validated_outcome` is the validator feature 240's
        # :func:`discovery.classify_failure` is the sibling of, and the
        # two agree on the words *and* on refusing the near-misses.  A
        # case variant is the near-miss that matters — ``OK`` looks like
        # ``ok`` and would silently split a failure histogram in two.
        _ledger()
        outcome = pytest.importorskip("ledger.outcome")
        validate = outcome.validated_outcome
        for word in discovery.FAIL_CLASSES:
            assert validate(word) == word
            assert discovery.classify_failure(word) == word
        # The ledger's own refusal class, named rather than caught blind:
        # this member may not import the sibling, so the class is reached
        # through the module the validator comes from.
        refusal = outcome.TrialRecordError
        for drifted in ("failed", "crashed", "OK", "tripwire-fail"):
            with pytest.raises(refusal):
                validate(drifted)
            with pytest.raises(discovery.AttemptLogError):
                discovery.classify_failure(drifted)

    def test_a_raised_failure_is_classified_as_the_evaluator_classifies_it(
        self,
    ) -> None:
        # The one classification rule that is not obvious, pinned against
        # the sibling that already ruled on it: **every raised failure is
        # ``error``, including a raised ``TimeoutError``.**  §5.2's timeout
        # is a control — the sandbox hard-kills the child and returns its
        # class as a *value* — so a timeout reaches the column by being
        # stated, never by being inferred from an exception, and a raised
        # ``TimeoutError`` is a host-side fault wearing a familiar name.
        #
        # This is worth a pin rather than only a test in this member's own
        # suite, because "``TimeoutError`` means ``timeout``" is the
        # reading a reasonable person arrives at unaided, and this module
        # had it wrong until the sibling's docstring was read.  A reader
        # who changes it back will now be told why not.
        pytest.importorskip(
            "evaluator", reason="the evaluator member is not in this workspace"
        )
        debit = pytest.importorskip("evaluator._debit")
        outcome = debit.failure_outcome
        for raised in (
            TimeoutError("hard kill"),
            RuntimeError("boom"),
            MemoryError(),
            ValueError("payload"),
        ):
            assert outcome(raised) == "error", raised
            assert discovery.classify_failure(raised) == "error", raised
        # The kill's own class still lands on the column — stated, not
        # inferred — so this is a change of *route* for ``timeout``, not a
        # loss of the class.
        assert discovery.classify_failure("timeout") == "timeout"
        assert outcome("timeout") == "timeout"

    def test_the_address_a_row_carries_is_the_artifacts_members_address(
        self, tmp_path: Path
    ) -> None:
        # ``file://`` over the node's directory, percent-encoded.  The
        # store here is the *real* :class:`artifacts.ArtifactStore` rather
        # than a double, because the thing under test is the agreement
        # between two members and a double would be this member agreeing
        # with itself.  Comparing the two spellings over one directory is
        # the pin; what it catches is this module drifting to a *different*
        # path (a root it resolved itself, a segment order it assumed),
        # which is the drift the seam exists to make impossible.
        #
        # ``AttemptLog.record`` is not called: it needs a tree to hang the
        # row from, and the address is rendered from the directory the
        # seam answers *before* any row is written — so the two spellings
        # are compared directly.
        artifacts = _artifacts()
        campaign = str(uuid_module.uuid4())
        node = str(uuid_module.uuid4())
        store = artifacts.ArtifactStore(tmp_path / "artifacts")
        directory = store.node_directory(campaign, node)
        assert discovery.persist._artifact_uri(directory) == artifacts.artifact_uri(
            store, campaign, node
        )

    def test_the_store_this_member_writes_through_speaks_the_whole_seam(
        self, tmp_path: Path
    ) -> None:
        # The structural claim the injected ``ArtifactDirectory`` makes:
        # the artifacts member's own store satisfies it by name, with no
        # adapter.  A store that grew a changed signature would fail here
        # rather than at the first attempt of a campaign.
        artifacts = _artifacts()
        store = artifacts.ArtifactStore(tmp_path / "artifacts")
        for method in ("node_directory", "write", "commit", "discard"):
            assert callable(getattr(store, method, None)), method
        # And the constructor's own check accepts it.
        discovery.AttemptLog("sqlite:///unused.db", store)
