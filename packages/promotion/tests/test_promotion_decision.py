"""The decision: §13 item 7's second stamp, persisted as the row's closing.

Feature 293's sentence — *"System persists each promotion decision into the
promotion_registry with its timestamp and criteria hash"* — and the file where
*persists* is the claim under test.  The row feature 291 opened is the whole
of the decision's record: this act adds one value to it (``decided_at``) and
touches none of the five the pre-registration wrote, so the decision is
persisted *with* its criteria hash in the strict sense that the row, read
back, carries both — the reading an auditor, feature 294's epoch charge and
feature 360's CI invariant all start from.

**The statement's shape is the boundary, and it is asserted as hard as the
behaviour.**  Feature 291's insert cannot name ``decided_at`` — a row is born
open by the *shape* of the statement — and this feature's update is the
mirror: its ``SET`` clause names ``decided_at`` and nothing else, so the hash,
the epoch, the node and the first stamp are values the closing write *cannot
touch*.  Each half of §13 item 7's ordering is enforced by the other
statement having no clause for it, and the tests here pin the mirror from
this side: the SET clause is parsed, not substring-matched, exactly as the
insert's test parses its column list.

**What this feature is not, asserted as hard as what it is.**  The verdict is
the deciding evaluation's; the mismatch refusal is feature 292's.  So the
first tests pin the boundary: this module never spells
``criteria_mismatch``, never takes a criteria hash or an epoch as an argument,
never reads a pool, a score, a coverage ledger or a campaign status.  A suite
that only tested the happy write would pass for a module that had quietly
re-implemented 292's comparison or 294's charge.

**The ordering refusal is the interesting one.**  A decision stamped before
the criteria were fixed would write a row whose own two columns state the
reverse of §13 item 7 — the stored row that lies, which is worse than no row
at all, and precisely the finding feature 360's CI invariant refuses a merge
over.  This store refuses the write-side face of that finding, and the
equality boundary is pinned as its own test because it is the pair a reader
is most likely to get wrong in either direction.

**The idempotence is a behaviour, not an optimisation.**  A second
:meth:`PromotionDecisions.record_decision` for a node already closed returns
the standing row byte for byte, ``decided_at`` included — the decided instant
is *when the promotion was decided*, and a caller that walked the path again
did not move it.  Pinned on the raw row, so a store that re-stamped and
returned a cached value could not pass; and the once-only close is asserted
in the *engine* too (``AND decided_at IS NULL`` in the ``WHERE``), so a raw
second writer matches no row either.
"""

from __future__ import annotations

import datetime as dt
import inspect
import sqlite3
import uuid
from contextlib import closing
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
    CRITERIA_HASH_COLUMN,
    DATABASE_URL_ENV,
    DECIDED_AT_COLUMN,
    DECISION_MIGRATION_ORDER,
    EPOCH_ID_COLUMN,
    MIGRATION_ORDER,
    NODE_ID_COLUMN,
    PRE_REGISTERED_AT_COLUMN,
    PROMOTION_DECISION_ERROR_CODE,
    PROMOTION_REGISTRY_ERROR_CODE,
    PROMOTION_REGISTRY_TABLE,
    PreRegisterEndpoint,
    PreRegistrationRequest,
    PromotionCriteria,
    PromotionDecisionError,
    PromotionDecisions,
    PromotionError,
    PromotionRecord,
    PromotionStoreError,
    criteria_hash,
    promotion_decision,
    record_decision,
)

#: The two instants the suite registers and decides at, named so an ordering
#: assertion reads as a statement about *two stamps* rather than about two
#: literals buried in a call.  The decision is a day after the registration —
#: the honest shape — and the refused and equal cases derive from these.
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: The hash the suite's registrations record, computed once from the document
#: the conftest states — the value every "the hash is untouched" assertion
#: compares the *table's* copy against, so agreement is with the criteria
#: module rather than with this suite's own arithmetic.
EXPECTED_HASH = criteria_hash(PromotionCriteria(**DEFAULT_CRITERIA_DOCUMENT))

REPO_ROOT = Path(__file__).resolve().parents[3]


def _request(**overrides) -> PreRegistrationRequest:
    """A well-formed pre-registration, with the named fields overridden."""
    fields = {
        "node_id": NODE_ID,
        "epoch_id": EPOCH_ID,
        "criteria": dict(DEFAULT_CRITERIA_DOCUMENT),
    }
    fields.update(overrides)
    return PreRegistrationRequest(**fields)


