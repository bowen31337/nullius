"""Feature 89: a ``charge_units`` stamp on every appended trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 89: *System
stamps every trial row with charge_units defaulting to 1.0, so a
cross-validated evaluation can cost more than one unit.*  These tests
hold the sentence to each clause:

* **charge_units … on every trial row**: the unit, given to the append or
  the debit, is what the row holds on read-back and the exact ``REAL`` the
  table stores — an ordinary trial's ``1.0`` lands as honestly as a
  cross-validated evaluation's larger count;
* **defaulting to 1.0**: a write that says nothing about units is charged
  §8's own ``1.0`` — the column's ``DEFAULT`` in the spec's DDL, mirrored
  as the record's field default, the store's parameter default and the
  debit request's field default, so a caller can omit it at every seam
  and still land an honest row.  This is where the feature *differs* from
  feature 90: §8 gives ``charge_units`` a default and ``charges_budget``
  none, and the asymmetry is the spec's;
* **so a cross-validated evaluation can cost more than one unit**: a
  caller that states a larger count gets that count on the row — the
  seam exists, and nothing clamps it back to one;
* **the unit is a positive finite real**: a non-number, a NaN, an
  infinity and anything at or below zero are refused at every seam that
  accepts one (the append, the debit, the debit request and the record),
  *before* the database is touched.  NaN is the sharp case and has its
  own test: SQLite persists a NaN as NULL, so a NaN that reached the
  append would land as the absence of a unit on a row this ledger can
  never correct;
* **a pre-unit database is upgraded in place**: a table written before
  feature 89 is brought forward with ``charge_units`` defaulting to 1.0 —
  the honest statement a row that predates the unit stamp can make (those
  evaluations were written before a caller could state more than one
  unit), and the value that leaves the honest counter's arithmetic
  unchanged across the upgrade.

The read path revalidates through the same check, so a row whose unit
wandered off the real line — a hand-edit, a corruption — is refused rather
than served.  The unit is also held *apart* from feature 90's directive:
a test below pins that a cross-validated real trial is several units with
``charges_budget`` true while a null node is one unit with it false, so a
later reader cannot conflate what the trial cost with whether it spent
statistical degrees of freedom.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    DEFAULT_CHARGE_UNITS,
    TRIAL_LEDGER_TABLE,
    DebitEndpoint,
    DebitRequest,
    TrialLedger,
    TrialLedgerRecord,
    TrialImmutableError,
    TrialRecordError,
    validated_charge_units,
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

# The schema this member wrote before feature 89 landed — the table as it
# was through features 86-91, recreated verbatim so a test can hand the
# store a database that genuinely predates the charge unit.  The columns
# the sibling stamps added are present, because this is the table
# test_budget.py and test_outcome.py leave behind: the unit is the only
# column missing, which is what makes these tests about *its* upgrade.
LEGACY_SCHEMA = f"""
CREATE TABLE {TRIAL_LEDGER_TABLE} (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    charges_budget  BOOLEAN NOT NULL
);
"""


def _legacy_database(db_path: Path) -> None:
    """Write a pre-unit ledger: the six-column table, holding one row."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget) "
            "VALUES (?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN), "ok", 1),
        )


# -- Every appended row carries its unit ----------------------------------------


@pytest.mark.parametrize("units", [1.0, 5.0, 0.5, 12.0])
def test_every_append_persists_the_unit_it_was_given(
    test_ledger: TrialLedger, units: float
) -> None:
    # The feature's own clause, one pass per cost: the row the append
    # returns, the row the read hands back, and the row the table holds
    # all say the same unit.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, units, ts=STAMP, epoch_id=EPOCH)
    assert record.charge_units == units
    assert test_ledger.get(record.seq) == record
    assert [row.charge_units for row in test_ledger.rows()] == [units]


@pytest.mark.parametrize("units", [1.0, 5.0, 0.5])
def test_the_stored_unit_is_the_real_the_column_holds(
    test_ledger: TrialLedger, db_path: Path, units: float
) -> None:
    # What the table holds, not what the record reports: the REAL column
    # stores the unit as a real number, so the value a caller stated is
    # the value on disk.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, units, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        stored, kind = connection.execute(
            f"SELECT charge_units, typeof(charge_units) FROM {TRIAL_LEDGER_TABLE} "
            "WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == units
    assert kind == "real"


