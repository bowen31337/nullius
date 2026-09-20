"""Feature 96: epoch usage counts, from ``epoch_ledger``.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 96: *System
derives epoch usage counts from the epoch_ledger, which returns how many
promotion decisions each sequestered epoch has served.*  These tests hold
the sentence to each clause:

* **from the epoch_ledger**: the read is over ``epoch_ledger`` (feature
  105's table), not over this member's ``trial_ledger`` — so the tests
  build the epoch rows the way the table's own writer does (the migration
  and feature 294's persist) and assert that trialling against
  ``trial_ledger`` moves this figure not at all;
* **how many promotion decisions each sequestered epoch has served**: the
  number is the ``promotion_decisions_served`` column verbatim, per
  epoch, with every sealed epoch reported — a fresh one at ``0``, a
  retired one at what it served;
* **derives**: the view is a read of stored state, recomputed on each
  call, and it refuses rather than resolves a row the table's primary key
  makes impossible.

The invariant docs/nullius-tech-architecture.md §15 names — *"Sequestered
epochs exhausted | Ledger usage count ≥ 3"* — is asserted as arithmetic:
the figure crosses three exactly when the epoch has served its third
decision, which is the moment feature 295 retires it and feature 296's
terminal state becomes reachable.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    EPOCH_LEDGER_TABLE,
    TRIAL_LEDGER_TABLE,
    EpochUsage,
    TrialLedger,
    TrialRecordError,
    derive_epoch_usage,
)

CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
OUTCOME = "ok"

#: Feature 105's DDL, spelled as ``migrations/versions/0110_epoch_ledger.py``
#: spells it.  Re-stated here rather than imported so the suite states the
#: sibling feature's contract it reads against; the migration's own
#: ``statements("sqlite")`` is the authority.
_EPOCH_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS epoch_ledger (
    epoch_id                   TEXT NOT NULL PRIMARY KEY,
    sealed_at                  TIMESTAMPTZ NOT NULL,
    promotion_decisions_served INT NOT NULL DEFAULT 0,
    retired                    BOOLEAN NOT NULL DEFAULT FALSE
)
"""


def _node() -> uuid.UUID:
    return uuid.uuid4()


def _seal(db_path: Path, epoch_id: str, *, served: int = 0, retired: bool = False) -> None:
    """Seal one epoch the way the table's own writers leave it.

    Creates the table if the migration has not (the promotion plugin's
    persist does so idempotently) and inserts one row — the two-column
    insert feature 105's ``DEFAULT 0`` defaults buy, plus the count and
    flag when the caller has something to state.  This is a *sibling*
    feature's write seam; feature 96 owns only the read, so the suite
    reaches for it directly.
    """
    with sqlite3.connect(db_path) as connection:
        connection.execute(_EPOCH_LEDGER_DDL)
        connection.execute(
            f"INSERT INTO {EPOCH_LEDGER_TABLE} "
            "(epoch_id, sealed_at, promotion_decisions_served, retired) "
            "VALUES (?, ?, ?, ?)",
            (epoch_id, STAMP.isoformat(), served, 1 if retired else 0),
        )


def _serve(db_path: Path, epoch_id: str, decisions: int) -> None:
    """Advance an epoch's served count — feature 294's persist, verbatim.

    ``UPDATE``, because that is the writer contract feature 105 states: a
    default fires only at insert, so the promotion plugin re-supplies the
    value on every advance.  The trial ledger's feature-92 wall does not
    reach another table, so this runs on a bare connection.
    """
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {EPOCH_LEDGER_TABLE} SET promotion_decisions_served = ? "
            "WHERE epoch_id = ?",
            (decisions, epoch_id),
        )


# -- The counts come from epoch_ledger ------------------------------------------