@pytest.fixture
def decisions(database_url: str) -> PromotionDecisions:
    """The decision store, pointed at this test's own fresh database.

    No migration has run: the store's first act is what brings the registry to
    the file — one owner, ``0108`` — the contract the schema adapter states
    for this feature.  The tests that need a *row* to close ask for
    :func:`registered` instead.
    """
    return PromotionDecisions(database_url)


@pytest.fixture
def registered(seeded_database) -> PromotionDecisions:
    """A decision store over a database where the node *is* pre-registered.

    The semantic precondition feature 293 inherits from ``depends_on="291"``:
    there is no decision to persist without a pre-registration to close.  The
    registration goes through feature 291's own endpoint rather than a raw
    ``INSERT``, at a clock this suite names — so the two writers agree on the
    row by construction, and the ordering tests have a first stamp to sit
    against.  The tests that check the *absent registration* refusal
    deliberately do not ask for this fixture.
    """
    PreRegisterEndpoint(seeded_database).post(
        _request(), clock=lambda: REGISTERED_AT
    )
    return PromotionDecisions(seeded_database.database_url)


@pytest.fixture
def raw_row(database_url: str):
    """Read the node's ``promotion_registry`` row raw, so a test sees the table.

    A raw ``SELECT`` rather than a store verb, for the reason the registry's
    own suite gives: the point of most of these assertions is what the
    *table* holds — including ``decided_at``'s NULL, the before/after of the
    five untouched columns, and a hand edit the store must refuse — and a
    test that asked the store would be asking the code under test to confirm
    itself.
    """

    def _row() -> sqlite3.Row | None:
        connection = sqlite3.connect(Path(database_url.removeprefix("sqlite:///")))
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT id, {NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, "
                f"{CRITERIA_HASH_COLUMN}, {PRE_REGISTERED_AT_COLUMN}, "
                f"{DECIDED_AT_COLUMN} FROM {PROMOTION_REGISTRY_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (NODE_ID,),
            )
            try:
                return cursor.fetchone()
            finally:
                cursor.close()
        finally:
            connection.close()

    return _row


# -- The boundary: this feature records, it does not judge --------------------------


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares a
    # promotion against its recorded hash, and a decision store that spelled
    # it would be two features in one module — with the second half unchecked
    # by 292's own suite.  Docstrings are stripped by ``code_of`` so the
    # module may *say* it is not 292 without tripping the test that pins it.
    from promotion import decision as module

    code = code_of(module)
    assert "criteria_mismatch" not in code


def test_the_module_imports_no_other_workspace_member() -> None:
    # No member imports another — every shared spelling is restated or, as
    # here, *used* from a sibling inside the same member.  The boundary that
    # matters for this feature is narrower than the block's (it reads no
    # ledger at all), and the assertion keeps it that way.
    from promotion import decision as module

    code = code_of(module)
    for leaked in ("import regime", "from regime", "import discovery", "from ledger"):
        assert leaked not in code, leaked


def test_the_module_judges_nothing_and_reads_no_evidence() -> None:
    # The hardest boundary assertion: whether the promotion *stands* is the
    # deciding evaluation's verdict, and the inputs to that verdict — a pool,
    # a score, a coverage ledger, a campaign status — are tables this act
    # never opens.  A store that read one would have re-implemented half of
    # 292, 294 or 298 with none of their suites.
    from promotion import decision as module

    code = code_of(module)
    for evidence in ("regime_coverage", "campaign", "score", "ir_oos", "calibration"):
        assert evidence not in code, evidence


def test_the_act_takes_no_criteria_hash_and_no_epoch() -> None:
    # The two arguments a caller might offer that this act must not take.  A
    # ``criteria_hash`` parameter would be one of two things — the hash to
    # *judge* against (292's act) or the hash to *write* (a forgery: the
    # post-hoc edit §13 item 7 exists to make impossible) — and an ``epoch_id``
    # would let a caller spend a different holdout than the one the
    # pre-registration booked, the reuse §13 item 4 retires epochs to prevent.
    # Asserted on the signature, so adding either parameter fails here rather
    # than in a caller's keyword argument.
    parameters = set(inspect.signature(
        PromotionDecisions.record_decision
    ).parameters)
    assert "criteria_hash" not in parameters
    assert "criteria" not in parameters
    assert "epoch_id" not in parameters
    assert set(inspect.signature(record_decision).parameters) <= (
        parameters | {"database_url", "env"}
    )