def test_an_integer_unit_lands_as_the_float_the_column_holds(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # A caller that states a fold count as an int states the same charge
    # as one that spells it 5.0: REAL affinity stores both as 5.0, and the
    # record normalises both to the float, so a unit of 5 and a unit of
    # 5.0 are one value and one row rather than two spellings of a cost.
    record = test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5, ts=STAMP, epoch_id=EPOCH)
    assert record.charge_units == 5.0
    assert isinstance(record.charge_units, float)
    with sqlite3.connect(db_path) as connection:
        (stored,) = connection.execute(
            f"SELECT charge_units FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == 5.0


def test_an_ordinary_trial_and_a_cross_validated_one_land_side_by_side(
    test_ledger: TrialLedger,
) -> None:
    # The feature's whole point, as two rows: one evaluation that ran a
    # single fit costs one unit, and one that ran five folds costs five.
    # The seam exists for exactly this — nothing in the ledger clamps the
    # larger charge back to one.
    ordinary = uuid.uuid4()
    cross_validated = uuid.uuid4()
    test_ledger.append(ordinary, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    test_ledger.append(
        cross_validated, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5.0, ts=STAMP, epoch_id=EPOCH)
    assert [row.charge_units for row in test_ledger.rows()] == [1.0, 5.0]


def test_the_debit_persists_the_unit_of_the_charge(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent half of the write surface carries the unit too: the
    # failure path §6.1 debits through the debit, and a cross-validated
    # evaluation that failed still cost its folds.
    record, appended = test_ledger.debit(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 3.0, ts=STAMP, epoch_id=EPOCH)
    assert appended is True
    assert record.charge_units == 3.0
    assert test_ledger.get(record.seq) == record


def test_the_endpoint_carries_the_unit_of_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # POST /ledger/debit's body names the unit; the response's record
    # carries it; the table holds it.
    response = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5.0, ts=STAMP, epoch_id=EPOCH)
    )
    assert response.record.charge_units == 5.0
    assert test_ledger.get(response.seq) == response.record


def test_the_column_tuple_carries_the_unit_seventh(
    test_ledger: TrialLedger,
) -> None:
    # The record's column tuple is the table's declaration order — the
    # unit sits seventh, after the directive it is easy to confuse it
    # with, and the reader that unpacks it cannot mistake a cost for an
    # identity, a stamp, the outcome or the directive.  Feature 88's
    # epoch closes the tuple; its own tests pin that end.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 4.0, ts=STAMP, epoch_id=EPOCH)
    assert record.row()[6] == 4.0
    assert record.row() == (
        record.seq,
        STAMP.isoformat(),
        str(NODE),
        str(CAMPAIGN),
        "ok",
        1,
        4.0,
        EPOCH,
    )


# -- The default is 1.0, at every seam -------------------------------------------


def test_the_default_is_1_0_at_every_write_seam(
    test_ledger: TrialLedger, test_endpoint: DebitEndpoint
) -> None:
    # §8's DDL: "charge_units REAL NOT NULL DEFAULT 1.0".  A caller that
    # states nothing about units is charged exactly one — the default is
    # threaded through the store's two write methods and the request, so
    # omitting it at any seam lands the same honest unit.
    assert DEFAULT_CHARGE_UNITS == 1.0
    assert test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH).charge_units == 1.0
    assert test_ledger.debit(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)[0].charge_units == 1.0
    assert test_endpoint.post(
        DebitRequest(uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    ).record.charge_units == 1.0


def test_the_default_mirrors_the_columns_own_default(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The default is not this member's invention: it is the DEFAULT
    # §8 declares on the column, and the record, the store and the request
    # all spell it from one constant.  The schema test below pins the DDL
    # half; this pins that a row written through the store with no unit
    # stated reads back as the same 1.0 the column would have supplied to
    # a writer that is not this store.  (The raw INSERT names an epoch —
    # that column has no default to lean on, which is feature 88's own
    # point — but the unit is left to the column's DEFAULT, the subject.)
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget, epoch_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(uuid.uuid4()), str(CAMPAIGN), "ok", 1, EPOCH),
        )
    assert [row.charge_units for row in test_ledger.rows()] == [1.0, 1.0]


def test_the_record_defaults_to_the_unit_an_ordinary_trial_costs() -> None:
    # The read path's default matters too: a record built for a row that
    # predates the stamp — or by a caller that simply does not care about
    # the cost of an ordinary trial — carries 1.0 rather than a None that
    # no column could hold.
    record = TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=CHARGES_BUDGET, epoch_id=EPOCH)
    assert record.charge_units == 1.0


