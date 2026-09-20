"""Feature 88: an ``epoch_id`` stamp on every appended trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 88: *System
records epoch_id naming which sequestered epoch a trial charged, which
rejects a write whose epoch_id is absent.*  These tests hold the
sentence to each clause:

* **records epoch_id … on every trial row**: the epoch, given to the
  append, the debit or the debit request, is what the row holds on
  read-back and the exact text the table stores — carried in the
  sealing process's own spelling, because the epoch namespace is the
  sealing process's (``epoch_ledger`` keys on it, feature 105) and this
  layer holds the name to being a name, coining and canonicalising
  none of it;
* **naming which sequestered epoch a trial charged**: the epoch is the
  holdout the spend is booked against — a depleting resource, §13 item
  4 retires one after three promotion decisions — and the grouping key
  ``K_effective`` is derived by (feature 93), so a charge that cannot
  name its holdout is a charge no audit can place;
* **rejects a write whose epoch_id is absent**: an absent epoch is
  refused at every seam that accepts one — the append, the debit, the
  debit request — *before* the database is touched, so a refused charge
  spends no sequence number; blank and non-string spellings are refused
  on the same ground, because neither names an epoch a sealing process
  coined.  The one seam that accepts ``None`` is the record, because
  the record is also the read, and a row written before the stamp
  landed honestly names no epoch;
* **a pre-epoch database is upgraded in place**: a table written before
  feature 88 is brought forward with a nullable ``epoch_id`` — SQLite
  refuses ``ADD COLUMN … NOT NULL`` without a non-NULL default, and for
  this one stamp no default is honest: 'ok', ``TRUE`` and ``1.0`` each
  asserted something true of every legacy row, while the only true
  statement a row that predates the epoch stamp can make is *no epoch
  was named*.  NULL is that statement, and it is the one feature 93's
  derivation already groups under the un-named epoch; the write's
  required-epoch refusal still holds on the brought-forward table, so
  no row this store writes ever lands without one.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    TRIAL_LEDGER_TABLE,
    UNNAMED_EPOCH,
    DebitEndpoint,
    DebitRequest,
    TrialLedger,
    TrialLedgerRecord,
    TrialRecordError,
    validated_epoch_id,
)

NODE = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
OUTCOME = "ok"
CHARGES_BUDGET = True

# The epoch these tests charge against.  The spelling is the sealing
# tests' own ('epoch-7'), because the point of the stamp is that the
# name is the sealing process's — this suite never coins one the
# sequestration would not recognise.
EPOCH = "epoch-7"
OTHER_EPOCH = "epoch-8"

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


# The schema this member wrote before feature 88 landed — the table as
# it was through features 86-91, holding every stamp but the epoch,
# recreated verbatim so a test can hand the store a database that
# genuinely predates the epoch stamp.
LEGACY_SCHEMA = f"""
CREATE TABLE {TRIAL_LEDGER_TABLE} (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    charges_budget  BOOLEAN NOT NULL,
    charge_units    REAL NOT NULL DEFAULT 1.0
);
"""


def _legacy_database(db_path: Path) -> None:
    """Write a pre-epoch ledger: the seven-column table, holding one row."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget, charge_units) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN), "ok", 1, 1.0),
        )


# -- Every appended row carries its epoch ---------------------------------------


def test_every_append_persists_the_epoch_it_was_given(
    test_ledger: TrialLedger,
) -> None:
    # The feature's own clause: the row the append returns, the row the
    # read hands back, and the row the table holds all name the epoch the
    # trial charged.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert record.epoch_id == EPOCH
    assert test_ledger.get(record.seq) == record
    assert [row.epoch_id for row in test_ledger.rows()] == [EPOCH]


