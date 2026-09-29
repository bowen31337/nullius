"""The selection gate: §13 item 4's stop, read off the count the charge landed.

Feature 295's sentence — *"System rejects further selection of a sequestered
epoch once it has served three promotion decisions"* — and the file where
*the refusal* is the claim under test.  The count on the ledger row is
feature 294's, the ``retired`` flag is feature 296's and the depleting
remainder is feature 297's; this feature's whole act is one comparison —
the count against §13 item 4's own number — performed on the row the
charge's own read answers with.  And the refusal that comparison yields is
not a failure anywhere else in the member: everything landed, everything
is readable, and the answer is *no*, which is why the class it raises is a
new sibling rather than a face of a write's or a read's.

**What this feature is not, asserted as hard as what it is.**  The verdict
is the deciding evaluation's; the retirement is 296's flag, not this
gate's law; the remainder is 297's whole-table question.  So the first
tests pin the boundary: this module never spells 292's mismatch verdict,
never reads the ``retired`` or ``sealed_at`` column, never reads a pool, a
score or a coverage ledger, and spells no statement of its own at all —
the row arrives through feature 294's seam, so there is no second reading
of one table for the tests to catch.  A suite that only tested the happy
answer would pass for a module that had quietly re-implemented 296's flag
check or invented its own ``SELECT``.

**``>=`` is the comparison, and the end-to-end path is what proves it.**
Three bookings, three decisions, one charge — the ledger holds three — and
the fourth selection is refused, through the real acts of features 291,
293 and 294 rather than a hand-written row.  A count *above* three is
refused on the same comparison, because a figure past the budget is not a
cleaner epoch for exceeding it.

**Nothing moves, on either side of the verdict.**  The count is 294's to
persist and the flag 296's to set, so both a permitted and a refused
selection leave the raw row byte-identical — asserted on the table, not on
the store's own testimony.  And the absence case keeps ``0110``'s two
answers apart: an epoch nobody sealed is refused, never read as a zero
count, because a never-sealed name selected is sequestration bypassed by a
typo.
"""

from __future__ import annotations

import datetime as dt
import inspect
import sqlite3
import uuid
from pathlib import Path

import promotion as member
import pytest
from conftest import (
    CAMPAIGN_ID,
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    code_of,
)
from promotion import (
    DATABASE_URL_ENV,
    EPOCH_CHARGE_ERROR_CODE,
    EPOCH_ID_COLUMN,
    EPOCH_LEDGER_TABLE,
    EPOCH_SELECTION_ERROR_CODE,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    RETIRED_COLUMN,
    SEALED_AT_COLUMN,
    EpochChargeError,
    EpochCharges,
    EpochSelectionError,
    EpochSelections,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PreRegistrations,
    PromotionDecisions,
    PromotionError,
    PromotionStoreError,
    SEQUESTERED_EPOCH_BUDGET,
    ServingEpoch,
    rejects_further_selection,
    select_epoch,
)

#: The three instants the suite works over — the sealing (the conftest's
#: own literal for the seeded row), the registration and the decision —
#: named so an assertion reads as a statement about stamps rather than
#: about literals buried in a call.
SEALED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: A second sequestered epoch, for the tests that pin one epoch's spend
#: cannot close another's door.
OTHER_EPOCH = "epoch-2026-02"

REPO_ROOT = Path(__file__).resolve().parents[3]


def _request(node_id: str = NODE_ID, epoch_id: str = EPOCH_ID):
    """A well-formed pre-registration, with the named fields overridden."""
    return PreRegistrationRequest(
        node_id=node_id,
        epoch_id=epoch_id,
        criteria=dict(DEFAULT_CRITERIA_DOCUMENT),
    )


def _add_parents(store, *, nodes=(), epochs=()) -> None:
    """Insert the tree's parent rows through the pre-registration's connect.

    A node's row is the discovery loop's write and an epoch's row is the
    sealing process's, neither of which is this member's to invent — the
    same stance the conftest's ``seeded_database`` takes for its two.
    """
    connection = store._connect()
    try:
        with connection:
            for node in nodes:
                connection.execute(
                    "INSERT INTO node (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, ?, ?)",
                    (node, str(uuid.uuid4()), "macro", 1),
                )
            for epoch in epochs:
                connection.execute(
                    "INSERT INTO epoch_ledger (epoch_id, sealed_at) "
                    "VALUES (?, ?)",
                    (epoch, SEALED_AT.isoformat()),
                )
    finally:
        connection.close()


def _register(store, node_id: str = NODE_ID, epoch_id: str = EPOCH_ID):
    """Pre-register one node against one epoch, at this suite's clock."""
    PreRegisterEndpoint(store).post(
        _request(node_id=node_id, epoch_id=epoch_id),
        clock=lambda: REGISTERED_AT,
    )


