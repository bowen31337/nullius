"""Feature 87: the provenance triple stamped on every appended trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 87: *System
stamps every trial_ledger row with evaluator_hash, snapshot_hash and
cost_model_hash.*  These tests hold the sentence to each clause:

* **stamps every trial row with the triple**: the three terms, given to
  the append, the debit or the debit request, are what the row holds on
  read-back and the exact lowercase hex the CHAR(64) columns store —
  carried in the sha256 hexdigest's own spelling, because each term is
  a digest a feature already computed (feature 70's evaluator, §4.2's
  snapshot, feature 60's cost model) and this layer coins and
  canonicalises none of it beyond folding case, the same courtesy the
  evaluator and snapshot members extend the sibling columns this row
  joins against;
* **evaluator_hash, snapshot_hash, cost_model_hash**: the three terms
  name one fact each — *which frozen evaluator scored the trial*,
  *which sealed snapshot it was scored against*, *which fee-and-fill
  regime priced it* — and §9.1 declares the same triple on the node
  table, because the row that was charged and the node that was
  evaluated must be able to name the same three terms without drift;
* **the write is refused when a term is absent**: an absent term is
  refused at every seam that accepts the triple — the append, the
  debit, the debit request — *before* the database is touched, so a
  refused charge spends no sequence number; a term that is not 64 hex
  characters — a ``sha256:``-prefixed image reference, a short hash, a
  non-hex token, a non-string — is refused on the same ground, because
  it names no evaluator, snapshot or cost model this system recorded.
  The one seam that accepts ``None`` is the record, because the record
  is also the read, and a row written before the stamp landed honestly
  names no provenance;
* **a pre-triple database is upgraded in place**: a table written
  before feature 87 is brought forward with the three columns
  appended nullable, in §8's declaration order, after the epoch —
  SQLite refuses ``ADD COLUMN … NOT NULL`` without a non-NULL default,
  and for the triple no default is honest: defaulting one would
  fabricate provenance no feature computed.  NULL is the statement a
  row that predates the stamp can truthfully make, the write's
  required-triple refusal still holds on the brought-forward table,
  and no row this store writes ever lands without the triple.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    PROVENANCE_COLUMNS,
    TRIAL_LEDGER_TABLE,
    DebitEndpoint,
    DebitRequest,
    TrialLedger,
    TrialLedgerRecord,
    TrialRecordError,
    validated_provenance_hash,
)

NODE = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
OUTCOME = "ok"
CHARGES_BUDGET = True

# The sequestered epoch these tests charge against: any name would do,
# and 'epoch-7' is the spelling the sealing tests coin.  The epoch's own
# behaviour is test_epoch.py's subject.
EPOCH = "epoch-7"

# The provenance triple these tests charge under: the frozen evaluator,
# the sealed snapshot and the cost model the trial ran against, each the
# sha256 hexdigest its owning feature computes.  Spelled as a mapping so
# every charge hands the whole triple with ``**``.
EVALUATOR_HASH = "27f6343f980c4c0ab821d9c72d211d0eb76b0853825cefd80476a05e43cab27e"
SNAPSHOT_HASH = "16a0eeb0791b6c92451fd284dd9f599e0a7dbe7f6ebea6e2d2d06c7f74aec112"
COST_MODEL_HASH = "7ceff1a68ddd995b2e87790bad3d75edd4bd42da19cf19039af8888851a7f520"
PROVENANCE = {
    "evaluator_hash": EVALUATOR_HASH,
    "snapshot_hash": SNAPSHOT_HASH,
    "cost_model_hash": COST_MODEL_HASH,
}

# A second frozen evaluator — a different digest, so a campaign's two
# charges can be shown to carry the provenance each ran under rather
# than one value restamped on every row.
OTHER_EVALUATOR_HASH = "ee062ac4e8ffa0c38b34438b6c538010957de8e893d88f987a1309ed0e51fccf"


# The schema this member wrote before feature 87 landed — the table as
# it was through features 86-88, holding every stamp but the triple —
# recreated verbatim so a test can hand the store a database that
# genuinely predates the provenance stamp.
LEGACY_SCHEMA = f"""
CREATE TABLE {TRIAL_LEDGER_TABLE} (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    node_id         TEXT NOT NULL,
    campaign_id     TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    charges_budget  BOOLEAN NOT NULL,
    charge_units    REAL NOT NULL DEFAULT 1.0,
    epoch_id        TEXT NOT NULL
);
"""


def _legacy_database(db_path: Path) -> None:
    """Write a pre-triple ledger: the eight-column table, holding one row."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget, charge_units, "
            "epoch_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN), "ok", 1, 1.0, EPOCH),
        )