def test_the_request_defaults_to_the_unit_an_ordinary_trial_costs() -> None:
    # The wire's default: a body that says nothing about units is an
    # ordinary evaluation, and the request carries 1.0 rather than
    # refusing a caller for omitting a term the spec defaults.
    request = DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, epoch_id=EPOCH)
    assert request.charge_units == 1.0


# -- The unit is a positive finite real, supplied not clamped --------------------


@pytest.mark.parametrize("units", [1, 5, 0.5, 2.25])
def test_validated_charge_units_normalises_a_number_to_a_float(
    units: object,
) -> None:
    # A genuine number is canonical once it is a float — the form the REAL
    # column holds — so an int and a float stating the same cost are one
    # value.
    result = validated_charge_units(units)
    assert result == float(units)  # type: ignore[arg-type]
    assert isinstance(result, float)


@pytest.mark.parametrize(
    "bad",
    [None, "1.0", "one", "", b"1", True, False, [1.0], {"units": 1.0}],
)
def test_a_non_number_unit_is_refused_at_every_write_seam(
    test_ledger: TrialLedger, bad: object
) -> None:
    # A unit that is not a number is a cost no audit can sum.  ``bool`` is
    # refused explicitly because ``isinstance(True, int)``: a unit of
    # ``True`` is a flag that wandered into a numeric column.
    with pytest.raises(TrialRecordError, match="charge_units must be a real number"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be a real number"):
        test_ledger.debit(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be a real number"):
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be a real number"):
        TrialLedgerRecord(
            seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
            outcome=OUTCOME, charges_budget=CHARGES_BUDGET, charge_units=bad, epoch_id=EPOCH)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_unit_is_refused_at_every_write_seam(
    test_ledger: TrialLedger, bad: float
) -> None:
    # NaN and the infinities are numbers by type and not by arithmetic: a
    # unit of NaN makes every later sum of the column NaN, and an infinity
    # swallows it.
    with pytest.raises(TrialRecordError, match="charge_units must be finite"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be finite"):
        test_ledger.debit(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be finite"):
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be finite"):
        TrialLedgerRecord(
            seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
            outcome=OUTCOME, charges_budget=CHARGES_BUDGET, charge_units=bad, epoch_id=EPOCH)  # type: ignore[arg-type]


def test_a_nan_is_refused_because_sqlite_would_store_it_as_null(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The sharpest reason the finiteness check exists, verified against
    # the dialect rather than asserted about it: SQLite persists a NaN as
    # NULL (the REAL affinity does not preserve it).  A NaN that reached
    # the append would therefore land as the *absence* of a unit — on an
    # append-only row this ledger can never correct.  So the refusal is at
    # the write, and the row is never created.
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE probe (x REAL)")
        connection.execute("INSERT INTO probe (x) VALUES (?)", (float("nan"),))
        stored, kind = connection.execute(
            "SELECT x, typeof(x) FROM probe"
        ).fetchone()
    assert stored is None
    assert kind == "null"
    # And the append refuses that value rather than creating such a row.
    with pytest.raises(TrialRecordError, match="charge_units must be finite"):
        test_ledger.append(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, float("nan"), epoch_id=EPOCH)
    assert test_ledger.count() == 0


@pytest.mark.parametrize("bad", [0.0, 0, -1.0, -0.5, -12])
def test_a_non_positive_unit_is_refused(
    test_ledger: TrialLedger, bad: object
) -> None:
    # §6.1's step 11 debits *even when the node fails*, so no trial this
    # ledger records is free: 0.0 is the spelling of "this evaluation was
    # free" and there is no such charge.  A negative is worse — it would
    # subtract from the count.  A caller whose trial should not count
    # states charges_budget=False (feature 90) instead.
    with pytest.raises(TrialRecordError, match="charge_units must be greater than zero"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be greater than zero"):
        test_ledger.debit(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    with pytest.raises(TrialRecordError, match="charge_units must be greater than zero"):
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)
    assert test_ledger.count() == 0


def test_a_negative_unit_is_refused_rather_than_clamped(
    test_ledger: TrialLedger,
) -> None:
    # Clamping a negative to 1.0 would be the ledger *deriving* a weight
    # the caller never stated, and it would derive in the direction that
    # inflates K — a negative charge silently becoming a full unit.  The
    # refusal is the clause made concrete: the unit is supplied.
    with pytest.raises(TrialRecordError, match="charge_units must be greater than zero"):
        test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, -5.0, epoch_id=EPOCH)
    assert test_ledger.count() == 0


def test_a_refused_unit_spends_no_sequence_number(
    test_ledger: TrialLedger,
) -> None:
    # The refusal lands before the database is touched, so a charge that
    # cannot state its unit costs nothing: the next honest append draws
    # the very first number.
    for bad in (None, float("nan"), 0.0, -1.0, "1.0"):
        with pytest.raises(TrialRecordError):
            test_ledger.append(
                NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, bad, epoch_id=EPOCH)  # type: ignore[arg-type]
    assert test_ledger.count() == 0
    assert test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH).seq == 1


# -- The retry keeps the original unit -------------------------------------------


def test_a_retry_does_not_restate_the_unit(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The worker died after the row landed; the worker that takes over
    # bills a different fold count.  The row is a fact about the charge
    # first debited — five units — and facts are never restated, exactly
    # as the stamp, the outcome and the directive are not.
    original = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5.0, ts=STAMP, epoch_id=EPOCH)
    )
    retry = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 1.0, ts=STAMP, epoch_id=EPOCH)
    )

    assert retry.seq == original.seq == 1
    assert retry.appended is False
    assert retry.record.charge_units == 5.0
    assert test_ledger.get(1).charge_units == 5.0
    assert test_ledger.count() == 1


# -- The unit is not the directive ----------------------------------------------


def test_the_unit_and_the_directive_are_independent_facts(
    test_ledger: TrialLedger,
) -> None:
    # The pair most easily conflated, pinned as four rows.  §10.3
    # penalizes trials_charged and deflates by K_effective, and feature
    # 89 prices the evaluation while feature 90 says whether it spent
    # statistical degrees of freedom — so a cross-validated real trial is
    # several units with charges_budget true (it cost more *and* it
    # counted), while a null node is one unit with it false (it cost an
    # ordinary evaluation *but* its signal was never compared to real
    # forward returns).  Neither column is derivable from the other.
    rows = [
        (True, 1.0),    # an ordinary real trial
        (True, 5.0),    # a cross-validated real trial
        (False, 1.0),   # a null node
        (False, 2.0),   # a null node that still ran two folds
    ]
    for budget, units in rows:
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, budget, units, ts=STAMP, epoch_id=EPOCH)
    assert [
        (row.charges_budget, row.charge_units) for row in test_ledger.rows()
    ] == rows