def _decide(store, node_id: str = NODE_ID) -> None:
    """Record one node's decision, at this suite's clock."""
    PromotionDecisions(store.database_url).record_decision(
        node_id, clock=lambda: DECIDED_AT
    )


def _write_served(database_url: str, served: object) -> None:
    """Write one epoch's served count raw, standing in for another process.

    This test's own connection, not the store's — the shape the charge's
    own suite uses to prove it holds no cache, used here for the same
    purpose and for the count-past-budget refusal no writer can produce.
    """
    connection = sqlite3.connect(
        Path(database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} "
                f"SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                (served, EPOCH_ID),
            )
    finally:
        connection.close()


def _seeded(database_url: str) -> PreRegistrations:
    """A fresh database brought up and given the two parent rows.

    The conftest's :func:`seeded_database` is function-scoped and shared by
    every fixture that asks for it, so ``gate`` and ``spent`` reaching for
    it would land on *one* database — and a test that holds both would read
    the epoch ``spent`` had charged through the gate ``gate`` was built to
    judge, spending the clean epoch before the clean assertion runs.  Each
    fixture therefore seeds its **own** file here: one store per URL, the
    store's own connect bringing the three tables up (feature 291's
    contract — the owning migrations' own statements, no DDL of this
    suite's), then the two parent rows the foreign keys demand.
    """
    store = PreRegistrations(database_url)
    connection = store._connect()
    try:
        with connection:
            connection.execute(
                "INSERT INTO node (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, ?, ?)",
                (NODE_ID, CAMPAIGN_ID, "macro", 1),
            )
            connection.execute(
                "INSERT INTO epoch_ledger (epoch_id, sealed_at) VALUES (?, ?)",
                (EPOCH_ID, SEALED_AT.isoformat()),
            )
    finally:
        connection.close()
    return store


@pytest.fixture
def gate(tmp_path) -> EpochSelections:
    """The selection gate, over the charge store on a freshly seeded epoch.

    Its own seeded database — :func:`_seeded` on a file only this fixture
    sees, not the shared :func:`seeded_database`, so a test that also asks
    for :func:`spent` judges two epochs in two files rather than one epoch
    twice.  The seeded epoch is sealed and has served nothing, so this
    gate's first answer is the permissive one — the tests that need the
    epoch *spent* ask for :func:`spent` instead.
    """
    return EpochSelections(
        EpochCharges(_seeded(f"sqlite:///{tmp_path / 'gate.db'}").database_url)
    )


@pytest.fixture
def spent(tmp_path) -> EpochSelections:
    """A gate over an epoch that has served §13 item 4's whole budget.

    Its own seeded database, for the same reason :func:`gate` takes one:
    the shared :func:`seeded_database` would make a test holding both
    fixtures read the epoch this fixture spends through the gate built to
    answer a clean one.  Three nodes booked against the one epoch through
    feature 291's real act, three decisions closed through feature 293's,
    one charge through feature 294's — so the count the gate refuses on is
    a figure the member's own writers landed, not a hand edit.  The
    assertion inside the fixture is the whole precondition: the ledger
    holds three.
    """
    store = _seeded(f"sqlite:///{tmp_path / 'spent.db'}")
    nodes = [NODE_ID] + [str(uuid.uuid4()) for _ in range(2)]
    _add_parents(store, nodes=nodes[1:])
    for node in nodes:
        _register(store, node_id=node)
    for node in nodes:
        _decide(store, node)
    charges = EpochCharges(store.database_url)
    epoch, advanced = charges.charge(NODE_ID)
    assert advanced is True
    assert epoch.promotion_decisions_served == SEQUESTERED_EPOCH_BUDGET
    return EpochSelections(charges)


@pytest.fixture
def raw_ledger_row(database_url: str):
    """Read one epoch's ``epoch_ledger`` row raw, so a test sees the table.

    A raw ``SELECT`` rather than a store verb, for the reason the charge's
    suite gives: the point of most of these assertions is what the *table*
    holds — including the row before and after a selection, permitted or
    refused — and a test that asked the code under test would be asking it
    to confirm itself.

    The callable takes the database URL when the caller has one — the gate
    or spent fixture's own file, since those now seed a database of their
    own rather than sharing this fixture's — and falls back to the file
    this fixture was pointed at.  A test that reads the row a fixture spent
    has to read *that* fixture's file, or it reads a clean epoch and pins
    nothing.
    """

    def _row(
        epoch_id: str = EPOCH_ID, url: str | None = None
    ) -> sqlite3.Row | None:
        connection = sqlite3.connect(
            Path((url or database_url).removeprefix("sqlite:///"))
        )
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT {EPOCH_ID_COLUMN}, {SEALED_AT_COLUMN}, "
                f"{PROMOTION_DECISIONS_SERVED_COLUMN}, {RETIRED_COLUMN} "
                f"FROM {EPOCH_LEDGER_TABLE} WHERE {EPOCH_ID_COLUMN} = ?",
                (epoch_id,),
            )
            try:
                return cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()

    return _row