# -- Every appended row carries its triple --------------------------------------


def test_every_append_persists_the_triple_it_was_given(
    test_ledger: TrialLedger,
) -> None:
    # The feature's own clause: the row the append returns, the row the
    # read hands back, and the row the table holds all name the triple
    # the trial ran under.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert record.evaluator_hash == EVALUATOR_HASH
    assert record.snapshot_hash == SNAPSHOT_HASH
    assert record.cost_model_hash == COST_MODEL_HASH
    assert test_ledger.get(record.seq) == record
    assert [(row.evaluator_hash, row.snapshot_hash, row.cost_model_hash) for row in test_ledger.rows()] == [
        (EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH)
    ]


def test_the_stored_triple_is_the_lowercase_hex_the_char64_columns_hold(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # What the table holds, not what the record reports: CHAR(64) has
    # TEXT affinity and stores the digest verbatim — 64 lowercase hex
    # characters, the sha256 hexdigest's own spelling — because §9.1's
    # node table and the members that computed the digests compare on
    # exactly this text.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    with sqlite3.connect(db_path) as connection:
        stored, e_kind, s_kind, c_kind = connection.execute(
            f"SELECT evaluator_hash, typeof(evaluator_hash), "
            "typeof(snapshot_hash), typeof(cost_model_hash) "
            f"FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == EVALUATOR_HASH
    assert (e_kind, s_kind, c_kind) == ("text", "text", "text")


def test_two_evaluators_land_side_by_side(
    test_ledger: TrialLedger,
) -> None:
    # A campaign whose two trials ran under two frozen evaluators: two
    # charges, two digests, each row its own — the provenance is a fact
    # about the evaluation, not a value restamped on every row.
    first = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
        epoch_id=EPOCH, **PROVENANCE,
    )
    second = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
        epoch_id=EPOCH, evaluator_hash=OTHER_EVALUATOR_HASH,
        snapshot_hash=SNAPSHOT_HASH, cost_model_hash=COST_MODEL_HASH,
    )
    assert [row.evaluator_hash for row in test_ledger.rows()] == [
        first.evaluator_hash,
        second.evaluator_hash,
    ] == [EVALUATOR_HASH, OTHER_EVALUATOR_HASH]


