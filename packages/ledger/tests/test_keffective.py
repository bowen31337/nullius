"""Feature 93: ``K_effective`` per epoch, counting only budget-charging trials.

app_spec.xml, "Trial Ledger Append-Only Accounting", feature 93: *System
derives K_effective per epoch by counting only rows with charges_budget
true, so null nodes never inflate the trial count.*  These tests hold the
sentence to each clause:

* **counting only rows with charges_budget true**: a row stamped ``True``
  contributes one to its epoch; a row stamped ``False`` contributes
  nothing, however many of them a campaign ran.  The derived count is
  therefore *not* the ledger's row count, and the tests assert the
  difference explicitly rather than through the derivation alone;
* **per epoch**: the grouping key is the row's ``epoch_id`` (feature 88's
  stamp, required at every write this store makes), and the un-named
  epoch for the rows that predate the stamp — a table the legacy upgrade
  brought forward holds NULL epochs, and the derivation reads them as
  one honest bucket labelled as naming no epoch rather than pretending
  to be one;
* **so null nodes never inflate the trial count**: the feature's whole
  point, tested as an arithmetic fact — charging any number of null nodes
  leaves ``K_effective`` untouched — and as the reason ``charges_budget``
  crossed the barrier as an opaque directive (feature 90) in the first
  place.

Two consequences the derivation states rather than leaves to inference
are tested too: an all-null epoch is reported with a count of ``0``
rather than omitted (the deflation term must be told an epoch contributed
no degrees of freedom), and a corrupted directive is refused rather than
silently skipped — understating ``K`` is the one error direction that
lets a false discovery through.
"""

from __future__ import annotations

import dataclasses
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ledger import (
    TRIAL_LEDGER_TABLE,
    UNNAMED_EPOCH,
    KEffective,
    TrialLedger,
    TrialRecordError,
    derive_k_effective,
)

CAMPAIGN = uuid.uuid4()
OTHER_CAMPAIGN = uuid.uuid4()
STAMP = datetime(2026, 9, 20, 5, 0, 0, tzinfo=timezone.utc)
OUTCOME = "ok"

# The epoch the filter tests charge against — any name would do.  The
# per-epoch grouping tests spell their own epochs ('epoch-7', 'epoch-8')
# because which epoch a row charged is their subject; the epoch's own
# behaviour is test_epoch.py's subject.
EPOCH = "epoch-7"

# The schema this member wrote before feature 88 landed — the table as it
# was through features 86-91, holding every stamp but the epoch, recreated
# verbatim so a test can hand the store a database whose rows genuinely
# predate the epoch stamp.
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


def _node() -> uuid.UUID:
    """A fresh node identity — one evaluation, one charge, one row."""
    return uuid.uuid4()


def _legacy_database(db_path: Path, rows: list[tuple[str, int]]) -> None:
    """Write a pre-epoch ledger: the seven-column table, holding rows.

    Each row is ``(node_id, charges_budget bit)`` — the derivation's
    whole input, stamped the way the pre-88 writer stamped it, which is
    to say not at all: no epoch on any row, because the write seam that
    requires one did not exist yet.
    """
    with sqlite3.connect(db_path) as connection:
        connection.executescript(LEGACY_SCHEMA)
        for node, directive in rows:
            connection.execute(
                f"INSERT INTO {TRIAL_LEDGER_TABLE} "
                "(ts, node_id, campaign_id, outcome, charges_budget, "
                "charge_units) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    STAMP.isoformat(),
                    node,
                    str(CAMPAIGN),
                    "ok",
                    directive,
                    1.0,
                ),
            )


# -- The filter is the feature --------------------------------------------------


def test_only_budget_charging_rows_are_counted(
    test_ledger: TrialLedger,
) -> None:
    # The sentence's own clause: True contributes, False does not.  Two
    # real trials and three null nodes give a K_effective of 2 — and a
    # plain count of 5, which is exactly the inflation the feature exists
    # to prevent.
    for _ in range(2):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH)
    for _ in range(3):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().total == 2
    assert test_ledger.count() == 5