# -- The boundary: this feature refuses on the count, and on nothing else -------------


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares
    # a promotion against its recorded hash, and a gate that spelled it
    # would be two features in one module.  Docstrings are stripped by
    # ``code_of`` so the module may *say* it is not 292 without tripping
    # the test that pins it.
    from promotion import selection as module

    assert "criteria_mismatch" not in code_of(module)


def test_the_module_reads_neither_the_flag_nor_the_sealing_instant() -> None:
    # The count is the whole of the law here: ``retired`` is feature
    # 296's flag and ``sealed_at`` is the sealing process's fact, and a
    # module that read either would be judging 296's clause or
    # re-deriving the sequestration this gate takes as given.  Pinned on
    # the *attribute access* rather than the bare word, because a refusal
    # message may legitimately quote §13 item 4's own "retired
    # permanently" — what the module must never do is read the fields.
    from promotion import selection as module

    code = code_of(module)
    assert ".retired" not in code
    assert ".sealed_at" not in code
    assert "RETIRED_COLUMN" not in code
    assert "SEALED_AT_COLUMN" not in code


def test_the_module_imports_no_other_workspace_member() -> None:
    # No member imports another — every shared spelling is restated or, as
    # here, *used* from a sibling inside the same member.
    from promotion import selection as module

    code = code_of(module)
    for leaked in ("import regime", "from regime", "import discovery", "from ledger"):
        assert leaked not in code, leaked


def test_the_module_judges_no_merit_and_reads_no_evidence() -> None:
    # Whether the promotion *stands* is the deciding evaluation's verdict,
    # and the inputs to that verdict — a pool, a score, a coverage ledger,
    # a calibration status — are tables this act never opens.  A gate that
    # read one would have re-implemented half of 292, 298 or 299 with none
    # of their suites.
    from promotion import selection as module

    code = code_of(module)
    for evidence in ("regime_coverage", "campaign", "ir_oos", "score", "calibration"):
        assert evidence not in code, evidence


def test_the_module_reads_the_ledger_through_the_charges_own_seam() -> None:
    # The discipline :mod:`promotion.forward` states for its window and
    # :mod:`promotion.epoch` states for its count, pinned for this gate:
    # the row is read through feature 294's own store (composed in
    # ``__init__``), never through a second ``SELECT`` spelled here — so
    # the count this act refuses on and the count the charge answered with
    # cannot be two readings of one table.
    from promotion import selection as module

    code = code_of(module)
    assert f"FROM {EPOCH_LEDGER_TABLE}" not in code
    assert f"FROM {PROMOTION_REGISTRY_TABLE}" not in code
    assert "self._charges.epoch(" in code


def test_the_module_spells_no_statement_and_authors_no_ddl() -> None:
    # A gate that writes nothing needs no connection, no bootstrap and no
    # statement — and :mod:`promotion.schema` gains no fifth order because
    # the set a bootstrap runs is the set an act's own statements name and
    # this act's statements name nothing at all.  Every token here is
    # pinned so a later statement smuggled in fails this test rather than
    # quietly widening the member's DDL footprint.
    from promotion import selection as module

    code = code_of(module)
    for token in (
        "import sqlite3",
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE TABLE",
        "bootstrap",
    ):
        assert token not in code, token


def test_the_act_takes_nothing_but_the_epoch() -> None:
    # The arguments a caller might offer that this act must not take.  A
    # ``clock`` would stamp something, and nothing here stamps: the count
    # is 294's and the flag 296's.  A ``count`` would be a figure the
    # caller derived, and the count this gate judges is a function of the
    # ledger row or nothing.  A ``node_id`` would turn a gate over the
    # holdout into a judgement over one promotion — features 292-293's
    # territory.  The module-level spelling may add only the URL seam the
    # member's other spellings take.
    assert set(inspect.signature(EpochSelections.select).parameters) == {
        "self",
        "epoch_id",
    }
    assert set(inspect.signature(select_epoch).parameters) == {
        "epoch_id",
        "database_url",
        "env",
    }