def test_the_debit_persists_the_triple_of_the_charge(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent half of the write surface carries the triple too:
    # the failure path §6.1 debits through the debit, and its charge
    # must be able to name what it ran under.
    record, appended = test_ledger.debit(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert appended is True
    assert record.evaluator_hash == EVALUATOR_HASH
    assert record.snapshot_hash == SNAPSHOT_HASH
    assert record.cost_model_hash == COST_MODEL_HASH
    assert test_ledger.get(record.seq) == record


def test_the_endpoint_carries_the_triple_of_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # POST /ledger/debit's body names the triple; the response's record
    # carries it; the table holds it.
    response = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    assert response.record.evaluator_hash == EVALUATOR_HASH
    assert response.record.snapshot_hash == SNAPSHOT_HASH
    assert response.record.cost_model_hash == COST_MODEL_HASH
    assert test_ledger.get(response.seq) == response.record


# -- The digest's own spelling, however the caller came by it -------------------


def test_uppercase_hex_is_folded_at_every_seam(
    test_ledger: TrialLedger,
) -> None:
    # A hash pasted from a report or a log line is commonly uppercase
    # and means the same value: the append, the debit and the request
    # all fold it to the lowercase hex the CHAR(64) columns hold, the
    # same treatment the evaluator and snapshot members give the
    # sibling columns this row joins against.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH,
        evaluator_hash=EVALUATOR_HASH.upper(),
        snapshot_hash=SNAPSHOT_HASH.upper(),
        cost_model_hash=COST_MODEL_HASH.upper(),
    )
    assert record.evaluator_hash == EVALUATOR_HASH
    assert record.snapshot_hash == SNAPSHOT_HASH
    assert record.cost_model_hash == COST_MODEL_HASH
    assert test_ledger.get(record.seq) == record


def test_surrounding_whitespace_is_stripped_not_refused(
    test_ledger: TrialLedger,
) -> None:
    # The pasted-from-a-report courtesy: whitespace around the digest is
    # not part of the value, and refusing it would punish a spelling
    # that names the same provenance.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH,
        evaluator_hash=f"  {EVALUATOR_HASH} ",
        snapshot_hash=SNAPSHOT_HASH,
        cost_model_hash=COST_MODEL_HASH,
    )
    assert record.evaluator_hash == EVALUATOR_HASH


def test_a_retry_never_restates_the_provenance_of_the_charge(
    test_endpoint: DebitEndpoint,
) -> None:
    # On a retry nothing is written — the triple the charge first named
    # stands exactly as first written, however the retry spelled it,
    # because this is append-only accounting and a charge is never
    # restated.  The retry's spelling is the loser of that rule; callers
    # that need to know which landed read it off the returned record.
    first = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE)
    )
    retry = test_endpoint.post(
        DebitRequest(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH,
            evaluator_hash=OTHER_EVALUATOR_HASH,
            snapshot_hash=SNAPSHOT_HASH, cost_model_hash=COST_MODEL_HASH,
        )
    )
    assert retry.retry is True
    assert retry.record.evaluator_hash == first.record.evaluator_hash == EVALUATOR_HASH


# -- The write is refused when a term cannot name provenance ---------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        f"sha256:{EVALUATOR_HASH}",
        EVALUATOR_HASH[:-1],  # 63: a truncated digest
        EVALUATOR_HASH + "f",  # 65
        "z" * 64,  # hex it is not
        7,
        1.5,
        True,
        [],
        object(),
    ],
)
def test_a_term_that_names_no_provenance_is_refused_at_every_seam(
    test_ledger: TrialLedger, bad: object
) -> None:
    # An absent term (None is the read's spelling, never the write's),
    # a prefixed image reference, a truncated digest, a non-hex token
    # and a non-string all name no evaluator, snapshot or cost model
    # this system recorded — and each is refused at all three seams
    # that accept the triple, before the database is touched.
    with pytest.raises(TrialRecordError, match="evaluator_hash"):
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
            epoch_id=EPOCH, evaluator_hash=bad,
            snapshot_hash=SNAPSHOT_HASH, cost_model_hash=COST_MODEL_HASH,
        )
    with pytest.raises(TrialRecordError, match="snapshot_hash"):
        test_ledger.debit(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
            epoch_id=EPOCH, evaluator_hash=EVALUATOR_HASH,
            snapshot_hash=bad, cost_model_hash=COST_MODEL_HASH,
        )
    with pytest.raises(TrialRecordError, match="cost_model_hash"):
        DebitRequest(
            NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH,
            evaluator_hash=EVALUATOR_HASH, snapshot_hash=SNAPSHOT_HASH,
            cost_model_hash=bad,
        )


@pytest.mark.parametrize("missing", ["evaluator_hash", "snapshot_hash", "cost_model_hash"])
def test_each_term_is_required_individually(
    test_ledger: TrialLedger, missing: str
) -> None:
    # The triple is three facts, and a body that states two of them has
    # still not said what it ran under: the refusal names the one term
    # it is missing, so a caller reading the error learns exactly which
    # provenance it failed to name.
    terms = dict(PROVENANCE)
    del terms[missing]
    with pytest.raises(TrialRecordError, match=f"{missing} is required"):
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
            epoch_id=EPOCH, **terms,
        )


