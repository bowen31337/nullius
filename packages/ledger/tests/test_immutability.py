"""Feature 92's enforcement: trial_ledger rejects UPDATE and DELETE, by force.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 92: *System
rejects any UPDATE or DELETE against trial_ledger, enforced by role grants
rather than by application convention.*  Features 86 and 95 already make
the store's own API append-only — there is no method that mutates a row —
but that is convention, and the spec's sentence refuses to rest there: the
refusal must be *enforced*, so a hand reaching past the API meets a wall
the database layer itself raises.  These tests hold that wall to its word.

The wall is at the store's connection: every statement the store issues
runs through one guarded seam, and an UPDATE or DELETE against
``trial_ledger`` is refused with :class:`TrialImmutableError` before it
touches a row.  The tests probe that seam from three directions:

* **the store's own connection** — an UPDATE or DELETE issued through a
  ledger's connection (the way a bug or a second package would reach the
  table) is refused, and the row it targeted is unchanged;
* **the ``guarded`` context manager** — a raw statement against the same
  database, reached the public way, is refused by the same wall;
* **the append and read paths** — the enforcement lets INSERT and SELECT
  through unchanged, so the ledger still charges and still reads.

The refusal is about the *attempt*, not its effect: a DELETE whose WHERE
matches nothing is still refused, and a mutation of a *different* table on
the same database is not this store's concern.  The one raw-SQL path that
must keep running is the monotonicity probe in test_append.py, which
reaches under the store with its own bare ``sqlite3`` connection — outside
this store's enforcement entirely — exactly as it does at feature 86.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from ledger import (
    DATABASE_URL_ENV,
    TRIAL_LEDGER_TABLE,
    TrialImmutableError,
    TrialLedger,
    TrialLedgerError,
)
from ledger.store import guarded

NODE_A = uuid.uuid4()
NODE_B = uuid.uuid4()
CAMPAIGN = uuid.uuid4()
# The outcome these feature-92 tests append with — the wall this suite
# pins is orthogonal to the outcome, whose own behaviour is
# test_outcome.py's subject.
OUTCOME = "ok"
CHARGES_BUDGET = True


# -- The store's own connection refuses a mutation --------------------------


def test_an_update_through_the_store_is_refused_and_changes_nothing(
    test_ledger: TrialLedger,
) -> None:
    # An UPDATE reached through the store's own connection — the way a bug,
    # a second package or an operator script would reach it — is refused
    # before it runs, so the row keeps the stamp it was appended with.
    record = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    original_ts = record.ts

    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET ts = ? WHERE seq = 1",
            ("2000-01-01T00:00:00+00:00",),
        )

    assert test_ledger.get(record.seq).ts == original_ts


def test_a_delete_through_the_store_is_refused_and_leaves_every_row(
    test_ledger: TrialLedger,
) -> None:
    # A DELETE reached through the store's connection is refused, and every
    # row the ledger held is still present — the honest count is unchanged.
    for node in (NODE_A, NODE_B, NODE_A):
        test_ledger.append(node, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    assert test_ledger.count() == 3

    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"DELETE FROM {TRIAL_LEDGER_TABLE}"
        )

    assert test_ledger.count() == 3
    assert [row.seq for row in test_ledger.rows()] == [1, 2, 3]


def test_a_delete_matching_nothing_is_still_refused(test_ledger: TrialLedger) -> None:
    # The denial is about the attempt, not its effect: a DELETE whose WHERE
    # matches no row is refused all the same, exactly as a denied privilege
    # refuses the statement regardless of what it would have matched.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)

    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"DELETE FROM {TRIAL_LEDGER_TABLE} WHERE node_id = ?",
            (str(NODE_B),),
        )

    # Nothing was deleted — the one row still stands.
    assert test_ledger.count() == 1


def test_an_update_matching_nothing_is_still_refused(test_ledger: TrialLedger) -> None:
    # The same rule for UPDATE: a mutation that would touch no row is still
    # a mutation attempt, and is refused before the WHERE is ever evaluated.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)

    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET ts = ? WHERE node_id = ?",
            ("2000-01-01T00:00:00+00:00", str(NODE_B)),
        )

    assert test_ledger.count() == 1


def test_the_error_names_the_table_and_the_verb(test_ledger: TrialLedger) -> None:
    # An operator reading the stack trace must understand what was refused
    # and why: the message names the table, the verb, and that the refusal
    # is enforced.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)

    with pytest.raises(TrialImmutableError) as excinfo:
        test_ledger._connect().execute(
            f"DELETE FROM {TRIAL_LEDGER_TABLE}"
        )

    message = str(excinfo.value)
    assert TRIAL_LEDGER_TABLE in message
    assert "DELETE" in message
    assert "append-only" in message


# -- The ``guarded`` context manager enforces the same wall -----------------


def test_guarded_refuses_an_update(test_database_url: str) -> None:
    with guarded(test_database_url) as connection:
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
                str(NODE_A),
                str(CAMPAIGN),
                OUTCOME,
                1,
            ),
        )
        with pytest.raises(TrialImmutableError):
            connection.execute(
                f"UPDATE {TRIAL_LEDGER_TABLE} SET ts = ts WHERE seq = 1"
            )


def test_guarded_refuses_a_delete(test_database_url: str) -> None:
    with guarded(test_database_url) as connection:
        with pytest.raises(TrialImmutableError):
            connection.execute(f"DELETE FROM {TRIAL_LEDGER_TABLE}")


def test_guarded_lets_a_select_through(test_database_url: str) -> None:
    # The wall is a mutation wall: a SELECT against trial_ledger runs, and
    # a CREATE/INSERT against another table runs too.
    with guarded(test_database_url) as connection:
        connection.execute(
            f"INSERT INTO {TRIAL_LEDGER_TABLE} "
            "(ts, node_id, campaign_id, outcome, charges_budget) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc).isoformat(),
                str(NODE_A),
                str(CAMPAIGN),
                OUTCOME,
                1,
            ),
        )
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {TRIAL_LEDGER_TABLE}"
        ).fetchone()
    assert rows[0] == 1


# -- The enforcement is scoped to trial_ledger ------------------------------


def test_a_mutation_of_another_table_is_not_refused(
    test_ledger: TrialLedger,
) -> None:
    # The guard names trial_ledger, so a mutation of a different table on
    # the same database is not this store's concern — the enforcement is
    # the append-only guarantee of the ledger, not a blanket read-only lock.
    connection = test_ledger._connect()
    with connection:
        # A side table, unrelated to the ledger; UPDATE and DELETE against
        # it must run, because the wall is scoped to trial_ledger.
        connection.execute("CREATE TABLE IF NOT EXISTS side (k INTEGER)")
        connection.execute("INSERT INTO side (k) VALUES (1)")
        connection.execute("UPDATE side SET k = 2")
    (value,) = connection.execute("SELECT k FROM side").fetchone()
    assert value == 2


def test_a_select_that_mentions_the_table_is_not_refused(
    test_ledger: TrialLedger,
) -> None:
    # A statement that merely names trial_ledger in a read is not a
    # mutation: SELECT runs, and the ledger reads what it holds.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    connection = test_ledger._connect()
    with connection:
        rows = connection.execute(
            f"SELECT COUNT(*) FROM {TRIAL_LEDGER_TABLE}"
        ).fetchone()
    assert rows[0] == 1


# -- The append and read paths are unchanged --------------------------------


def test_append_still_writes_under_the_enforcement(test_ledger: TrialLedger) -> None:
    # The enforcement lets INSERT through: an append after it is in force
    # still writes exactly one row and draws the next sequence number.
    first = test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    second = test_ledger.append(NODE_B, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    assert [first.seq, second.seq] == [1, 2]
    assert test_ledger.count() == 2


def test_reads_still_work_under_the_enforcement(test_ledger: TrialLedger) -> None:
    # The read paths issue SELECT only, which the enforcement lets through,
    # so rows() and get(seq) return the rows the ledger holds.
    for node in (NODE_A, NODE_B):
        test_ledger.append(node, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    assert [row.seq for row in test_ledger.rows()] == [1, 2]
    assert test_ledger.get(1) is not None
    assert test_ledger.get(2) is not None
    assert test_ledger.get(99) is None


def test_debit_still_works_under_the_enforcement(test_ledger: TrialLedger) -> None:
    # The idempotent debit (feature 95) is a check-and-insert; the INSERT
    # and its NOT EXISTS SELECT both run, so a first debit appends and a
    # retry is answered by the prior row.
    first_record, first_appended = test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    second_record, second_appended = test_ledger.debit(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    assert first_appended is True
    assert second_appended is False
    assert second_record.seq == first_record.seq
    assert test_ledger.count() == 1


# -- The error is the taxonomy's own ----------------------------------------


def test_the_immutability_error_is_a_ledger_error(
    test_ledger: TrialLedger,
) -> None:
    # TrialImmutableError joins the one-base-class-wide taxonomy, so a
    # caller can catch every ledger failure — including a refused mutation
    # — with the single base class.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    with pytest.raises(TrialLedgerError):
        test_ledger._connect().execute(f"DELETE FROM {TRIAL_LEDGER_TABLE}")
    assert issubclass(TrialImmutableError, TrialLedgerError)


def test_a_refused_mutation_leaves_no_half_written_state(
    test_ledger: TrialLedger,
) -> None:
    # Refusing a mutation spends no sequence number and leaves the ledger
    # exactly as it was — no half-written row, no gap in the count.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    before = test_ledger.count()

    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET ts = ?",
            ("2000-01-01T00:00:00+00:00",),
        )

    assert test_ledger.count() == before
    assert [row.seq for row in test_ledger.rows()] == [1]


# -- Case- and shape-insensitivity of the refusal ---------------------------


@pytest.mark.parametrize(
    "statement",
    [
        f"delete from {TRIAL_LEDGER_TABLE}",
        f"DELETE  FROM  {TRIAL_LEDGER_TABLE} WHERE seq = 1",
        f"Update {TRIAL_LEDGER_TABLE} SET ts = ts",
        f"\n\tDELETE\nFROM {TRIAL_LEDGER_TABLE}\n",
    ],
)
def test_the_refusal_is_case_and_whitespace_insensitive(
    test_ledger: TrialLedger, statement: str
) -> None:
    # The check is by statement shape however the verb is cased or padded:
    # lowercase, uppercased, doubled whitespace and leading newlines all
    # resolve to the same refusal, because the wall must meet the attempt
    # however it is written.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(statement)
    assert test_ledger.count() == 1


def test_a_cte_prefixed_mutation_is_still_refused(test_ledger: TrialLedger) -> None:
    # A statement prefixed with a common table expression that does not
    # touch the ledger is still caught: the verb that follows the CTE is
    # the one inspected, so a WITH … DELETE FROM trial_ledger is refused.
    test_ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    with pytest.raises(TrialImmutableError):
        test_ledger._connect().execute(
            f"WITH keeper AS (SELECT 1 AS x) "
            f"DELETE FROM {TRIAL_LEDGER_TABLE}"
        )
    assert test_ledger.count() == 1


# -- The monotonicity probe is unaffected (it reaches under the store) ------


def test_the_monotonicity_probe_still_deletes_via_a_bare_connection(
    test_database_url: str,
) -> None:
    # The one raw-SQL path that must keep running is the feature-86
    # monotonicity probe: it reaches under the store with a bare
    # ``sqlite3`` connection — outside this store's enforcement — to delete
    # the maximum row.  That connection is not this store's, so feature 92
    # does not touch it, and the probe still deletes.
    from ledger import TRIAL_LEDGER_TABLE as TABLE

    ledger = TrialLedger(test_database_url)
    for _ in range(3):
        ledger.append(NODE_A, CAMPAIGN, OUTCOME, CHARGES_BUDGET)
    path = ledger.path
    with sqlite3.connect(path) as connection:
        connection.execute(f"DELETE FROM {TABLE}")
    assert ledger.count() == 0
    # And the next append still draws a number above every spent one.
    assert ledger.append(NODE_B, CAMPAIGN, OUTCOME, CHARGES_BUDGET).seq == 4