# -- The schema: the column, its constraint, its default -------------------------


def test_the_unit_column_is_real_not_null_defaulting_to_1_0(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # §8's DDL for the column is "REAL NOT NULL DEFAULT 1.0", and all
    # three parts are load-bearing: REAL because a fold count is a real
    # number, NOT NULL because every trial has a cost, and the DEFAULT
    # because an ordinary evaluation's cost is a fact the spec states
    # rather than one the writer must repeat.  SQLite reports a REAL
    # column's declared type verbatim.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        rows = {row[1]: row for row in info}
    # (cid, name, type, notnull, dflt_value, pk) for the charge_units column.
    _, _, kind, notnull, default, pk = rows["charge_units"]
    assert kind == "REAL"
    assert notnull == 1
    # SQLite reports the default as the literal text the DDL spelled.
    assert float(default) == 1.0
    assert pk == 0


def test_a_row_whose_unit_wandered_off_the_real_line_is_refused(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The read path revalidates through the unit check, so a hand-edited
    # unit — like a hand-edited stamp, outcome or directive — is refused
    # rather than served: in an append-only log, one unreadable row is
    # evidence, not noise.  A REAL column is not declared STRICT and
    # SQLite's affinity does not coerce a non-numeric string, so text can
    # genuinely be stored in this column by a writer that reached past the
    # append — which is exactly the case the read-side check exists for.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charge_units = ? WHERE seq = 1",
            ("free",),
        )
    with pytest.raises(TrialRecordError, match="seq=1"):
        test_ledger.rows()


@pytest.mark.parametrize("stored", [0.0, -1.0, 2.5])
def test_a_stored_non_positive_unit_is_refused_on_read(
    test_ledger: TrialLedger, db_path: Path, stored: float
) -> None:
    # A row that arrives with a unit no honest write could have produced
    # is refused rather than served — including the two values a caller
    # cannot state through the store but a raw UPDATE can still leave.
    # 2.5 is the control: a legitimate unit that a raw write may hold and
    # the read must accept.
    test_ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charge_units = ? WHERE seq = 1",
            (stored,),
        )
    if stored > 0.0:
        assert test_ledger.get(1).charge_units == stored
    else:
        with pytest.raises(TrialRecordError, match="seq=1"):
            test_ledger.rows()


