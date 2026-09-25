"""Feature 340's act: reconciling realized fill costs against modeled ones.

app_spec.xml, "Forward-Test Tracking", feature 340: *System reconciles
realized fill costs against modeled costs in basis points, persisting the
difference per rebalance.*  These tests pin the four halves of that
sentence:

* **reconciles** — the store computes the difference between the two
  figures it is handed, and there is no spelling anywhere in the API at
  which a caller may state one; the sign of what lands is the fact (prd's
  *cost model optimism* is one of the two directions, and only the other
  one is good news);
* **realized against modeled** — both sides land beside the difference
  they produced, because §6.2's divergence and §15's repair (*reconcile
  the cost model*) both need the evidence, not just the verdict;
* **in basis points** — the figures are finite reals, refused rather than
  bounded or clamped, with ``bool`` and NaN refused by name and no sign
  bound at all;
* **per rebalance** — one row per ``(book_id, rebalance_ts)`` pair, the
  pair feature 309 persists and feature 316 hashes: a retry is answered by
  the standing row, a disagreement is refused, the sweep reads in the
  rebalances' own order — and the record's own ``realized_cost_bps``
  column stays NULL, because a book-level figure is not this member's to
  allocate across signal-days.
"""

from __future__ import annotations

import datetime as dt
import inspect
import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import forward.reconciliation
import pytest
from conftest import code_of
from forward import (
    DATABASE_URL_ENV,
    FORWARD_COST_RECONCILIATION_TABLE,
    CostReconciliation,
    ForwardCostReconciliations,
    ForwardIdentityError,
    ForwardReconciliationError,
    ForwardStoreError,
    reconcile_fill_costs,
    reconciled_fill_costs,
)
from forward.record import _sqlite_path

#: The book every test reconciles for, and the rebalances it reconciles —
#: fixed instants after the suite's promotion boundary, so a reconciliation
#: never trips over a record fixture's dates by accident: the two grains are
#: independent by design and the constants keep them visibly so.
BOOK = "alpha-book"
OTHER_BOOK = "beta-book"
REBALANCE = dt.datetime(2026, 3, 5, 9, 30, 0, tzinfo=dt.UTC)
REBALANCE_LATER = dt.datetime(2026, 3, 6, 9, 30, 0, tzinfo=dt.UTC)
REBALANCE_EARLIER = dt.datetime(2026, 3, 4, 9, 30, 0, tzinfo=dt.UTC)

#: The one UTC spelling the table must hold, stated as a literal beside the
#: instants above so a conftest or constant change that moved one without
#: the other fails here rather than quietly re-spelling every key.
REBALANCE_TEXT = "2026-03-05T09:30:00+00:00"


@pytest.fixture
def reconciliations(database_url: str) -> ForwardCostReconciliations:
    """The reconciliation store over this test's own fresh database.

    No schema is brought up by the fixture — the store's first act is what
    creates the table (the member-owned DDL runs on connect), which is what
    lets the "no file after a refusal" test below ask its question of a
    genuinely fresh database.
    """
    return ForwardCostReconciliations(database_url)


def _raw_rows(database_url: str) -> list[tuple]:
    """Read the ledger raw, so a test can see what actually landed.

    A raw ``SELECT`` rather than a store verb, for the reason
    :func:`conftest.forward_rows` states about the record's own table: the
    point of most of these assertions is what the *table* holds — the
    stored difference, the minted sequence, the exact spelling of the key —
    and a test that asked the store would be asking the code under test to
    confirm itself.
    """
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection:
        return connection.execute(
            f"SELECT sequence, book_id, rebalance_ts, realized_cost_bps, "
            f"modeled_cost_bps, difference_bps, recorded_at "
            f"FROM {FORWARD_COST_RECONCILIATION_TABLE} ORDER BY sequence"
        ).fetchall()


def _raw_exec(database_url: str, sql: str, parameters: tuple = ()) -> None:
    """Hand-edit the ledger, the way no tool this member vouches for would.

    For the read-face refusals: SQLite's columns are dynamically typed and
    the table is writable by any tool that can open the file, so the row
    contract has to hold at the read too — and the honest way to test that
    is to corrupt a row exactly as a foreign hand would and read it back.
    """
    with closing(sqlite3.connect(_sqlite_path(database_url))) as connection, connection:
        connection.execute(sql, parameters)


# -- The feature's sentence -----------------------------------------------------


