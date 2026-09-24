"""The epoch's charge: §13 item 4's count, persisted as one column.

Feature 294's sentence — *"System persists the running promotion decision
count against the serving epoch in the epoch_ledger"* — and the file where
*the running count* is the claim under test.  The ledger row is the
sealing process's; this act adds one value to it (the count) and touches
neither of the two the sealing wrote, so the count is persisted *against
the serving epoch* in the strict sense that the row, read back, carries
the number of closed ``promotion_registry`` rows that epoch booked — the
reading features 295-297's exhaustion machinery and feature 96's usage
derivation all start from.

**Derived, not incremented — and the derivation is what the tests pin.**
An increment would make the ledger a tally beside the registry rather than
a function of it, and a retried charge would double-count a decision that
happened once.  This store recounts: the figure written is
:func:`~promotion.epoch.decisions_served` over feature 293's own listing,
so the idempotence is a *behaviour* of the derivation (a re-charge writes
nothing) rather than a guard the writer remembers to make, and a later
node's charge advances the column to the new total rather than past it.

**What this feature is not, asserted as hard as what it is.**  The verdict
is the deciding evaluation's; the threshold is feature 295's; the
retirement is feature 296's.  So the first tests pin the boundary: this
module never spells 292's mismatch verdict, never carries its own
predicate for the number §13 item 4 retires at, never reads a pool, a
score or a coverage ledger, and never takes an ``epoch_id``, a ``count``
or a ``clock`` — the epoch is read off the booked row, the figure is
derived from the closed rows, and nothing here stamps anything.  A suite
that only tested the happy write would pass for a module that had quietly
re-implemented 295's threshold or invented a sequestration instant.

**The one-column law, and the two hands it refuses.**  The ``SET`` clause
names ``promotion_decisions_served`` and nothing else, parsed rather than
substring-matched exactly as the decision's suite parses its own mirror.
And the two states no writer of this member can produce — a booking whose
ledger row is gone, and a derivation *below* the standing count — are
refused rather than repaired, because both are a hand that reached past
the member, and the one repair this store must not offer is minting a
``sealed_at`` it was never the author of.
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
    DEFAULT_CRITERIA_DOCUMENT,
    EPOCH_ID,
    NODE_ID,
    code_of,
)
from promotion import (
    CHARGE_MIGRATION_ORDER,
    DATABASE_URL_ENV,
    DECISION_MIGRATION_ORDER,
    EPOCH_CHARGE_ERROR_CODE,
    EPOCH_ID_COLUMN,
    EPOCH_LEDGER_TABLE,
    MIGRATION_ORDER,
    NODE_ID_COLUMN,
    PROMOTION_DECISION_ERROR_CODE,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    RETIRED_COLUMN,
    SEALED_AT_COLUMN,
    EpochChargeError,
    EpochCharges,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PromotionCriteria,
    PromotionDecisions,
    PromotionError,
    PromotionStoreError,
    ServingEpoch,
    charge_epoch,
    criteria_hash,
    decisions_served,
    epoch_charge,
)

#: The three instants the suite works over — the sealing (the conftest's
#: own literal for the seeded row), the registration and the decision —
#: named so an assertion reads as a statement about stamps rather than
#: about literals buried in a call.
SEALED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: A second sequestered epoch, for the tests that pin one epoch's count
#: cannot move another's row.
OTHER_EPOCH = "epoch-2026-02"

#: The hash the suite's registrations record — the value the open-row
#: refusal is asserted to name, computed from the conftest's document so
#: agreement is with the criteria module rather than this suite's own
#: arithmetic.
EXPECTED_HASH = criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))

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
    same stance the conftest's ``seeded_database`` takes for its two.  The
    inserts go through feature 291's own store so the tables are the
    migrations' and the pragma is on.
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


@pytest.fixture
def charges(database_url: str) -> EpochCharges:
    """The charge store, pointed at this test's own fresh database.

    No migration has run: the store's first act is what brings the ledger
    to the file — one owner, ``0110`` — the contract the schema adapter
    states for this feature.  The tests that need a *booking* to bill ask
    for :func:`registered` or :func:`decided` instead.
    """
    return EpochCharges(database_url)


@pytest.fixture
def registered(seeded_database) -> EpochCharges:
    """A charge store over a database holding one booked-but-undecided row.

    The open row this fixture leaves behind is the precondition
    ``depends_on="293"`` makes load-bearing, and the tests that check the
    *open row* refusal ask for exactly this fixture.
    """
    _register(seeded_database)
    return EpochCharges(seeded_database.database_url)


@pytest.fixture
def decided(seeded_database) -> EpochCharges:
    """A charge store over a database holding one decided registration.

    The semantic precondition of the charge: a promotion decision has been
    recorded (feature 293's stamp), so the epoch it booked has served one
    and there is a count to persist.  The registration and the decision
    both go through their own features' writers at clocks this suite
    names, so all three acts agree on the rows by construction.
    """
    _register(seeded_database)
    _decide(seeded_database)
    return EpochCharges(seeded_database.database_url)


@pytest.fixture
def raw_ledger_row(database_url: str):
    """Read one epoch's ``epoch_ledger`` row raw, so a test sees the table.

    A raw ``SELECT`` rather than a store verb, for the reason the decision
    suite gives: the point of most of these assertions is what the *table*
    holds — including the count before and after a charge, the two
    columns a charge must not move, and a hand edit the store must refuse
    — and a test that asked the store would be asking the code under test
    to confirm itself.
    """

    def _row(epoch_id: str = EPOCH_ID) -> sqlite3.Row | None:
        connection = sqlite3.connect(
            Path(database_url.removeprefix("sqlite:///"))
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


# -- The boundary: this feature counts, it does not judge or budget ------------------


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares
    # a promotion against its recorded hash, and a charge store that
    # spelled it would be two features in one module.  Docstrings are
    # stripped by ``code_of`` so the module may *say* it is not 292
    # without tripping the test that pins it.
    from promotion import epoch as module

    assert "criteria_mismatch" not in code_of(module)


def test_the_module_carries_no_threshold_of_its_own() -> None:
    # §13 item 4's number is feature 295's refusal, and the count this
    # module persists is the input to it — not the verdict.  A module that
    # carried its own predicate for the budget would be a second place the
    # threshold lives, free to disagree with 295's; the pins are the
    # predicate's name and its comparison, asserted on the code so the
    # module may *say* it stops at the count without tripping the test.
    from promotion import epoch as module

    code = code_of(module)
    assert "served_three" not in code
    assert ">= 3" not in code


def test_the_module_imports_no_other_workspace_member() -> None:
    # No member imports another — every shared spelling is restated or, as
    # here, *used* from a sibling inside the same member.
    from promotion import epoch as module

    code = code_of(module)
    for leaked in ("import regime", "from regime", "import discovery", "from ledger"):
        assert leaked not in code, leaked


def test_the_module_judges_nothing_and_reads_no_evidence() -> None:
    # Whether the promotion *stands* is the deciding evaluation's verdict,
    # and the inputs to that verdict — a pool, a score, a coverage ledger,
    # a calibration status — are tables this act never opens.  A store
    # that read one would have re-implemented half of 292, 298 or 299
    # with none of their suites.
    from promotion import epoch as module

    code = code_of(module)
    for evidence in ("regime_coverage", "campaign", "ir_oos", "score", "calibration"):
        assert evidence not in code, evidence


def test_the_module_reads_the_registry_through_the_decisions_own_seam() -> None:
    # The discipline :mod:`promotion.forward` states for its window, pinned
    # for this member's first *writer*: the registry is read through
    # feature 293's own store (composed in ``__init__``), never through a
    # second ``SELECT`` spelled here — so the count this act persists and
    # the decisions that store reports cannot be two readings of one
    # table.
    from promotion import epoch as module

    code = code_of(module)
    assert f"FROM {PROMOTION_REGISTRY_TABLE}" not in code
    assert "PromotionDecisions(" in code


def test_the_act_takes_no_epoch_no_count_and_no_clock() -> None:
    # The three arguments a caller might offer that this act must not
    # take.  An ``epoch_id`` would let a caller bill a different holdout
    # than the one the pre-registration booked — the reuse §13 item 4
    # retires epochs to prevent, and the refusal feature 293's own
    # signature makes.  A ``count`` would be a figure the caller derived,
    # and the count this store persists is a function of the registry or
    # nothing.  A ``clock`` would stamp something, and nothing here
    # stamps: the sealing instant is the sealing process's fact.
    parameters = set(inspect.signature(EpochCharges.charge).parameters)
    assert "epoch_id" not in parameters
    assert "count" not in parameters
    assert "clock" not in parameters
    assert set(inspect.signature(charge_epoch).parameters) <= (
        parameters | {"database_url", "env"}
    )


def test_the_update_cannot_name_anything_but_the_count() -> None:
    # The one-column law, enforced by the shape of the statement rather
    # than by a check the writer remembers to make — the mirror of the
    # decision's SET-clause test.  ``sealed_at`` and ``retired`` are
    # values this statement has no clause for, so the charging write
    # cannot mint a sequestration instant or pronounce a retirement.
    from promotion.epoch import _UPDATE_SQL

    head, tail = _UPDATE_SQL.split("SET", 1)
    set_clause, where_clause = tail.split("WHERE", 1)
    assert EPOCH_LEDGER_TABLE in head
    assigned = [side.strip() for side in set_clause.split("=", 1)]
    assert assigned == [PROMOTION_DECISIONS_SERVED_COLUMN, "?"]
    # And the WHERE names the key and nothing else — deliberately, because
    # unlike the decision's once-only close the charge is repeatable: a
    # second writer billing the same epoch writes the same derived figure.
    assert where_clause.strip() == f"{EPOCH_ID_COLUMN} = ?"


# -- The write -----------------------------------------------------------------------


def test_a_charge_persists_the_derived_count(decided, raw_ledger_row) -> None:
    # Feature 294 in one act: the epoch's row acquires the count of closed
    # rows that booked it, and the answer is the row the table holds —
    # proved by the raw read, not by the returned value agreeing with
    # itself.
    epoch, advanced = decided.charge(NODE_ID)
    assert advanced is True
    assert epoch.promotion_decisions_served == 1
    row = raw_ledger_row()
    assert row is not None
    assert row[PROMOTION_DECISIONS_SERVED_COLUMN] == 1


def test_the_count_includes_every_decision_the_epoch_served(
    seeded_database,
) -> None:
    # The *running* of the running count: one charge bills the epoch for
    # every decision it has served, not only the caller's own — three
    # closed rows booked against one epoch answer three, which is §13
    # item 4's whole budget reached in one figure and exactly what
    # features 295-297 read.
    nodes = [NODE_ID] + [str(uuid.uuid4()) for _ in range(2)]
    _add_parents(seeded_database, nodes=nodes[1:])
    for node in nodes:
        _register(seeded_database, node_id=node)
    for node in nodes:
        _decide(seeded_database, node)
    charges = EpochCharges(seeded_database.database_url)
    epoch, advanced = charges.charge(NODE_ID)
    assert advanced is True
    assert epoch.promotion_decisions_served == 3


def test_one_epochs_charge_moves_no_other_epochs_row(
    seeded_database, raw_ledger_row
) -> None:
    # The ledger keys by epoch, and so does the count: a decision booked
    # against the second epoch advances only its row.  A charge that
    # bumped every row it could see would retire epochs nobody spent.
    other = str(uuid.uuid4())
    _add_parents(seeded_database, nodes=[other], epochs=[OTHER_EPOCH])
    _register(seeded_database)
    _decide(seeded_database)
    _register(seeded_database, node_id=other, epoch_id=OTHER_EPOCH)
    _decide(seeded_database, node_id=other)
    charges = EpochCharges(seeded_database.database_url)
    first, _ = charges.charge(NODE_ID)
    second, _ = charges.charge(other)
    assert first.epoch_id == EPOCH_ID
    assert second.epoch_id == OTHER_EPOCH
    assert first.promotion_decisions_served == 1
    assert second.promotion_decisions_served == 1
    assert raw_ledger_row(OTHER_EPOCH)[PROMOTION_DECISIONS_SERVED_COLUMN] == 1


def test_nothing_else_on_the_row_moves(decided, raw_ledger_row) -> None:
    # The two columns the sealing process wrote are byte-identical after
    # the charge — read *before* and *after* on the raw row, because the
    # point is what the table holds and a store-returned record could not
    # witness its own write's restraint.
    before = raw_ledger_row()
    decided.charge(NODE_ID)
    after = raw_ledger_row()
    for column in (EPOCH_ID_COLUMN, SEALED_AT_COLUMN, RETIRED_COLUMN):
        assert after[column] == before[column], column
    assert before[PROMOTION_DECISIONS_SERVED_COLUMN] == 0
    assert after[PROMOTION_DECISIONS_SERVED_COLUMN] == 1


def test_the_answer_is_the_row_the_table_holds(decided) -> None:
    # The answer is a :class:`ServingEpoch` read back after the write, not
    # a record assembled from the arguments — the epoch's name, the
    # sealing instant as an aware datetime, the count and the flag are
    # all the table's own.
    epoch, advanced = decided.charge(NODE_ID)
    assert advanced is True
    assert epoch.epoch_id == EPOCH_ID
    assert epoch.sealed_at == SEALED_AT
    assert epoch.retired is False
    assert epoch.row() == {
        EPOCH_ID_COLUMN: EPOCH_ID,
        SEALED_AT_COLUMN: SEALED_AT,
        PROMOTION_DECISIONS_SERVED_COLUMN: 1,
        RETIRED_COLUMN: False,
    }


def test_a_re_charge_returns_the_standing_row_and_moves_nothing(
    decided, raw_ledger_row
) -> None:
    # The derivation *is* the idempotence: a retried charge recounts the
    # same closed rows, finds the standing figure, and writes nothing —
    # asserted on the raw row, so a store that incremented and returned a
    # cached value could not pass.
    first, advanced = decided.charge(NODE_ID)
    assert advanced is True
    again, advanced_again = decided.charge(NODE_ID)
    assert advanced_again is False
    assert again == first
    assert raw_ledger_row()[PROMOTION_DECISIONS_SERVED_COLUMN] == 1


def test_a_later_decided_node_advances_the_count(
    seeded_database, raw_ledger_row
) -> None:
    # The running count over time: a first charge answers one, a second
    # decision lands, and the next charge re-supplies two — the column
    # tracks the registry's whole history for the epoch, not the calls
    # this process happened to make.
    _register(seeded_database)
    _decide(seeded_database)
    charges = EpochCharges(seeded_database.database_url)
    first, _ = charges.charge(NODE_ID)
    assert first.promotion_decisions_served == 1
    later = str(uuid.uuid4())
    _add_parents(seeded_database, nodes=[later])
    _register(seeded_database, node_id=later)
    _decide(seeded_database, node_id=later)
    second, advanced = charges.charge(later)
    assert advanced is True
    assert second.promotion_decisions_served == 2
    assert raw_ledger_row()[PROMOTION_DECISIONS_SERVED_COLUMN] == 2


# -- The reads ------------------------------------------------------------------------


def test_a_freshly_sealed_epoch_serves_zero_and_that_is_a_row(
    registered,
) -> None:
    # ``0110``'s default exists so that *freshly sealed* and *never
    # sealed* stay two answers: a sealed epoch with no decisions is a row
    # whose count is zero — *returned*, not collapsed into the absence,
    # because zero served is a fact feature 297's remainder reads.
    epoch = registered.epoch(EPOCH_ID)
    assert isinstance(epoch, ServingEpoch)
    assert epoch.promotion_decisions_served == 0
    assert epoch.retired is False


def test_an_epoch_the_ledger_does_not_hold_answers_none(registered) -> None:
    # ``None`` is *no sequestered epoch to ask about* — deliberately not
    # a zeroed record, which would report a served count for an epoch the
    # sealing process never sealed.
    assert registered.epoch(OTHER_EPOCH) is None


def test_a_malformed_epoch_name_is_refused_rather_than_answered_none(
    registered,
) -> None:
    # A name that states nothing is a malformed ask, not an unsealed
    # epoch, and the two must not collapse into one answer — a caller
    # branching on ``None`` would read a typo as a clean ledger.
    with pytest.raises(EpochChargeError) as raised:
        registered.epoch("   ")
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


def test_the_store_holds_no_cache_of_the_counts_it_wrote(
    decided, raw_ledger_row
) -> None:
    # The ledger row is the only record of what an epoch has served, so
    # it is the only thing an answer is drawn from.  Driven by writing
    # behind the store's back — this test's own connection, standing in
    # for another process's charge — and reading it back.
    decided.charge(NODE_ID)
    connection = sqlite3.connect(
        Path(decided.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} "
                f"SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                (4, EPOCH_ID),
            )
    finally:
        connection.close()
    assert raw_ledger_row()[PROMOTION_DECISIONS_SERVED_COLUMN] == 4
    assert decided.epoch(EPOCH_ID).promotion_decisions_served == 4


def test_the_retired_flag_is_coerced_from_sqlites_integers(
    seeded_database,
) -> None:
    # The DBAPI affinity trap this workspace states for its boolean
    # columns: SQLite hands ``retired`` back as ``0`` and ``1``, and the
    # record answers a real ``bool`` — so feature 296's terminal state is
    # a question about a flag, not about which of two equal spellings the
    # row happens to carry.  The retired row is written raw, standing in
    # for the exhaustion machinery's own write of the flag.
    connection = sqlite3.connect(
        Path(seeded_database.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {EPOCH_LEDGER_TABLE} "
                f"({EPOCH_ID_COLUMN}, {SEALED_AT_COLUMN}, {RETIRED_COLUMN}) "
                "VALUES (?, ?, 1)",
                (OTHER_EPOCH, SEALED_AT.isoformat()),
            )
    finally:
        connection.close()
    charges = EpochCharges(seeded_database.database_url)
    retired_epoch = charges.epoch(OTHER_EPOCH)
    fresh_epoch = charges.epoch(EPOCH_ID)
    assert retired_epoch.retired is True
    assert isinstance(retired_epoch.retired, bool)
    assert fresh_epoch.retired is False
    assert isinstance(fresh_epoch.retired, bool)


def test_a_hand_edit_below_the_tables_meaning_is_refused_on_read(
    decided,
) -> None:
    # SQLite's columns are dynamically typed, so a raw write from another
    # tool can land anything here.  A read that swallowed a corrupt row
    # would certify a count nobody derived, so the read validates — in
    # this feature's vocabulary, naming the epoch it came off, and with
    # one code word rather than two.
    connection = sqlite3.connect(
        Path(decided.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} "
                f"SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ? "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                ("many", EPOCH_ID),
            )
    finally:
        connection.close()
    with pytest.raises(EpochChargeError) as raised:
        decided.epoch(EPOCH_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert EPOCH_ID in message
    assert message.count(EPOCH_CHARGE_ERROR_CODE) == 1


def test_a_bool_where_a_count_belongs_is_refused() -> None:
    # ``True`` is ``1`` in Python, and a flag where a served count belongs
    # would silently answer one decision nobody recorded — refused at the
    # record, which is where a hand-edited row reaches.
    with pytest.raises(EpochChargeError):
        ServingEpoch(
            epoch_id=EPOCH_ID,
            sealed_at=SEALED_AT,
            promotion_decisions_served=True,
            retired=False,
        )
    with pytest.raises(EpochChargeError):
        ServingEpoch(
            epoch_id=EPOCH_ID,
            sealed_at=SEALED_AT,
            promotion_decisions_served=-1,
            retired=False,
        )


# -- The derivation --------------------------------------------------------------------


class _StandIn:
    """A duck-typed stand-in for a registry row — the reader's contract.

    :func:`decisions_served` reads ``epoch_id`` and ``open`` and nothing
    else, so a caller may count anything shaped like a decision — this
    suite's stand-ins, or the composed listing, identically.
    """

    __slots__ = ("epoch_id", "open")

    def __init__(self, epoch_id: str, open_: bool) -> None:
        self.epoch_id = epoch_id
        self.open = open_


def test_decisions_served_counts_the_closed_rows_for_one_epoch_alone() -> None:
    # The pure half of the pair: two closed rows against the epoch, one
    # open row against it, and one closed row against another epoch — the
    # answer is two, because an open row is a pre-registration and another
    # epoch's spend is not this epoch's.
    records = (
        _StandIn(EPOCH_ID, False),
        _StandIn(EPOCH_ID, True),
        _StandIn(OTHER_EPOCH, False),
        _StandIn(EPOCH_ID, False),
    )
    assert decisions_served(records, EPOCH_ID) == 2
    assert decisions_served(records, OTHER_EPOCH) == 1
    assert decisions_served((), EPOCH_ID) == 0


def test_decisions_served_agrees_with_the_persisted_count(decided) -> None:
    # The derivation and the write are one fact: over the real listing,
    # through the store's own seam, the pure function's answer is the
    # figure the charge landed — asserted against the table's row, so the
    # agreement is with the database and not with the store's arithmetic.
    counted = decisions_served(
        decided.decisions.decisions(), EPOCH_ID
    )
    epoch, _ = decided.charge(NODE_ID)
    assert counted == 1 == epoch.promotion_decisions_served


def test_decisions_served_refuses_a_name_that_states_nothing() -> None:
    # The one value this function's caller supplies is the epoch's name,
    # and it is validated — a blank would silently count nothing and
    # answer zero, which is a cleaner-looking epoch than the ask deserved.
    with pytest.raises(EpochChargeError) as raised:
        decisions_served((), "   ")
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


# -- The refusals: the ask and the absence -----------------------------------------------


def test_a_malformed_node_is_refused(tmp_path: Path) -> None:
    # The node is an identity, and a charge that cannot be joined to its
    # booking is a count no later reader can act on.  Refused without a
    # database, because the ask is malformed whatever the ledger holds —
    # and nothing is created, which is the sharper half.
    store = EpochCharges(f"sqlite:///{tmp_path / 'never-opened.db'}")
    with pytest.raises(EpochChargeError) as raised:
        store.charge("not-a-uuid")
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)
    assert not (tmp_path / "never-opened.db").exists()


def test_a_node_with_no_pre_registration_is_refused_by_name(
    registered,
) -> None:
    # The precondition ``depends_on="293"`` (and, before it, ``291``)
    # makes load-bearing: a charge bills the epoch a *decided*
    # promotion's row booked, so the row has to exist before there is
    # anything to bill.  Refused by probe rather than left to the engine,
    # because the row's absence *is* the failure.
    other = str(uuid.uuid4())
    with pytest.raises(EpochChargeError) as raised:
        registered.charge(other)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert PROMOTION_REGISTRY_TABLE in message
    assert other in message
    assert "Pre-register" in message


def test_an_open_row_is_refused_with_its_registration_facts(
    registered, raw_ledger_row
) -> None:
    # The case that makes ``depends_on="293"`` a gate rather than a
    # formality: the row exists but the deciding evaluation has not run,
    # so the epoch has served no decision for it — and billing one anyway
    # would retire clean epochs early on promotions that were never
    # decided.  The refusal names the row's own facts (the first stamp
    # and the criteria hash), and the ledger's count stays at zero.
    with pytest.raises(EpochChargeError) as raised:
        registered.charge(NODE_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert REGISTERED_AT.isoformat() in message
    assert EXPECTED_HASH in message
    assert raw_ledger_row()[PROMOTION_DECISIONS_SERVED_COLUMN] == 0


def test_a_booking_whose_ledger_row_is_gone_is_refused(
    decided, raw_ledger_row
) -> None:
    # Unreachable through this member's writers — the pre-registration
    # probes the ledger before it writes and every connection the member
    # opens enforces the foreign key — so the state is a hand that
    # reached past them.  Refused rather than repaired: the one repair
    # this store must not offer is minting a ``sealed_at``, and the
    # message says so.
    connection = sqlite3.connect(
        Path(decided.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"DELETE FROM {EPOCH_LEDGER_TABLE} "
                f"WHERE {EPOCH_ID_COLUMN} = ?",
                (EPOCH_ID,),
            )
    finally:
        connection.close()
    assert raw_ledger_row() is None
    with pytest.raises(EpochChargeError) as raised:
        decided.charge(NODE_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert EPOCH_ID in message
    assert NODE_ID in message
    assert "sealing" in message


def test_a_shrinking_derivation_is_refused_and_moves_nothing(
    seeded_database, raw_ledger_row
) -> None:
    # A decided row never reopens, so a derivation *below* the standing
    # figure can only mean closed rows were deleted past the member — and
    # persisting it would author exactly the state ``0110``'s docstring
    # dreads: feature 295's threshold reading a spent epoch as clean.  The
    # refusal names both figures and the ledger keeps the standing one.
    nodes = [NODE_ID, str(uuid.uuid4())]
    _add_parents(seeded_database, nodes=nodes[1:])
    for node in nodes:
        _register(seeded_database, node_id=node)
    for node in nodes:
        _decide(seeded_database, node)
    charges = EpochCharges(seeded_database.database_url)
    epoch, _ = charges.charge(NODE_ID)
    assert epoch.promotion_decisions_served == 2
    connection = sqlite3.connect(
        Path(charges.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"DELETE FROM {PROMOTION_REGISTRY_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (nodes[1],),
            )
    finally:
        connection.close()
    with pytest.raises(EpochChargeError) as raised:
        charges.charge(NODE_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert "1" in message
    assert "2" in message
    assert raw_ledger_row()[PROMOTION_DECISIONS_SERVED_COLUMN] == 2


def test_a_store_pointed_at_nothing_is_refused() -> None:
    # A URL that names no database names no place a count could be
    # persisted, and a store that accepted one would fail identically on
    # every charge — the wrong place for a deployment to discover a wiring
    # fault.
    with pytest.raises(EpochChargeError) as raised:
        EpochCharges("   ")
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


def test_a_url_this_member_cannot_speak_is_refused_in_this_features_words() -> None:
    # The translation at the seam: ``promotion.pre_register``'s URL
    # translator raises its own store vocabulary, and a caller whose
    # single ``except EpochChargeError`` guards its epoch-governance path
    # must not be defeated by a refusal phrased for a different act.  The
    # class is translated and the sibling's message carried through, so
    # nothing an operator needs is lost.
    store = EpochCharges("postgresql://host/ledger")
    with pytest.raises(EpochChargeError) as raised:
        store.charge(NODE_ID)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert "postgresql" in message


# -- The vocabulary -----------------------------------------------------------------------


def test_every_refusal_is_one_gathered_class() -> None:
    # The gathering is the design: this feature's caller is a *gate*, whose
    # one failure mode is silence, so a single ``except EpochChargeError``
    # has to catch every face — a malformed ask, an unreachable address,
    # an absent booking, a missing ledger row, a shrinking count, a failed
    # write.  This test is where a later feature that split them would be
    # caught, because the caller's guard would develop a hole.
    from promotion import epoch as module

    assert issubclass(EpochChargeError, PromotionError)
    assert not issubclass(EpochChargeError, PromotionStoreError)
    code = code_of(module)
    assert "raise PromotionError(" not in code
    assert "raise PromotionStoreError(" not in code


def test_the_charge_class_is_not_the_decision_class() -> None:
    # The closest sibling and the one the split is for: the decision's
    # class reports *a stamp did not land* in ``promotion_registry``, this
    # one *a count did not land* in ``epoch_ledger`` — two writes to two
    # tables, and collapsing the classes would make the two
    # indistinguishable exactly where telling them apart sends an
    # operator to the right column.
    from promotion import PromotionDecisionError

    assert EpochChargeError.__bases__ == (PromotionError,)
    assert not issubclass(EpochChargeError, PromotionDecisionError)
    assert not issubclass(PromotionDecisionError, EpochChargeError)


def test_the_code_word_opens_every_refusal_the_store_raises(decided) -> None:
    # An operator greps one word for *an epoch served a decision and the
    # count did not land*.  Driven through the real paths rather than
    # asserted about the constant, and asserted as a *prefix* so a refusal
    # that merely mentioned the word in passing could not pass.
    for call in (
        lambda: decided.charge("not-a-uuid"),
        lambda: decided.charge(str(uuid.uuid4())),
        lambda: decided.epoch("   "),
        lambda: EpochCharges("  "),
    ):
        with pytest.raises(EpochChargeError) as raised:
            call()
        assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


def test_the_code_word_is_not_the_decisions_own() -> None:
    # Two acts, two words: the decision's names *a stamp did not land* and
    # this one names *a count did not land*, and an operator who lands on
    # the wrong one would be debugging the wrong write to the wrong
    # table.  The words agree on their domain prefix and differ where the
    # acts do.
    assert EPOCH_CHARGE_ERROR_CODE != PROMOTION_DECISION_ERROR_CODE
    assert EPOCH_CHARGE_ERROR_CODE == "epoch_charge_unpersisted"


# -- The schema this feature's act needs ------------------------------------------------------


def test_the_charge_order_is_one_owner_and_not_a_widening() -> None:
    # The rule ``promotion.schema`` states — *the set is the tables this
    # act's own statements name* — pinned from this feature's side: the
    # read and the one-column update name ``epoch_ledger`` and nothing
    # else, so the order is one pair where the insert's is three.
    # Restated as data here rather than imported, so a widening of either
    # constant fails this test rather than agreeing with the member by
    # construction.
    assert CHARGE_MIGRATION_ORDER == (
        (EPOCH_LEDGER_TABLE, "0110_epoch_ledger"),
    )
    assert len(CHARGE_MIGRATION_ORDER) < len(MIGRATION_ORDER)
    assert CHARGE_MIGRATION_ORDER != MIGRATION_ORDER
    assert CHARGE_MIGRATION_ORDER != DECISION_MIGRATION_ORDER


def test_the_bootstrap_authors_no_ddl_and_runs_the_owner_whole() -> None:
    # Not "agrees with" the owning migration — *is* it, statement for
    # statement: this is the property that makes drift impossible rather
    # than merely unlikely.  Asserted here for the charge's own
    # statements, with the migration loaded by path as its runner loads
    # it.
    from conftest import _load_migration
    from promotion.schema import _charge_statements

    owner = _load_migration("0110_epoch_ledger")
    assert list(_charge_statements("sqlite")) == list(
        owner.statements("sqlite")
    )


def test_a_fresh_database_gets_the_ledger_and_neither_the_registry_nor_its_parents(
    charges,
) -> None:
    # The one-owner claim from the data side: the charge store's connect
    # leaves a database holding the ledger and creating neither the
    # registry (whose rows the act counts *through feature 293's seam*) nor
    # the node tree — tables no statement of this act names.  The habit
    # :mod:`promotion.schema` exists to keep distinguishable from a
    # dependency, asserted as an absence rather than argued as a
    # preference.
    assert charges.epoch(EPOCH_ID) is None
    connection = charges._connect()
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


def test_a_charge_lands_on_a_database_the_chain_migrated(
    migrated_database,
) -> None:
    # The convergence the other bootstraps reach, from this feature's side
    # of it: a deployment where the versioned tree got there first is
    # served by the same act — the store's bootstrap is ``IF NOT EXISTS``
    # over the owner's own statements, so there is one schema and both
    # creators run it.
    from promotion import PreRegistrations

    parents = PreRegistrations(migrated_database)
    _add_parents(parents, nodes=[NODE_ID], epochs=[EPOCH_ID])
    _register(parents)
    _decide(parents)
    charges = EpochCharges(migrated_database)
    epoch, advanced = charges.charge(NODE_ID)
    assert advanced is True
    assert epoch.promotion_decisions_served == 1


def test_bootstrapping_twice_changes_nothing(charges) -> None:
    # Idempotent by construction, asserted rather than assumed — the store
    # calls the bootstrap on every connect, so a bootstrap that re-created
    # anything would drop a populated ledger on the second write.
    def _shape(client: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (name, (sql or "").strip())
            for name, sql in client.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
            )
        }

    with charges._connect() as first_connection:
        first = _shape(first_connection)
    with charges._connect() as second_connection:
        second = _shape(second_connection)
    assert first == second


# -- The module-level spellings -----------------------------------------------------------------


def test_charge_epoch_resolves_the_url_it_is_handed(decided) -> None:
    # The feature's sentence as one call, for the caller that wants the
    # act without holding a store — the epoch-governance path's line after
    # feature 293's stamp has landed.
    epoch, advanced = member.charge_epoch(
        NODE_ID, database_url=decided.database_url
    )
    assert advanced is True
    assert epoch.promotion_decisions_served == 1


def test_epoch_charge_resolves_the_url_it_is_handed(decided) -> None:
    # The module-level read, so a caller that charges through one spelling
    # and reads through the other is reading the row it advanced.
    member.charge_epoch(NODE_ID, database_url=decided.database_url)
    read = epoch_charge(EPOCH_ID, database_url=decided.database_url)
    assert read is not None
    assert read.promotion_decisions_served == 1
    assert epoch_charge(OTHER_EPOCH, database_url=decided.database_url) is None


def test_the_module_level_spellings_resolve_the_ambient_variable(
    monkeypatch, decided
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace
    # reads, so a deployment points every member at one database or at
    # none.
    monkeypatch.setenv(DATABASE_URL_ENV, decided.database_url)
    epoch, advanced = charge_epoch(NODE_ID)
    assert advanced is True
    assert epoch_charge(EPOCH_ID) == epoch


def test_a_deployment_naming_no_database_is_refused_by_name(
    monkeypatch,
) -> None:
    # The silence is the dangerous failure here and not the refusal: a
    # count that quietly went unpersisted leaves the epoch reading
    # cleaner than it is — the state §13 item 4's ledger exists to make
    # impossible — so a store resolved from nothing is refused by name.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(EpochChargeError) as raised:
        charge_epoch(NODE_ID)
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)
    with pytest.raises(EpochChargeError) as raised:
        epoch_charge(EPOCH_ID)
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


def test_resolve_answers_none_without_a_database(monkeypatch) -> None:
    # Absent is not an error: it is a deployment without a relational
    # store, and the caller that must charge an epoch is the caller that
    # must not find itself in it.  The *refusal* belongs to the caller,
    # which the module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert EpochCharges.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert EpochCharges.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere.db")
    assert isinstance(EpochCharges.resolve(), EpochCharges)


# -- The member's surface, the seat, and the spec -------------------------------------------------


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole surface; a caller charging an epoch
    # should not have to reach past ``promotion`` into a submodule to make
    # the act or read the row.
    assert member.charge_epoch is charge_epoch
    assert member.epoch_charge is epoch_charge
    assert member.decisions_served is decisions_served
    assert member.EpochCharges is EpochCharges
    assert member.ServingEpoch is ServingEpoch
    assert member.EpochChargeError is EpochChargeError


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 294 adds no component: a builder takes no arguments and is
    # built on every ``create_app()`` call, while a count is evidence the
    # factory does not hold — a decision has to have been recorded
    # somewhere else first.  So the member's one registered contribution
    # stands, and this assertion is where a second ``@register`` would be
    # noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_seat_is_untouched_by_this_feature() -> None:
    # The seat still answers one question, and it deliberately does not
    # re-export the charge vocabulary: a caller who has the store reaches
    # ``charge`` on it, and a second spelling there would be a second
    # thing to keep in sync.
    from app.modules import promotion as seat

    assert set(seat.__all__) == {"COMPONENT_NAME", "promotion_registry_component"}
    assert not hasattr(seat, "EpochCharges")
    assert not hasattr(seat, "EpochChargeError")


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
        "System persists the running promotion decision count against the "
        "serving epoch in the epoch_ledger" in spec.read_text(encoding="utf-8")
    )