def test_the_stored_epoch_is_the_text_the_sealing_process_coined(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # What the table holds, not what the record reports: TEXT stores the
    # name verbatim — no folding, no normalising — because the namespace
    # is the sealing process's and epoch_ledger keys on exactly it.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    with sqlite3.connect(db_path) as connection:
        stored, kind = connection.execute(
            f"SELECT epoch_id, typeof(epoch_id) FROM {TRIAL_LEDGER_TABLE} "
            "WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == EPOCH
    assert kind == "text"


def test_two_epochs_land_side_by_side(
    test_ledger: TrialLedger,
) -> None:
    # A campaign that spent two holdouts: two charges, two epochs, each
    # row its own — the dimension feature 93's derivation groups by.
    first = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    second = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
        epoch_id=OTHER_EPOCH, **PROVENANCE,
    )
    assert [row.epoch_id for row in test_ledger.rows()] == [
        first.epoch_id,
        second.epoch_id,
    ]


def test_the_debit_persists_the_epoch_of_the_charge(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent half of the write surface carries the epoch too: the
    # failure path §6.1 debits through the debit, and its charge must be
    # able to say which holdout it spent.
    record, appended = test_ledger.debit(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert appended is True
    assert record.epoch_id == EPOCH
    assert test_ledger.get(record.seq) == record


def test_the_endpoint_carries_the_epoch_of_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # POST /ledger/debit's body names the epoch; the response's record
    # carries it; the table holds it.
    response = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    assert response.record.epoch_id == EPOCH
    assert test_ledger.get(response.seq) == response.record


def test_the_column_tuple_carries_the_epoch_eighth(
    test_ledger: TrialLedger,
) -> None:
    # The record's column tuple is the table's declaration order — the
    # epoch sits eighth, after every stamp that describes the trial, and
    # the reader that unpacks it cannot mistake a holdout's name for an
    # identity, a stamp, the outcome, the directive or the unit.  The
    # provenance triple (feature 87) now closes the row; its own tests
    # pin that end.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert record.row()[7] == EPOCH
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


def test_a_retry_never_restates_the_epoch_of_the_charge(
    test_endpoint: DebitEndpoint,
) -> None:
    # On a retry nothing is written — the epoch the charge first named
    # stands exactly as first written, however the retry spelled it,
    # because this is append-only accounting and a charge is never
    # restated.  The retry's epoch is the loser of that rule; callers
    # that need to know which landed read it off the returned record.
    first = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    retry = test_endpoint.post(
        DebitRequest(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=OTHER_EPOCH, **PROVENANCE
        )
    )
    assert retry.appended is False
    assert retry.record.epoch_id == EPOCH == first.record.epoch_id


# -- An absent epoch is rejected at every write seam ------------------------------


@pytest.mark.parametrize("bad", [None, "", "   ", "\t", 7, 1.5, True, [], object()])
def test_an_absent_or_unnamed_epoch_is_refused_at_the_append(
    test_ledger: TrialLedger, bad: object
) -> None:
    # The feature's own refusal, at the raw write: an absent epoch (None,
    # the omitted-parameter default) is refused outright, and so are the
    # spellings that name no epoch a sealing process coined — a blank
    # string is a name nobody sealed, and a non-string is not a name at
    # all.  Every refusal lands *before* the database is touched, so a
    # refused charge spends no sequence number.
    with pytest.raises(TrialRecordError, match="epoch_id"):
        test_ledger.append(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=bad, **PROVENANCE
        )  # type: ignore[arg-type]
    assert test_ledger.count() == 0


@pytest.mark.parametrize("bad", [None, "", "   ", 7, True, [], object()])
def test_an_absent_or_unnamed_epoch_is_refused_at_the_debit(
    test_ledger: TrialLedger, bad: object
) -> None:
    # The idempotent spelling of the charge is still a charge, and a
    # charge that cannot name its holdout is a charge no audit can
    # place — the same refusal, at the store's second write seam.
    with pytest.raises(TrialRecordError, match="epoch_id"):
        test_ledger.debit(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=bad, **PROVENANCE
        )  # type: ignore[arg-type]
    assert test_ledger.count() == 0


@pytest.mark.parametrize("bad", [None, "", "   ", 7, True, [], object()])
def test_an_absent_or_unnamed_epoch_is_refused_at_the_wire(
    test_endpoint: DebitEndpoint, bad: object
) -> None:
    # Feature 95's body gets the same refusal at construction, so a
    # malformed POST never reaches the store at all: the refusal names
    # the requirement, and the ledger's count and sequence are exactly
    # what they were.
    with pytest.raises(TrialRecordError, match="epoch_id"):
        DebitRequest(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=bad, **PROVENANCE
        )  # type: ignore[arg-type]


def test_a_refused_epoch_spends_no_sequence_number(
    test_ledger: TrialLedger,
) -> None:
    # The refusal's cost, asserted as arithmetic: however many charges
    # the epoch refused, the next honest charge draws sequence 1 — the
    # ledger never spent a number on a charge that never landed.
    for bad in (None, "", "  ", 7, object()):
        with pytest.raises(TrialRecordError, match="epoch_id"):
            test_ledger.append(
                NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=bad, **PROVENANCE
            )  # type: ignore[arg-type]
    assert test_ledger.count() == 0
    landed = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert landed.seq == 1


def test_the_refusal_names_the_requirement_and_the_column() -> None:
    # The error is the contract stated at the moment it is broken: it
    # names the column (§8's own comment — "which sequestered epoch was
    # charged"), the reason the epoch is required (a depleting resource
    # counted in epoch_ledger), and the value that named none.
    with pytest.raises(TrialRecordError, match="sequestered epoch"):
        validated_epoch_id(None, required=True)
    with pytest.raises(TrialRecordError, match="non-empty string"):
        validated_epoch_id(7)


# -- The validator: a name carried, never coined ----------------------------------


def test_the_validator_carries_a_name_in_its_own_spelling() -> None:
    # What the sealing process named is what the row stores and what
    # epoch_ledger keys on — no case folding, no trimming, no coining.
    # The layer holds the name to being a name.
    assert validated_epoch_id("epoch-7") == "epoch-7"
    assert validated_epoch_id("holdout-2026-09") == "holdout-2026-09"
    assert validated_epoch_id(EPOCH) is EPOCH


def test_the_validator_passes_none_through_when_not_required() -> None:
    # ``None`` is the read's spelling for a row that predates the stamp
    # — a statement about the ledger's history, not an epoch a caller
    # named.  The read passes it through; the write seams are the ones
    # that ask for required=True, and the record is also the read.
    assert validated_epoch_id(None) is None


def test_the_record_accepts_none_because_the_record_is_also_the_read(
    test_ledger: TrialLedger,
) -> None:
    # The one seam that tolerates an absent epoch: a hand-built record
    # (the read path's shape) names no epoch honestly, and its column
    # tuple carries the NULL a brought-forward table's upgrade column
    # holds.  The write's refusal lives at the store and the endpoint,
    # exactly where the feature's sentence puts it.
    record = TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=CHARGES_BUDGET,
    )
    assert record.epoch_id is None
    assert record.row()[7] is None


# -- A pre-epoch database is upgraded in place -------------------------------------


def test_a_pre_epoch_table_is_brought_forward_with_a_nullable_column(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The upgrade adds the column and refuses to invent a value: each
    # earlier stamp's legacy default asserted something true of every
    # legacy row ('ok', TRUE, 1.0), while for the epoch the only true
    # statement a pre-stamp row can make is *no epoch was named* — NULL,
    # the spelling SQLite's plain ADD COLUMN lands on and the one the
    # read already understands.  The provenance triple (87) rides the
    # same upgrade, in the columns that follow the epoch's.
    _legacy_database(db_path)
    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({TRIAL_LEDGER_TABLE})"
            )
        ]
        assert "epoch_id" not in columns  # the table predates the stamp

    rows = test_ledger.rows()  # the store's connect performs the upgrade
    assert [row.epoch_id for row in rows] == [None]
    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(
                f"PRAGMA table_info({TRIAL_LEDGER_TABLE})"
            )
        ]
        (stored,) = connection.execute(
            f"SELECT epoch_id FROM {TRIAL_LEDGER_TABLE} WHERE seq = 1"
        ).fetchone()
    assert columns[-4:] == [
        "epoch_id", "evaluator_hash", "snapshot_hash", "cost_model_hash",
    ]
    assert stored is None


def test_legacy_rows_group_under_the_unnamed_epoch(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The NULL upgrade column is not a dead end: feature 93's derivation
    # reads it as the un-named epoch — one honest bucket, labelled as
    # naming no epoch rather than pretending to be one — so the epoch a
    # legacy row did not name never corrupts the per-epoch view.
    _legacy_database(db_path)
    view = test_ledger.k_effective()
    assert view.counts == ((UNNAMED_EPOCH, 1),)
    assert view.of(UNNAMED_EPOCH) == 1


def test_a_brought_forward_table_still_requires_the_epoch_at_the_write(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The nullable upgrade column is the *table's* history, not the
    # write's licence: NOT NULL holds for every row this store writes
    # because the write seams refuse a charge that names no epoch — on a
    # brought-forward table exactly as on a fresh one.
    _legacy_database(db_path)
    with pytest.raises(TrialRecordError, match="epoch_id"):
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP
        )
    landed = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert landed.seq == 2
    assert [row.epoch_id for row in test_ledger.rows()] == [None, EPOCH]