def test_the_store_computes_the_difference_and_never_asks_for_it(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # "Reconciles" is an act the store performs, not a fact the caller
    # states.  There is no parameter for a difference at any spelling —
    # not on the store's verb, not on the module-level one — because a
    # caller-supplied difference would let the table persist two figures
    # and a third that disagrees with both: an unreconciled claim, held on
    # trust.  The same holds for recorded_at: the moment the row was
    # written is the store's own fact, and a caller that could state it
    # could forge the batch-vs-live gap the two stamps make readable.
    for verb in (
        ForwardCostReconciliations.reconcile,
        reconcile_fill_costs,
    ):
        parameters = inspect.signature(verb).parameters
        assert "difference_bps" not in parameters, verb
        assert "recorded_at" not in parameters, verb
    record, created = reconciliations.reconcile(
        BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.25,
    )
    assert created is True
    # Computed, exactly, in the unit the columns name — and narrowed to the
    # float the REAL column holds, so the retry comparison is a comparison
    # of two floats rather than of a float and whatever the caller's
    # library handed over.
    assert record.difference_bps == 4.5 - 3.25
    assert isinstance(record.difference_bps, float)
    # An int figure answers its float: the store narrows on the way in.
    narrowed, _ = reconciliations.reconcile(
        OTHER_BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=12,
        modeled_cost_bps=5,
    )
    assert narrowed.difference_bps == 7.0


def test_both_sides_land_beside_the_difference_they_produced(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # §6.2's divergence is a fact about *two* figures, and §15's repair
    # ("reconcile the cost model") needs the evidence, not just the
    # verdict: a recalibration that knew only "1.25 bps off" could not say
    # whether the model was optimistic about a cheap rebalance or honest
    # about an expensive one.  So the row carries both sides beside the
    # difference, and the raw table is where that is asserted.
    reconciliations.reconcile(
        BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.25,
    )
    (row,) = _raw_rows(database_url)
    sequence, book, moment, realized, modeled, difference, recorded = row
    assert sequence == 1
    assert book == BOOK
    assert moment == REBALANCE_TEXT
    assert realized == 4.5
    assert modeled == 3.25
    assert difference == 1.25
    # The write's own stamp is an ISO moment the read-back can parse —
    # and not the rebalance's: the two stamps are two facts.
    stamped = dt.datetime.fromisoformat(recorded)
    assert stamped.tzinfo is not None
    assert stamped != REBALANCE


def test_the_sign_of_the_difference_carries_the_direction(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # prd's risk register names *cost model optimism* — the model charged
    # less than the fills cost — as the failure this feature watches for,
    # and optimism is one of the two directions a difference can point.
    # The other direction (the model overcharging) wastes capacity but
    # lies to nobody, and a perfectly calibrated model is a third state
    # distinct from both.  All three are persisted, none is refused, and
    # the readable name answers the question the register actually asks.
    optimistic, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE_EARLIER, realized_cost_bps=6.0, modeled_cost_bps=4.0
    )
    pessimistic, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.0, modeled_cost_bps=5.0
    )
    calibrated, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE_LATER, realized_cost_bps=4.0, modeled_cost_bps=4.0
    )
    assert optimistic.difference_bps == 2.0
    assert optimistic.modeled_understates is True
    assert pessimistic.difference_bps == -1.0
    assert pessimistic.modeled_understates is False
    assert calibrated.difference_bps == 0.0
    assert calibrated.modeled_understates is False  # zero is not optimism
    # Both figures may be negative — fills that improved on their
    # benchmark against a venue that rebates — and no sign bound refuses
    # the good news an honest reconciliation sometimes carries.
    negative, _ = reconciliations.reconcile(
        OTHER_BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=-1.0,
        modeled_cost_bps=-2.0,
    )
    assert negative.difference_bps == 1.0
    assert negative.modeled_understates is True
    # And the summary is a sentence an operator can grep the ledger by,
    # naming the direction in the register's own terms.
    assert "model understates" in optimistic.summary
    assert "does not understate" in calibrated.summary
    assert BOOK in optimistic.summary
    assert str(optimistic.difference_bps) in optimistic.summary