def test_null_nodes_never_inflate_the_trial_count(
    test_ledger: TrialLedger,
) -> None:
    # The feature's whole point, as arithmetic: charging any number of
    # null nodes leaves K_effective exactly where it was.  A campaign
    # running a thousand null nodes has spent compute and no degrees of
    # freedom, and the deflation input must read that way.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH)
    before = test_ledger.k_effective().total
    for _ in range(50):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH)
    assert before == 1
    assert test_ledger.k_effective().total == 1
    assert test_ledger.count() == 51


def test_a_ledger_of_nothing_but_null_nodes_counts_zero(
    test_ledger: TrialLedger,
) -> None:
    # The sharp end: rows exist, budget charged is nil.  K_effective is 0
    # and the view is falsy — the deflation term adds nothing — while the
    # ledger is demonstrably not empty.
    for _ in range(3):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH)
    view = test_ledger.k_effective()
    assert view.total == 0
    assert bool(view) is False
    assert test_ledger.count() == 3


def test_an_empty_ledger_counts_zero(test_ledger: TrialLedger) -> None:
    # No rows at all: no epochs observed, no budget charged.  A caller
    # asking before any trial ran gets an honest zero rather than an
    # error — the same stance the store takes toward an absent store.
    view = test_ledger.k_effective()
    assert view.counts == ()
    assert view.total == 0
    assert view.epochs == ()
    assert bool(view) is False