def test_the_budget_is_the_prds_own_number_spelled_once() -> None:
    # §13 item 4's "3 promotion decisions", spelled in exactly one place:
    # a second spelling anywhere else in the member would be a second
    # place the budget lives, free to disagree with the one the gate
    # compares against.  The charge's module is the nearest neighbour that
    # could have carried it — 0110's docstring says it deliberately does
    # not — so that is where the absence is pinned.
    from promotion import epoch as charge_module
    from promotion import selection as module

    assert SEQUESTERED_EPOCH_BUDGET == 3
    assert "SEQUESTERED_EPOCH_BUDGET = 3" in code_of(module)
    assert "SEQUESTERED_EPOCH_BUDGET" not in code_of(charge_module)


# -- The gate ---------------------------------------------------------------------------


def test_a_freshly_sealed_epoch_is_selectable_and_answers_its_row(gate) -> None:
    # ``0110``'s default exists so that *freshly sealed* and *never sealed*
    # stay two answers, and this is the first one: a sealed epoch with no
    # decisions is selectable, and the answer is the row itself — the
    # value the caller goes on to book against, not a derived remainder.
    selected = gate.select(EPOCH_ID)
    assert isinstance(selected, ServingEpoch)
    assert selected.epoch_id == EPOCH_ID
    assert selected.sealed_at == SEALED_AT
    assert selected.promotion_decisions_served == 0
    assert selected.retired is False
    assert selected.row() == {
        EPOCH_ID_COLUMN: EPOCH_ID,
        SEALED_AT_COLUMN: SEALED_AT,
        PROMOTION_DECISIONS_SERVED_COLUMN: 0,
        RETIRED_COLUMN: False,
    }


def test_one_and_two_served_are_still_selectable(seeded_database) -> None:
    # The budget is three, so the epochs that have served some of it are
    # not spent: one decision served leaves two of the budget, two leaves
    # one, and both are selectable — the *running* count is what the gate
    # reads, not any single decision.
    charges = EpochCharges(seeded_database.database_url)
    for served in (1, 2):
        node = str(uuid.uuid4())
        _add_parents(seeded_database, nodes=[node])
        _register(seeded_database, node_id=node)
        _decide(seeded_database, node)
        epoch, _ = charges.charge(node)
        assert epoch.promotion_decisions_served == served
        assert (
            EpochSelections(charges).select(EPOCH_ID).promotion_decisions_served
            == served
        )


