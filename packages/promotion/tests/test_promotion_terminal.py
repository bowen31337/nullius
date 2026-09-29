"""The terminal verdict: §13 item 4's stop, judged over the whole ledger.

Feature 296's sentence — *"System blocks promotion when no clean sequestered
epoch remains, which returns a terminal state rather than reusing a retired
epoch."* — and the file where *the whole-table stop* is the claim under test.
The count on each ledger row is feature 294's, the ``retired`` flag is this
feature's own reader's, and the depleting remainder is feature 297's; this
feature's whole act is one comparison — every row against §13 item 4's own
number — performed on the rows the charge's own read answers with.  And the
refusal that comparison yields is not a failure anywhere else in the member:
everything landed, everything is readable, and the answer is *the system
stops*, which is why the class it raises is a new sibling rather than a face
of a write's or a read's.

**What this feature is not, asserted as hard as what it is.**  The verdict is
the deciding evaluation's; the retirement is this feature's flag, not this
gate's law; the remainder is 297's whole-table question.  So the first tests
pin the boundary: this module never spells 292's mismatch verdict, never
reads the ``retired`` or ``sealed_at`` column, never reads a pool, a score or
a coverage ledger, and spells no statement of its own at all — the rows arrive
through feature 294's ``epochs`` seam, so there is no second reading of one
table for the tests to catch.  A suite that only tested the happy answer would
pass for a module that had quietly re-implemented the flag check or invented
its own ``SELECT``.

**The verdict is not the conjunction of feature 295's per-epoch refusals, and
that is the test that catches the difference.**  When every epoch is spent the
verdict refuses with ``no_clean_epoch_remains`` and names the whole ledger;
when one epoch is spent and another is clean it does **not** refuse — it
answers that the system may continue (the clean epoch), leaving the per-epoch
refusal to feature 295's gate at the moment that spent epoch is selected.  A
suite that only tested "every epoch spent" would pass for a module that had
quietly become ``all(select(e))`` rather than its own whole-table judgment.

**The empty ledger is refused as a distinct terminal fact.**  No sequestered
epoch at all is not "zero spent, all clean": there is no epoch to spend, so
promotion has nothing to run on, and reading the absence as "all clean" would
let a deployment that never sequestered an epoch book a promotion against
nothing.

**``>=`` is the comparison, and the end-to-end path is what proves it.**  Book
and decide three promotions against each of two epochs, charge each — the
ledger holds three on each — and the verdict refuses, through the real acts of
features 291, 293 and 294 rather than a hand-written row.  A count *above*
three counts as spent on the same comparison.

**Nothing moves, on either side of the verdict.**  The count is 294's to
persist and the flag this feature's own reader's to set, so both a permitted
and a refused verdict leave the raw ledger byte-identical — asserted on the
table, not on the gate's own testimony.
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
    REPO_ROOT,
    code_of,
)
from promotion import (
    DATABASE_URL_ENV,
    EPOCH_CHARGE_ERROR_CODE,
    EPOCH_ID_COLUMN,
    EPOCH_LEDGER_TABLE,
    EPOCH_SELECTION_ERROR_CODE,
    NO_CLEAN_EPOCH_REMAINS_CODE,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    RETIRED_COLUMN,
    SEALED_AT_COLUMN,
    SEQUESTERED_EPOCH_BUDGET,
    EpochChargeError,
    EpochCharges,
    EpochSelectionError,
    PromotionBlockedError,
    PromotionDecisionError,
    PromotionError,
    PromotionStoreError,
    ServingEpoch,
    TerminalStates,
    block_when_no_clean_epoch_remains,
    blocks_when_no_clean_epoch_remains,
)

#: The three instants the suite works over — the sealing (the conftest's own
#: literal for the seeded row), the registration and the decision — named so
#: an assertion reads as a statement about stamps rather than about literals
#: buried in a call.
SEALED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: A second epoch name, so a verdict over two rows reads as a statement about
#: the whole ledger rather than about one.
OTHER_EPOCH = "epoch-2026-02"


def _request(node_id: str = NODE_ID, epoch_id: str = EPOCH_ID):
    """A well-formed pre-registration, with the named fields overridden."""
    return member.PreRegistrationRequest(
        node_id=node_id,
        epoch_id=epoch_id,
        criteria=dict(DEFAULT_CRITERIA_DOCUMENT),
    )


def _add_parents(store, *, nodes=(), epochs=()) -> None:
    """Insert the tree's parent rows through the pre-registration's connect.

    A node's row is the discovery loop's write and an epoch's row is the
    sealing process's, neither of which is this member's to invent — the same
    stance the conftest's ``seeded_database`` takes for its two.
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
    member.PreRegisterEndpoint(store).post(
        _request(node_id=node_id, epoch_id=epoch_id),
        clock=lambda: REGISTERED_AT,
    )