def test_a_refused_charge_spends_no_sequence_number(
    test_ledger: TrialLedger,
) -> None:
    # The refusal happens in the write's validation, before the INSERT
    # — the same guarantee every stamp's refusal holds: a charge that
    # cannot name its provenance is not half-written, and the honest
    # counter's count is not moved by it.
    with pytest.raises(TrialRecordError, match="evaluator_hash is required"):
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH
        )
    assert test_ledger.count() == 0
    landed = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert landed.seq == 1


def test_the_refusal_names_the_epoch_first_when_both_stamps_are_absent(
    test_ledger: TrialLedger,
) -> None:
    # The stamps are validated in the order the features landed, so a
    # write that names neither its epoch nor its provenance is told
    # about the epoch — the earlier feature's refusal — and not a
    # cascade of both at once.  One missing fact, one instruction.
    with pytest.raises(TrialRecordError, match="epoch_id"):
        test_ledger.append(uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP)
    assert test_ledger.count() == 0


# -- The validator's own contract -------------------------------------------------


def test_none_passes_when_the_read_asks() -> None:
    # The read path validates without ``required``: a row that predates
    # the stamp honestly names no provenance, and the validator's None
    # is that statement, not a hash a feature computed.
    assert validated_provenance_hash(None, "evaluator_hash") is None


def test_the_validator_folds_case_and_strips_whitespace() -> None:
    assert (
        validated_provenance_hash(EVALUATOR_HASH.upper(), "evaluator_hash")
        == EVALUATOR_HASH
    )
    assert (
        validated_provenance_hash(f"  {EVALUATOR_HASH} ", "evaluator_hash")
        == EVALUATOR_HASH
    )


def test_the_validator_refuses_an_image_reference_on_its_own_ground() -> None:
    # The prefixed spelling gets the refusal that explains it: a
    # sha256:<hex> digest is an *image reference*, and accepting it
    # would let a caller compare a digest against a hash and get
    # "different" for the wrong reason — feature 71's mismatched-
    # provenance refusal would answer a question nobody asked.
    with pytest.raises(TrialRecordError, match="image reference"):
        validated_provenance_hash(f"sha256:{EVALUATOR_HASH}", "evaluator_hash")


def test_the_columns_are_declared_in_section_8s_order() -> None:
    # One spelling shared by the schema, the legacy upgrade and these
    # tests, in the order §8 declares the triple and the order the
    # table's columns land in.
    assert PROVENANCE_COLUMNS == ("evaluator_hash", "snapshot_hash", "cost_model_hash")


# -- The record is also the read --------------------------------------------------


def test_a_record_that_predates_the_triple_names_none_honestly() -> None:
    # The one seam that tolerates an absent triple: a hand-built record
    # (the read path's shape) names no provenance honestly, and its
    # column tuple carries the NULLs a brought-forward table's upgrade
    # columns hold.  The write's refusal lives at the store and the
    # endpoint, exactly where the feature's sentence puts it.
    record = TrialLedgerRecord(
        seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN,
        outcome=OUTCOME, charges_budget=CHARGES_BUDGET, epoch_id=EPOCH,
    )
    assert record.evaluator_hash is None
    assert record.snapshot_hash is None
    assert record.cost_model_hash is None
    assert record.row()[8:] == (None, None, None)


def test_the_column_tuple_closes_with_the_triple(
    test_ledger: TrialLedger,
) -> None:
    # The record's column tuple is the table's declaration order — the
    # triple closes the row, in §8's own order, and the reader that
    # unpacks it cannot mistake a provenance digest for an identity, a
    # stamp, the outcome, the directive, the unit or the epoch.
    record = test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    assert record.row()[-3:] == (EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH)


# -- The schema: three CHAR(64) columns, NOT NULL, no default ---------------------