def test_a_stored_integer_unit_reads_back_as_the_float_it_is():
    # A row written by a writer that stored the unit as an integer — or by
    # an older table whose column the upgrade widened — reads back as the
    # float the REAL column holds, so the record never carries a unit in
    # one type at the write and another at the read.
    record = TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=CHARGES_BUDGET, charge_units=3, epoch_id=EPOCH)
    assert record.charge_units == 3.0
    assert isinstance(record.charge_units, float)


# -- A pre-unit database is upgraded in place ------------------------------------


def test_a_pre_unit_database_is_upgraded_in_place(
    test_database_url: str, db_path: Path
) -> None:
    # CREATE TABLE IF NOT EXISTS cannot evolve the table a database
    # already holds; without the upgrade every append on this database
    # would die on "no column named charge_units".  The first operation
    # brings the table forward instead.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].charge_units == 1.0
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        columns = [row[1] for row in info]
    # The legacy table held every stamp but the unit; the upgrade adds
    # the unit and the epoch — the one stamp whose legacy rows carry no
    # value at all (test_epoch.py pins that half of the upgrade).
    assert columns == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units", "epoch_id",
    ]


def test_the_legacy_default_is_the_ordinary_trials_unit(
    test_database_url: str, db_path: Path
) -> None:
    # Rows the pre-unit append debited were written before a caller could
    # state more than one unit, so every one of them was an ordinary
    # evaluation and 1.0 asserts exactly that.  It is also the value that
    # keeps the honest counter's arithmetic unchanged across the upgrade:
    # the legacy rows' cost is what it always was, where any other value
    # would silently restate what those trials spent.
    _legacy_database(db_path)
    assert TrialLedger(test_database_url).get(1).charge_units == 1.0


def test_the_upgrade_continues_the_sequence_above_the_legacy_rows(
    test_database_url: str, db_path: Path
) -> None:
    # The upgrade adds a column; it drops nothing, restates nothing,
    # spends nothing.  AUTOINCREMENT's high-water mark survives it, so the
    # first post-upgrade charge draws the number after the legacy maximum.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    record = ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5.0, ts=STAMP, epoch_id=EPOCH)
    assert record.seq == 2
    assert [row.seq for row in ledger.rows()] == [1, 2]
    assert [row.charge_units for row in ledger.rows()] == [1.0, 5.0]


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
                f"UPDATE {TRIAL_LEDGER_TABLE} SET charge_units = 99 WHERE seq = 1"
            )


def test_the_upgrade_is_idempotent_across_repeated_connects(
    test_database_url: str, db_path: Path
) -> None:
    # Every operation opens its own connection and runs the upgrade, so a
    # table that already holds the column must be left exactly as it was:
    # the second connect takes the same cheap path as the first, and a
    # value already stored is never reset to the default.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    ledger.append(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, 5.0, ts=STAMP, epoch_id=EPOCH)
    # Several more connects, each re-running the upgrade.
    for _ in range(3):
        assert ledger.count() == 2
    assert [row.charge_units for row in ledger.rows()] == [1.0, 5.0]


def test_the_upgrade_fills_a_missing_unit_column_without_touching_the_others(
    test_database_url: str, db_path: Path
) -> None:
    # The brought-forward table's other columns are untouched — the
    # directive the legacy row carried stays the FALSE it was written
    # with, rather than being reset along with the widened column.
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget) "
            "VALUES (?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN), "timeout", 0),
        )
    row = TrialLedger(test_database_url).get(1)
    assert row.charges_budget is False
    assert row.outcome == "timeout"
    assert row.charge_units == 1.0


# -- The gate's own arithmetic is untouched -------------------------------------


def test_k_effective_still_counts_rows_rather_than_units(
    test_ledger: TrialLedger,
) -> None:
    # feature 93's derivation filters on charges_budget and counts *rows*;
    # feature 89 prices them.  A cross-validated trial therefore does not
    # move K_effective by five, and this test exists so a later reader who
    # expects units to weight the deflation input finds the current
    # behaviour stated rather than assumed either way.
    test_ledger.append(uuid.uuid4(), CAMPAIGN, OUTCOME, True, 5.0, ts=STAMP, epoch_id=EPOCH)
    test_ledger.append(uuid.uuid4(), CAMPAIGN, OUTCOME, False, 5.0, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().total == 1


def test_nan_is_rejected_before_it_can_reach_the_column() -> None:
    # The unit-level companion to the store test above: the check is a
    # property of the validator, so no seam can admit the one value SQLite
    # would silently turn into a NULL.
    assert math.isnan(float("nan"))
    with pytest.raises(TrialRecordError, match="must be finite"):
        validated_charge_units(float("nan"))