def test_the_update_cannot_name_anything_but_decided_at() -> None:
    # §13 item 7's law, enforced by the shape of the statement rather than by
    # a check the writer remembers to make — the mirror of the insert's test.
    # The ``SET`` clause names exactly one column, so the criteria hash, the
    # epoch, the node and the first stamp are values this statement cannot
    # touch, and the two-timestamp record cannot be edited into a different
    # promotion by the one act that closes it.
    from promotion.decision import _UPDATE_SQL

    head, tail = _UPDATE_SQL.split("SET", 1)
    set_clause, where_clause = tail.split("WHERE", 1)
    assert PROMOTION_REGISTRY_TABLE in head
    assigned = [side.strip() for side in set_clause.split("=", 1)]
    assert assigned == [DECIDED_AT_COLUMN, "?"]
    # And the once-only close is in the *engine*: the WHERE carries the key
    # and the openness it closes, so a raw second writer — another process,
    # a hand with a connection — matches no row and moves no stamp.
    assert NODE_ID_COLUMN in where_clause
    assert f"{DECIDED_AT_COLUMN} IS NULL" in where_clause


# -- The write ----------------------------------------------------------------------


def test_a_decision_closes_the_row_with_its_timestamp(
    registered, raw_row
) -> None:
    # Feature 293 in one act: the row acquires ``decided_at``, and the answer
    # is the row the table holds — proved by the raw read, not by the
    # returned value agreeing with itself.
    _record, created = registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert created is True
    row = raw_row()
    assert row is not None
    assert row[DECIDED_AT_COLUMN] == DECIDED_AT.isoformat()


def test_the_answer_carries_the_timestamp_and_the_criteria_hash(
    registered,
) -> None:
    # The sentence's two nouns, read off the row rather than assembled from
    # the arguments: the persisted decision *is* the closed record, and its
    # criteria hash is the one feature 291 recorded — not a value this call
    # was handed, because the act takes none.
    record, created = registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert created is True
    assert record.decided_at == DECIDED_AT
    assert record.criteria_hash == EXPECTED_HASH
    assert record.open is False


def test_nothing_else_on_the_row_moves(registered, raw_row) -> None:
    # The five columns the pre-registration wrote are byte-identical after
    # the close — read *before* and *after* on the raw row, because the point
    # is what the table holds and a store-returned record could not witness
    # its own write's restraint.
    before = raw_row()
    registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    after = raw_row()
    for column in (
        "id",
        NODE_ID_COLUMN,
        EPOCH_ID_COLUMN,
        CRITERIA_HASH_COLUMN,
        PRE_REGISTERED_AT_COLUMN,
    ):
        assert after[column] == before[column], column
    assert before[DECIDED_AT_COLUMN] is None
    assert after[DECIDED_AT_COLUMN] == DECIDED_AT.isoformat()


# -- The idempotence ----------------------------------------------------------------


def test_a_re_decision_returns_the_standing_row_and_moves_nothing(
    registered, raw_row
) -> None:
    # The decided instant is when the promotion *was* decided, so a caller
    # that recorded again did not move it — the stance a retried
    # pre-registration takes toward ``pre_registered_at``.  Asserted on the
    # raw row, so a store that re-stamped and returned a cached value could
    # not pass.
    first, created = registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert created is True
    stamped = raw_row()[DECIDED_AT_COLUMN]
    again, created_again = registered.record_decision(
        NODE_ID, clock=lambda: dt.datetime(2026, 9, 9, tzinfo=dt.UTC)
    )
    assert created_again is False
    assert again == first
    assert raw_row()[DECIDED_AT_COLUMN] == stamped


