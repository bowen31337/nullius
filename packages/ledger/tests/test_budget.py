"""Feature 90: an opaque ``charges_budget`` directive on every appended trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 90: *System
stamps every trial row with charges_budget supplied by the null oracle as
an opaque directive, never as a derived label.*  These tests hold the
sentence to each clause:

* **charges_budget … on every appended trial row**: the directive, given
  to the append or the debit, is what the row holds on read-back and the
  exact ``0``/``1`` the table stores — a null node (False) lands as
  honestly as a real trial (True), which is what ``K_effective`` (feature
  93) filters on;
* **supplied by the null oracle as an opaque directive**: the value is a
  genuine :class:`bool`, carried through untouched — True is not folded
  to 1, False is not folded to 0 at the write; anything that is not a
  bool (a ``1``, a ``0``, an absent ``None``) is refused at the write
  with :class:`~ledger.errors.TrialRecordError`, at every seam that
  accepts one: the append, the debit, the debit request and the record;
* **never as a derived label**: the ledger does not infer the directive —
  a ``1`` or a ``0`` is not the oracle's directive, and accepting one
  would be the ledger beginning to compute the bit it is only meant to
  carry; the refusal is the clause made concrete;
* **a pre-directive database is upgraded in place**: a table written
  before feature 90 is brought forward with ``charges_budget`` defaulting
  to TRUE — the honest statement a row that predates the null oracle can
  make (no null node was ever among them) and the safe direction for the
  honest counter.

The read path is the one place a non-bool is *coerced* rather than
refused: a row arrives as the ``0``/``1`` the SQLite ``BOOLEAN`` column
stores, and that is coerced to its bool; only a stored value that is
neither bit is refused, because a directive that is neither 0 nor 1 is a
hand that reached past the append.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    TRIAL_LEDGER_TABLE,
    DebitEndpoint,
    DebitRequest,
    TrialLedger,
    TrialLedgerRecord,
    TrialImmutableError,
    TrialRecordError,
    validated_charges_budget,
)
from ledger.store import guarded

NODE = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
OUTCOME = "ok"
CHARGES_BUDGET = True

# The sequestered epoch these tests charge against: any name would do,
# and 'epoch-7' is the spelling the sealing tests coin.  The epoch's own
# behaviour — required at the write, refused when absent, ``None`` on a
# pre-stamp read — is test_epoch.py's subject.
EPOCH = "epoch-7"

# The provenance triple these tests charge under (feature 87): the frozen
# evaluator, the sealed snapshot and the cost model the trial ran against,
# each the sha256 hexdigest its owning feature computes.  The triple's own
# behaviour -- required at the write, refused when absent or malformed,
# normalised to lowercase hex, ``None`` on a pre-stamp read -- is
# test_provenance.py's subject; here it is spelled once as a mapping and
# handed to every charge with ``**``.
EVALUATOR_HASH = "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e"
SNAPSHOT_HASH = "16a0eeb0791b6c92451fd284dd9f599e0a7dbe7f6ebea6e2d2d06c7f74aec112"
COST_MODEL_HASH = "7ceff1a68ddd995b2e87790bad3d75edd4bd42da19cf19039af8888851a7f520"
PROVENANCE = {
    "evaluator_hash": EVALUATOR_HASH,
    "snapshot_hash": SNAPSHOT_HASH,
    "cost_model_hash": COST_MODEL_HASH,
}


# The schema this member wrote before feature 90 landed — the table as it
# was through features 86-91, recreated verbatim so a test can hand the
# store a database that genuinely predates the budget directive.
LEGACY_SCHEMA = f"""
CREATE TABLE {TRIAL_LEDGER_TABLE} (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    campaign_id TEXT NOT NULL,
    outcome     TEXT NOT NULL
);
"""


def _legacy_database(db_path: Path) -> None:
    """Write a pre-directive ledger: the outcome-bearing table, one row."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome) VALUES (?, ?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN), "ok"),
        )


# -- Every appended row carries its directive -----------------------------------