def test_the_triple_is_three_char64_columns_not_null_with_no_default(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # §8's DDL for each column is CHAR(64) NOT NULL, with no DEFAULT —
    # the shape that makes the triple the caller's to state, not the
    # table's to presume.  SQLite reports a column's declared type
    # verbatim; the length itself is not enforced by this engine, which
    # is why the write seams and the read hold it.
    test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        rows = {row[1]: row for row in info}
    assert list(rows) == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units", "epoch_id", "evaluator_hash", "snapshot_hash",
        "cost_model_hash",
    ]
    for column in PROVENANCE_COLUMNS:
        _, _, kind, notnull, default, pk = rows[column]
        assert kind == "CHAR(64)"
        assert notnull == 1
        assert default is None
        assert pk == 0


# -- A pre-triple database is upgraded in place -----------------------------------


def test_a_pre_triple_table_is_brought_forward_with_nullable_columns(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The upgrade adds the three columns and refuses to invent a value:
    # SQLite refuses ADD COLUMN … NOT NULL without a non-NULL default,
    # and for the triple no default is honest — 'ok', TRUE and 1.0 each
    # asserted something true of every legacy row, while the only true
    # statement a pre-triple row can make about its provenance is that
    # none was named.  NULL is that statement, and the columns land
    # after the epoch, in §8's declaration order, so a fresh table and
    # a brought-forward one agree on what a reader unpacks.
    _legacy_database(db_path)
    with sqlite3.connect(db_path) as connection:
        columns = [
            row[1]
            for row in connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        ]
        assert "evaluator_hash" not in columns  # the table predates the stamp

    rows = test_ledger.rows()  # the store's connect performs the upgrade
    assert len(rows) == 1
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        after = {row[1]: row for row in info}
    assert list(after)[-3:] == list(PROVENANCE_COLUMNS)
    for column in PROVENANCE_COLUMNS:
        _, _, kind, notnull, default, _ = after[column]
        assert kind == "CHAR(64)"
        assert notnull == 0
        assert default is None


def test_legacy_rows_read_back_with_no_provenance(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The NULL upgrade columns are not a dead end: the row reads back
    # naming no evaluator, no snapshot and no cost model — a statement
    # about the ledger's history, never mistaken for provenance this
    # system recorded, because no placeholder digest could be.
    _legacy_database(db_path)
    (row,) = test_ledger.rows()
    assert row.evaluator_hash is None
    assert row.snapshot_hash is None
    assert row.cost_model_hash is None


def test_a_brought_forward_table_still_requires_the_triple_at_the_write(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The nullable upgrade columns are the *table's* history, not the
    # write's licence: NOT NULL holds for every row this store writes
    # because the write seams refuse a charge that names no provenance
    # — on a brought-forward table exactly as on a fresh one.
    _legacy_database(db_path)
    with pytest.raises(TrialRecordError, match="evaluator_hash is required"):
        test_ledger.append(
            uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH
        )
    landed = test_ledger.append(
        uuid.uuid4(), CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP,
        epoch_id=EPOCH, **PROVENANCE,
    )
    assert landed.seq == 2
    assert [(row.evaluator_hash, row.snapshot_hash, row.cost_model_hash) for row in test_ledger.rows()] == [
        (None, None, None),
        (EVALUATOR_HASH, SNAPSHOT_HASH, COST_MODEL_HASH),
    ]


def test_a_row_whose_provenance_wandered_on_disk_is_refused_by_its_seq(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The read path revalidates through the record constructor, so a row
    # that wandered in from outside the append — here, a hand-edited
    # cost-model hash that names no cost model — is refused rather than
    # served: in an append-only log, one unreadable row is evidence,
    # not noise.
    test_ledger.append(
        NODE, CAMPAIGN, OUTCOME, CHARGES_BUDGET, ts=STAMP, epoch_id=EPOCH, **PROVENANCE
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET cost_model_hash = ? WHERE seq = 1",
            ("z" * 64,),
        )
    with pytest.raises(TrialRecordError, match="seq=1"):
        test_ledger.rows()