def test_the_once_only_close_is_in_the_engine_not_only_the_flow(
    registered, raw_row
) -> None:
    # ``AND decided_at IS NULL`` in the WHERE, driven from the data side: a
    # raw second writer — this test's own connection, standing in for another
    # process racing this one — must match no row, so the stamp the store
    # placed is the one the table keeps whoever runs next.
    registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    stamped = raw_row()[DECIDED_AT_COLUMN]
    connection = sqlite3.connect(
        Path(registered.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            cursor = connection.execute(
                f"UPDATE {PROMOTION_REGISTRY_TABLE} SET {DECIDED_AT_COLUMN} = ? "
                f"WHERE {NODE_ID_COLUMN} = ? AND {DECIDED_AT_COLUMN} IS NULL",
                ("2030-01-01T00:00:00+00:00", NODE_ID),
            )
            moved = cursor.rowcount
            cursor.close()
    finally:
        connection.close()
    assert moved == 0
    assert raw_row()[DECIDED_AT_COLUMN] == stamped


# -- The reads ----------------------------------------------------------------------


def test_decision_answers_the_open_row_before_the_act(registered) -> None:
    # The pair this store must keep apart: a promotion whose deciding
    # evaluation has not been recorded, and one that has.  The open row is
    # *returned* — with its hash, its epoch and its first stamp — rather than
    # collapsed into the absence, because "criteria are fixed and the
    # evaluation is pending" is a fact §13 item 7's readers ask for by name.
    standing = registered.decision(NODE_ID)
    assert standing is not None
    assert standing.open is True
    assert standing.decided_at is None
    assert standing.criteria_hash == EXPECTED_HASH


def test_decision_answers_none_for_a_node_with_no_row(registered) -> None:
    # ``None`` is *no promotion to ask about* — deliberately not a record,
    # which would report an undated decision about a hypothesis nobody
    # pre-registered.  A store that answered a zeroed record would make every
    # downstream ``if record:`` branch wrong.
    other = str(uuid.uuid4())
    assert registered.decision(other) is None
    assert not isinstance(registered.decision(other), PromotionRecord)


def test_decisions_enumerates_every_closed_row_and_no_open_one(
    seeded_database,
) -> None:
    # The *each* of the feature's sentence made enumerable: one closed row per
    # promotion, carrying its deciding stamp and its criteria hash — the
    # listing feature 294's epoch charge reads before it counts.  An open row
    # is deliberately absent: it is a pre-registration, not a decision.
    store = PromotionDecisions(seeded_database.database_url)
    nodes = sorted(str(uuid.uuid4()) for _ in range(3))
    connection = seeded_database._connect()
    try:
        with connection:
            for node in nodes:
                connection.execute(
                    "INSERT INTO node (id, campaign_id, theme_root, depth) "
                    "VALUES (?, ?, ?, ?)",
                    (node, str(uuid.uuid4()), "macro", 1),
                )
    finally:
        connection.close()
    for node in nodes:
        PreRegisterEndpoint(seeded_database).post(
            _request(node_id=node), clock=lambda: REGISTERED_AT
        )
    for node in nodes[:2]:
        store.record_decision(node, clock=lambda: DECIDED_AT)
    listed = store.decisions()
    assert isinstance(listed, tuple)
    assert [record.node_id for record in listed] == nodes[:2]
    assert all(record.decided_at == DECIDED_AT for record in listed)
    assert all(record.criteria_hash == EXPECTED_HASH for record in listed)


def test_the_listing_is_empty_rather_than_absent_on_a_fresh_store(
    decisions,
) -> None:
    # An empty listing is a real answer about a real database — no promotion
    # has been decided here — and it is deliberately not an error.  The
    # store's first *read* brings the registry up, so the answer is ``()``
    # rather than a refusal.
    assert decisions.decisions() == ()


def test_the_store_holds_no_cache_of_the_rows_it_closed(registered) -> None:
    # The row is the only record of the decision, so it is the only thing an
    # answer is drawn from.  A memo of decided nodes would make *was this
    # promotion decided, and when?* a question about this process's history —
    # and the readers asking it (294's charge, 300's window, 360's invariant)
    # all run somewhere else entirely.  Driven by writing behind the store's
    # back and reading it back.
    registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    connection = sqlite3.connect(
        Path(registered.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"DELETE FROM {PROMOTION_REGISTRY_TABLE} WHERE {NODE_ID_COLUMN} = ?",
                (NODE_ID,),
            )
    finally:
        connection.close()
    assert registered.decision(NODE_ID) is None
    assert registered.decisions() == ()


def test_a_second_store_over_one_database_sees_the_same_row(registered) -> None:
    # The other face of the same fact: the record is the table's, so two
    # stores over one database — two processes, in production — agree without
    # sharing anything but the URL.
    registered.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    other = PromotionDecisions(registered.database_url)
    read = other.decision(NODE_ID)
    assert read == registered.decision(NODE_ID)
    assert read is not None and read.decided_at == DECIDED_AT


def test_a_hand_edit_below_the_tables_meaning_is_refused_on_read(
    registered,
) -> None:
    # SQLite's columns are dynamically typed, so a raw write from another tool
    # can land anything here.  A read that swallowed a corrupt row would
    # report a decision nobody recorded, so the read validates — in this
    # feature's vocabulary, naming the node it came off.
    connection = sqlite3.connect(
        Path(registered.database_url.removeprefix("sqlite:///"))
    )
    try:
        with connection:
            connection.execute(
                f"UPDATE {PROMOTION_REGISTRY_TABLE} SET {CRITERIA_HASH_COLUMN} = ? "
                f"WHERE {NODE_ID_COLUMN} = ?",
                ("not-a-hash", NODE_ID),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionDecisionError) as raised:
        registered.decision(NODE_ID)
    message = str(raised.value)
    assert PROMOTION_DECISION_ERROR_CODE in message
    assert NODE_ID in message
    # One refusal carries one code word, not two — the greppable marker is
    # for the *act*, and a doubled one would read as two unrecorded decisions.
    assert message.count(PROMOTION_DECISION_ERROR_CODE) == 1


def test_a_node_holding_two_rows_is_refused_rather_than_resolved(
    seeded_database,
) -> None:
    # A node holding two registry rows holds two answers to *what was this
    # promotion decided against?* and closing "the" row would be a choice
    # between them.  Nothing this member writes can produce the state —
    # 291's insert makes one row per node — so a second row is a hand that
    # reached past it, and the message says so.
    PreRegisterEndpoint(seeded_database).post(_request())
    other = PromotionDecisions(seeded_database.database_url)
    connection = seeded_database._connect()
    try:
        with connection:
            connection.execute(
                f"INSERT INTO {PROMOTION_REGISTRY_TABLE} "
                f"({NODE_ID_COLUMN}, {EPOCH_ID_COLUMN}, "
                f"{CRITERIA_HASH_COLUMN}, {PRE_REGISTERED_AT_COLUMN}) "
                "VALUES (?, ?, ?, ?)",
                (NODE_ID, EPOCH_ID, "0" * 64, REGISTERED_AT.isoformat()),
            )
    finally:
        connection.close()
    with pytest.raises(PromotionDecisionError) as raised:
        other.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)
    assert "2" in str(raised.value)


# -- The refusals: the ask ----------------------------------------------------------


def test_a_malformed_node_is_refused(tmp_path: Path) -> None:
    # The node is an identity, and a decision that cannot be joined to its
    # hypothesis is a row no later reader can act on.  Refused without a
    # store, because the ask is malformed whatever the database holds —
    # pointed at a path under ``tmp_path`` so the refusal is what is observed
    # and no file is left in the repository either way.
    store = PromotionDecisions(f"sqlite:///{tmp_path / 'never-opened.db'}")
    with pytest.raises(PromotionDecisionError) as raised:
        store.record_decision("not-a-uuid")
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)
    # And nothing was created, which is the sharper half: the ask face is
    # refusable without a database at all.
    assert not (tmp_path / "never-opened.db").exists()


def test_a_naive_stamp_is_refused(registered) -> None:
    # The decision is an instant, and a naive one has no offset to order
    # against the criteria's — the same refusal feature 291's stamp makes, in
    # this feature's class because the caller's ``except`` guard is the same
    # guard.  The inner refusal is 291's own message, carried through the
    # seam; only the frame is this feature's.
    with pytest.raises(PromotionDecisionError) as raised:
        registered.record_decision(
            NODE_ID, decided_at=dt.datetime(2026, 3, 2)  # noqa: DTZ001
        )
    message = str(raised.value)
    assert PROMOTION_DECISION_ERROR_CODE in message
    assert "timezone-aware" in message


def test_an_unparseable_stamp_is_refused(registered) -> None:
    # Text that does not parse is not an instant the ordering can range —
    # the second half of the validator's calendar, driven through text
    # because the table stores text and a row read back revalidates as one.
    with pytest.raises(PromotionDecisionError) as raised:
        registered.record_decision(NODE_ID, decided_at="not-a-stamp")
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)


