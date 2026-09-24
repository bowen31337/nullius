"""The depleting count of clean epochs remaining — feature 297, §13 item 4's gauge.

Feature 297's sentence — *"System reports remaining clean epochs as a depleting
count, which returns the figure so exhaustion is visible well before it
arrives."* — and the file where *how many clean epochs remain* is the whole of
the act under test.  The count on each ledger row is feature 294's, the
``retired`` flag is feature 296's reader's, and this feature's whole act is one
count — how many rows have not served §13 item 4's budget — performed on the
rows the charge's own read answers with.  And the figure it returns is not a
write anywhere else in the member: everything landed, everything is readable,
and the answer is *the number*, which is why this feature returns rather than
raises — the deliberate contrast with feature 296, whose terminal verdict
raises.

**What this feature is not, asserted as hard as what it is.**  The count is a
function of the ledger rows; the retirement is feature 296's flag, not this
gauge's law; the stop is feature 296's verdict.  So the first tests pin the
boundary: this module never spells feature 292's mismatch verdict, never reads
the ``retired`` or ``sealed_at`` column, never reads a pool, a score or a
coverage ledger, spells no statement of its own at all, and never raises on the
figure — the rows arrive through feature 294's ``epochs`` seam, so there is no
second reading of one table for the tests to catch, and a spent or empty ledger
answers ``0`` rather than an exception.  A suite that only tested the happy
answer would pass for a module that had quietly re-implemented the flag check,
invented its own ``SELECT``, or become feature 296 again.

**The gauge is not feature 296's verdict, and that is the test that catches the
difference.**  Feature 296 raises when no clean epoch remains and is silent
about every count short of the end — one clean epoch left and fifty both answer
"the system may continue".  This gauge *returns the number*, so a ledger with
one clean epoch left and one with fifty are told apart, and a ledger that is
wholly spent answers ``0`` rather than raising.  A suite that only tested "one
clean epoch" would pass for a module that had quietly become feature 296's
verdict; the tests that pin ``0`` on a spent ledger and the exact count on a
partially spent one are what keep the gauge a readout and not a stop.

**``>=`` is the comparison, through the shared derivation.**  A clean epoch is
one that has not served the budget — ``served < budget``, the complement of
feature 296's ``served >= budget`` — and the count is shared with feature 296's
verdict through :func:`promotion.selection._spent_count`, so the figure this
gauge returns and the clean remainder feature 296 reports between its refusals
are one figure.  Book and decide three promotions against each of two epochs,
charge each — the ledger holds three on each — and the gauge answers ``0``,
through the real acts of features 291, 293 and 294 rather than a hand-written
row.  A count *above* three counts as spent on the same comparison.

**Nothing moves on either side of the count.**  The count is 294's to persist
and the flag feature 296's to set, so a read of the gauge — permitted, spent or
empty — leaves the raw ledger byte-identical.

**Zero is an answer, not a refusal.**  An empty ledger, or one whose every epoch
has served the budget, answers ``0`` — the figure the caller asked for, and the
visible exhaustion the sentence promises.  This is the deliberate contrast with
feature 296, which refuses the empty ledger as a distinct terminal fact; this
gauge reports ``0``, because a readout that only spoke at the end would not make
exhaustion visible before it arrives.
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
    REPO_ROOT,
    code_of,
)
from promotion import (
    DATABASE_URL_ENV,
    EPOCH_CHARGE_ERROR_CODE,
    EPOCH_ID_COLUMN,
    EPOCH_LEDGER_TABLE,
    PROMOTION_DECISIONS_SERVED_COLUMN,
    PROMOTION_REGISTRY_TABLE,
    SEALED_AT_COLUMN,
    SEQUESTERED_EPOCH_BUDGET,
    EpochChargeError,
    EpochCharges,
    PromotionBlockedError,
    RemainingCleanEpochs,
    ServingEpoch,
    clean_epochs_remaining,
    remaining_clean_epochs,
)

#: The three instants the suite works over — the sealing (the conftest's own
#: literal for the seeded row), the registration and the decision — named so
#: an assertion reads as a statement about stamps rather than about literals
#: buried in a call.
SEALED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
REGISTERED_AT = dt.datetime(2026, 3, 1, tzinfo=dt.UTC)
DECIDED_AT = dt.datetime(2026, 3, 2, tzinfo=dt.UTC)

#: A second and third epoch name, so a count over several rows reads as a
#: statement about the whole ledger rather than about one.
OTHER_EPOCH = "epoch-2026-02"
THIRD_EPOCH = "epoch-2026-03"


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


def _write_served(database_url: str, served: object, epoch: str = EPOCH_ID) -> None:
    """Write one epoch's served count raw, standing in for another process.

    This test's own connection, not the store's — the shape the charge's own
    suite uses to prove it holds no cache, used here for the same purpose.
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
    holds — including the rows before and after a count — and a test that asked
    the code under test would be asking it to confirm itself.
    """

    def _rows() -> list[sqlite3.Row]:
        connection = sqlite3.connect(
            Path(database_url.removeprefix("sqlite:///"))
        )
        try:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                f"SELECT {EPOCH_ID_COLUMN}, {SEALED_AT_COLUMN}, "
                f"{PROMOTION_DECISIONS_SERVED_COLUMN} "
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


# -- The boundary: this feature counts the whole ledger, and on nothing else ----------


def test_the_module_never_spells_the_mismatch_verdict() -> None:
    # Feature 292's verdict is the only act in this category that compares a
    # promotion against its recorded hash, and a gauge that spelled it would be
    # two features in one module.  Docstrings are stripped by ``code_of`` so
    # the module may *say* it is not 292 without tripping the test that pins
    # it.
    from promotion import remaining as module

    assert "criteria_mismatch" not in code_of(module)


def test_the_gauge_reads_neither_the_flag_nor_the_sealing_instant() -> None:
    # The count is the whole of the law here: ``retired`` is feature 296's own
    # reader's flag and ``sealed_at`` is the sealing process's fact, and a
    # gauge that read either would be judging the flag or re-deriving the
    # sequestration this gauge takes as given.  Pinned on the *attribute
    # access* rather than the bare word, because a docstring may legitimately
    # quote §13 item 4's own "retired permanently" — what the module must never
    # do is read the fields.
    from promotion import remaining as module

    code = code_of(module)
    assert ".retired" not in code
    assert ".sealed_at" not in code
    assert "RETIRED_COLUMN" not in code
    assert "SEALED_AT_COLUMN" not in code


def test_the_gauge_reads_no_merit_and_no_evidence() -> None:
    # Whether the promotion *stands* is the deciding evaluation's verdict, and
    # the inputs to that verdict — a pool, a score, a coverage ledger, a
    # calibration status — are tables this act never opens.  A gauge that read
    # one would have re-implemented half of 292, 298 or 299 with none of their
    # suites.
    from promotion import remaining as module

    code = code_of(module)
    for evidence in ("regime_coverage", "campaign", "ir_oos", "score", "calibration"):
        assert evidence not in code, evidence


def test_the_gauge_reads_the_ledger_through_the_charges_own_seam() -> None:
    # The discipline :mod:`promotion.terminal` states for its verdict, pinned
    # for this gauge: the rows are read through feature 294's own store
    # (composed in ``__init__``), never through a second ``SELECT`` spelled
    # here — so the count this act makes and the counts the charge answered
    # with cannot be two readings of one table.
    from promotion import remaining as module

    code = code_of(module)
    assert f"FROM {EPOCH_LEDGER_TABLE}" not in code
    assert f"FROM {PROMOTION_REGISTRY_TABLE}" not in code
    assert "self._charges.epochs(" in code


def test_the_gauge_spells_no_statement_and_authors_no_ddl() -> None:
    # A gauge that writes nothing needs no connection, no bootstrap and no
    # statement — and :mod:`promotion.schema` gains no order because the set a
    # bootstrap runs is the set an act's own statements name and this act's
    # statements name nothing at all.  Every token here is pinned so a later
    # statement smuggled in fails this test rather than quietly widening the
    # member's DDL footprint.
    from promotion import remaining as module

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


def test_the_gauge_never_raises_on_the_figure() -> None:
    # A gauge reports the figure even at the end: a spent or empty ledger
    # answers ``0`` rather than raising.  This is the deliberate contrast with
    # feature 296, whose verdict *raises* — and the reason this feature is a
    # readout and not a stop.  The pure count takes only the rows and the
    # budget; the module-level spelling may add only the URL seam the member's
    # other spellings take.
    assert set(inspect.signature(clean_epochs_remaining).parameters) == {
        "rows",
        "budget",
    }
    assert set(inspect.signature(remaining_clean_epochs).parameters) == {
        "rows_or_url",
        "database_url",
        "env",
    }


def test_the_budget_is_the_prds_own_number_used_not_restated() -> None:
    # §13 item 4's "3 promotion decisions", spelled in exactly one place: a
    # second spelling anywhere else in the member would be a second place the
    # budget lives, free to disagree with the one the gate compares against.
    # This gauge *uses* the budget — the imported name appears (it is the pure
    # count's default) — but does not restate it, and shares its derivation
    # with feature 296 rather than spelling its own.
    from promotion import remaining as module

    assert SEQUESTERED_EPOCH_BUDGET == 3
    assert "SEQUESTERED_EPOCH_BUDGET = 3" not in code_of(module)
    assert "_spent_count(" in code_of(module)


# -- The pure count -------------------------------------------------------------------


def _row(epoch: str, served: int) -> ServingEpoch:
    """A serving epoch standing in for one ledger row."""
    return ServingEpoch(
        epoch_id=epoch,
        sealed_at=SEALED_AT,
        promotion_decisions_served=served,
        retired=False,
    )


def test_all_clean_answers_the_count_of_clean_epochs() -> None:
    # The permissive half of the pair: when no epoch has served the budget, the
    # gauge answers the count of clean epochs — the figure it exists to report.
    assert clean_epochs_remaining([_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 0)]) == 2


def test_a_partially_spent_ledger_answers_the_clean_remainder() -> None:
    # The gauge is a question about the *system's* remaining headroom, not
    # about any one epoch's spend: it counts the rows that have not served the
    # budget, wherever they sit in the ledger.
    assert clean_epochs_remaining([_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 0)]) == 1
    # Three epochs, none spent: all three are clean, so the answer is three —
    # the gauge counts the clean rows, not the spent ones.
    assert (
        clean_epochs_remaining(
            [_row(EPOCH_ID, 1), _row(OTHER_EPOCH, 2), _row(THIRD_EPOCH, 0)]
        )
        == 3
    )


def test_a_wholly_spent_ledger_answers_zero_not_a_refusal(tmp_path: Path) -> None:
    # The gauge's whole point: a ledger whose every epoch has served the budget
    # answers ``0`` — the visible exhaustion the sentence promises — rather
    # than raising.  This is the contrast with feature 296, whose verdict
    # raises on exactly this ledger.  The figure the gauge returns is a figure
    # the member's own writers landed, not a hand edit.
    url = f"sqlite:///{tmp_path / 'spent.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    charges = EpochCharges(url)
    for epoch in (EPOCH_ID, OTHER_EPOCH):
        nodes = [str(uuid.uuid4()) for _ in range(SEQUESTERED_EPOCH_BUDGET)]
        _add_parents(store, nodes=nodes)
        for node in nodes:
            member.PreRegisterEndpoint(store).post(
                member.PreRegistrationRequest(
                    node_id=node,
                    epoch_id=epoch,
                    criteria=dict(DEFAULT_CRITERIA_DOCUMENT),
                ),
                clock=lambda: REGISTERED_AT,
            )
        for node in nodes:
            member.PromotionDecisions(url).record_decision(
                node, clock=lambda: DECIDED_AT
            )
        for node in nodes:
            charges.charge(node)
    rows = _raw_ledger(url)()
    assert {r[PROMOTION_DECISIONS_SERVED_COLUMN] for r in rows} == {3}
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 0
    # The same ledger makes feature 296's verdict raise — the two are told
    # apart: the verdict stops, the gauge reports zero.
    with pytest.raises(PromotionBlockedError):
        member.blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())


def test_an_empty_ledger_answers_zero_not_a_refusal(tmp_path: Path) -> None:
    # The deliberate contrast with feature 296: that verdict refuses the empty
    # ledger as a distinct terminal fact, because a *stop* that answered
    # "continue" on an unsequestered deployment would book a promotion against
    # nothing.  This gauge is not a stop: it reports *how many are clean*, and
    # the honest answer to "how many clean epochs?" when none were ever sealed
    # is *zero*.  A caller that wants the stop asks feature 296.
    url = f"sqlite:///{tmp_path / 'empty.db'}"
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 0
    with pytest.raises(PromotionBlockedError):
        member.blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs())


def test_a_count_past_the_budget_is_spent_on_the_same_comparison(
    tmp_path: Path,
) -> None:
    # ``>=``, not ``==``: no writer in this member can land a count above three,
    # so the state is a hand edit or a future writer's — and either way the
    # epoch has served at least its budget, which is the whole of the question.
    # An equality pin would read a figure of four as cleaner than three.
    url = f"sqlite:///{tmp_path / 'over.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 4, epoch=EPOCH_ID)
    _write_served(url, 4, epoch=OTHER_EPOCH)
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 0


def test_the_gauge_and_the_verdict_agree_on_the_clean_remainder(
    tmp_path: Path,
) -> None:
    # One figure, two acts: the gauge's count and the clean remainder feature
    # 296 reports between its refusals are the same number over the same rows —
    # the shared derivation through :func:`promotion.selection._spent_count`.
    url = f"sqlite:///{tmp_path / 'agree.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH, THIRD_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    _write_served(url, 1, epoch=THIRD_EPOCH)
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 2
    assert (
        member.blocks_when_no_clean_epoch_remains(EpochCharges(url).epochs()) == 2
    )


# -- Nothing moves on a read of the gauge ---------------------------------------------


def test_nothing_moves_on_a_read_of_the_gauge(tmp_path: Path) -> None:
    # The count is 294's to persist and the flag feature 296's to set, so a
    # read of the gauge — permitted, spent or empty — writes nothing.  Read
    # *before* and *after* on the raw table, because the point is what the
    # table holds and the gauge's own answer could not witness its own
    # restraint.
    url = f"sqlite:///{tmp_path / 'permit.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 0, epoch=EPOCH_ID)
    _write_served(url, 3, epoch=OTHER_EPOCH)
    before = _raw_ledger(url)()
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 1
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 1
    assert _raw_ledger(url)() == before


# -- The gauge holds no cache ---------------------------------------------------------


def test_the_gauge_counts_the_rows_every_time_it_is_asked(tmp_path: Path) -> None:
    # No cache: the ledger is the only record of what the epochs have served,
    # so it is the only thing a count is drawn from.  Driven by writing behind
    # the gauge's back — this test's own connection, standing in for another
    # process's charge — and reading it back.
    url = f"sqlite:///{tmp_path / 'cache.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 0, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 2
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 3, epoch=OTHER_EPOCH)
    assert clean_epochs_remaining(EpochCharges(url).epochs()) == 0


# -- The gate ---------------------------------------------------------------------------


class _StandIn:
    """A duck-typed stand-in for the charge store — the gauge's contract.

    :class:`RemainingCleanEpochs` reads ``epochs`` and nothing else, so a caller
    may count through anything shaped like the charge store — this suite's
    stand-in, or the composed store, identically.  The check is the verbs
    rather than the class, because the factory's scan imports this member under
    a synthetic module name and a class check would refuse the very store the
    factory hands out.
    """

    def __init__(self, rows: tuple[ServingEpoch, ...]) -> None:
        self._rows = rows

    def epochs(self) -> tuple[ServingEpoch, ...]:
        return self._rows


def test_a_duck_typed_stand_in_is_a_valid_thing_to_count_through() -> None:
    # The gauge answers with what the pure count answers with — the gate
    # delegates to it — identically through the stand-in and through the real
    # store.
    gate = RemainingCleanEpochs(
        _StandIn((_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 0)))
    )
    assert gate.remaining() == 2
    assert RemainingCleanEpochs(
        _StandIn((_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 0)))
    ).remaining() == 1
    assert RemainingCleanEpochs(
        _StandIn((_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 3)))
    ).remaining() == 0


def test_a_seam_missing_the_verb_is_refused_at_construction() -> None:
    # A reader with nothing to read through names no ledger, and the fault is
    # a *programming* error — a ``TypeError``, not a promotion state no
    # operator can fix by sequestering or spending anything.
    with pytest.raises(TypeError):
        RemainingCleanEpochs(object())


def test_the_class_rather_than_an_instance_is_refused_at_construction() -> None:
    # A class exposes its methods as plain functions, so it would pass the verb
    # check and then fail on the first call with a missing positional argument
    # — a confusing way to learn the store was never built.
    with pytest.raises(TypeError):
        RemainingCleanEpochs(EpochCharges)


def test_the_gate_delegates_to_the_pure_count() -> None:
    # One count in the member: the gate delegates to the pure count, so the two
    # cannot disagree.  Asserted across three ledgers — all clean, partially
    # spent, wholly spent — because a delegation that survived only one would
    # be two counts again.
    all_clean = (_row(EPOCH_ID, 0), _row(OTHER_EPOCH, 0))
    assert RemainingCleanEpochs(_StandIn(all_clean)).remaining() == 2
    assert clean_epochs_remaining(all_clean) == 2
    mixed = (_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 0))
    assert RemainingCleanEpochs(_StandIn(mixed)).remaining() == 1
    assert clean_epochs_remaining(mixed) == 1
    spent = (_row(EPOCH_ID, 3), _row(OTHER_EPOCH, 3))
    assert RemainingCleanEpochs(_StandIn(spent)).remaining() == 0
    assert clean_epochs_remaining(spent) == 0


# -- The schema this feature's act needs ------------------------------------------------


def test_a_fresh_database_gets_only_the_table_the_seams_owner_creates(
    tmp_path: Path,
) -> None:
    # This act owns no order in :mod:`promotion.schema` because its own
    # statements name no table: the one table the read needs is brought up by
    # the charge store's own connect, which is the rule's smallest illustration
    # — a dependency stated as a composition rather than as a list.  The
    # gauge's first read on a fresh database leaves it holding the ledger and
    # creating neither the registry nor the node tree.
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    assert RemainingCleanEpochs(EpochCharges(url)).remaining() == 0
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


def test_the_gauge_propagates_a_read_refusal_in_its_own_vocabulary(
    tmp_path: Path,
) -> None:
    # A refusal the read raises (a row that cannot be read back) propagates in
    # feature 294's vocabulary — the count is judged on the rows, and a row
    # that cannot be read is a different fact from one that is spent.  The
    # gauge never raises on the *figure*; it does not swallow the *read*.
    url = f"sqlite:///{tmp_path / 'corrupt.db'}"
    store = _fresh(url)
    _add_parents(store, epochs=[EPOCH_ID])
    # A served count that is not a count of rows — a text value, which SQLite
    # preserves as text and feature 294's read therefore refuses (a Python
    # ``True`` would round-trip to the integer ``1`` and read as clean, which
    # is not the refusal this test drives).  The gauge lets feature 294's
    # refusal surface rather than answering a figure nobody derived.
    connection = sqlite3.connect(Path(url.removeprefix("sqlite:///")))
    try:
        with connection:
            connection.execute(
                f"UPDATE {EPOCH_LEDGER_TABLE} "
                f"SET {PROMOTION_DECISIONS_SERVED_COLUMN} = ?",
                ("three",),
            )
    finally:
        connection.close()
    with pytest.raises(EpochChargeError) as raised:
        RemainingCleanEpochs(EpochCharges(url)).remaining()
    assert str(raised.value).startswith(EPOCH_CHARGE_ERROR_CODE)


# -- The module-level spellings -----------------------------------------------------------------


def test_remaining_clean_epochs_resolves_the_url_it_is_handed(
    tmp_path: Path,
) -> None:
    # The feature's sentence as one call, for the caller that wants the figure
    # without holding stores — both halves, on two databases this test built.
    clean = f"sqlite:///{tmp_path / 'clean.db'}"
    spent = f"sqlite:///{tmp_path / 'spent.db'}"
    for url in (clean, spent):
        _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(clean, 0, epoch=EPOCH_ID)
    _write_served(clean, 0, epoch=OTHER_EPOCH)
    _write_served(spent, 3, epoch=EPOCH_ID)
    _write_served(spent, 3, epoch=OTHER_EPOCH)
    assert remaining_clean_epochs(None, database_url=clean) == 2
    assert remaining_clean_epochs(None, database_url=spent) == 0


def test_the_module_level_spelling_resolves_the_ambient_variable(
    monkeypatch, tmp_path: Path
) -> None:
    # The other half of the resolution: an explicit URL wins, else
    # ``DATABASE_URL`` — the same seam every store in this workspace reads, so a
    # deployment points every member at one database or at none.
    url = f"sqlite:///{tmp_path / 'ambient.db'}"
    _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    monkeypatch.setenv(DATABASE_URL_ENV, url)
    assert remaining_clean_epochs(None) == 1


def test_a_deployment_naming_no_database_is_refused_by_name(monkeypatch) -> None:
    # The silence is the dangerous failure here and not the refusal: a gauge
    # that quietly returned nothing would leave a dashboard showing a full
    # ledger while the epochs ran out unseen, which is the state §13 item 4's
    # ledger exists to make visible rather than hide — so a gauge resolved from
    # nothing is refused by name.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    with pytest.raises(EpochChargeError) as raised:
        remaining_clean_epochs(None)
    message = str(raised.value)
    assert message.startswith(EPOCH_CHARGE_ERROR_CODE)
    assert DATABASE_URL_ENV in message


def test_from_env_answers_none_without_a_database(monkeypatch, tmp_path: Path) -> None:
    # Absent is not an error: it is a deployment without a relational store, and
    # the caller that must show depletion coming is the caller that must not
    # find itself without the figure.  The *refusal* belongs to the caller,
    # which the module-level spellings make.
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
    assert RemainingCleanEpochs.from_env() is None
    monkeypatch.setenv(DATABASE_URL_ENV, "   ")
    assert RemainingCleanEpochs.from_env() is None
    url = f"sqlite:///{tmp_path / 'env.db'}"
    _add_parents(_fresh(url), epochs=[EPOCH_ID, OTHER_EPOCH])
    _write_served(url, 3, epoch=EPOCH_ID)
    _write_served(url, 0, epoch=OTHER_EPOCH)
    resolved = RemainingCleanEpochs.from_env({DATABASE_URL_ENV: url})
    assert isinstance(resolved, RemainingCleanEpochs)
    assert resolved.remaining() == 1


# -- The member's surface, the seat, and the spec -------------------------------------------------


def test_the_vocabulary_is_reachable_from_the_members_surface() -> None:
    # The member re-exports its whole surface; a caller watching depletion
    # should not have to reach past ``promotion`` into a submodule to make the
    # act.
    assert member.clean_epochs_remaining is clean_epochs_remaining
    assert member.RemainingCleanEpochs is RemainingCleanEpochs
    assert member.remaining_clean_epochs is remaining_clean_epochs


def test_the_member_still_exports_exactly_one_builder() -> None:
    # Feature 297 adds no component, for the reason every sibling states: a
    # builder takes no arguments and is built on every ``create_app()`` call,
    # while *how many clean epochs remain* is a fact about rows that move — a
    # charge lands, an epoch spends — and no composition can supply it.  This
    # assertion is where a second ``@register`` would be noticed.
    assert [name for name in dir(member) if name.startswith("build_")] == [
        "build_promotion_registry"
    ]


def test_the_seat_is_untouched_by_this_feature() -> None:
    # The seat still answers one question, and it deliberately does not
    # re-export the gauge vocabulary: a caller who has the store constructs the
    # gauge, and a second spelling there would be a second thing to keep in
    # sync.
    from app.modules import promotion as seat

    assert set(seat.__all__) == {"COMPONENT_NAME", "promotion_registry_component"}
    assert not hasattr(seat, "RemainingCleanEpochs")
    assert not hasattr(seat, "clean_epochs_remaining")


def test_the_specs_sentence_is_what_this_module_implements() -> None:
    # The feature's own line, quoted so a reader of this suite does not have to
    # go looking, and so a re-scoped feature would fail a test rather than
    # quietly leaving the suite asserting something the spec no longer says.
    # The module's docstring quotes it too; this is the data-side copy.
    spec = REPO_ROOT / "app_spec.xml"
    if not spec.is_file():  # pragma: no cover - the spec is in the checkout
        pytest.skip("app_spec.xml is not in this checkout")
    assert (
        "System reports remaining clean epochs as a depleting count, "
        "which returns the figure so exhaustion is visible well before it "
        "arrives" in spec.read_text(encoding="utf-8")
    )