@pytest.mark.parametrize("outcome", ["ok", "timeout", "error", "tripwire_fail"])
def test_the_count_is_of_outcomes_not_of_successes(
    test_ledger: TrialLedger, outcome: str
) -> None:
    # §6.1's step 11 debits even when the node fails, so a failed trial
    # consumed a hypothesis exactly as a successful one did.  Only
    # charges_budget decides this filter; the outcome never does.
    test_ledger.append(_node(), CAMPAIGN, outcome, True, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().total == 1


def test_a_debit_charges_budget_the_same_as_an_append(
    test_ledger: TrialLedger,
) -> None:
    # The idempotent write path feeds the same derivation: the debit's
    # directive lands on the row, and the row is what is counted.
    test_ledger.debit(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH)
    test_ledger.debit(_node(), CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().total == 1


# -- The count is per epoch -----------------------------------------------------


def test_a_pre_stamp_table_groups_every_row_under_the_unnamed_epoch(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # A table written before feature 88's stamp landed holds rows that
    # name no epoch — the legacy upgrade brings the column forward, but
    # no value could honestly fill it — so every row groups under the
    # un-named epoch: one honest bucket, labelled as naming no epoch
    # rather than pretending to be one.
    _legacy_database(db_path, [(str(_node()), 1), (str(_node()), 0)])
    view = test_ledger.k_effective()
    assert view.counts == ((UNNAMED_EPOCH, 1),)
    assert view.epochs == (UNNAMED_EPOCH,)
    assert view.of(UNNAMED_EPOCH) == 1
    assert UNNAMED_EPOCH is None


def test_the_derivation_groups_by_the_epoch_each_row_charged(
    test_ledger: TrialLedger,
) -> None:
    # Feature 88's stamp is on every row the store writes now, and the
    # derivation is a genuine per-epoch view over them: rows are counted
    # into the epoch each one charged, and the filter still holds inside
    # each epoch.
    first, second, third = _node(), _node(), _node()
    test_ledger.append(first, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7")
    test_ledger.append(second, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id="epoch-7")
    test_ledger.append(third, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-8")

    view = test_ledger.k_effective()
    assert view.of("epoch-7") == 1
    assert view.of("epoch-8") == 1
    assert view.total == 2
    assert view.by_epoch == {"epoch-7": 1, "epoch-8": 1}


def test_an_all_null_epoch_is_reported_at_zero_not_omitted(
    test_ledger: TrialLedger,
) -> None:
    # An epoch whose every trial was a null node charged no degrees of
    # freedom, and the deflation term must be *told* that rather than
    # left to infer it from a missing key — a key a reader has to infer
    # is a key a reader can silently get wrong.  So the epoch is listed,
    # at zero.
    charged, nulled = _node(), _node()
    test_ledger.append(charged, CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7")
    test_ledger.append(nulled, CAMPAIGN, OUTCOME, False, ts=STAMP, epoch_id="epoch-8")

    view = test_ledger.k_effective()
    assert view.of("epoch-8") == 0
    assert "epoch-8" in view.epochs
    assert view.by_epoch == {"epoch-7": 1, "epoch-8": 0}
    assert view.total == 1


def test_an_epoch_never_observed_answers_zero(test_ledger: TrialLedger) -> None:
    # An unobserved epoch and an observed all-null epoch give the same
    # answer, because it is the same honest count — were they to differ,
    # a reader's arithmetic would depend on whether a campaign had
    # bothered to run the epoch's null nodes.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().of("never-run") == 0


def test_the_same_epoch_across_two_campaigns_is_one_epoch(
    test_ledger: TrialLedger,
) -> None:
    # The grouping key is the epoch, not the campaign: sequestered epochs
    # are a global, non-renewable resource (§6.1), so two campaigns'
    # trials in one epoch spend the same degrees of freedom and are
    # counted together.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7")
    test_ledger.append(
        _node(), OTHER_CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id="epoch-7"
    )
    assert test_ledger.k_effective().of("epoch-7") == 2


# -- The derivation as a value --------------------------------------------------


def test_an_all_null_epoch_reports_a_zero_without_vanishing() -> None:
    # The pure derivation states the same rule the store's read does: an
    # epoch is recorded by its first *row*, not by its first charge.
    view = derive_k_effective(
        [("epoch-7", True), ("epoch-8", False), ("epoch-7", False)]
    )
    assert view.counts == (("epoch-7", 1), ("epoch-8", 0))
    assert view.total == 1
    assert len(view) == 2


def test_the_derivation_returns_an_immutable_value() -> None:
    # The view is a statement about the ledger at one moment; editing it
    # in place would be restating a derivation, and the honest counter
    # restates nothing.
    view = derive_k_effective([("epoch-7", True)])
    assert isinstance(view, KEffective)
    with pytest.raises(dataclasses.FrozenInstanceError):
        view.counts = ()  # type: ignore[misc]
    # The mapping handed out cannot reach back into the view either.
    with pytest.raises(TypeError):
        view.by_epoch["epoch-7"] = 99  # type: ignore[index]


def test_equal_derivations_are_equal_values() -> None:
    # Same trials, same view — however the pairs were ordered — so a test
    # or a downstream term can compare two derivations directly.
    a = derive_k_effective([("epoch-7", True), ("epoch-8", True)])
    b = derive_k_effective([("epoch-8", True), ("epoch-7", True)])
    assert a == b
    assert hash(a) == hash(b)


def test_the_unnamed_epoch_sorts_before_the_named_ones() -> None:
    # One stable order, so a breakdown reads the same way twice: the
    # un-named bucket first (it is not an epoch a caller named), then the
    # epochs ascending.
    view = derive_k_effective(
        [("epoch-9", True), (None, True), ("epoch-7", True)]
    )
    assert view.epochs == (None, "epoch-7", "epoch-9")


def test_repeated_pairs_for_one_epoch_accumulate() -> None:
    # Each pair is one trial, so a flat sequence is summed into the
    # epoch's count rather than the last pair winning.
    view = derive_k_effective([("epoch-7", True), ("epoch-7", True)])
    assert view.of("epoch-7") == 2


def test_a_stored_0_or_1_reads_as_its_bool() -> None:
    # The projection arrives from a SQLite BOOLEAN column, so the same
    # 0/1 coercion the row layer applies applies here.
    assert derive_k_effective([("epoch-7", 1), ("epoch-7", 0)]).of("epoch-7") == 1


# -- A corrupted or malformed input is refused ----------------------------------


@pytest.mark.parametrize("bad", [None, 2, "true", "True", "", 1.0, b"1"])
def test_a_corrupted_directive_is_refused_not_discounted(bad: object) -> None:
    # A stored value that is neither 0 nor 1 is a hand that reached past
    # the append.  Skipping it would look safe and would silently shrink
    # the deflation input — the one direction the honest counter must
    # never move by accident — so it is refused instead.
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        derive_k_effective([("epoch-7", bad)])


def test_a_corrupted_directive_on_disk_is_refused_by_the_store_read(
    test_ledger: TrialLedger, db_path: Path
) -> None:
    # The store's read is where an operator actually meets the
    # corruption, so the refusal is asserted end to end: a row whose
    # stored directive wandered off the bit makes the derivation refuse
    # rather than under-count.
    test_ledger.append(_node(), CAMPAIGN, OUTCOME, True, ts=STAMP, epoch_id=EPOCH)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"UPDATE {TRIAL_LEDGER_TABLE} SET charges_budget = 2 WHERE seq = 1"
        )
    with pytest.raises(TrialRecordError, match="charges_budget must be a bool"):
        test_ledger.k_effective()


@pytest.mark.parametrize("bad", ["", "   ", 7, [], object()])
def test_an_epoch_key_that_names_no_epoch_is_refused(bad: object) -> None:
    # epoch_id is TEXT NOT NULL, so an empty or blank spelling names no
    # epoch; becoming a bucket of its own would report a phantom epoch to
    # every later count.
    with pytest.raises(TrialRecordError, match="epoch_id grouping key"):
        derive_k_effective([(bad, True)])


@pytest.mark.parametrize("bad", [-1, 1.0, "1", None])
def test_a_hand_built_count_must_be_a_non_negative_int(bad: object) -> None:
    # A caller that builds a view by hand gets the same refusals the
    # derivation's own path gets — the constructor is the one seam.
    with pytest.raises(TrialRecordError, match="non-negative integer"):
        KEffective((("epoch-7", bad),))  # type: ignore[arg-type]


def test_a_truth_value_is_not_a_count() -> None:
    # bool is an int subclass, and True is not a trial count — the same
    # discipline the row layer applies to seq.
    with pytest.raises(TrialRecordError, match="non-negative integer"):
        KEffective((("epoch-7", True),))  # type: ignore[arg-type]


# -- The derived view is the store's, and the plain count is not it -------------


def test_the_gap_between_the_two_reads_is_exactly_the_null_nodes(
    test_ledger: TrialLedger,
) -> None:
    # The two reads are one state seen two ways, asserted against the
    # same ledger so neither can drift into the other — and the *gap*
    # between them is the fact the feature is about: the plain count
    # exceeds K_effective by exactly the null nodes that ran, no more
    # and no less.
    for budget in (True, False, False, True, False):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP, epoch_id=EPOCH)
    view = test_ledger.k_effective()
    null_nodes = 3
    assert view.total == 2
    assert test_ledger.count() == 5
    assert test_ledger.count() - view.total == null_nodes
    assert view.of(EPOCH) == view.total


def test_the_derivation_reads_the_log_in_sequence_order(
    test_ledger: TrialLedger,
) -> None:
    # The view is built by walking the log, so it is order-insensitive by
    # construction — the counts are what the log *says*, not where a row
    # happened to sit.  Asserted over a ragged interleaving so a
    # first-row-wins bug could not pass.
    for budget in (True, False, True, False, False, True):
        test_ledger.append(_node(), CAMPAIGN, OUTCOME, budget, ts=STAMP, epoch_id=EPOCH)
    assert test_ledger.k_effective().total == 3
    assert test_ledger.count() == 6