# -- The refusals: the absence ------------------------------------------------------


def test_a_node_with_no_pre_registration_is_refused_by_name(registered) -> None:
    # The precondition ``depends_on="291"`` makes load-bearing: §13 item 7
    # fixes the criteria *before* the evaluation, so the row this act closes
    # has to exist before the stamp does.  Refused by probe rather than left
    # to the engine, because the row's absence *is* the failure and SQLite's
    # errors would name neither the node nor the repair.
    other = str(uuid.uuid4())
    with pytest.raises(PromotionDecisionError) as raised:
        registered.record_decision(other, clock=lambda: DECIDED_AT)
    message = str(raised.value)
    assert PROMOTION_DECISION_ERROR_CODE in message
    assert PROMOTION_REGISTRY_TABLE in message
    assert other in message
    assert "Pre-register" in message


def test_the_absent_registration_is_refused_on_a_bare_store(decisions) -> None:
    # The same refusal one level down, on a database the decision store
    # itself brought up — no parent rows, no registrations, just the registry
    # the one-owner bootstrap creates.  The refusal is the *semantic* one
    # (no row for this node), not a structural complaint about the tree.
    with pytest.raises(PromotionDecisionError) as raised:
        decisions.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert PROMOTION_REGISTRY_TABLE in str(raised.value)