def test_a_missing_epoch_ledger_is_an_empty_pool(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # This store does not create epoch_ledger: the table is feature 105's,
    # and a database that has never sealed an epoch genuinely has none.
    # The honest answer is an empty pool — no epochs observed — which is
    # also §15's terminal state rather than a licence to promote.
    view = test_ledger.epoch_usage()
    assert view.counts == ()
    assert view.epochs == ()
    assert len(view) == 0
    assert view.total == 0
    assert bool(view) is False


def test_every_sealed_epoch_is_reported_with_its_served_count(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The sentence's own clause: how many promotion decisions each
    # sequestered epoch has served.  Three epochs, three different
    # counts, each reported verbatim under its own name.
    _seal(db_path, "epoch-7", served=0)
    _seal(db_path, "epoch-8", served=1)
    _seal(db_path, "epoch-9", served=3)

    view = test_ledger.epoch_usage()
    assert view.counts == (("epoch-7", 0), ("epoch-8", 1), ("epoch-9", 3))
    assert view.of("epoch-7") == 0
    assert view.of("epoch-8") == 1
    assert view.of("epoch-9") == 3
    assert view.total == 4
    assert len(view) == 3


def test_a_freshly_sealed_epoch_is_reported_at_zero_not_omitted(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # Feature 105's DEFAULT 0 is "a fact to record as a 0, not an
    # absence", and the pool is a depleting resource: feature 297's
    # remaining-clean-epoch figure has to be *told* the pool's size, not
    # left to infer it from the rows that happen to be non-zero.
    _seal(db_path, "epoch-7")
    view = test_ledger.epoch_usage()
    assert view.of("epoch-7") == 0
    assert "epoch-7" in view.epochs
    assert view.by_epoch == {"epoch-7": 0}
    # A pool of unspent epochs is a real, non-empty resource — unlike
    # KEffective, whose falsiness turns on budget *spent*.
    assert bool(view) is True
    assert len(view) == 1


def test_an_epoch_sealed_after_a_read_appears_on_the_next_read(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The view is derived, not cached: each call reads the table, so the
    # pool's size follows the sealing events rather than whatever was
    # true when the store was constructed.
    assert test_ledger.epoch_usage().counts == ()
    _seal(db_path, "epoch-7")
    assert test_ledger.epoch_usage().epochs == ("epoch-7",)


def test_an_advanced_count_appears_on_the_next_read(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # Feature 294 advances the count with an UPDATE; the derivation reads
    # the current value, so the usage figure tracks the decisions served
    # rather than the epoch's state at sealing time.
    _seal(db_path, "epoch-7")
    assert test_ledger.epoch_usage().of("epoch-7") == 0
    _serve(db_path, "epoch-7", 2)
    assert test_ledger.epoch_usage().of("epoch-7") == 2


# -- The figure is per epoch, and the threshold is readable ----------------------


@pytest.mark.parametrize("decisions", [0, 1, 2, 3, 4, 10])
def test_the_served_count_is_the_stored_column_however_high(
    test_ledger: TrialLedger, db_path: Path, decisions: int
) -> None:
    # Nothing is thresholded, capped or filtered here: feature 295's
    # "≥ 3" refusal and feature 296's terminal state read this number,
    # and a derivation that clamped it would hide the very fact they
    # decide on.  An epoch past its budget still reports what it served.
    _seal(db_path, "epoch-7", served=decisions)
    assert test_ledger.epoch_usage().of("epoch-7") == decisions


def test_the_usage_figure_crosses_three_on_the_third_decision(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # §15's invariant as arithmetic: an epoch is exhausted exactly when
    # its usage count reaches three.  Asserted across all four states so
    # an off-by-one in the read — the failure that would let a spent
    # epoch be selected a fourth time — cannot pass.
    _seal(db_path, "epoch-7")
    for decisions in (0, 1, 2):
        _serve(db_path, "epoch-7", decisions)
        assert test_ledger.epoch_usage().of("epoch-7") < 3
    _serve(db_path, "epoch-7", 3)
    assert test_ledger.epoch_usage().of("epoch-7") >= 3


def test_each_epoch_is_counted_separately(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The grouping key is the epoch: one epoch serving three decisions
    # does not spend another's budget, and a reader asking whether any
    # clean epoch remains must see the difference.
    _seal(db_path, "epoch-7", served=3)
    _seal(db_path, "epoch-8", served=0)
    view = test_ledger.epoch_usage()
    assert view.of("epoch-7") == 3
    assert view.of("epoch-8") == 0
    assert view.total == 3
    assert len(view) == 2


def test_a_retired_epoch_still_reports_what_it_served(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # Retirement does not erase the count.  The ``retired`` column is
    # feature 296's and this derivation deliberately does not read it:
    # hiding a spent epoch's count would understate the pool's burn at
    # exactly the moment an operator asks how the pool got here.
    _seal(db_path, "epoch-7", served=3, retired=True)
    _seal(db_path, "epoch-8", served=1)
    view = test_ledger.epoch_usage()
    assert view.by_epoch == {"epoch-7": 3, "epoch-8": 1}
    assert len(view) == 2


def test_an_epoch_never_sealed_answers_zero(test_ledger: TrialLedger, db_path: Path) -> None:
    # An unsealed epoch and a freshly sealed one give the same answer,
    # because it is the same honest count — and it is the safe one for
    # §15: an epoch this ledger cannot find is an epoch it cannot vouch
    # for as clean.
    _seal(db_path, "epoch-7", served=2)
    assert test_ledger.epoch_usage().of("never-sealed") == 0


# -- The two derived views are two reads over two tables -------------------------


def test_trial_charges_do_not_move_the_epoch_usage(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The point of the feature being its own read: §6.1's step 11 debits
    # a trial and a promotion decision debits an epoch — different
    # events, different tables, different resources.  Charging any number
    # of trials (budget-charging or null) leaves the usage count exactly
    # where it was.
    _seal(db_path, "epoch-7")
    before = test_ledger.epoch_usage().of("epoch-7")
    for budget in (True, False, True, True):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP)
    assert before == 0
    assert test_ledger.epoch_usage().of("epoch-7") == 0
    assert test_ledger.count() == 4
    assert test_ledger.k_effective().total == 3


def test_the_two_views_read_different_tables(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # K_effective reads trial_ledger and counts budget-charging rows;
    # epoch usage reads epoch_ledger and reports stored counts.  Built
    # together so neither can drift into the other: a trial charged in
    # epoch-7 does not appear in the usage view, and an epoch sealed with
    # three decisions served does not appear in K_effective.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP)  # creates the table
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"ALTER TABLE {TRIAL_LEDGER_TABLE} ADD COLUMN epoch_id TEXT")
        connection.execute(f"UPDATE {TRIAL_LEDGER_TABLE} SET epoch_id = 'epoch-7'")
    _seal(db_path, "epoch-8", served=3)

    k = test_ledger.k_effective()
    usage = test_ledger.epoch_usage()
    assert k.by_epoch == {"epoch-7": 1}
    assert usage.by_epoch == {"epoch-8": 3}
    # Neither view names the other's epoch.
    assert k.of("epoch-8") == 0
    assert usage.of("epoch-7") == 0


# -- A row the table cannot hold is refused -------------------------------------


@pytest.mark.parametrize("bad", ["", "   ", None, 7, [], object()])
def test_an_epoch_id_that_names_no_epoch_is_refused(bad: object) -> None:
    # epoch_id is TEXT NOT NULL PRIMARY KEY: the row *is* the sealing
    # event, so an epoch that cannot be named cannot have been
    # sequestered.  Reporting such a key would give every later count a
    # phantom epoch of its own.
    with pytest.raises(TrialRecordError, match="non-empty epoch_id"):
        derive_epoch_usage([(bad, 0)])


@pytest.mark.parametrize("bad", [-1, 1.0, "1", None, b"2"])
def test_a_served_count_that_is_not_a_count_is_refused(bad: object) -> None:
    # The column is INT NOT NULL DEFAULT 0 and counts decisions served;
    # a negative one is a hand that reached past feature 294's advance,
    # and it is the one value that could make a spent epoch read clean.
    with pytest.raises(TrialRecordError, match="non-negative integer"):
        derive_epoch_usage([("epoch-7", bad)])


def test_a_truth_value_is_not_a_decision_count() -> None:
    # bool is an int subclass and True is not a count of promotion
    # decisions — the same discipline the row layer applies to seq.
    with pytest.raises(TrialRecordError, match="non-negative integer"):
        derive_epoch_usage([("epoch-7", True)])


@pytest.mark.parametrize("bad", [None, 1, "epoch-7", ("epoch-7",)])
def test_a_malformed_pair_is_refused(bad: object) -> None:
    with pytest.raises(TrialRecordError, match="\\(epoch, served\\) pair"):
        derive_epoch_usage([bad])


def test_a_repeated_epoch_is_refused_rather_than_resolved() -> None:
    # epoch_id is the table's PRIMARY KEY — feature 105's "unique
    # constraint on epoch_id" — so two entries for one epoch are rows the
    # table cannot hold.  Both silent resolutions are wrong in the
    # direction that matters: summing invents decisions the epoch never
    # served, and last-wins can *lower* a count, which is exactly what
    # would let an exhausted epoch read as clean.
    with pytest.raises(TrialRecordError, match="appears twice"):
        derive_epoch_usage([("epoch-7", 3), ("epoch-7", 0)])


def test_a_duplicate_in_the_table_is_refused_by_the_store_read(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The table enforces the primary key, so reaching this state takes a
    # hand that reached past it (a table created without the key, a
    # rebuilt db).  The refusal is asserted end to end because this is
    # where an operator would actually meet it.
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"CREATE TABLE {EPOCH_LEDGER_TABLE} ("
            "epoch_id TEXT, promotion_decisions_served INT NOT NULL DEFAULT 0)"
        )
        connection.execute(
            f"INSERT INTO {EPOCH_LEDGER_TABLE} VALUES ('epoch-7', 3), ('epoch-7', 0)"
        )
    with pytest.raises(TrialRecordError, match="appears twice"):
        test_ledger.epoch_usage()


# -- The derivation as a value --------------------------------------------------


def test_the_derivation_returns_an_immutable_value() -> None:
    view = derive_epoch_usage([("epoch-7", 2)])
    assert isinstance(view, EpochUsage)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.counts = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        view.by_epoch["epoch-7"] = 99  # type: ignore[index]


def test_equal_derivations_are_equal_values() -> None:
    # Same rows, same view — however they were ordered — so a test or a
    # downstream reader can compare two derivations directly.
    a = derive_epoch_usage([("epoch-7", 0), ("epoch-8", 3)])
    b = derive_epoch_usage([("epoch-8", 3), ("epoch-7", 0)])
    assert a == b
    assert hash(a) == hash(b)


def test_the_epochs_are_sorted_by_name() -> None:
    # One stable order, so a breakdown reads the same way twice.
    view = derive_epoch_usage([("epoch-9", 1), ("epoch-7", 0), ("epoch-10", 2)])
    assert view.epochs == ("epoch-10", "epoch-7", "epoch-9")


def test_an_empty_derivation_is_the_empty_pool() -> None:
    view = derive_epoch_usage([])
    assert view.counts == ()
    assert len(view) == 0
    assert view.total == 0
    assert bool(view) is False


def test_a_hand_built_view_gets_the_same_refusals() -> None:
    # The constructor is the one seam: a caller building a view by hand
    # is held to exactly what the derivation's own path is held to.
    with pytest.raises(TrialRecordError, match="non-empty epoch_id"):
        EpochUsage((("", 0),))  # type: ignore[arg-type]
    with pytest.raises(TrialRecordError, match="non-negative integer"):
        EpochUsage((("epoch-7", -1),))  # type: ignore[arg-type]