def test_three_served_is_refused_end_to_end(spent, raw_ledger_row) -> None:
    # The feature's own sentence, through the real acts: three bookings,
    # three decisions, one charge — the ledger holds three, read raw — and
    # the fourth selection is refused, naming the epoch, the figure and
    # §13 item 4's own words for what happens next.
    assert raw_ledger_row(url=spent.charges.database_url)[
        PROMOTION_DECISIONS_SERVED_COLUMN
    ] == 3
    with pytest.raises(EpochSelectionError) as raised:
        spent.select(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert EPOCH_ID in message
    assert "3" in message
    assert "legitimate terminal state" in message
    assert message.count(EPOCH_SELECTION_ERROR_CODE) == 1


def test_a_count_past_the_budget_is_refused_on_the_same_comparison(
    spent, raw_ledger_row
) -> None:
    # ``>=``, not ``==``: no writer in this member can land a count above
    # three, so the state is a hand edit or a future writer's — and either
    # way the epoch has served at least its budget, which is the whole of
    # the question.  An equality pin would read a figure of four as
    # cleaner than three, which is absurd, and the comparison is pinned
    # here so it cannot quietly become one.
    _write_served(spent.charges.database_url, 4)
    assert raw_ledger_row(url=spent.charges.database_url)[
        PROMOTION_DECISIONS_SERVED_COLUMN
    ] == 4
    with pytest.raises(EpochSelectionError) as raised:
        spent.select(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert "4" in message


def test_a_spent_epoch_does_not_close_its_neighbours_door(seeded_database) -> None:
    # The ledger keys by epoch, and so does the spend: refusing EPOCH_ID's
    # further selection says nothing about OTHER_EPOCH, which is the whole
    # difference between a per-epoch budget and the terminal state feature
    # 296 declares only when *every* epoch is spent.
    _add_parents(seeded_database, epochs=[OTHER_EPOCH])
    nodes = [NODE_ID] + [str(uuid.uuid4()) for _ in range(2)]
    _add_parents(seeded_database, nodes=nodes[1:])
    for node in nodes:
        _register(seeded_database, node_id=node)
    for node in nodes:
        _decide(seeded_database, node)
    charges = EpochCharges(seeded_database.database_url)
    charges.charge(NODE_ID)
    gate = EpochSelections(charges)
    with pytest.raises(EpochSelectionError):
        gate.select(EPOCH_ID)
    other = gate.select(OTHER_EPOCH)
    assert other.promotion_decisions_served == 0


def test_a_retired_epoch_under_budget_is_admitted(seeded_database) -> None:
    # The count is the law here and the flag is feature 296's: "never
    # reuse a retired epoch" is §13 item 4's *second* sentence and 296's
    # reader, while this gate is the *first* sentence's threshold.  A gate
    # that quietly judged the flag too would be two features in one module
    # — pinned by writing the flag raw (standing in for the exhaustion
    # machinery's own write) and asserting the admission anyway.
    gate = EpochSelections(EpochCharges(seeded_database.database_url))
    connection = sqlite3.connect(
        Path(seeded_database.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} SET {RETIRED_COLUMN} = 1 "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                (EPOCH_ID,),
            )
    finally:
        connection.close()
    selected = gate.select(EPOCH_ID)
    assert selected.retired is True
    assert selected.promotion_decisions_served == 0


def test_a_retired_epoch_at_budget_is_refused_on_the_count(spent) -> None:
    # The other half of the split: when both features would refuse, this
    # gate refuses for *its* reason — the count — and the refusal names
    # the budget, not the flag, because that is the comparison this module
    # is allowed to make.
    connection = sqlite3.connect(
        Path(spent.charges.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} SET {RETIRED_COLUMN} = 1 "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                (EPOCH_ID,),
            )
    finally:
        connection.close()
    with pytest.raises(EpochSelectionError) as raised:
        spent.select(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert "budget" in message


def test_nothing_moves_on_a_permitted_selection(gate, raw_ledger_row) -> None:
    # The count is 294's to persist and the flag 296's to set, so a
    # selection that proceeds writes nothing — read *before* and *after*
    # on the raw row, because the point is what the table holds and the
    # gate's own answer could not witness its own restraint.
    before = raw_ledger_row(url=gate.charges.database_url)
    gate.select(EPOCH_ID)
    assert tuple(raw_ledger_row(url=gate.charges.database_url)) == tuple(before)


def test_nothing_moves_on_a_refused_selection(spent, raw_ledger_row) -> None:
    # The refusal is the act, and it is not a write: there is no
    # "selection" row to record, because the booking itself — feature
    # 291's insert — is the record of a selection that *proceeded*.  A
    # refused one leaves the database exactly as it was.
    before = raw_ledger_row(url=spent.charges.database_url)
    with pytest.raises(EpochSelectionError):
        spent.select(EPOCH_ID)
    assert (
        tuple(raw_ledger_row(url=spent.charges.database_url)) == tuple(before)
    )


def test_the_gate_judges_the_row_every_time_it_is_asked(
    gate, raw_ledger_row
) -> None:
    # No cache: the ledger row is the only record of what an epoch has
    # served, so it is the only thing the verdict is drawn from.  Driven
    # by writing behind the gate's back — this test's own connection,
    # standing in for another process's charge — and reading it back.
    assert gate.select(EPOCH_ID).promotion_decisions_served == 0
    _write_served(gate.charges.database_url, 3)
    assert raw_ledger_row(url=gate.charges.database_url)[
        PROMOTION_DECISIONS_SERVED_COLUMN
    ] == 3
    with pytest.raises(EpochSelectionError):
        gate.select(EPOCH_ID)


def test_an_epoch_nobody_sealed_is_refused_not_read_as_clean(gate) -> None:
    # ``0110``'s other answer: an absent row is *nobody sealed it*, not a
    # clean epoch, and a gate that read the absence as a zero count would
    # make any never-sealed name selectable — sequestration bypassed by a
    # typo.  The refusal names the table, the epoch and the repair.
    with pytest.raises(EpochSelectionError) as raised:
        gate.select(OTHER_EPOCH)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert EPOCH_LEDGER_TABLE in message
    assert OTHER_EPOCH in message
    assert "sealing" in message


def test_a_malformed_epoch_is_refused_without_touching_a_database(
    tmp_path: Path,
) -> None:
    # The ask is validated before anything is read, so a malformed
    # selection is refused without opening a database — and nothing is
    # created, which is the sharper half: a refused call leaves no file
    # behind.
    gate = EpochSelections(
        EpochCharges(f"sqlite:///{tmp_path / 'never-opened.db'}")
    )
    with pytest.raises(EpochSelectionError) as raised:
        gate.select("   ")
    assert str(raised.value).startswith(EPOCH_SELECTION_ERROR_CODE)
    assert not (tmp_path / "never-opened.db").exists()


def test_a_corrupt_row_arrives_translated_with_one_word_in_front(
    gate,
) -> None:
    # SQLite's columns are dynamically typed, so a raw write from another
    # tool can land anything in the count's column.  The charge's read
    # refuses it in *its* vocabulary and this gate translates — one code
    # word in front, the sibling's finding carried through whole, so an
    # operator loses nothing and a caller's single ``except`` holds.
    _write_served(gate.charges.database_url, "many")
    with pytest.raises(EpochSelectionError) as raised:
        gate.select(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert EPOCH_CHARGE_ERROR_CODE in message
    assert message.count(EPOCH_SELECTION_ERROR_CODE) == 1
    assert message.count(EPOCH_CHARGE_ERROR_CODE) == 1


def test_a_url_this_member_cannot_speak_is_refused_in_this_features_words() -> None:
    # The translation at the seam: the charge store raises its own
    # vocabulary for an address it cannot speak, and a caller whose single
    # ``except EpochSelectionError`` guards its selection path must not be
    # defeated by a refusal phrased for a charge it never made.  The class
    # is translated and the sibling's message carried through, so nothing
    # an operator needs is lost.
    gate = EpochSelections(EpochCharges("postgresql://host/ledger"))
    with pytest.raises(EpochSelectionError) as raised:
        gate.select(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert "postgresql" in message


# -- The pure judgment --------------------------------------------------------------------


def test_counts_under_the_budget_clear_and_answer_their_figure() -> None:
    # The pure half of the pair: the figure a reader found, and the answer
    # is that same figure — so a caller that wants to log or carry it does
    # not read the row a second time.
    for served in (0, 1, 2):
        assert rejects_further_selection(EPOCH_ID, served) == served


def test_the_budget_and_beyond_are_refused() -> None:
    # Three is §13 item 4's budget and four is past it, and both are
    # refused — the comparison is ``>=``, the spelling ``0110``'s own
    # docstring gives this feature.
    for served in (SEQUESTERED_EPOCH_BUDGET, SEQUESTERED_EPOCH_BUDGET + 1):
        with pytest.raises(EpochSelectionError) as raised:
            rejects_further_selection(EPOCH_ID, served)
        message = str(raised.value)
        assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
        assert str(served) in message


def test_the_refusal_names_the_epoch_the_figures_and_the_law() -> None:
    # An operator greps one word and lands on a message that states the
    # whole case: which epoch, how many decisions, what budget, and §13
    # item 4's own sentence for what the system does when the clean epochs
    # run out.
    with pytest.raises(EpochSelectionError) as raised:
        rejects_further_selection(OTHER_EPOCH, SEQUESTERED_EPOCH_BUDGET)
    message = str(raised.value)
    assert OTHER_EPOCH in message
    assert str(SEQUESTERED_EPOCH_BUDGET) in message
    assert "§13 item 4" in message
    assert "legitimate terminal state" in message


def test_a_name_that_states_nothing_is_refused() -> None:
    # The one value this function's caller supplies besides the figure is
    # the epoch's name, and it is validated — a blank would name no row an
    # operator could go and read, and the refusal must name *which* epoch
    # was spent.
    with pytest.raises(EpochSelectionError) as raised:
        rejects_further_selection("   ", 0)
    assert str(raised.value).startswith(EPOCH_SELECTION_ERROR_CODE)


def test_a_figure_that_is_not_a_count_is_refused() -> None:
    # ``True`` is ``1`` in Python and a flag where a count belongs would
    # silently answer one decision nobody recorded; a negative or a
    # fraction or text is a figure nobody derived.  Judging a selection on
    # any of them would be admitting or refusing an epoch on a number that
    # is not the ledger's.
    for bad in (True, -1, "three", 1.0, None):
        with pytest.raises(EpochSelectionError):
            rejects_further_selection(EPOCH_ID, bad)


def test_the_pure_judgment_agrees_with_the_gate(spent) -> None:
    # One comparison in the member: the gate delegates to the pure
    # judgment, so the two cannot disagree.  Asserted on both halves —
    # the row the gate refuses and a row it admits, reached by writing
    # behind its back the way another process's re-supply would — because
    # a delegation that survived only one half would be two comparisons
    # again.
    standing = spent.charges.epoch(EPOCH_ID)
    assert standing.promotion_decisions_served == SEQUESTERED_EPOCH_BUDGET
    with pytest.raises(EpochSelectionError):
        rejects_further_selection(EPOCH_ID, standing.promotion_decisions_served)
    _write_served(spent.charges.database_url, 2)
    recovered = spent.charges.epoch(EPOCH_ID)
    assert (
        rejects_further_selection(
            EPOCH_ID, recovered.promotion_decisions_served
        )
        == 2
    )
    assert spent.select(EPOCH_ID).promotion_decisions_served == 2


# -- The seam -------------------------------------------------------------------------------


class _StandIn:
    """A duck-typed stand-in for the charge store — the gate's contract.

    :class:`EpochSelections` reads ``epoch`` and nothing else, so a caller
    may judge through anything shaped like the charge store — this suite's
    stand-in, or the composed store, identically.  The check is the verbs
    rather than the class, because the factory's scan imports this member
    under a synthetic module name and a class check would refuse the very
    store the factory hands out.
    """

    def __init__(self, standing: ServingEpoch | None) -> None:
        self._standing = standing

    def epoch(self, epoch_id: str) -> ServingEpoch | None:
        return self._standing


def test_a_duck_typed_stand_in_is_a_valid_thing_to_judge_through() -> None:
    # The gate answers with the row the seam answered with — identity, not
    # a copy — and refuses on that row's figure, and the absence refusal
    # fires off the seam's ``None`` exactly as it does off the real store.
    standing = ServingEpoch(
        epoch_id=EPOCH_ID,
        sealed_at=SEALED_AT,
        promotion_decisions_served=2,
        retired=False,
    )
    gate = EpochSelections(_StandIn(standing))
    assert gate.select(EPOCH_ID) is standing
    with pytest.raises(EpochSelectionError):
        EpochSelections(_StandIn(None)).select(EPOCH_ID)


def test_a_seam_missing_the_verb_is_refused_at_construction() -> None:
    # A reader with nothing to read through names no ledger, and the fault
    # is a *programming* error — a ``TypeError``, not a promotion state no
    # operator can fix by sealing or spending anything.
    with pytest.raises(TypeError):
        EpochSelections(object())


def test_the_class_rather_than_an_instance_is_refused_at_construction() -> None:
    # A class exposes its methods as plain functions, so it would pass the
    # verb check and then fail on the first call with a missing positional
    # argument — a confusing way to learn the store was never built.
    with pytest.raises(TypeError):
        EpochSelections(EpochCharges)


# -- The schema this feature's act needs -------------------------------------------------------


def test_a_fresh_database_gets_only_the_table_the_seams_owner_creates(
    tmp_path: Path,
) -> None:
    # This act owns no order in :mod:`promotion.schema` because its own
    # statements name no table: the one table the read needs is brought up
    # by the charge store's own connect, which is the rule's smallest
    # illustration — a dependency stated as a composition rather than as a
    # list.  The gate's first read on a fresh database leaves it holding
    # the ledger and creating neither the registry nor the node tree.
    gate = EpochSelections(
        EpochCharges(f"sqlite:///{tmp_path / 'fresh.db'}")
    )
    with pytest.raises(EpochSelectionError):
        gate.select(EPOCH_ID)
    connection = sqlite3.connect(tmp_path / "fresh.db")
    try:
        names = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert EPOCH_LEDGER_TABLE in names
    assert PROMOTION_REGISTRY_TABLE not in names
    assert "node" not in names


def test_selection_lands_on_a_database_the_chain_migrated(
    migrated_database,
) -> None:
    # The convergence the other readers reach, from this feature's side of
    # it: a deployment where the versioned tree got there first is served
    # by the same gate — the row it judges is the row the charge read off
    # a schema the migrations own, and both creators of the table run the
    # same statements.
    parents = PreRegistrations(migrated_database)
    _add_parents(parents, nodes=[NODE_ID], epochs=[EPOCH_ID])
    _register(parents)
    _decide(parents)
    charges = EpochCharges(migrated_database)
    charges.charge(NODE_ID)
    selected = EpochSelections(charges).select(EPOCH_ID)
    assert selected.promotion_decisions_served == 1


# -- The vocabulary -----------------------------------------------------------------------------


def test_every_refusal_is_one_gathered_class() -> None:
    # The gathering is the design: this feature's caller is a *gate* whose
    # one failure mode is silence, so a single ``except
    # EpochSelectionError`` has to catch every face — a malformed ask, an
    # unreachable address, an epoch nobody sealed, a corrupt row, and the
    # spend itself.  This test is where a later feature that split them
    # would be caught, because the caller's guard would develop a hole.
    from promotion import selection as module

    assert issubclass(EpochSelectionError, PromotionError)
    assert not issubclass(EpochSelectionError, PromotionStoreError)
    code = code_of(module)
    assert "raise PromotionError(" not in code
    assert "raise PromotionStoreError(" not in code
    assert "raise EpochChargeError(" not in code


def test_the_selection_class_is_not_the_charge_class() -> None:
    # The closest sibling and the one the split is for: the charge's class
    # reports *a count did not land*, this one *a count reached its
    # budget* — the write and the refusal over one column.  Collapsing the
    # classes would send an operator debugging a write that succeeded when
    # the finding is §13 item 4's own law.
    assert EpochSelectionError.__bases__ == (PromotionError,)
    assert not issubclass(EpochSelectionError, EpochChargeError)
    assert not issubclass(EpochChargeError, EpochSelectionError)


def test_the_code_word_opens_every_refusal_the_gate_raises(spent, gate) -> None:
    # An operator greps one word for *this epoch's budget is spent*.  All
    # five faces driven through their real paths, and asserted as a
    # *prefix* so a refusal that merely mentioned the word in passing
    # could not pass.
    for call in (
        lambda: gate.select("   "),
        lambda: gate.select(OTHER_EPOCH),
        lambda: spent.select(EPOCH_ID),
        lambda: select_epoch(EPOCH_ID, database_url="   "),
        lambda: EpochSelections(EpochCharges("postgresql://host/ledger")).select(
            EPOCH_ID
        ),
    ):
        with pytest.raises(EpochSelectionError) as raised:
            call()
        assert str(raised.value).startswith(EPOCH_SELECTION_ERROR_CODE)


def test_the_code_word_is_not_the_charges_own() -> None:
    # Two acts, two words: the charge's names *a count did not land* and
    # this one names *a count reached its budget*, and an operator who
    # lands on the wrong one would be debugging a successful write.  The
    # words agree on their domain prefix and differ where the acts do.
    assert EPOCH_SELECTION_ERROR_CODE != EPOCH_CHARGE_ERROR_CODE
    assert EPOCH_SELECTION_ERROR_CODE == "epoch_budget_spent"


# -- The module-level spellings -------------------------------------------------------------------


def test_select_epoch_resolves_the_url_it_is_handed(gate, spent) -> None:
    # The feature's sentence as one call, for the caller that wants the
    # gate without holding stores — both halves, on the two databases the
    # fixtures built.
    clean = select_epoch(EPOCH_ID, database_url=gate.charges.database_url)
    assert clean.promotion_decisions_served == 0
    with pytest.raises(EpochSelectionError):
        select_epoch(EPOCH_ID, database_url=spent.charges.database_url)


def test_the_module_level_spelling_resolves_the_ambient_variable(
    monkeypatch, gate
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace
    # reads, so a deployment points every member at one database or at
    # none.
    monkeypatch.setenv(DATABASE_URL_ENV, gate.charges.database_url)
    assert select_epoch(EPOCH_ID).promotion_decisions_served == 0


def test_a_deployment_naming_no_database_is_refused_by_name(
    monkeypatch,
) -> None:
    # The silence is the dangerous failure here and not the refusal: a
    # selection that quietly went unjudged is a spent epoch read as clean,
    # which is the state §13 item 4's ledger exists to make impossible —
    # so a gate resolved from nothing is refused by name.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(EpochSelectionError) as raised:
        select_epoch(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_SELECTION_ERROR_CODE)
    assert DATABASE_URL_ENV in message


def test_from_env_answers_none_without_a_database(monkeypatch, gate) -> None:
    # Absent is not an error: it is a deployment without a relational
    # store, and the caller that must select an epoch is the caller that
    # must not find itself in it.  The *refusal* belongs to the caller,
    # which the module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert EpochSelections.from_env() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert EpochSelections.from_env() is None
    resolved = EpochSelections.from_env(
        {DATABASE_URL_ENV: gate.charges.database_url}
    )
    assert isinstance(resolved, EpochSelections)
    assert resolved.select(EPOCH_ID).promotion_decisions_served == 0


# -- The member's surface and the spec --------------------------------------------------------


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole surface; a caller judging an epoch
    # selectable should not have to reach past ``promotion`` into a
    # submodule to make the act or catch the refusal.
    assert member.SEQUESTERED_EPOCH_BUDGET is SEQUESTERED_EPOCH_BUDGET
    assert member.EpochSelections is EpochSelections
    assert member.EpochSelectionError is EpochSelectionError
    assert member.rejects_further_selection is rejects_further_selection
    assert member.select_epoch is select_epoch


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 295 adds no component, for the reason every sibling states:
    # a builder takes no arguments and is built on every ``create_app()``
    # call, while *which epochs are still clean* is a fact about rows that
    # move — a charge lands, an epoch spends — and no composition can
    # supply it.  This assertion is where a second ``@register`` would be
    # noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not
    # have to go looking, and so a re-scoped feature would fail a test
    # rather than quietly leaving the suite asserting something the spec
    # no longer says.  The module's docstring quotes it too; this is the
    # data-side copy.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System rejects further selection of a sequestered epoch once it "
        "has served three promotion decisions" in spec.read_text(encoding="utf-8")
    )