# -- The refusals: the ordering -----------------------------------------------------


def test_a_decision_stamped_before_the_criteria_is_refused(
    registered, raw_row
) -> None:
    # §13 item 7's law, checked at the write: a pair with ``decided_at``
    # strictly earlier would write a row whose own two columns state that the
    # promotion was decided before its criteria existed — the stored row that
    # lies, and precisely the finding feature 360's CI invariant refuses a
    # merge over, authored here rather than caught there.  The row stays
    # open, so the refused call leaves the database exactly as it was.
    with pytest.raises(PromotionDecisionError) as raised:
        registered.record_decision(
            NODE_ID,
            decided_at=REGISTERED_AT - dt.timedelta(days=1),
        )
    message = str(raised.value)
    assert PROMOTION_DECISION_ERROR_CODE in message
    assert "§13 item 7" in message
    assert raw_row()[DECIDED_AT_COLUMN] is None


def test_a_decision_stamped_at_the_same_instant_as_the_criteria_closes_the_row(
    registered, raw_row
) -> None:
    # The boundary, and the pair a reader is most likely to get wrong: the
    # row holds the instant the decision was *recorded*, not the span the
    # evaluation ran over, and a stamp equal to the criteria's is neither
    # before them nor a finding 360 names.  Feature 360's own line is
    # *recorded after* — this store refuses the strict reverse and honours
    # the equality, so the two boundaries are complements.
    record, created = registered.record_decision(
        NODE_ID, decided_at=REGISTERED_AT
    )
    assert created is True
    assert record.decided_at == REGISTERED_AT
    assert raw_row()[DECIDED_AT_COLUMN] == REGISTERED_AT.isoformat()


# -- The refusals: the address and the write ----------------------------------------


def test_a_store_pointed_at_nothing_is_refused() -> None:
    # A URL that names no database names no place a decision could be
    # recorded, and a store that accepted one would fail identically on every
    # decision — the wrong place for a deployment to discover a wiring fault.
    with pytest.raises(PromotionDecisionError) as raised:
        PromotionDecisions("   ")
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)


def test_a_url_this_member_cannot_speak_is_refused_in_this_features_words() -> None:
    # The translation at the seam: ``promotion.pre_register``'s URL translator
    # raises its own store vocabulary, and a caller whose single
    # ``except PromotionDecisionError`` guards its promotion path must not be
    # defeated by a refusal phrased for a different act.  The class is
    # translated at the seam and the sibling's message carried through, so
    # nothing an operator needs is lost.
    store = PromotionDecisions("postgresql://host/registry")
    with pytest.raises(PromotionDecisionError) as raised:
        store.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    message = str(raised.value)
    assert PROMOTION_DECISION_ERROR_CODE in message
    assert "postgresql" in message


# -- The vocabulary -----------------------------------------------------------------


def test_every_refusal_is_one_gathered_class() -> None:
    # The gathering is the design: this feature's caller is a *gate*, whose
    # one failure mode is silence, so a single ``except
    # PromotionDecisionError`` has to catch every face — a malformed ask, an
    # unreachable address, an absent registration, a reversed ordering, a
    # failed write.  This test is where a later feature that split them would
    # be caught, because the caller's guard would develop a hole.
    from promotion import decision as module

    assert issubclass(PromotionDecisionError, PromotionError)
    assert not issubclass(PromotionDecisionError, PromotionStoreError)
    # Every refusal in the module's code raises this one class — checked by
    # the absence of the siblings' names from the code, the classes a split
    # would reach for.
    code = code_of(module)
    assert "raise PromotionError(" not in code
    assert "raise PromotionStoreError(" not in code