def test_a_retried_rebalance_is_answered_by_the_standing_row(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # One row per rebalance, and the retry is the worker that died after
    # the row landed but before the response made it back — the same
    # semantics open_record establishes one feature earlier.  The retry
    # moves nothing: not the figures, not the stamps, not the sequence,
    # and the raw table still holds exactly one row for the rebalance.
    first, created_first = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    assert created_first is True
    after_first = _raw_rows(database_url)
    second, created_second = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    assert created_second is False
    assert second == first  # frozen value equality, sequence and stamps included
    assert second.recorded_at == first.recorded_at  # the standing row's own stamp
    assert _raw_rows(database_url) == after_first  # the retry moved nothing at all


def test_the_same_instant_stated_in_another_offset_is_the_same_rebalance(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The key's spelling is the store's, not the caller's: every
    # rebalance_ts this store writes goes through one UTC rendering, so
    # 11:30+02:00 and 09:30+00:00 — one instant — are one row, never two.
    # A ledger that let the caller's offset choose the key would file one
    # rebalance under two spellings and answer "no reconciliation" for
    # the second spelling of a rebalance that holds one.
    reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    two_hours_ahead = REBALANCE.astimezone(
        dt.timezone(dt.timedelta(hours=2))
    )
    assert two_hours_ahead.isoformat() != REBALANCE.isoformat()  # another spelling...
    assert two_hours_ahead == REBALANCE  # ...of the same instant
    answered, created = reconciliations.reconcile(
        BOOK,
        rebalance_ts=two_hours_ahead,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.0,
    )
    assert created is False
    assert answered.rebalance_ts == REBALANCE  # and the row's instant is the value's
    assert len(_raw_rows(database_url)) == 1


def test_a_disagreement_with_the_standing_row_is_refused(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The per-rebalance face of the identity law: a rebalance happened
    # once and its divergence is one fact, so a second reconciliation
    # naming *different* figures is two claims about one rebalance's
    # costs, and the store refuses to choose between them — last-wins
    # would revise a divergence feature 338's β₄ recalibration may already
    # have consumed, and first-wins would hand the caller a response whose
    # figures contradict the fills it just watched, which looks like
    # success.  The refusal is the identity error (the law's own class,
    # not the store's), and it leaves the standing row untouched.
    standing, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    with pytest.raises(ForwardIdentityError) as excinfo:
        reconciliations.reconcile(
            BOOK, rebalance_ts=REBALANCE, realized_cost_bps=5.5, modeled_cost_bps=3.0
        )
    message = str(excinfo.value)
    assert "forward_record_already_open" in message  # the law's one greppable word
    assert str(standing.sequence) in message  # names the standing row
    assert REBALANCE_TEXT in message
    rows = _raw_rows(database_url)
    assert len(rows) == 1
    assert rows[0][3] == 4.5  # the ledger still holds the first measurement


def test_two_rebalances_are_two_rows(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # "Per rebalance" cuts both ways: the law is one row *per rebalance*,
    # not one row per book, because §16's metric and §13.4's recalibration
    # read the divergence of every rebalance.  Two instants, one book —
    # two rows, two sequences, both sweeps answering both.
    first, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    second, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE_LATER, realized_cost_bps=5.5, modeled_cost_bps=3.0
    )
    assert first.sequence != second.sequence
    rows = _raw_rows(database_url)
    assert [row[0] for row in rows] == [first.sequence, second.sequence]
    assert [row[2] for row in rows] == [REBALANCE_TEXT, "2026-03-06T09:30:00+00:00"]


def test_two_books_at_one_instant_keep_the_order_they_were_reconciled_in(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # The sequence tiebreak: two books can rebalance at the same instant
    # (two deployments of one book, or a shared venue clock), and the only
    # order those two rows have is the order they were reconciled in —
    # which is what AUTOINCREMENT's never-reuse monotone key holds, and
    # what the sweep's tiebreak reads.
    alpha, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    beta, _ = reconciliations.reconcile(
        OTHER_BOOK, rebalance_ts=REBALANCE, realized_cost_bps=1.5, modeled_cost_bps=1.0
    )
    assert alpha.sequence < beta.sequence
    swept = reconciliations.reconciliations()
    assert [row.book_id for row in swept] == [BOOK, OTHER_BOOK]
    assert [row.sequence for row in swept] == [alpha.sequence, beta.sequence]


def test_the_sweep_answers_in_the_rebalances_own_order(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # §13.4's recalibration consumes these rows in the order the
    # rebalances *happened*, so that is the order the sweep answers in —
    # not the order the writes landed, not the order a batch accounting
    # ran in.  A reconciliation computed late still takes its place at its
    # rebalance's moment, because the sweep answers "when did trading
    # diverge from its model", not "when did we find out".
    reconciliations.reconcile(  # landed third, happened first
        BOOK, rebalance_ts=REBALANCE_LATER, realized_cost_bps=7.0, modeled_cost_bps=3.0
    )
    reconciliations.reconcile(  # landed first, happened second
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.0, modeled_cost_bps=3.0
    )
    reconciliations.reconcile(  # landed second, happened last
        OTHER_BOOK,
        rebalance_ts=REBALANCE_EARLIER,
        realized_cost_bps=5.0,
        modeled_cost_bps=3.0,
    )
    swept = reconciliations.reconciliations()
    assert [row.rebalance_ts for row in swept] == [
        REBALANCE_EARLIER,
        REBALANCE,
        REBALANCE_LATER,
    ]


def test_the_ledgers_numbers_are_never_reused(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # AUTOINCREMENT is the ledger's own law stated where a raw row
    # disposal cannot quietly break it: a reconciliation number an
    # operator cites in a recalibration report names one row for the life
    # of the table.  Delete a row by hand and the next reconciliation
    # still mints a number the deleted one wore — sqlite_sequence
    # remembers, and a MAX()+1 key would not.
    first, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.0, modeled_cost_bps=3.0
    )
    second, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE_LATER, realized_cost_bps=5.0, modeled_cost_bps=3.0
    )
    assert (first.sequence, second.sequence) == (1, 2)
    _raw_exec(
        database_url,
        f"DELETE FROM {FORWARD_COST_RECONCILIATION_TABLE} WHERE sequence = ?",
        (first.sequence,),
    )
    third, _ = reconciliations.reconcile(
        OTHER_BOOK,
        rebalance_ts=REBALANCE_EARLIER,
        realized_cost_bps=6.0,
        modeled_cost_bps=3.0,
    )
    assert third.sequence == 3  # not 1 — the number is retired, not recycled


def test_the_row_renders_as_the_table_holds_it(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # The mapping rendering names the same things the same way the row
    # does — the discipline every record in this workspace follows — so
    # an operator joining a rendered reconciliation to the raw table
    # writes one join, not a translation.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    rendered = record.row()
    assert set(rendered) == {
        "sequence",
        "book_id",
        "rebalance_ts",
        "realized_cost_bps",
        "modeled_cost_bps",
        "difference_bps",
        "recorded_at",
    }
    assert rendered["rebalance_ts"] == REBALANCE_TEXT
    assert rendered["difference_bps"] == 1.5
    assert rendered["sequence"] == record.sequence


# -- The reads ------------------------------------------------------------------


def test_get_answers_one_rebalance_or_none(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # The point read — the operator path for "what did *this* rebalance's
    # fills cost against its model?".  None is the honest absent answer
    # (the rebalance was never reconciled), not an error: presence is the
    # write path's law to hold.  And the read normalises the instant the
    # way the write does, so an offset-stated rebalance finds its row.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    assert reconciliations.get(book_id=BOOK, rebalance_ts=REBALANCE) == record
    two_hours_ahead = REBALANCE.astimezone(dt.timezone(dt.timedelta(hours=2)))
    assert reconciliations.get(book_id=BOOK, rebalance_ts=two_hours_ahead) == record
    assert reconciliations.get(book_id=BOOK, rebalance_ts=REBALANCE_LATER) is None
    assert reconciliations.get(book_id=OTHER_BOOK, rebalance_ts=REBALANCE) is None


def test_history_answers_one_book_in_its_own_order(
    reconciliations: ForwardCostReconciliations,
) -> None:
    # The operator path for "is this book's cost model drifting?" — one
    # book's divergences in the order its rebalances happened, which is
    # the order a drift appears in, and no other book's rows mixed in.
    # A book that states nothing is refused rather than answered with an
    # empty history, because an empty history and an unaskable one are
    # different facts an operator must not have to tell apart by
    # re-reading their own argument.
    reconciliations.reconcile(
        OTHER_BOOK, rebalance_ts=REBALANCE, realized_cost_bps=1.0, modeled_cost_bps=1.0
    )
    reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE_LATER, realized_cost_bps=5.0, modeled_cost_bps=3.0
    )
    reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.0, modeled_cost_bps=3.0
    )
    history = reconciliations.history(BOOK)
    assert [row.rebalance_ts for row in history] == [REBALANCE, REBALANCE_LATER]
    assert all(row.book_id == BOOK for row in history)
    with pytest.raises(ForwardReconciliationError):
        reconciliations.history("   ")


# -- The store and its seam ------------------------------------------------------


def test_the_store_is_built_over_the_composed_store_or_any_duck_one(
    database_url: str,
) -> None:
    # The bridge from the seat: one question — "what is the composed
    # forward-record store?" — and this act holds the writer for the same
    # database the record and its observations landed in.  The attribute
    # is the seam, not a class: the loader imports a member under a
    # synthetic name, so the composed store is structurally a
    # ForwardRecords and never the same class object a direct import
    # yields, and an isinstance would defeat the composition this
    # workspace runs on.
    from forward import ForwardRecords

    composed = ForwardRecords(database_url)
    over_composed = ForwardCostReconciliations.over(composed)
    assert over_composed.database_url == composed.database_url
    over_duck = ForwardCostReconciliations.over(
        SimpleNamespace(database_url=database_url)
    )
    assert over_duck.database_url == database_url
    with pytest.raises(TypeError):
        ForwardCostReconciliations.over(SimpleNamespace())


def test_resolve_reads_the_url_the_deployment_names() -> None:
    # The composed-component resolution: DATABASE_URL names the store, an
    # empty or whitespace value counts as unset, and absent is a
    # discoverable deployment state (no component composes) rather than an
    # exception — the stance every store in this workspace takes.
    assert ForwardCostReconciliations.resolve({}) is None
    assert ForwardCostReconciliations.resolve({"DATABASE_URL": "   "}) is None
    resolved = ForwardCostReconciliations.resolve({"DATABASE_URL": "sqlite:///x.db"})
    assert resolved is not None
    assert resolved.database_url == "sqlite:///x.db"
    assert ForwardCostReconciliations.resolve({"DATABASE_URL": "sqlite:///x.db "}) is not None


def test_a_second_store_over_the_same_database_reads_what_the_first_wrote(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # There is no cache, on purpose: the readers these rows exist for
    # (feature 338's recalibration, §16's metric, an operator a quarter
    # later) all run in another process entirely, so the rows are the only
    # record and every store over the URL must read them — including one
    # constructed after the writes, which has never seen this process at
    # all.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    later = ForwardCostReconciliations(database_url)
    assert later.reconciliations() == (record,)
    assert later.get(book_id=BOOK, rebalance_ts=REBALANCE) == record


def test_the_reconciliation_lands_beside_the_record_and_never_touches_it(
    opened_record, promoted_signal, forward_rows
) -> None:
    # The grain decision, pinned from both sides at once: the
    # reconciliation lands in *the same database* the record lives in —
    # one URL, the composed store's own — and touches neither the record
    # nor its columns.  A rebalance is a book-level act naming no column
    # of a signal-day table, and 0108's nullable realized_cost_bps stays
    # NULL for whoever owns that aggregation: this store allocating one
    # book-level figure across signal-days would be a fabrication no spec
    # states.
    ledger = ForwardCostReconciliations.over(promoted_signal)
    _record, created = ledger.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    assert created is True
    rows = forward_rows()
    assert len(rows) == 1  # the record 332 opened, and nothing appended to it
    assert rows[0]["realized_cost_bps"] is None
    assert rows[0]["live_ic"] is None
    # Both tables stand in the one database: coexistence by construction,
    # neither member naming the other's schema.
    with closing(
        sqlite3.connect(_sqlite_path(promoted_signal.database_url))
    ) as raw:
        tables = {
            name for (name,) in raw.execute("SELECT name FROM sqlite_master")
        }
    assert "forward_record" in tables
    assert FORWARD_COST_RECONCILIATION_TABLE in tables


def test_the_schema_bootstrap_is_idempotent(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # Every act opens its own connection and brings its own table up, so
    # a fresh database, one the record store already brought up, and one
    # this store prepared earlier all take the same path.  Three
    # reconciliations over three store instances are three bootstraps on
    # one file, and the ledger answers all three rows afterwards.
    moments = (REBALANCE_EARLIER, REBALANCE, REBALANCE_LATER)
    for moment in moments:
        ForwardCostReconciliations(database_url).reconcile(
            BOOK, rebalance_ts=moment, realized_cost_bps=4.0, modeled_cost_bps=3.0
        )
    swept = reconciliations.reconciliations()
    assert [row.rebalance_ts for row in swept] == list(moments)


def test_a_url_this_member_cannot_speak_is_refused_by_name(
    database_url: str,
) -> None:
    # Construction performs no I/O — the fault surfaces on the first
    # operation, in the member's one store vocabulary (the same
    # translation the record store refuses through), so a deployment
    # misrouted at the URL fails as a store fault, not a reconciliation
    # one: the row was fine, the address was not.
    misrouted = ForwardCostReconciliations("postgres://host:5432/nowhere")
    with pytest.raises(ForwardStoreError):
        misrouted.reconcile(
            BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.0, modeled_cost_bps=3.0
        )
    with pytest.raises(ForwardStoreError):
        misrouted.reconciliations()
    # And a store pointed at nothing is refused at construction, before
    # any reconciliation is asked about at all.
    with pytest.raises(ForwardStoreError):
        ForwardCostReconciliations("")
    with pytest.raises(ForwardStoreError):
        ForwardCostReconciliations("   ")


# -- The module-level spellings --------------------------------------------------


def test_the_module_level_write_lands_what_the_module_level_read_sweeps(
    database_url: str,
) -> None:
    # The feature's sentence as one call, and its reader: the execution
    # path's settlement step spells the act through the module level, and
    # the answer is the row the table holds — the same value a retry
    # would return, because an act asked for as one call has nobody to
    # tell about a retry.  Writing through one spelling and reading
    # through the other is writing and reading the same database.
    record = reconcile_fill_costs(
        BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.0,
        database_url=database_url,
    )
    assert isinstance(record, CostReconciliation)
    assert record.difference_bps == 1.5
    (swept,) = reconciled_fill_costs(database_url=database_url)
    assert swept == record


def test_the_write_refuses_without_a_store_and_the_read_answers_nothing() -> None:
    # The absence cuts asymmetrically, the halt ledger's own split.  A
    # divergence that silently went nowhere is exactly the hole that
    # leaves β₄ recalibrating from a record with a piece missing — a fill
    # that already happened cannot be re-measured — so the *write*
    # refuses by name.  A deployment that names no store holds no
    # reconciliations, and the *read* answering the empty tuple is the
    # truthful one, not a clean bill of health for the cost model: the
    # distinction is what keeps a caller from recalibrating against
    # nothing and calling the model honest.
    with pytest.raises(ForwardStoreError) as excinfo:
        reconcile_fill_costs(
            BOOK,
            rebalance_ts=REBALANCE,
            realized_cost_bps=4.5,
            modeled_cost_bps=3.0,
            env={},
        )
    assert DATABASE_URL_ENV in str(excinfo.value)
    assert reconciled_fill_costs(env={}) == ()


def test_an_explicit_url_wins_and_a_named_environment_is_read(
    database_url: str, tmp_path
) -> None:
    # The resolution ladder: database_url wins when stated, else
    # DATABASE_URL — exactly the seam the opening act resolves through,
    # so a caller writing through one spelling and reading through the
    # other cannot land two databases by mistake.
    elsewhere = f"sqlite:///{tmp_path / 'elsewhere.db'}"
    reconcile_fill_costs(
        BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.0,
        database_url=database_url,
        env={"DATABASE_URL": elsewhere},
    )
    assert len(reconciled_fill_costs(database_url=database_url)) == 1
    assert reconciled_fill_costs(database_url=elsewhere) == ()
    named = reconcile_fill_costs(
        OTHER_BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=1.5,
        modeled_cost_bps=1.0,
        env={"DATABASE_URL": elsewhere},
    )
    (swept,) = reconciled_fill_costs(database_url=elsewhere)
    assert swept == named


# -- The ask's refusals ----------------------------------------------------------


def test_a_malformed_ask_is_refused_before_anything_is_touched(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The ask face of the row contract, each refusal naming what it is
    # about: a book that states nothing, a rebalance instant that states
    # no time (naive, or text — the caller states the instant, the row
    # rebuild parses the spelling, and two parsers where one is the law
    # is how one rebalance becomes two), and a figure that is not a
    # finite real — bool first (True is 1, and a flag where a cost
    # belongs is a figure nobody measured), then NaN (it would propagate
    # into feature 338's recalibration and read as a measurement that
    # gaps) and infinity (not a cost at all).
    asks = [
        ("", REBALANCE, 4.5, 3.0),
        ("   ", REBALANCE, 4.5, 3.0),
        (BOOK, REBALANCE.replace(tzinfo=None), 4.5, 3.0),
        (BOOK, REBALANCE_TEXT, 4.5, 3.0),
        (BOOK, REBALANCE, True, 3.0),
        (BOOK, REBALANCE, 4.5, float("nan")),
        (BOOK, REBALANCE, float("inf"), 3.0),
    ]
    for book, instant, realized, modeled in asks:
        with pytest.raises(
            ForwardReconciliationError,
            match="forward_reconciliation_malformed",
        ):
            reconciliations.reconcile(
                book,
                rebalance_ts=instant,
                realized_cost_bps=realized,
                modeled_cost_bps=modeled,
            )
    # And every one of them was refused *before anything was opened*: no
    # row, no table, no file — a refused reconciliation leaves no state
    # behind for a later reader to trip over.
    assert not _sqlite_path(database_url).exists()


def test_the_read_refuses_a_row_whose_difference_disagrees_with_its_sides(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The read face: SQLite's columns are dynamically typed, so a hand
    # that edited one figure would reach β₄'s recalibration and §16's
    # metric as a divergence nobody measured.  A stored difference that
    # disagrees with the two sides stored beside it is a row lying about
    # its own arithmetic, refused rather than served — and the refusal
    # names the row, so an operator gets an address to repair instead of
    # a complaint about a value with none.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    _raw_exec(
        database_url,
        f"UPDATE {FORWARD_COST_RECONCILIATION_TABLE} SET difference_bps = ? "
        f"WHERE sequence = ?",
        (99.0, record.sequence),
    )
    with pytest.raises(ForwardReconciliationError) as excinfo:
        reconciliations.reconciliations()
    message = str(excinfo.value)
    assert "forward_reconciliation_malformed" in message
    assert str(record.sequence) in message
    assert BOOK in message


def test_the_read_refuses_a_row_whose_moment_no_parser_accepts(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # A moment no parser accepts cannot be ordered in the sweep, and a
    # trend drawn over a row that sorts "somewhere" is a trend drawn on a
    # comparison the reader cannot justify — so the row is refused, again
    # naming where it came from.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    _raw_exec(
        database_url,
        f"UPDATE {FORWARD_COST_RECONCILIATION_TABLE} SET rebalance_ts = ? "
        f"WHERE sequence = ?",
        ("not-a-moment", record.sequence),
    )
    with pytest.raises(ForwardReconciliationError):
        reconciliations.reconciliations()
    with pytest.raises(ForwardReconciliationError):
        reconciliations.history(BOOK)


def test_the_read_refuses_a_sequence_the_ledger_never_minted(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The sequence is minted by the insert — monotone, never reused — so
    # a row wearing 0 is a row this store did not write, and the number an
    # operator would cite in a recalibration report must be a number the
    # ledger actually issued.
    record, _ = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    _raw_exec(
        database_url,
        f"UPDATE {FORWARD_COST_RECONCILIATION_TABLE} SET sequence = ? "
        f"WHERE sequence = ?",
        (0, record.sequence),
    )
    with pytest.raises(ForwardReconciliationError):
        reconciliations.reconciliations()


def test_the_value_layer_holds_the_same_contract_without_a_table() -> None:
    # The row contract lives on the value, not only on the store:
    # dataclasses.replace and unpickling both rebuild instances past a
    # factory's nose, and the read path needs the same check the write
    # path does.  A value whose difference disagrees with its sides is
    # refused wherever it was built — with no database involved at all.
    with pytest.raises(ForwardReconciliationError):
        CostReconciliation(
            sequence=1,
            book_id=BOOK,
            rebalance_ts=REBALANCE,
            realized_cost_bps=4.5,
            modeled_cost_bps=3.0,
            difference_bps=99.0,
            recorded_at=REBALANCE_LATER,
        )
    with pytest.raises(ForwardReconciliationError):
        CostReconciliation(
            sequence=0,  # the ledger never mints this
            book_id=BOOK,
            rebalance_ts=REBALANCE,
            realized_cost_bps=4.5,
            modeled_cost_bps=3.0,
            difference_bps=1.5,
            recorded_at=REBALANCE_LATER,
        )
    # And a well-formed one is built, frozen, and equal to itself read
    # back — the equality the write path's retry test is made of.
    good = CostReconciliation(
        sequence=1,
        book_id=BOOK,
        rebalance_ts=REBALANCE,
        realized_cost_bps=4.5,
        modeled_cost_bps=3.0,
        difference_bps=1.5,
        recorded_at=REBALANCE_LATER,
    )
    # Equality is over the stored fields, which is what the write path's
    # retry test is made of: a rebuilt value equals the one it rebuilds.
    assert replace(good) == good
    with pytest.raises(FrozenInstanceError):
        good.difference_bps = 0.0  # frozen, like the fact it holds


# -- The concurrent window -------------------------------------------------------


def _racing_row_at(
    store: ForwardCostReconciliations,
    competing: tuple[float, float],
) -> None:
    """Patch the store's row read to simulate the race the UNIQUE holds.

    The window that matters is the one between *"this rebalance holds no
    row"* and *"the row is written"*: a second writer landing the
    rebalance inside it is what the ``UNIQUE (book_id, rebalance_ts)``
    constraint exists for, and the honest way to test the handler is to
    interleave exactly that — the read answers ``None``, a competing row
    lands through another connection, and only then does the insert run
    and the constraint fire.  The injection is a real committed row, not a
    mock: the handler's re-read has to find it in the table.
    """
    real = store._row_at
    raced = False

    def racing(connection: sqlite3.Connection, book: str, moment: str):
        nonlocal raced
        row = real(connection, book, moment)
        if row is None and not raced:
            raced = True
            realized, modeled = competing
            with closing(sqlite3.connect(store.path)) as other, other:
                other.execute(
                    f"INSERT INTO {FORWARD_COST_RECONCILIATION_TABLE} "
                    "(book_id, rebalance_ts, realized_cost_bps, "
                    "modeled_cost_bps, difference_bps, recorded_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        book,
                        moment,
                        realized,
                        modeled,
                        realized - modeled,
                        "2026-03-05T09:31:00+00:00",
                    ),
                )
        return row

    store._row_at = racing  # type: ignore[method-assign]


def test_a_row_landed_between_the_check_and_the_write_is_answered_not_duplicated(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # Two writers, one rebalance: the second's check reads no row (the
    # first had not written yet), the first's row lands, and the second's
    # insert fires the UNIQUE.  The answer is the law's, not a corruption
    # report — the same figures, so the same reconciliation, answered by
    # the row that stands with created=False — and the table still holds
    # exactly one row for the rebalance.
    _racing_row_at(reconciliations, (4.5, 3.0))
    answered, created = reconciliations.reconcile(
        BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
    )
    assert created is False
    assert answered.realized_cost_bps == 4.5
    assert answered.modeled_cost_bps == 3.0
    assert answered.difference_bps == 1.5
    rows = _raw_rows(database_url)
    assert len(rows) == 1  # the concurrent writer's row, and no second one


def test_a_row_landed_between_the_check_and_the_write_disagreeing_is_refused(
    reconciliations: ForwardCostReconciliations, database_url: str
) -> None:
    # The same window with different figures: two claims about one
    # rebalance's costs, and the constraint-driven path refuses exactly as
    # the checked path would — last-wins would revise a divergence β₄'s
    # recalibration may already have consumed, whichever of the two
    # writers happened to arrive second.
    _racing_row_at(reconciliations, (5.5, 3.0))
    with pytest.raises(ForwardIdentityError):
        reconciliations.reconcile(
            BOOK, rebalance_ts=REBALANCE, realized_cost_bps=4.5, modeled_cost_bps=3.0
        )
    rows = _raw_rows(database_url)
    assert len(rows) == 1
    assert rows[0][3] == 5.5  # the concurrent writer's measurement stands


# -- The DDL and code laws -------------------------------------------------------


def test_the_module_authors_exactly_one_table_and_it_is_this_features_own() -> None:
    # The member-owned DDL stance risk.halt_events and book._rebalance
    # take for their own per-event tables, restated for this one: the
    # migration tree drew the signal-day grain and is closed (this member
    # runs its statements verbatim and never edits them), the
    # per-rebalance grain has exactly one writer, and CREATE IF NOT
    # EXISTS makes the bootstrap idempotent on fresh and migrated
    # databases alike.  Exactly one CREATE TABLE, one INSERT target, and
    # the one-row law held in the schema itself — which this member *may*
    # state on its own table where 0108 declined to hold the observation
    # law on its.
    text = code_of(forward.reconciliation)
    assert text.count("CREATE TABLE") == 1
    assert (
        "CREATE TABLE IF NOT EXISTS {FORWARD_COST_RECONCILIATION_TABLE}" in text
    )
    assert (
        "CREATE INDEX IF NOT EXISTS {FORWARD_COST_RECONCILIATION_TABLE}"
        "_rebalance_ts" in text
    )
    assert "UNIQUE (book_id, rebalance_ts)" in text
    assert text.count("INSERT INTO") == 1
    assert "INSERT INTO {FORWARD_COST_RECONCILIATION_TABLE}" in text
    assert "AUTOINCREMENT" in text


def test_the_module_never_names_the_record_table_in_its_code() -> None:
    # The insert-naming discipline, stated as the boundary it is: a
    # writer that cannot name a column cannot fabricate its value, and a
    # reconciliation module that named the record table in *code* (as
    # opposed to in the prose that explains why it refuses to) would be
    # one ALTER or UPDATE away from allocating one book-level figure
    # across signal-days — the fabrication no spec states.  Docstrings
    # may name it, and do, to explain this very refusal; code cannot.
    assert "forward_record" not in code_of(forward.reconciliation)