def _decide(store, node_id: str = NODE_ID) -> None:
    """Record one node's decision, at this suite's clock."""
    member.PromotionDecisions(store.database_url).record_decision(
        node_id, clock=lambda: DECIDED_AT
    )


def _write_served(database_url: str, served: object, epoch: str = EPOCH_ID) -> None:
    """Write one epoch's served count raw, standing in for another process.

    This test's own connection, not the store's — the shape the charge's own
    suite uses to prove it holds no cache, used here for the same purpose and
    for the count-past-budget refusal no writer can produce.
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
                (served, epoch),
            )
    finally:
        connection.close()


def _raw_ledger(database_url: str):
    """Read the whole ``epoch_ledger`` table raw, so a test sees the table.

    A raw ``SELECT`` rather than a store verb, for the reason the charge's
    suite gives: the point of most of these assertions is what the *table*
    holds — including the rows before and after a verdict, permitted or
    refused — and a test that asked the code under test would be asking it to
    confirm itself.
    """

    def _rows() -> list[sqlite3.Row]:
        connection = sqlite3.connect(
            Path(database_url.removeprefix("sqlite:///"))
        )
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT {EPOCH_ID_COLUMN}, {SEALED_AT_COLUMN}, "
                f"{PROMOTION_DECISIONS_SERVED_COLUMN}, {RETIRED_COLUMN} "
                f"FROM {EPOCH_LEDGER_TABLE} ORDER BY {EPOCH_ID_COLUMN}"
            )
            try:
                return cursor.fetchall()
            finally:
                cursor.close()
        finally:
            connection.close()

    return _rows


def _fresh(database_url: str):
    """A store over the named database, for seeding parents and rows."""
    return member.PreRegistrations(database_url)


# -- The boundary: this feature judges the whole ledger, and on nothing else ----------


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares a
    # promotion against its recorded hash, and a verdict that spelled it
    # would be two features in one module.  Docstrings are stripped by
    # ``code_of`` so the module may *say* it is not 292 without tripping the
    # test that pins it.
    from promotion import terminal as module

    assert "criteria_mismatch" not in code_of(module)


def test_the_verdict_reads_neither_the_flag_nor_the_sealing_instant() -> None:
    # The count is the whole of the law here: ``retired`` is this feature's
    # own reader's flag and ``sealed_at`` is the sealing process's fact, and
    # a verdict that read either would be judging the flag or re-deriving the
    # sequestration this verdict takes as given.  Pinned on the *attribute
    # access* rather than the bare word, because a refusal message may
    # legitimately quote §13 item 4's own "retired permanently" — what the
    # module must never do is read the fields.
    from promotion import terminal as module

    code = code_of(module)
    assert ".retired" not in code
    assert ".sealed_at" not in code
    assert "RETIRED_COLUMN" not in code
    assert "SEALED_AT_COLUMN" not in code


def test_the_verdict_reads_no_merit_and_no_evidence() -> None:
    # Whether the promotion *stands* is the deciding evaluation's verdict,
    # and the inputs to that verdict — a pool, a score, a coverage ledger, a
    # calibration status — are tables this act never opens.  A verdict that
    # read one would have re-implemented half of 292, 298 or 299 with none of
    # their suites.
    from promotion import terminal as module

    code = code_of(module)
    for evidence in ("regime_coverage", "campaign", "ir_oos", "score", "calibration"):
        assert evidence not in code, evidence


def test_the_verdict_reads_the_ledger_through_the_charges_own_seam() -> None:
    # The discipline :mod:`promotion.selection` states for its gate, pinned
    # for this verdict: the rows are read through feature 294's own store
    # (composed in ``__init__``), never through a second ``SELECT`` spelled
    # here — so the count this act judges and the counts the charge answered
    # with cannot be two readings of one table.
    from promotion import terminal as module

    code = code_of(module)
    assert f"FROM {EPOCH_LEDGER_TABLE}" not in code
    assert f"FROM {PROMOTION_REGISTRY_TABLE}" not in code
    assert "self._charges.epochs(" in code


def test_the_verdict_spells_no_statement_and_authors_no_ddl() -> None:
    # A verdict that writes nothing needs no connection, no bootstrap and no
    # statement — and :mod:`promotion.schema` gains no order because the set a
    # bootstrap runs is the set an act's own statements name and this act's
    # statements name nothing at all.  Every token here is pinned so a later
    # statement smuggled in fails this test rather than quietly widening the
    # member's DDL footprint.
    from promotion import terminal as module

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


def test_the_verdict_takes_no_clock_no_node_and_reads_the_rows() -> None:
    # The arguments a caller might offer that this act must not take.  A
    # ``clock`` would stamp something, and nothing here stamps: the count is
    # 294's and the flag this feature's own reader's.  A ``count`` would be a
    # figure the caller derived, and the count this verdict judges is a
    # function of the ledger rows or nothing.  A ``node_id`` would turn a gate
    # over the whole ledger into a judgment over one promotion — features
    # 292-293's territory.  The pure judgment takes only the rows and the
    # budget; the module-level spelling may add only the URL seam the member's
    # other spellings take.
    assert set(inspect.signature(blocks_when_no_clean_epoch_remains).parameters) == {
        "rows",
        "budget",
    }
    assert set(inspect.signature(block_when_no_clean_epoch_remains).parameters) == {
        "rows_or_url",
        "database_url",
        "env",
    }


def test_the_budget_is_the_prds_own_number_spelled_once() -> None:
    # §13 item 4's "3 promotion decisions", spelled in exactly one place: a
    # second spelling anywhere else in the member would be a second place the
    # budget lives, free to disagree with the one the gate compares against.
    # The charge's module is the nearest neighbour that could have carried it
    # — 0110's docstring says it deliberately does not — so that is where the
    # absence is pinned, and the terminal module's too.
    from promotion import epoch as charge_module
    from promotion import selection as selection_module
    from promotion import terminal as module

    assert SEQUESTERED_EPOCH_BUDGET == 3
    assert "SEQUESTERED_EPOCH_BUDGET = 3" in code_of(selection_module)
    assert "SEQUESTERED_EPOCH_BUDGET" not in code_of(charge_module)
    # The terminal module *uses* the budget, not restates it: the imported
    # name appears (it is the pure judgment's default), but the literal ``= 3``
    # definition does not — a second spelling would be a second place the
    # budget lives, free to disagree with the one the gate compares against.
    assert "SEQUESTERED_EPOCH_BUDGET = 3" not in code_of(module)


# -- The pure judgment ------------------------------------------------------------------


def _row(epoch: str, served: int) -> ServingEpoch:
    """A serving epoch standing in for one ledger row."""
    return ServingEpoch(
        epoch_id=epoch,
        sealed_at=SEALED_AT,
        promotion_decisions_served=served,
        retired=False,
    )


def test_all_clean_answers_the_count_of_clean_epochs_remaining() -> None:
    # The permissive half of the pair: when no epoch has served the budget,
    # the verdict answers that the system may continue, and the answer is the
    # count of clean epochs — the figure feature 297's depleting count reports
    # and this verdict agrees with, so a caller that wants to log or carry it
    # does not read the table a second time.
    assert (
        blocks_when_no_clean_epoch_remains([_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 0)])
        == 2
    )


def test_a_partially_spent_ledger_answers_the_clean_remainder() -> None:
    # The verdict is a question about the *system's* continuation, not about
    # any one epoch's spend: one epoch spent and one clean is not the terminal
    # state — the system may continue on the clean epoch, and the answer is
    # the one clean epoch remaining.  This is the difference between a
    # whole-table verdict and the conjunction of per-epoch refusals.
    assert (
        blocks_when_no_clean_epoch_remains([_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 0)])
        == 1
    )
    # Three epochs, none spent: all three are clean, so the answer is three —
    # the verdict counts the clean rows, not the spent ones.
    assert (
        blocks_when_no_clean_epoch_remains(
            [_row(EPOCH_ID, 1), _row(OTHER_EPOCH, 2), _row("epoch-2026-03", 0)]
        )
        == 3
    )


def test_every_epoch_spent_is_refused_end_to_end(tmp_path: Path) -> None:
    # The feature's own sentence, through the real acts: book and decide three
    # promotions against each of two epochs, charge each — the ledger holds
    # three on each, read raw — and the verdict refuses, naming the whole
    # ledger and §13 item 4's own words for what happens next.  The figure the
    # verdict refuses on is a figure the member's own writers landed, not a
    # hand edit.
    url = f"sqlite:///{tmp_path / 'e2e.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    charges = EpochCharges(url)
    for epoch in (EPOCH_ID, OTHER_EPOCH):
        # Three bookings against the epoch through feature 291's real act,
        # three decisions closed through feature 293's, one charge through
        # feature 294's — so the count the verdict refuses on is a figure the
        # member's own writers landed, not a hand edit.
        nodes = [str(uuid.uuid4()) for _ in range(SEQUESTERED_EPOCH_BUDGET)]
        _add_parents(store, nodes=nodes)
        for node in nodes:
            _register(store, node_id=node, epoch_id=epoch)
        for node in nodes:
            _decide(store, node)
        for node in nodes:
            charges.charge(node)
    rows = _raw_ledger(url)()
    assert {r[PROMOTION_DECISIONS_SERVED_COLUMN] for r in rows} == {3}
    with pytest.raises(PromotionBlockedError) as raised:
        TerminalStates(charges).blocks()
    message = str(raised.value)
    assert message.startswith(NO_CLEAN_EPOCH_REMAINS_CODE)
    assert "2 of 2" in message
    assert "legitimate terminal state" in message
    assert message.count(NO_CLEAN_EPOCH_REMAINS_CODE) == 1


def test_a_count_past_the_budget_is_spent_on_the_same_comparison(
    tmp_path: Path,
) -> None:
    # ``>=``, not ``==``: no writer in this member can land a count above
    # three, so the state is a hand edit or a future writer's — and either way
    # the epoch has served at least its budget, which is the whole of the
    # question.  An equality pin would read a figure of four as cleaner than
    # three, which is absurd, and the comparison is pinned here so it cannot
    # quietly become one.
    url = f"sqlite:///{tmp_path / 'over.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 4, epoch=EPOCH_ID)
    _write_served(url, 4, epoch=OTHER_EPOCH)
    with pytest.raises(PromotionBlockedError) as raised:
        blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())
    assert str(raised.value).startswith(NO_CLEAN_EPOCH_REMAINS_CODE)


def test_an_empty_ledger_is_refused_as_a_distinct_terminal_fact(
    tmp_path: Path,
) -> None:
    # ``0110``'s other answer at the whole-table level: a ledger with no row
    # is *nobody sequestered anything*, not a ledger full of clean epochs, and
    # a verdict that read the absence as "zero spent, all clean" would let a
    # deployment that never sequestered an epoch book a promotion against
    # nothing.  The refusal names the sealing process's act as the repair.
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    with pytest.raises(PromotionBlockedError) as raised:
        blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())
    message = str(raised.value)
    assert message.startswith(NO_CLEAN_EPOCH_REMAINS_CODE)
    assert "no sequestered epoch remains" in message
    assert "seal" in message


def test_one_spent_and_one_clean_does_not_refuse(tmp_path: Path) -> None:
    # The difference between a whole-table verdict and the conjunction of
    # per-epoch refusals: when EPOCH_ID is spent and OTHER_EPOCH is clean, the
    # verdict does **not** refuse — it answers that the system may continue
    # (the clean epoch), leaving the per-epoch refusal to feature 295's gate at
    # the moment that spent epoch is selected.  A verdict that refused here
    # would be answering feature 295's question, not this feature's.
    url = f"sqlite:///{tmp_path / 'mixed.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    remaining = blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())
    assert remaining == 1


# -- Nothing moves on either side of the verdict --------------------------------------


def test_nothing_moves_on_a_permitted_verdict(tmp_path: Path) -> None:
    # The count is 294's to persist and the flag this feature's own reader's to
    # set, so a verdict that proceeds writes nothing — read *before* and
    # *after* on the raw table, because the point is what the table holds and
    # the gate's own answer could not witness its own restraint.
    url = f"sqlite:///{tmp_path / 'permit.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 0, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    before = _raw_ledger(url)()
    assert blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs()) == 2
    assert _raw_ledger(url)() == before


def test_nothing_moves_on_a_refused_verdict(tmp_path: Path) -> None:
    # The refusal is the act, and it is not a write: there is no "blocked" row
    # to record, because the terminal state is not an event this member
    # persists — the ``retired`` flag is the exhaustion machinery's later act,
    # not this verdict's.  A refused verdict leaves the database exactly as it
    # was.
    url = f"sqlite:///{tmp_path / 'refuse.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 3, epoch=OTHER_EPOCH)
    before = _raw_ledger(url)()
    with pytest.raises(PromotionBlockedError):
        blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())
    assert _raw_ledger(url)() == before


# -- The verdict holds no cache -------------------------------------------------------


def test_the_verdict_judges_the_rows_every_time_it_is_asked(tmp_path: Path) -> None:
    # No cache: the ledger is the only record of what the epochs have served,
    # so it is the only thing a verdict is drawn from.  Driven by writing
    # behind the verdict's back — this test's own connection, standing in for
    # another process's charge — and reading it back.
    url = f"sqlite:///{tmp_path / 'cache.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 0, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    assert blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs()) == 2
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 3, epoch=OTHER_EPOCH)
    with pytest.raises(PromotionBlockedError):
        blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())


# -- The served count is validated ----------------------------------------------------


def test_a_served_count_that_is_not_a_count_is_refused() -> None:
    # ``True`` is ``1`` in Python and a flag where a count belongs would
    # silently answer one decision nobody recorded; a negative or a fraction or
    # text is a figure nobody derived.  Judging the system's continuation on
    # any of them would be blocking or admitting promotion on a number that is
    # not the ledger's.  A *plain* stand-in rather than a :class:`ServingEpoch`,
    # because that value validates its own count at construction — the point of
    # this test is that the *verdict* refuses the bad figure, not the value it
    # is handed.
    class _Row:
        def __init__(self, served: object) -> None:
            self.epoch_id = EPOCH_ID
            self.promotion_decisions_served = served

    for bad in (True, -1, "three", 1.0, None):
        with pytest.raises(PromotionBlockedError):
            blocks_when_no_clean_epoch_remains([_Row(bad)])


# -- The gate ---------------------------------------------------------------------------


class _StandIn:
    """A duck-typed stand-in for the charge store — the verdict's contract.

    :class:`TerminalStates` reads ``epochs`` and nothing else, so a caller may
    judge through anything shaped like the charge store — this suite's
    stand-in, or the composed store, identically.  The check is the verbs
    rather than the class, because the factory's scan imports this member under
    a synthetic module name and a class check would refuse the very store the
    factory hands out.
    """

    def __init__(self, rows: tuple[ServingEpoch, ...]) -> None:
        self._rows = rows

    def epochs(self) -> tuple[ServingEpoch, ...]:
        return self._rows


def test_a_duck_typed_stand_in_is_a_valid_thing_to_judge_through() -> None:
    # The verdict answers with what the pure judgment answers with — the gate
    # delegates to it — and refuses on the whole ledger's figure, identically
    # through the stand-in and through the real store.
    gate = TerminalStates(
        _StandIn((_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 0)))
    )
    assert gate.blocks() == 2
    with pytest.raises(PromotionBlockedError):
        TerminalStates(_StandIn((_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 3)))).blocks()


def test_a_seam_missing_the_verb_is_refused_at_construction() -> None:
    # A reader with nothing to read through names no ledger, and the fault is
    # a *programming* error — a ``TypeError``, not a promotion state no
    # operator can fix by sequestering or spending anything.
    with pytest.raises(TypeError):
        TerminalStates(object())


def test_the_class_rather_than_an_instance_is_refused_at_construction() -> None:
    # A class exposes its methods as plain functions, so it would pass the verb
    # check and then fail on the first call with a missing positional argument
    # — a confusing way to learn the store was never built.
    with pytest.raises(TypeError):
        TerminalStates(EpochCharges)


def test_the_gate_delegates_to_the_pure_judgment() -> None:
    # One comparison in the member: the gate delegates to the pure judgment, so
    # the two cannot disagree.  Asserted on both halves — the ledger the gate
    # refuses and one it admits — because a delegation that survived only one
    # half would be two comparisons again.
    spent = (_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 3))
    with pytest.raises(PromotionBlockedError):
        TerminalStates(_StandIn(spent)).blocks()
    with pytest.raises(PromotionBlockedError):
        blocks_when_no_clean_epoch_remains(spent)
    mixed = (_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 3))
    assert TerminalStates(_StandIn(mixed)).blocks() == 1
    assert blocks_when_no_clean_epoch_remains(mixed) == 1


# -- The schema this feature's act needs ------------------------------------------------


def test_a_fresh_database_gets_only_the_table_the_seams_owner_creates(
    tmp_path: Path,
) -> None:
    # This act owns no order in :mod:`promotion.schema` because its own
    # statements name no table: the one table the read needs is brought up by
    # the charge store's own connect, which is the rule's smallest illustration
    # — a dependency stated as a composition rather than as a list.  The
    # verdict's first read on a fresh database leaves it holding the ledger and
    # creating neither the registry nor the node tree.
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    with pytest.raises(PromotionBlockedError):
        TerminalStates(EpochCharges(url)).blocks()
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


# -- The vocabulary -----------------------------------------------------------------------------


def test_promotion_blocked_error_is_a_promotion_error_and_a_sibling() -> None:
    # The gathering is the design: this feature's caller is a *gate* whose one
    # failure mode is silence, so a single ``except PromotionBlockedError`` has
    # to catch every face — the verdict and the malformed ask.  And it is a
    # sibling, not a subclass of any of the others: its noun is *every epoch is
    # spent*, unlike 295's *one epoch's budget is spent*, 294's *a count did
    # not land*, or 293's *a stamp did not land*.
    assert issubclass(PromotionBlockedError, PromotionError)
    assert PromotionBlockedError.__bases__ == (PromotionError,)
    assert not issubclass(PromotionBlockedError, EpochSelectionError)
    assert not issubclass(PromotionBlockedError, EpochChargeError)
    assert not issubclass(PromotionBlockedError, PromotionDecisionError)
    assert not issubclass(PromotionBlockedError, PromotionStoreError)


def test_the_code_is_distinct_on_the_shared_domain_prefix() -> None:
    # Three acts, three words: the charge's names *a count did not land*, the
    # selection's *one epoch's budget is spent*, and this one *no clean epoch
    # remains*.  They agree on their ``epoch``/``epoch_charge``/``no_clean``
    # domain and differ where the acts do, so an operator who greps one word
    # lands on exactly one act.
    assert NO_CLEAN_EPOCH_REMAINS_CODE == "no_clean_epoch_remains"
    assert NO_CLEAN_EPOCH_REMAINS_CODE != EPOCH_SELECTION_ERROR_CODE
    assert NO_CLEAN_EPOCH_REMAINS_CODE != EPOCH_CHARGE_ERROR_CODE


def test_every_refusal_the_verdict_drives_is_one_gathered_class() -> None:
    # The gathering is the design, pinned on the real paths: the verdict over a
    # spent ledger, the verdict over an empty ledger, the module-level spelling
    # naming no database, and the malformed ask — all one class, so a caller's
    # single guard holds.
    from promotion import terminal as module

    code = code_of(module)
    assert "raise PromotionError(" not in code
    assert "raise EpochChargeError(" not in code
    assert "raise EpochSelectionError(" not in code


# -- The module-level spellings -----------------------------------------------------------------


def test_block_when_no_clean_epoch_remains_resolves_the_url_it_is_handed(
    tmp_path: Path,
) -> None:
    # The feature's sentence as one call, for the caller that wants the verdict
    # without holding stores — both halves, on two databases this test built.
    clean = f"sqlite:///{tmp_path / 'clean.db'}"
    spent = f"sqlite:///{tmp_path / 'spent.db'}"
    for url in (clean, spent):
        _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(clean, 0, epoch=EPOCH_ID)
    _write_served(clean, 0, epoch=OTHER_EPOCH)
    _write_served(spent, 3, epoch=EPOCH_ID)
    _write_served(spent, 3, epoch=OTHER_EPOCH)
    assert block_when_no_clean_epoch_remains(None, database_url=clean) == 2
    with pytest.raises(PromotionBlockedError):
        block_when_no_clean_epoch_remains(None, database_url=spent)


def test_the_module_level_spelling_resolves_the_ambient_variable(
    monkeypatch, tmp_path: Path
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace reads, so a
    # deployment points every member at one database or at none.
    url = f"sqlite:///{tmp_path / 'ambient.db'}"
    _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 0, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    assert block_when_no_clean_epoch_remains(None) == 2


def test_a_deployment_naming_no_database_is_refused_by_name(monkeypatch) -> None:
    # The silence is the dangerous failure here and not the refusal: a verdict
    # that quietly went unjudged is an exhausted ledger read as clean, which is
    # the state §13 item 4's ledger exists to make impossible — so a verdict
    # resolved from nothing is refused by name.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(PromotionBlockedError) as raised:
        block_when_no_clean_epoch_remains(None)
    message = str(raised.value)
    assert message.startswith(NO_CLEAN_EPOCH_REMAINS_CODE)
    assert DATABASE_URL_ENV in message


def test_from_env_answers_none_without_a_database(monkeypatch, tmp_path: Path) -> None:
    # Absent is not an error: it is a deployment without a relational store, and
    # the caller that must not proceed on an exhausted ledger is the caller that
    # must not find itself in it.  The *refusal* belongs to the caller, which
    # the module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert TerminalStates.from_env() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert TerminalStates.from_env() is None
    url = f"sqlite:///{tmp_path / 'env.db'}"
    _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 3, epoch=OTHER_EPOCH)
    resolved = TerminalStates.from_env({DATABASE_URL_ENV: url})
    assert isinstance(resolved, TerminalStates)
    with pytest.raises(PromotionBlockedError):
        resolved.blocks()


# -- The member's surface and the spec ------------------------------------------------------


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole surface; a caller judging the system's
    # continuation should not have to reach past ``promotion`` into a submodule
    # to make the act or catch the refusal.
    assert member.NO_CLEAN_EPOCH_REMAINS_CODE is NO_CLEAN_EPOCH_REMAINS_CODE
    assert member.PromotionBlockedError is PromotionBlockedError
    assert member.blocks_when_no_clean_epoch_remains is blocks_when_no_clean_epoch_remains
    assert member.TerminalStates is TerminalStates
    assert member.block_when_no_clean_epoch_remains is block_when_no_clean_epoch_remains


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 296 adds no component, for the reason every sibling states: a
    # builder takes no arguments and is built on every ``create_app()`` call,
    # while *whether every epoch is spent* is a fact about rows that move — a
    # charge lands, an epoch spends — and no composition can supply it.  This
    # assertion is where a second ``@register`` would be noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not have to
    # go looking, and so a re-scoped feature would fail a test rather than
    # quietly leaving the suite asserting something the spec no longer says.
    # The module's docstring quotes it too; this is the data-side copy.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System blocks promotion when no clean sequestered epoch remains, "
        "which returns a terminal state rather than reusing a retired epoch"
        in spec.read_text(encoding="utf-8")
    )