def test_the_decision_class_is_not_the_registry_class() -> None:
    # A caller that gathered the two would read *the registry could not be
    # written to* where the truth is *a decision did not land* — two acts
    # over one table, two writes an operator has to tell apart by grep, and
    # collapsing the classes would make the member's two halves of §13
    # item 7's record indistinguishable exactly where distinguishing them is
    # the point.
    assert not issubclass(PromotionDecisionError, PromotionStoreError)
    assert not issubclass(PromotionStoreError, PromotionDecisionError)
    assert PromotionDecisionError.__bases__ == (PromotionError,)


def test_the_code_word_opens_every_refusal_the_store_raises(registered) -> None:
    # An operator greps one word for *a promotion was decided and the
    # decision was not recorded*.  Driven through the real paths rather than
    # asserted about the constant, and asserted as a *prefix* so a refusal
    # that merely mentioned the word in passing could not pass.
    for call in (
        lambda: registered.record_decision("not-a-uuid"),
        lambda: registered.record_decision(
            NODE_ID, decided_at=dt.datetime(2026, 3, 2)  # noqa: DTZ001
        ),
        lambda: registered.record_decision(
            str(uuid.uuid4()), clock=lambda: DECIDED_AT
        ),
        lambda: PromotionDecisions("  "),
    ):
        with pytest.raises(PromotionDecisionError) as raised:
            call()
        assert str(raised.value).startswith(PROMOTION_DECISION_ERROR_CODE)


def test_the_code_word_is_not_the_registrys_own() -> None:
    # Two acts, two words: the registry's names *a pre-registration did not
    # land* and this one names *a decision did not land*, and an operator who
    # lands on the wrong one would be debugging the wrong write.  The words
    # agree on their prefix because they name one table's two writers, and
    # differ where the acts do.
    assert PROMOTION_DECISION_ERROR_CODE != PROMOTION_REGISTRY_ERROR_CODE
    assert PROMOTION_DECISION_ERROR_CODE == "promotion_decision_unrecorded"


# -- The schema this feature's act needs ---------------------------------------------


def test_the_decision_order_is_one_owner_and_not_a_widening() -> None:
    # The rule ``promotion.schema`` states — *the set is the tables this
    # act's own statements name* — pinned from this feature's side: the read
    # and the one-column update name ``promotion_registry`` and nothing else,
    # so the order is one pair where the insert's is three.  Restated as data
    # here rather than imported, so a widening of either constant fails this
    # test rather than agreeing with the member by construction.
    assert DECISION_MIGRATION_ORDER == (
        (PROMOTION_REGISTRY_TABLE, "0108_forward_and_universe_tables"),
    )
    assert len(DECISION_MIGRATION_ORDER) < len(MIGRATION_ORDER)
    assert DECISION_MIGRATION_ORDER != MIGRATION_ORDER


def test_the_bootstrap_authors_no_ddl_and_runs_the_owner_whole() -> None:
    # Not "agrees with" the owning migration — *is* it, tuple for tuple:
    # this is the property that makes drift impossible rather than merely
    # unlikely, and the member's schema suite pins the same claim for the
    # other two acts.  Asserted here for the decision's own statements, with
    # the migration loaded by path as its runner loads it.
    from conftest import _load_migration
    from promotion.schema import _decision_statements

    owner = _load_migration("0108_forward_and_universe_tables")
    assert list(_decision_statements("sqlite")) == list(
        owner.statements("sqlite")
    )
    from promotion import schema as schema_module

    assert "CREATE TABLE" not in code_of(schema_module)