@pytest.mark.parametrize("charges_budget", [True, False])
def test_every_append_persists_the_directive_it_was_given(
    test_ledger: TrialLedger, charges_budget: bool
) -> None:
    # The feature's own clause, one pass per directive value: the row the
    # append returns, the row the read hands back, and the row the table
    # holds all say the same directive.
    record = test_ledger.append(NODE, CAMPAIGN, OUTCOME, charges_budget, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert record.charges_budget is charges_budget
    assert test_ledger.get(record.seq) == record
    assert [row.charges_budget for row in test_ledger.rows()] == [charges_budget]


@pytest.mark.parametrize("charges_budget", [True, False])
def test_the_stored_directive_is_the_0_or_1_the_column_stores(
    test_ledger: TrialLedger, db_path: Path, charges_budget: bool
) -> None:
    # What the table holds, not what the record reports: the SQLite
    # BOOLEAN column stores the bit as 0 or 1, and a genuine bool at the
    # write lands as exactly that integer — True as 1, False as 0.
    record = test_ledger.append(NODE, CAMPAIGN, OUTCOME, charges_budget, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    with sqlite3.connect(db_path) as connection:
        (stored,) = connection.execute(
            f"SELECT charges_budget FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == (1 if charges_budget else 0)


def test_a_real_trial_and_a_null_node_land_side_by_side(
    test_ledger: TrialLedger,
) -> None:
    # A campaign that scored one real node and one null node: two charges,
    # two directives, each row its own — K_effective counts only the
    # budget-charging one.
    real = uuid.uuid4()
    null = uuid.uuid4()
    test_ledger.append(real, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    test_ledger.append(null, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert [row.charges_budget for row in test_ledger.rows()] == [True, False]


def test_the_debit_persists_the_directive_of_the_charge(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent half of the write surface carries the directive too:
    # the failure path §6.1 debits through the debit, and its charge must
    # be able to say whether it consumed statistical budget.
    record, appended = test_ledger.debit(NODE, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert appended is True
    assert record.charges_budget is False
    assert test_ledger.get(record.seq) == record


def test_the_endpoint_carries_the_directive_of_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # POST /ledger/debit's body names the directive; the response's
    # record carries it; the table holds it.
    response = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    assert response.record.charges_budget is False
    assert test_ledger.get(response.seq) == response.record


def test_the_column_tuple_carries_the_directive(
    test_ledger: TrialLedger,
) -> None:
    # The record's column tuple is the table's declaration order — the
    # directive sits where §8 declares it, and the reader that unpacks it
    # cannot mistake it for an identity, a stamp or the outcome.  Feature
    # 89's unit and feature 88's epoch follow it, and feature 87's triple
    # closes the row (its own tests pin that end).
    record = test_ledger.append(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert record.row()[5] == 1
    assert record.row() == (
        record.seq,
        STAMP.isoformat(),
        str(NODE),
        str(CAMPAIGN),
        "ok",
        1,
        1.0,
        EPOCH,
        EVALUATOR_HASH,
        SNAPSHOT_HASH,
        COST_MODEL_HASH,
    )


# -- The directive is a genuine bool, supplied not derived ----------------------


def test_validated_charges_budget_carries_a_bool_through_untouched() -> None:
    # A genuine bool is canonical: True stays True, False stays False,
    # with nothing to normalise — the directive is carried, not computed.
    assert validated_charges_budget(True, strict=True) is True
    assert validated_charges_budget(False, strict=True) is False


@pytest.mark.parametrize(
    "bad",
    [None, 1, 0, 2, "true", "True", "", True + True, 1.0, b"1"],
)
def test_a_non_bool_directive_is_refused_at_every_write_seam(
    test_ledger: TrialLedger, bad: object
) -> None:
    # The directive is supplied, never derived: a 1 or a 0 or an absent
    # None is not the oracle's directive, and accepting one would be the
    # ledger beginning to compute the bit.  So every seam that *writes* a
    # directive refuses a non-bool — the append, the debit, the debit
    # request.  (The record constructor is the read path, and coerces the
    # stored 0/1 rather than refusing it — see the coercion test below.)
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, bad, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_ledger.debit(NODE, CAMPAIGN, OUTCOME, bad, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        DebitRequest(NODE, CAMPAIGN, OUTCOME, bad, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [None, 2, "true", "True", "", 1.0, b"1"],
)
def test_the_record_read_path_coerces_0_or_1_but_refuses_any_other_non_bool(
    bad: object,
) -> None:
    # The record constructor is the read path, so it coerces the 0/1 a
    # SQLite BOOLEAN column stores — a row written by any writer reads as
    # a genuine bool.  But a stored value that is neither 0 nor 1 is a
    # hand that reached past the append, and is refused rather than
    # served, exactly as a hand-edited stamp or outcome is.
    assert TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=0, epoch_id=EPOCH, **PROVENANCE).charges_budget is False
    assert TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=1, epoch_id=EPOCH, **PROVENANCE).charges_budget is True
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        TrialLedgerRecord(
            seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
            outcome=OUTCOME, charges_budget=bad, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]


def test_a_1_or_0_is_not_a_directive(test_ledger: TrialLedger) -> None:
    # The refusal's sharpest point: the directive crosses the barrier as a
    # bool, and §7.2's oracle answers a bool.  A caller that hands an int
    # — even the "same" bit — is handing a value the ledger would have to
    # derive the meaning of, which is exactly the derivation the feature
    # forbids.
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, 1, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, 0, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]


def test_an_absent_directive_is_refused_not_defaulted(
    test_ledger: TrialLedger,
) -> None:
    # The one refusal worth naming on its own: the caller that debits a
    # trial without the oracle's directive.  There is no honest
    # presumption — §8 gives charge_units a default and gives
    # charges_budget none — because a default would be the ledger
    # deciding the answer the oracle must supply.
    with pytest.raises(TrialRecordError, match="got None"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, epoch_id=EPOCH, **PROVENANCE)
    with pytest.raises(TrialRecordError, match="got None"):
        test_ledger.debit(NODE, CAMPAIGN, OUTCOME, epoch_id=EPOCH, **PROVENANCE)
    with pytest.raises(TrialRecordError, match="got None"):
        DebitRequest(NODE, CAMPAIGN, OUTCOME, epoch_id=EPOCH, **PROVENANCE)
    assert test_ledger.count() == 0


@pytest.mark.parametrize("bad", [1, 0, None, "true"])
def test_a_refused_directive_spends_no_sequence_number(
    test_ledger: TrialLedger, bad: object
) -> None:
    # The refusal lands before the database is touched, so a charge that
    # cannot state its directive costs nothing: the next honest append
    # draws the very first number.
    with pytest.raises(TrialRecordError):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, bad, epoch_id=EPOCH, **PROVENANCE)  # type: ignore[arg-type]
    assert test_ledger.count() == 0
    assert test_ledger.append(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE).seq == 1


# -- The retry keeps the original directive -------------------------------------


def test_a_retry_does_not_restate_the_directive(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The worker died after the row landed; the worker that takes over
    # holds a directive the oracle answered differently.  The row is a
    # fact about the charge first debited — directive False — and facts
    # are never restated; the response's record says which directive
    # landed, exactly as it says which stamp and which outcome landed.
    original = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    retry = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )

    assert retry.seq == original.seq == 1
    assert retry.appended is False
    assert retry.record.charges_budget is False
    assert test_ledger.get(1).charges_budget is False
    assert test_ledger.count() == 1


# -- The schema: the column, its constraint, its place --------------------------


def test_the_directive_column_is_boolean_not_null_with_no_default(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # §8's DDL for the column is BOOLEAN NOT NULL with no default — the
    # shape that makes the directive the caller's to state, not the
    # table's to presume.  The column sits in the declaration order the
    # record's row() tuple mirrors, before feature 89's unit, feature
    # 88's epoch and feature 87's provenance triple.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        rows = {row[1]: row for row in info}
    assert list(rows) == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units", "epoch_id", "evaluator_hash", "snapshot_hash",
        "cost_model_hash",
    ]
    # (cid, name, type, notnull, dflt_value, pk) for the charges_budget column.
    # SQLite preserves the declared type name; the value is still stored as
    # the 0/1 an INTEGER-affinity column holds.
    _, _, kind, notnull, default, pk = rows["charges_budget"]
    assert kind == "BOOLEAN"
    assert notnull == 1
    assert default is None
    assert pk == 0


def test_a_row_whose_directive_wandered_off_the_bit_is_refused(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The read path revalidates through the budget check, so a hand-edited
    # directive — like a hand-edited stamp or outcome — is refused rather
    # than served: in an append-only log, one unreadable row is evidence,
    # not noise.  A stored value that is neither 0 nor 1 is corruption.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charges_budget = ? WHERE seq = 1",
            (2,),
        )
    with pytest.raises(TrialRecordError, match="seq=1"):
        test_ledger.rows()


def test_the_read_path_coerces_a_stored_0_or_1_to_a_bool(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # A row read back arrives as the 0/1 the column stores; the read path
    # coerces it to its bool, so a row written by another writer that
    # stored the bit as an integer reads as a genuine bool.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charges_budget = 0 WHERE seq = 1"
        )
    assert test_ledger.get(1).charges_budget is False


# -- A pre-directive database is upgraded in place -------------------------------


def test_a_pre_directive_database_is_upgraded_in_place(
    test_database_url: str, db_path: Path
) -> None:
    # CREATE TABLE IF NOT EXISTS cannot evolve the table a database
    # already holds; without the upgrade every append on this database
    # would die on "no column named charges_budget".  The first operation
    # brings the table forward instead.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].charges_budget is True
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        columns = [row[1] for row in info]
    # The legacy table held outcome alone; the upgrade adds every stamp
    # the rows predate — the directive, the unit, the epoch and the
    # provenance triple — so every column a reader needs exists.
    assert columns == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units", "epoch_id", "evaluator_hash", "snapshot_hash",
        "cost_model_hash",
    ]


def test_the_legacy_default_is_the_budget_charging_spelling(
    test_database_url: str, db_path: Path
) -> None:
    # Rows the pre-directive append debited predate the null oracle, so no
    # null node was ever among them — every one was a real trial that
    # consumed statistical degrees of freedom, and TRUE asserts exactly
    # that.  It is also the safe direction for the honest counter:
    # counting a legacy row as budget-charging can only ever understate
    # the deflation the null nodes introduce, never overstate it.
    _legacy_database(db_path)
    assert TrialLedger(test_database_url).get(1).charges_budget is True


def test_the_upgrade_continues_the_sequence_above_the_legacy_rows(
    test_database_url: str, db_path: Path
) -> None:
    # The upgrade adds a column; it drops nothing, restates nothing,
    # spends nothing.  AUTOINCREMENT's high-water mark survives it, so the
    # first post-upgrade charge draws the number after the legacy maximum.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    record = ledger.append(NODE, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    assert record.seq == 2
    assert [row.seq for row in ledger.rows()] == [1, 2]
    assert [row.charges_budget for row in ledger.rows()] == [True, False]


def test_the_upgrade_passes_the_immutability_wall(
    test_database_url: str, db_path: Path
) -> None:
    # The wall is a mutation wall, not a schema freeze: the upgrade's
    # ALTER is neither an UPDATE nor a DELETE, restates no charge and
    # spends no sequence number, so it runs on the guarded connection
    # itself — and once it has, the wall still refuses the mutation it
    # always refused.
    _legacy_database(db_path)
    with guarded(test_database_url) as connection:
        (count,) = connection.execute(
            f"SELECT COUNT(*) FROM {TRIAL_LEDGER_TABLE}"
        ).fetchone()
        assert count == 1
        with pytest.raises(TrialImmutableError):
            connection.execute(
                f"UPDATE {TRIAL_LEDGER_TABLE} SET charges_budget = 0 WHERE seq = 1"
            )
