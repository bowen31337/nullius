"""Feature 91: an outcome on every appended trial row.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 91: *System
persists an outcome of ok, timeout, error or tripwire_fail on every
appended trial row.*  These tests hold the sentence to each clause:

* **an outcome … on every appended trial row**: each of the four, given
  to the append or the debit, is the outcome the row holds on read-back
  and the exact text the table stores — a failed evaluation (timeout,
  error, tripwire_fail) lands as honestly as a successful one, which is
  §6.1's "step 11 happens even when the node fails" made countable;
* **ok, timeout, error or tripwire_fail**: the vocabulary is closed and
  canonically spelled — anything else (absent, case-variant, synonym,
  non-string) is refused at the write with
  :class:`~ledger.errors.TrialRecordError`, before any sequence number
  is spent, at every seam that accepts one: the append, the debit, the
  debit request and the record;
* **persists**: the column is part of the table's schema — ``TEXT NOT
  NULL`` with no default, because unlike ``charge_units`` (feature 89,
  "defaulting to 1.0") there is no honest presumption of *how* a trial
  ended — a database written by the pre-outcome schema is upgraded in
  place with 'ok' as the no-recorded-failure spelling, and the
  upgrade's ``ALTER`` passes feature 92's wall because it is neither an
  ``UPDATE`` nor a ``DELETE``;
* and the clause feature 95 lends this one: a retried debit does not
  restate the outcome any more than it restates the stamp — the row
  stands exactly as first written.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    OUTCOMES,
    TRIAL_LEDGER_TABLE,
    DebitEndpoint,
    DebitRequest,
    TrialImmutableError,
    TrialLedger,
    TrialLedgerRecord,
    TrialRecordError,
)
from ledger.store import guarded

NODE = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
CHARGES_BUDGET = True

# The schema this member wrote before feature 91 landed — the four
# columns of features 86-95, recreated verbatim so a test can hand the
# store a database that genuinely predates the outcome.
LEGACY_SCHEMA = f"""
CREATE TABLE {TRIAL_LEDGER_TABLE} (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    node_id     TEXT NOT NULL,
    campaign_id TEXT NOT NULL
);
"""


def _legacy_database(db_path: Path) -> None:
    """Write a pre-outcome ledger: the four-column table, holding one row."""
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} (ts, node_id, campaign_id) "
            "VALUES (?, ?, ?)",
            (STAMP.isoformat(), str(NODE), str(CAMPAIGN)),
        )


# -- Every appended row carries its outcome -----------------------------------


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_every_append_persists_the_outcome_it_was_given(
    test_ledger: TrialLedger, outcome: str
) -> None:
    # The feature's own clause, one pass per vocabulary entry: the row
    # the append returns, the row the read hands back, and the row the
    # table holds all say the same outcome.
    record = test_ledger.append(NODE, CAMPAIGN, outcome, CHARGES_BUDGET, ts=STAMP)
    assert record.outcome == outcome
    assert test_ledger.get(record.seq) == record
    assert [row.outcome for row in test_ledger.rows()] == [outcome]


@pytest.mark.parametrize("outcome", OUTCOMES)
def test_the_stored_outcome_is_the_exactly_spelled_text(
    test_ledger: TrialLedger, db_path: Path, outcome: str
) -> None:
    # What the table holds, not what the record reports: the column's
    # text is the canonical spelling, untransformed — the closed
    # vocabulary is a storage contract, not a display convention.
    record = test_ledger.append(NODE, CAMPAIGN, outcome, CHARGES_BUDGET, ts=STAMP)
    with sqlite3.connect(db_path) as connection:
        (stored,) = connection.execute(
            f"SELECT outcome FROM {TRIAL_LEDGER_TABLE} WHERE seq = ?",
            (record.seq,),
        ).fetchone()
    assert stored == outcome


def test_a_mixture_of_outcomes_persists_row_by_row(
    test_ledger: TrialLedger,
) -> None:
    # A campaign that scored one node, timed one out, crashed one and
    # had one trip the leakage wires: four charges, four outcomes, each
    # row its own — the count stays honest about *what* it counted.
    for outcome in OUTCOMES:
        test_ledger.append(NODE, CAMPAIGN, outcome, CHARGES_BUDGET, ts=STAMP)
    assert [row.outcome for row in test_ledger.rows()] == list(OUTCOMES)


def test_the_debit_persists_the_outcome_of_the_charge(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent half of the write surface carries the stamp too:
    # the failure path §6.1 debits through the debit, not the raw
    # append, and its charge must be classifiable like any other.
    record, appended = test_ledger.debit(NODE, CAMPAIGN, "error", CHARGES_BUDGET, ts=STAMP)
    assert appended is True
    assert record.outcome == "error"
    assert test_ledger.get(record.seq) == record


def test_the_endpoint_carries_the_outcome_of_the_request(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # POST /ledger/debit's body names the outcome; the response's
    # record carries it; the table holds it.
    response = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, "tripwire_fail", CHARGES_BUDGET, ts=STAMP)
    )
    assert response.record.outcome == "tripwire_fail"
    assert test_ledger.get(response.seq) == response.record


def test_the_column_tuple_places_the_outcome_before_the_directive(
    test_ledger: TrialLedger,
) -> None:
    # The record's column tuple is the table's declaration order — the
    # outcome sits where §8 declares it, and the reader that unpacks it
    # cannot mistake it for an identity or a stamp.  The directive (5)
    # and feature 89's unit (6) follow it; each has its own test.
    record = test_ledger.append(NODE, CAMPAIGN, "timeout", CHARGES_BUDGET, ts=STAMP)
    assert record.row()[4] == "timeout"
    assert record.row() == (
        record.seq,
        STAMP.isoformat(),
        str(NODE),
        str(CAMPAIGN),
        "timeout",
        1,
        1.0,
    )


# -- The vocabulary is closed and canonically spelled --------------------------


def test_the_vocabulary_is_the_four_in_spec_order() -> None:
    # §8's own comment spells the column 'ok | timeout | error |
    # tripwire_fail'; the member's one spelling of that set is the same
    # four, in the same order, exported from the package.
    assert OUTCOMES == ("ok", "timeout", "error", "tripwire_fail")


@pytest.mark.parametrize(
    "bad",
    [None, "OK", "Timeout", " Tripwire_Fail", "ok ", "crashed", "failed", "", 42, True, b"ok"],
)
def test_an_outcome_outside_the_four_is_refused_at_every_seam(
    test_ledger: TrialLedger, bad: object
) -> None:
    # One closed vocabulary, enforced wherever an outcome enters the
    # member: the append, the debit, the debit request, the record.  A
    # case variant or a synonym is not canonicalised — folding it would
    # bless a caller whose vocabulary had drifted from the contract,
    # and storing it as-is would fragment every later "how did the
    # trials end?" query.
    with pytest.raises(TrialRecordError, match="outcome must be one of"):
        test_ledger.append(NODE, CAMPAIGN, bad)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="outcome must be one of"):
        test_ledger.debit(NODE, CAMPAIGN, bad)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="outcome must be one of"):
        DebitRequest(NODE, CAMPAIGN, bad)  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="outcome must be one of"):
        TrialLedgerRecord(
            seq=1, ts=STAMP, node_id=NODE, campaign_id=CAMPAIGN, outcome=bad,
            charges_budget=CHARGES_BUDGET,
        )  # type: ignore[arg-type]


def test_the_refusal_names_the_four_accepted_spellings(
    test_ledger: TrialLedger,
) -> None:
    # A caller refused here is a caller that must be told what the four
    # are; the message quotes them in §8's order.
    with pytest.raises(
        TrialRecordError, match="'ok', 'timeout', 'error', 'tripwire_fail'"
    ):
        test_ledger.append(NODE, CAMPAIGN, "aborted")


def test_an_absent_outcome_is_refused_not_defaulted(
    test_ledger: TrialLedger,
) -> None:
    # The one refusal worth naming on its own: the caller that debits a
    # trial without saying how it ended.  Defaulting to 'ok' would
    # record every failed evaluation as a success, which is the exact
    # lie this category exists to make impossible — §8 gives
    # charge_units a default and gives outcome none.
    with pytest.raises(TrialRecordError, match="got None"):
        test_ledger.append(NODE, CAMPAIGN)
    with pytest.raises(TrialRecordError, match="got None"):
        test_ledger.debit(NODE, CAMPAIGN)
    with pytest.raises(TrialRecordError, match="got None"):
        DebitRequest(NODE, CAMPAIGN)
    assert test_ledger.count() == 0


@pytest.mark.parametrize("bad", ["OK", "crashed", 7])
def test_a_refused_outcome_spends_no_sequence_number(
    test_ledger: TrialLedger, bad: object
) -> None:
    # The refusal lands before the database is touched, so a charge
    # that cannot be classified costs nothing: the next honest append
    # draws the very first number.
    with pytest.raises(TrialRecordError):
        test_ledger.append(NODE, CAMPAIGN, bad)  # type: ignore[arg-type]
    assert test_ledger.count() == 0
    assert test_ledger.append(NODE, CAMPAIGN, "ok", CHARGES_BUDGET, ts=STAMP).seq == 1


# -- The retry keeps the original outcome --------------------------------------


def test_a_retry_does_not_restate_the_outcome(
    test_endpoint: DebitEndpoint, test_ledger: TrialLedger
) -> None:
    # The worker died after the row landed; the worker that takes over
    # knows the re-run ended 'ok'.  The row is a fact about the charge
    # first debited — outcome 'error' — and facts are never restated;
    # the response's record says which outcome landed, exactly as it
    # says which stamp landed.
    original = test_endpoint.post(
        DebitRequest(NODE, CAMPAIGN, "error", CHARGES_BUDGET, ts=STAMP)
    )
    retry = test_endpoint.post(DebitRequest(NODE, CAMPAIGN, "ok", CHARGES_BUDGET, ts=STAMP))

    assert retry.seq == original.seq == 1
    assert retry.appended is False
    assert retry.record.outcome == "error"
    assert test_ledger.get(1).outcome == "error"
    assert test_ledger.count() == 1


# -- The schema: the column, its constraint, its place -------------------------


def test_the_outcome_column_is_not_null_with_no_default(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # §8's DDL for the column is TEXT NOT NULL with no default — the
    # shape that makes the outcome the caller's to state, not the
    # table's to presume.  The column sits in the declaration order the
    # record's row() tuple mirrors, before the directive and the unit.
    test_ledger.append(NODE, CAMPAIGN, "ok", CHARGES_BUDGET, ts=STAMP)
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        rows = {row[1]: row for row in info}
    assert list(rows) == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units",
    ]
    # (cid, name, type, notnull, dflt_value, pk) for the outcome column.
    _, _, kind, notnull, default, pk = rows["outcome"]
    assert kind == "TEXT"
    assert notnull == 1
    assert default is None
    assert pk == 0


def test_a_row_whose_outcome_wandered_outside_the_four_is_refused(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The read path revalidates through the record constructor, so a
    # hand-edited outcome — like a hand-edited stamp — is refused
    # rather than served: in an append-only log, one unreadable row is
    # evidence, not noise.
    test_ledger.append(NODE, CAMPAIGN, "ok", CHARGES_BUDGET, ts=STAMP)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET outcome = ? WHERE seq = 1",
            ("fine",),
        )
    with pytest.raises(TrialRecordError, match="seq=1"):
        test_ledger.rows()


# -- A pre-outcome database is upgraded in place -------------------------------


def test_a_pre_outcome_database_is_upgraded_in_place(
    test_database_url: str, db_path: Path
) -> None:
    # CREATE TABLE IF NOT EXISTS cannot evolve the table a database
    # already holds; without the upgrade every append on this database
    # would die on "no column named outcome".  The first operation
    # brings the table forward instead.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].outcome == "ok"
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        columns = [row[1] for row in info]
    # The legacy table held the four columns of features 86-95; the
    # upgrade adds the outcome's successors, the directive and the unit.
    assert columns == [
        "seq", "ts", "node_id", "campaign_id", "outcome", "charges_budget",
        "charge_units",
    ]


def test_the_legacy_default_is_the_no_recorded_failure_spelling(
    test_database_url: str, db_path: Path
) -> None:
    # Rows the pre-outcome append debited recorded no failure — the
    # outcome-bearing charge arrives with this column — so among the
    # four only 'ok' is honest for them: 'timeout', 'error' and
    # 'tripwire_fail' would fabricate a failure the ledger never
    # observed.  The legacy stamp asserts the absence of a recorded
    # failure, nothing more.
    _legacy_database(db_path)
    assert TrialLedger(test_database_url).get(1).outcome == "ok"


def test_the_upgrade_continues_the_sequence_above_the_legacy_rows(
    test_database_url: str, db_path: Path
) -> None:
    # The upgrade adds a column; it drops nothing, restates nothing,
    # spends nothing.  AUTOINCREMENT's high-water mark survives it, so
    # the first post-upgrade charge draws the number after the legacy
    # maximum, exactly as it would have without the outcome.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    record = ledger.append(NODE, CAMPAIGN, "timeout", CHARGES_BUDGET, ts=STAMP)
    assert record.seq == 2
    assert [row.seq for row in ledger.rows()] == [1, 2]
    assert [row.outcome for row in ledger.rows()] == ["ok", "timeout"]


def test_the_upgrade_is_idempotent(test_database_url: str, db_path: Path) -> None:
    # Every connect takes the same path, and a table that already holds
    # the column is left untouched — a second ALTER would be a
    # duplicate-column error, so two clean reads are the proof.
    _legacy_database(db_path)
    ledger = TrialLedger(test_database_url)
    assert ledger.count() == 1
    assert ledger.count() == 1
    with sqlite3.connect(db_path) as connection:
        info = connection.execute(f"PRAGMA table_info({TRIAL_LEDGER_TABLE})")
        assert [row[1] for row in info].count("outcome") == 1


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
        # The wall still refuses what it always refused, after the
        # upgrade has run under it.
        with pytest.raises(TrialImmutableError):
            connection.execute(
                f"UPDATE {TRIAL_LEDGER_TABLE} SET outcome = ? WHERE seq = 1",
                ("error",),
            )
        with pytest.raises(TrialImmutableError):
            connection.execute(f"DELETE FROM {TRIAL_LEDGER_TABLE}")