def test_a_fresh_database_gets_the_registry_and_neither_parent(decisions) -> None:
    # The one-owner claim from the data side, and the SQLite fact that makes
    # it honest: the update sets a non-key column and resolves no foreign-key
    # parent, so the decision store's connect leaves a database holding the
    # registry (and ``0108``'s own five neighbours) but creating neither
    # ``node`` nor ``epoch_ledger`` — tables no statement of this act names.
    # The habit :mod:`promotion.schema` exists to keep distinguishable from a
    # dependency, asserted as an absence rather than argued as a preference.
    connection = decisions._connect()
    try:
        names = {
            name
            for (name,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()
    assert PROMOTION_REGISTRY_TABLE in names
    assert "node" not in names
    assert "epoch_ledger" not in names


def test_a_decision_lands_on_a_database_the_chain_migrated(
    migrated_database,
) -> None:
    # The convergence the other bootstraps reach, from this feature's side of
    # it: a deployment where the versioned tree got there first is served by
    # the same act — the store's bootstrap is ``IF NOT EXISTS`` over the
    # owner's own statements, so there is one schema and both creators run it.
    store = PromotionDecisions(migrated_database)
    with pytest.raises(PromotionDecisionError) as raised:
        store.record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    # No registration exists on this database, so the act refuses — which is
    # the proof the store *reached* the migrated registry rather than failing
    # to bring its own up.
    assert PROMOTION_REGISTRY_TABLE in str(raised.value)


def test_bootstrapping_twice_changes_nothing(decisions) -> None:
    # Idempotent by construction, asserted rather than assumed — the store
    # calls the bootstrap on every connect, so a bootstrap that re-created
    # anything would drop a populated database on the second write.
    def _shape(client: sqlite3.Connection) -> set[tuple[str, str]]:
        return {
            (name, (sql or "").strip())
            for name, sql in client.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
            )
        }

    with closing(decisions._connect()) as connection:
        first = _shape(connection)
    with closing(decisions._connect()) as connection:
        second = _shape(connection)
    assert first == second


# -- The module-level spellings ------------------------------------------------------


def test_record_decision_resolves_the_url_it_is_handed(registered) -> None:
    # The feature's sentence as one call, for the caller that wants the act
    # without holding a store — the promotion path's last line, after the
    # deciding evaluation has run and after 292's and 298's refusals have
    # had theirs.
    record, created = member.record_decision(
        NODE_ID, clock=lambda: DECIDED_AT, database_url=registered.database_url
    )
    assert created is True
    assert record.criteria_hash == EXPECTED_HASH
    assert record.decided_at == DECIDED_AT


def test_promotion_decision_resolves_the_url_it_is_handed(registered) -> None:
    # The module-level read, so a caller that records through one spelling
    # and reads through the other is reading the row it closed.
    member.record_decision(
        NODE_ID, clock=lambda: DECIDED_AT, database_url=registered.database_url
    )
    read = promotion_decision(NODE_ID, database_url=registered.database_url)
    assert read is not None
    assert read.decided_at == DECIDED_AT
    assert promotion_decision(
        str(uuid.uuid4()), database_url=registered.database_url
    ) is None


def test_the_module_level_spellings_resolve_the_ambient_variable(
    monkeypatch, registered
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace reads,
    # so a deployment points every member at one database or at none.
    monkeypatch.setenv(DATABASE_URL_ENV, registered.database_url)
    record, created = record_decision(NODE_ID, clock=lambda: DECIDED_AT)
    assert created is True
    assert promotion_decision(NODE_ID) == record


def test_a_deployment_naming_no_database_is_refused_by_name(monkeypatch) -> None:
    # The silence is the dangerous failure here and not the refusal: a
    # decision that quietly went unrecorded leaves an epoch never charged and
    # a forward window never opened, neither of which any later reader can
    # recover — the state §13 item 4's ledger exists to make impossible.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(PromotionDecisionError) as raised:
        record_decision(NODE_ID)
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)
    with pytest.raises(PromotionDecisionError) as raised:
        promotion_decision(NODE_ID)
    assert PROMOTION_DECISION_ERROR_CODE in str(raised.value)


def test_resolve_answers_none_without_a_database(monkeypatch) -> None:
    # Absent is not an error: it is a deployment without a relational store,
    # and the caller that must record a decision is the caller that must not
    # find itself in it.  The *refusal* belongs to the caller, which the
    # module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert PromotionDecisions.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert PromotionDecisions.resolve() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "sqlite:///somewhere.db")
    assert isinstance(PromotionDecisions.resolve(), PromotionDecisions)


# -- The member's surface and the spec -----------------------------------------


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole surface; a caller recording a decision
    # should not have to reach past ``promotion`` into a submodule to make
    # the act or read the row.
    assert member.record_decision is record_decision
    assert member.promotion_decision is promotion_decision
    assert member.PromotionDecisions is PromotionDecisions
    assert member.PromotionDecisionError is PromotionDecisionError


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 293 adds no component: a builder takes no arguments and is
    # built on every ``create_app()`` call, while a decision is evidence the
    # factory does not hold — the evaluation has run, somewhere else, and its
    # outcome is the caller's to bring.  So the member's one registered
    # contribution stands, and this assertion is where a second ``@register``
    # would be noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not have
    # to go looking, and so a re-scoped feature would fail a test rather than
    # quietly leaving the suite asserting something the spec no longer says.
    # The module's docstring quotes it too; this is the data-side copy.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System persists each promotion decision into the promotion_registry "
        "with its timestamp and criteria hash" in spec.read_text(encoding="utf-8")
    )
