"""Feature 340: reconciling realized fill costs against modeled ones, per
rebalance, in basis points.

app_spec.xml, "Forward-Test Tracking", feature 340: *System reconciles
realized fill costs against modeled costs in basis points, persisting the
difference per rebalance.*  Its declared parent is feature 333 — the
observed track record — and the sentence is the cost half of the loop §13.4
closes: *"Those outcomes become the labels that recalibrate ``β₄`` and the
decay priors in the outer loop."*  Where features 332 and 333 measure what
a promoted signal *predicted* out of sample, this module measures what its
execution *cost* out of sample, against what the cost model said it would
cost — the divergence §6.2 names when it makes the cost library shared:
*"Divergence between these two is exactly the quantity ``β₄`` penalizes, so
they must be the same code, not two implementations of the same document."*

Three documents state why the divergence is worth a table of its own:

* §16's live-metrics list names the figure directly — *"realized vs.
  modeled fill costs in bps"* — beside the IC ratio and the reject rate, as
  one of the numbers a deployment watches continuously;
* §15's failure table names the repair it drives — *"Live/sim divergence |
  ``β₄`` monitor | Auto-demote; reconcile the cost model"* — so the rows
  here are where *reconcile the cost model* starts from;
* prd's risk register names the failure mode — *cost model optimism,
  high, live shadow reconciliation; ``β₄`` penalty* — and optimism is a
  signed quantity: it means the model charged less than the fills cost,
  and only a persisted difference carries the sign.

**Per rebalance, and where that key comes from.**  A rebalance is the act
the book member already keys — feature 309 persists each target weight set
under ``(book_id, rebalance_ts)``, and feature 316 hashes the same pair
(plus the leg) into its client order identifier — so the rebalance this
module prices is the one those features name, and the pair is its whole
key.  The caller states it; nothing here re-derives it, and nothing here
foreign-keys to the book member's table, because the rebalance being
reconciled is one that *happened on a venue*: its identity is the pair the
order path already agrees on, which is exactly why two processes that
never spoke can reconcile and read the same row.

**Why this is its own table, and not the record's third REAL column.**
``0108`` gave ``forward_record`` a nullable ``realized_cost_bps``, and this
member's earlier docstrings anticipated this feature filling it — but the
sentence's own grain refuses: *persisting the difference per rebalance*, and
a rebalance is a book-level act that names no column of a table keyed
``(node_id, observed_on)``.  One rebalance originates from several promoted
signals (feature 309's row carries them), so landing the difference in the
record would mean allocating one book-level figure across signal-days — an
allocation no spec states and no honest default exists for, which is the
fabrication this member's insert-naming discipline exists to prevent.  So
the column stays NULL for whoever owns that aggregation, and this feature
persists its differences in its own table, ``forward_cost_reconciliation``,
in the same database ``DATABASE_URL`` names.  The DDL is authored here —
deliberately not a migration, the stance :mod:`risk.halt_events` takes for
``risk_halt_event`` and :mod:`book._rebalance` for
``book_rebalance_target_weights``: the migration tree drew the signal-day
grain and is closed (this member runs ``0108``'s and ``0118``'s statements
verbatim and never edits them), the per-rebalance grain has exactly one
writer and its readers right here, and ``CREATE TABLE IF NOT EXISTS`` makes
the bootstrap idempotent on fresh and migrated databases alike.

**The store reconciles; the caller does not.**  The caller — the execution
path that watched the fills land, and the shared cost library that priced
them — states the two figures, and :meth:`ForwardCostReconciliations.
reconcile` computes the difference: ``realized_cost_bps −
modeled_cost_bps``, persisted beside the two sides that produced it.  A
caller-supplied difference would let the system persist an unreconciled
claim — two figures and a third that disagrees with both — so there is no
parameter for it, on the ask or anywhere else.  The sign is the headline: a
positive difference is the model understating what trading cost, prd's
*cost model optimism*, the one direction that quietly flatters every score
the evaluator ever produced; a negative difference is the model
overcharging, which wastes capacity but lies to nobody.  All three figures
are finite reals, refused rather than bounded — see
:class:`~forward.errors.ForwardReconciliationError` for the argument — and
the unit is the column's own name: basis points, stated by the seam that
hands the figures over, because no validator can check a unit.

**One row per rebalance, held three ways.**  The law lives in the write
path (a check-and-insert inside one transaction on one connection, the
discipline :mod:`forward.observation` states), in the schema
(``UNIQUE (book_id, rebalance_ts)``, which this member *may* state because
this table is its own — where ``0108`` declined to hold observation rows'
law in a constraint, nothing stops this DDL from holding this one), and in
the key's spelling (every ``rebalance_ts`` this store writes goes through
one UTC ISO-8601 rendering, so ``12:00+02:00`` and ``10:00+00:00`` — one
instant — are one row, never two).  A **retry** — the same rebalance, the
same two figures; the worker dying between the row and the response — is
answered by the standing row with ``created=False``, the semantics
:meth:`forward.record.ForwardRecords.open_record` establishes.  A
**disagreement** — the same rebalance naming different figures — is refused
(:class:`~forward.errors.ForwardIdentityError`, the law's per-rebalance
face), because last-wins would revise a divergence that feature 338's β₄
recalibration may already have consumed: the outer loop would quietly
re-learn from a number nobody measured.

**The read is a sweep, because its reader is a loop.**  §13.4's β₄
recalibration and §16's metric read *every* rebalance's divergence, oldest
first, so :meth:`ForwardCostReconciliations.reconciliations` answers the
whole ledger ordered by the rebalance's own moment with the append order
breaking same-instant ties — a reconciliation computed after the fills
settled still takes its place at its rebalance's moment, not at the moment
of the write.  :meth:`ForwardCostReconciliations.get` answers one
rebalance, :meth:`ForwardCostReconciliations.history` one book's run of
them — the operator path for *is this book's cost model drifting?*.

**Two stamps, and only one is the caller's.**  ``rebalance_ts`` is the
rebalance's own instant, stated by the caller exactly as feature 309
states it and feature 316 hashes it — a reconciliation computed late is
still the reconciliation of the rebalance it names, and moving it to the
write's moment would order the sweep by when the accounting ran rather
than by when trading happened.  ``recorded_at`` is the store's own fact
and not a parameter at all: the gap between the two is itself readable
(an execution path that reconciles long after its rebalances was batch,
not live), and a caller that could set it could forge that gap.

**The absence cuts asymmetrically, the halt ledger's own split.**
:func:`reconcile_fill_costs` — the execution path's spelling — *refuses*
when nothing names a store: a divergence that silently went nowhere is
exactly the hole that leaves β₄ recalibrating from a record with a piece
missing.  :func:`reconciled_fill_costs` — the reader's spelling — answers
an empty tuple when nothing names a store: a deployment that names none
holds no reconciliations, and the empty answer is the truthful one, not a
clean bill of health for the cost model.

**No component, no route, no second registration.**  The member's
registered surface stays feature 332's one store, the stance :mod:
`forward.observation` takes and the promotion member's post-291 features
take before it: the composed ``forward`` component is the deployment's
one database pointer, and this store is built over its URL
(:meth:`ForwardCostReconciliations.over`) or resolved from
``DATABASE_URL`` (:meth:`ForwardCostReconciliations.resolve`).  The spec's
API summary names no route for this domain's cost half — *"persists"* is
not *"exposes"* — and the reader that makes the rows visible is §16's
metrics surface, not a forward endpoint.

**Stdlib only, and import-cheap.**  ``os``, ``math``, ``sqlite3`` and the
typing shapes at module scope; from this member's own modules only the
error vocabulary, the member's one URL translation and its one clock —
no third-party import and no import of another workspace member, so the
factory's scan imports this package for the near-nothing it always did
and a reconciliation costs its caller only the store it already held.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_IDENTITY_ERROR_CODE,
    FORWARD_RECONCILIATION_ERROR_CODE,
    ForwardError,
    ForwardIdentityError,
    ForwardReconciliationError,
    ForwardStoreError,
)
from .record import DATABASE_URL_ENV, _sqlite_path, utc_now

__all__ = [
    "FORWARD_COST_RECONCILIATION_TABLE",
    "FORWARD_RECONCILIATION_SEAM",
    "CostReconciliation",
    "ForwardCostReconciliations",
    "reconcile_fill_costs",
    "reconciled_fill_costs",
]

#: This feature's own table — one row per rebalance, the per-rebalance cost
#: divergence β₄'s recalibration and §16's live metric read.  Deliberately
#: not a column on the record table and not a row of it: the record is the
#: signal-day grain ``0108`` drew, a rebalance is the ``(book_id,
#: rebalance_ts)`` pair the book and order paths already key, and no
#: allocation between the two grains is this feature's to invent (see the
#: module docstring for the argument).
FORWARD_COST_RECONCILIATION_TABLE = "forward_cost_reconciliation"

#: The one attribute :meth:`ForwardCostReconciliations.over` reads off the
#: composed store, spelled once so the constructor and its refusal name the
#: same seam — the same bridge :data:`forward.observation.
#: FORWARD_OBSERVATION_SEAM` is for the observing act.  The URL is all this
#: act needs from the component: the reconciliation lands in the same
#: database the deployment already names, and it is read as an attribute
#: rather than checked as a class for the reason every seam in this
#: workspace states — the loader imports a member under a synthetic module
#: name, so the composed store is structurally a ``ForwardRecords`` and
#: never the same class object a direct import yields.
FORWARD_RECONCILIATION_SEAM = "database_url"

#: The table's DDL, authored here beside the only writer — the member-owned
#: stance :mod:`risk.halt_events` and :mod:`book._rebalance` take for their
#: own per-event tables, and deliberately not a migration: the versioned
#: tree drew the signal-day grain and this feature's sentence draws a
#: per-rebalance one no revision declares.
#:
#: The ``AUTOINCREMENT`` key is the ledger's own law stated where a raw row
#: disposal cannot quietly break it: reconciliation numbers are monotone and
#: never reused, so a number an operator cites in a recalibration report
#: names one row for the life of the table, and two rebalances at the same
#: instant keep the order they were reconciled in — the only order they
#: have.  ``UNIQUE (book_id, rebalance_ts)`` is the one-row-per-rebalance
#: law held structurally, which this member *may* state on its own table
#: where ``0108`` declined to hold the observation law on its: the
#: write path still checks first (for the refusal that names the standing
#: row), and the constraint is what makes the law hold against a concurrent
#: writer and a hand that reaches past this store.
_SCHEMA = f"""
-- Feature 340: one row per rebalance, carrying the realized fill cost
-- against the modeled cost, both in basis points, and the difference the
-- store computed between them.  The rebalance is the act feature 309
-- persists under (book_id, rebalance_ts) and feature 316 hashes into its
-- client order identifiers -- the pair the order path already agrees on --
-- and the row's key is that pair.  `difference_bps` is derived
-- (realized - modeled) and stored, with both sides beside it: the
-- difference is the headline, the sides are the evidence a β₄
-- recalibration and a cost-model repair both need.  `rebalance_ts` is the
-- rebalance's own instant in one UTC ISO-8601 spelling; `recorded_at` is
-- when this row was written, and the gap between the two is a fact a
-- reader may act on (a long gap was batch, not live).  Nothing updates or
-- deletes: a reconciliation is a rebalance's fact, once.
CREATE TABLE IF NOT EXISTS {FORWARD_COST_RECONCILIATION_TABLE} (
    sequence           INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id            TEXT NOT NULL,
    rebalance_ts       TEXT NOT NULL,  -- ISO 8601 UTC, one spelling
    realized_cost_bps  REAL NOT NULL,
    modeled_cost_bps   REAL NOT NULL,
    difference_bps     REAL NOT NULL,  -- realized - modeled, computed
    recorded_at        TEXT NOT NULL,
    UNIQUE (book_id, rebalance_ts)
);

-- The recalibration and metric reads sweep the whole ledger in the
-- rebalances' own order, so that is the indexed column; the sequence
-- tiebreak rides the same scan.
CREATE INDEX IF NOT EXISTS {FORWARD_COST_RECONCILIATION_TABLE}_rebalance_ts
    ON {FORWARD_COST_RECONCILIATION_TABLE} (rebalance_ts);
"""

#: The columns of :data:`FORWARD_COST_RECONCILIATION_TABLE`, in the order
#: the insert names them and the order the read-back unpacks them.  Spelled
#: once so the write and the read cannot drift apart on a column order —
#: the failure a positional ``SELECT *`` invites.  ``sequence`` is
#: deliberately absent from the write and present in the read: it is the
#: row's own number, minted by the insert, never supplied by the caller.
_COLUMNS = (
    "book_id, rebalance_ts, realized_cost_bps, modeled_cost_bps, "
    "difference_bps, recorded_at"
)

_INSERT_SQL = (
    f"INSERT INTO {FORWARD_COST_RECONCILIATION_TABLE} ({_COLUMNS}) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)

#: One rebalance's row, column by column rather than ``SELECT *``: the
#: order :meth:`ForwardCostReconciliations._from_row` unpacks must be the
#: order this names, and a hand that appends a column must not silently
#: shift the fields.
_READ_ONE_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_COST_RECONCILIATION_TABLE} "
    f"WHERE book_id = ? AND rebalance_ts = ?"
)

#: One book's rebalances, oldest first.  Ordered by the stored instant,
#: which is correct exactly because every row this store writes goes through
#: :func:`_isoformat_utc` — one UTC offset, one format, one width.  A row
#: another tool wrote in another spelling may therefore sort outside where
#: it "should" fall, and that is the safe direction: such a row is refused
#: by :meth:`ForwardCostReconciliations._from_row` rather than counted into
#: a trend on a comparison the reader cannot justify.
_READ_BOOK_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_COST_RECONCILIATION_TABLE} "
    f"WHERE book_id = ? ORDER BY rebalance_ts, sequence"
)

#: The whole ledger, oldest rebalance first — the sweep §13.4's
#: recalibration and §16's metric perform, with the append order breaking
#: same-instant ties.
_READ_ALL_SQL = (
    f"SELECT sequence, {_COLUMNS} FROM {FORWARD_COST_RECONCILIATION_TABLE} "
    f"ORDER BY rebalance_ts, sequence"
)


# -- Validation -------------------------------------------------------------------


def _validated_book_id(value: Any) -> str:
    """Return ``value`` as a book identity, or refuse what cannot be one.

    Non-empty text, stripped — the near-miss a trailing newline or an
    indented copy would otherwise persist as a *second* book against a
    table whose whole identity is one row per book per rebalance.  The
    stance is :func:`book._rebalance._validated_book_id`'s, restated here
    rather than imported because a member never imports another — and for
    the same reason nothing else is normalised: a book's identity is its
    deployment's configuration, and a store that case-folded or re-spelled
    one would be silently renaming the book the order path hashes into its
    client order identifiers.
    """
    if not isinstance(value, str) or not value.strip():
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: a book must be named by "
            f"non-empty text — got {value!r} ({type(value).__name__}); a cost "
            "reconciliation is keyed by the rebalance it prices, and the "
            "rebalance is keyed by the book the order path hashed its client "
            "order identifiers from. A name that states nothing names no book "
            "whose fill costs could be reconciled (feature 340)"
        )
    return value.strip()


def _validated_rebalance_instant(value: Any) -> datetime:
    """Return ``value`` as the rebalance's own aware instant, or refuse it.

    A ``datetime`` and only a ``datetime`` — the stance
    :func:`book._rebalance._validated_instant` holds its caller to, restated
    in this member's vocabulary: the caller states the rebalance's own
    instant exactly as feature 309 states it and feature 316 hashes it, and
    the row-rebuild parses the stored spelling separately
    (:meth:`ForwardCostReconciliations._from_row`), so accepting text here
    would be a second parser where one is the law.  A naive timestamp
    cannot say unambiguously *when* the rebalance was for, and a ledger
    keyed by one would file two books' rebalances in one order or none —
    which is the answer the sweep orders by, so the check is here rather
    than assumed.
    """
    if not isinstance(value, datetime):
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: the rebalance's instant "
            f"must be a datetime, not {type(value).__name__}; the "
            "reconciliation is keyed by the rebalance's own instant — the "
            "one feature 309 persisted and feature 316 hashed — and it must "
            "say unambiguously when the rebalance was for (feature 340)"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: the rebalance's instant "
            f"must be timezone-aware — got the naive datetime "
            f"{value.isoformat()!r}; a naive stamp cannot say when a "
            "rebalance was for, and the sweep this table exists for would "
            "order it by whichever offset happened to read it. Pass the "
            "aware instant the rebalance was decided at (feature 340)"
        )
    return value


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this store writes goes through here — one UTC offset, one
    format, one width policy — and the key compares these strings for
    equality and the sweep compares them for order, which is correct
    exactly because of that: ``12:00+02:00`` and ``10:00+00:00`` are one
    instant and must be one row, and an offset-stated instant that reached
    the table in its own spelling would quietly become a second one.
    """
    return moment.astimezone(UTC).isoformat()


def _validated_bps(value: Any, field_name: str) -> float:
    """Return ``value`` as one of the reconciliation's two figures, or
    refuse what cannot be one.

    The rule is two gates, each refused rather than resolved:

    * **A finite real.**  ``bool`` is refused first, for the reason every
      numeric validator in this workspace refuses it: ``True`` is ``1``,
      and a flag where a cost belongs would persist a figure nobody
      measured.  Anything that is not a :class:`~numbers.Real` is refused
      with it — text, ``None``, a sequence — because a cost is one number,
      not a thing to be coerced.
    * **Finite.**  A NaN would propagate into feature 338's β₄
      recalibration and into every trend an operator draws over these
      rows — a gap that *looks* like a measurement — and an infinity is
      not a cost at all; SQLite stores either happily, which is exactly
      why the gate belongs here rather than in the column.

    There is deliberately **no sign bound**, and the absence is the point:
    a realized figure can be negative (fills that improved on their
    benchmark), a modeled one can be (a venue that rebates), and the sign
    of the difference — the model understated, or overcharged — is the
    very fact this table exists to persist.  Refusing a negative figure
    would refuse exactly the good news a honest reconciliation sometimes
    carries.  There is likewise no magnitude bound, because basis points
    carry no structural limit the way a correlation's ``[−1, 1]`` does —
    the unit is part of the seam's contract, named in every column, and a
    validator cannot check a unit.

    Returns the value narrowed to ``float`` — the type the REAL column
    holds — so a caller's ``int`` figure and the row's read-back of it
    compare equal, and the retry comparison in the write path is a
    comparison of two floats rather than of a float and whatever the
    caller's library handed over.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: {field_name} must be a "
            f"fill cost in basis points as a real number — got {value!r} "
            f"({type(value).__name__}); a reconciliation is two measured "
            "figures and the difference between them (prd's *cost model "
            "optimism* is the sign of that difference), and a value that is "
            "not one number is not a measurement any later reader — β₄'s "
            "recalibration, §16's live metric — can account with "
            "(feature 340)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: {field_name} must be "
            f"finite — got {narrowed!r}; a NaN would propagate into feature "
            "338's β₄ recalibration and read as a measurement that gaps, and "
            "an infinity is not a fill cost at all — the whole value of this "
            "table is that its figures were measured, and a value that "
            "cannot be one of them must be refused rather than stored "
            "(feature 340)"
        )
    return narrowed


def _require_sequence(value: Any) -> int:
    """Return ``value`` as a ledger sequence, or refuse it by name.

    The sequence is the row's ``AUTOINCREMENT`` number — minted by the
    insert, monotone, never reused — so a caller never supplies one and a
    row carrying ``0``, a negative, a bool dressed as an int, or anything
    that is not an ``int`` is a row this store did not write.  The stance
    is :func:`risk.halt_events._require_sequence`'s, restated in this
    member's vocabulary: the number is how an operator cites one
    reconciliation in a recalibration report, and a value that cannot be
    one is a row no reader filed.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: a reconciliation's "
            f"sequence is the number the ledger minted, an int — got "
            f"{value!r} ({type(value).__name__}); the number is how an "
            "operator cites one row in a recalibration report, and a value "
            "that cannot be one is a row this store did not write "
            "(feature 340)"
        )
    if value < 1:
        raise ForwardReconciliationError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: a reconciliation's "
            f"sequence is numbered from 1 upward — got {value!r}; "
            "AUTOINCREMENT never mints 0 or a negative, and a row wearing "
            "one is a row this store did not write (feature 340)"
        )
    return value


# -- The reconciliation -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostReconciliation:
    """One ``forward_cost_reconciliation`` row, as the table holds it.

    The seven fields are the table's seven columns: the rebalance the
    divergence belongs to (``book_id`` / ``rebalance_ts``), the two figures
    the execution path and the shared cost library stated, the difference
    the store computed between them, the ledger's own number, and the
    moment the row was written.  One type serves the write and the read —
    :meth:`ForwardCostReconciliations.reconcile` returns what landed,
    :meth:`ForwardCostReconciliations.reconciliations` rebuilds what stands
    — so the row an operator reconciles against and the row the ledger
    holds cannot be two things that disagree.

    **Frozen**, because a caller who could edit ``difference_bps`` in
    memory could revise a divergence after β₄'s recalibration consumed it —
    the in-memory spelling of the revision the write path refuses.  Frozen
    also buys equality over the stored fields, which is what makes the
    write path's retry test (*is the standing row the one this request
    would have written?*) a comparison of values rather than of columns
    read by hand.

    Validated in :meth:`__post_init__` rather than only through the store,
    for the reason every sibling record states: ``dataclasses.replace``
    and unpickling both rebuild instances past a factory's nose, and the
    *read* path needs the same check the write path does — SQLite's
    columns are dynamically typed, so a hand-edited row is reachable here.
    The one check beyond the field validators is the table's own
    arithmetic: ``difference_bps`` must equal ``realized_cost_bps −
    modeled_cost_bps`` exactly, and a row where it does not is a row lying
    about its own subtraction — refused rather than served, because every
    reader downstream (feature 338, §16's metric) trusts the stored
    difference without recomputing it.
    """

    #: The row's own number — the ``AUTOINCREMENT`` key the insert minted.
    #: Monotone, never reused, and the tiebreak the sweep orders
    #: same-instant rebalances by.
    sequence: int
    #: The book whose rebalance this divergence prices — the identity the
    #: order path hashed into its client order identifiers.
    book_id: str
    #: When the rebalance was for — the rebalance's own instant, in the
    #: table's one UTC spelling on the row and as an aware UTC datetime on
    #: the value.
    rebalance_ts: datetime
    #: What the fills actually cost, in basis points — the execution
    #: path's figure, stated, never derived here.
    realized_cost_bps: float
    #: What the shared cost model charged for the same rebalance, in basis
    #: points — §6.2's library's figure over the same legs.
    modeled_cost_bps: float
    #: The reconciliation's own answer: ``realized_cost_bps −
    #: modeled_cost_bps``, computed by the store, never stated by the
    #: caller.  Positive is the model understating — prd's *cost model
    #: optimism*.
    difference_bps: float
    #: When this row was written — the store's own fact, never the
    #: caller's to state, and deliberately beside ``rebalance_ts``: the
    #: gap between the two is readable (a long gap was batch, not live).
    recorded_at: datetime

    def __post_init__(self) -> None:
        # frozen+slots forbids plain assignment, so canonicalisation writes
        # through object.__setattr__ exactly once, at construction — the
        # same discipline the record, the observation row and every sibling
        # value in this workspace follow.
        object.__setattr__(self, "sequence", _require_sequence(self.sequence))
        object.__setattr__(self, "book_id", _validated_book_id(self.book_id))
        object.__setattr__(
            self,
            "rebalance_ts",
            _validated_rebalance_instant(self.rebalance_ts),
        )
        object.__setattr__(
            self,
            "realized_cost_bps",
            _validated_bps(self.realized_cost_bps, "realized_cost_bps"),
        )
        object.__setattr__(
            self,
            "modeled_cost_bps",
            _validated_bps(self.modeled_cost_bps, "modeled_cost_bps"),
        )
        object.__setattr__(
            self,
            "difference_bps",
            _validated_bps(self.difference_bps, "difference_bps"),
        )
        object.__setattr__(
            self, "recorded_at", _validated_rebalance_instant(self.recorded_at)
        )
        # The table's own arithmetic, checked on the value so no path —
        # write, read, replace, unpickle — can carry a difference that
        # disagrees with the sides stored beside it.  The comparison is
        # exact on purpose: both sides round-trip through SQLite as the
        # same IEEE doubles this subtraction was first computed from, so
        # anything but exact equality is a hand that edited one of the
        # three — and a row that lies about its own subtraction is refused
        # rather than served.
        if self.difference_bps != self.realized_cost_bps - self.modeled_cost_bps:
            raise ForwardReconciliationError(
                f"{FORWARD_RECONCILIATION_ERROR_CODE}: reconciliation "
                f"{self.sequence} for book {self.book_id!r} carries "
                f"difference_bps {self.difference_bps!r} beside "
                f"realized_cost_bps {self.realized_cost_bps!r} and "
                f"modeled_cost_bps {self.modeled_cost_bps!r}, and the three "
                "disagree — the difference is realized minus modeled, "
                "computed by the store and never stated by the caller, so a "
                "row where it does not hold is a row edited past this "
                "member. Every downstream reader (feature 338's β₄ "
                "recalibration, §16's live metric) trusts the stored "
                "difference without recomputing it, so the row is refused "
                "rather than served (feature 340)"
            )

    @property
    def modeled_understates(self) -> bool:
        """Whether the model charged less than the fills cost.

        The readable name for the difference's sign — prd's *cost model
        optimism*, the one direction that quietly flatters every score the
        evaluator produced, and the state §15's repair (*reconcile the cost
        model*) exists for.  A zero difference — a perfectly calibrated
        model — is not an understatement, which is the honest answer rather
        than a tolerance: 0.0 is 0.0 exactly on the row or the value layer
        refused it.
        """
        return self.difference_bps > 0.0

    @property
    def summary(self) -> str:
        """One sentence: which rebalance, both figures, and the difference.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the row's own
        facts to live, and an edited row would then disagree with its own
        summary.  The number leads, because *which reconciliation?* is the
        question a recalibration report answers first, and the moments ride
        in the table's own ISO form so an operator reading a log line can
        grep the ledger by either.
        """
        return (
            f"cost reconciliation {self.sequence}: book {self.book_id!r} "
            f"rebalanced at {_isoformat_utc(self.rebalance_ts)} realized "
            f"{self.realized_cost_bps!r} bps against "
            f"{self.modeled_cost_bps!r} bps modeled — difference "
            f"{self.difference_bps!r} bps "
            f"({'model understates' if self.modeled_understates else 'model does not understate'})"
        )

    def row(self) -> dict[str, Any]:
        """The reconciliation as a store-shaped mapping — a fresh dict per
        call.

        The column names are the table's own, the discipline every record
        in this workspace follows: a rendered mapping names the same things
        the same way the row does.
        """
        return {
            "sequence": self.sequence,
            "book_id": self.book_id,
            "rebalance_ts": _isoformat_utc(self.rebalance_ts),
            "realized_cost_bps": self.realized_cost_bps,
            "modeled_cost_bps": self.modeled_cost_bps,
            "difference_bps": self.difference_bps,
            "recorded_at": _isoformat_utc(self.recorded_at),
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"{type(self).__name__}(book_id={self.book_id!r}, "
            f"rebalance_ts={_isoformat_utc(self.rebalance_ts)!r}, "
            f"difference_bps={self.difference_bps!r})"
        )


# -- The store --------------------------------------------------------------------


class ForwardCostReconciliations:
    """Reconciles one rebalance's fill costs, and reads the ledger back.

    Constructed with the database URL the reconciliations land in;
    :meth:`reconcile` computes the difference and lands the row,
    :meth:`reconciliations` / :meth:`history` / :meth:`get` read what
    stands.  The class resolves its path lazily, so constructing one
    performs no I/O: composition-time work must not touch the disk, the
    contract every store in this workspace states.

    **Duck-built from the composed component.**  :meth:`over` reads the URL
    off anything that exposes one — the composed ``forward`` component, a
    :class:`~forward.record.ForwardRecords` a caller built itself — so the
    reconciliation writer, the record opener and the observation writer all
    point at the one database the deployment names, without an
    ``isinstance`` the loader's synthetic module names would defeat.

    **There is no cache.**  A memo of reconciled rebalances would make
    *what did this deployment's trading actually cost?* a question about
    this process's history — and the readers asking it (feature 338's β₄
    recalibration, §16's metric, an operator a quarter later) all run
    somewhere else entirely.  The rows are the only record, so they are the
    only thing an answer is drawn from, on every call, in every process.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the reconciliations land in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one reconciliation: a URL
        that is not a non-empty string names no table, and a store that
        accepted one would fail identically on every write — the wrong
        place for a deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardStoreError(
                f"{FORWARD_RECONCILIATION_ERROR_CODE}: {DATABASE_URL_ENV} "
                "must be a non-empty database URL. A fill-cost "
                "reconciliation is a row in the database the deployment "
                "names, and a store pointed at nothing has nowhere to "
                "persist the divergence β₄'s recalibration reads "
                "(feature 340)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> ForwardCostReconciliations | None:
        """The reconciliation store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no reconciliation writer — a discoverable state, not an exception —
        while the execution path that has just watched a rebalance's fills
        settle is, like the caller that must open a record, the one that
        must not find itself in it.  A divergence that went nowhere is a
        piece of β₄'s evidence missing, and §13.4's loop cannot re-measure
        a fill that already happened.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardCostReconciliations:
        """The reconciliation store over a composed forward-record store.

        The bridge from the seat to this act: a caller holding the composed
        ``forward`` component (:func:`app.modules.forward.
        forward_records_component`) asks this one question and holds the
        writer for the same database the component points at — one URL, two
        tables, three acts (the record, the observations, the
        reconciliations).  The one thing read is the store's
        ``database_url``; there is no ``isinstance`` to defeat, and no
        second store constructed beside the component to keep consistent,
        because the URL *is* the component's own.
        """
        url = getattr(records, FORWARD_RECONCILIATION_SEAM, None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardCostReconciliations is built over a forward-record "
                f"store — something exposing a "
                f"{FORWARD_RECONCILIATION_SEAM!r} string (the composed "
                "'forward' component, or a ForwardRecords); got "
                f"{type(records).__name__}, which names no database. A "
                "reconciliation lands in the same database the record and "
                "its observations landed in, so the acts share one URL by "
                "construction (feature 340)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store reconciles into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the ledger, resolved on first use.

        Nothing is created at construction — the URL is translated the first
        time an operation needs it, by the member's one spelling of that
        translation (:func:`forward.record._sqlite_path`), so a URL this
        member cannot speak is refused in the member's one vocabulary
        whichever store translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the ledger's database, bringing this member's own table up.

        The DDL is this module's own — the one table in the forward domain
        the migration tree does not declare — created idempotently beside
        the only writer, so a fresh database, one the record store already
        brought up, and one this store prepared earlier all take the same
        path, and coexistence is by construction: the record's two tables
        and this one live in the file ``DATABASE_URL`` names without any
        member naming another's schema.  There is no ``PRAGMA
        foreign_keys`` to set: this table references nothing — the
        rebalance it keys is an act on a venue, not a row in a table this
        member could name (the pair is the one the book and order paths
        already agree on), and a foreign key to another member's table
        would make this bootstrap depend on a schema this feature does not
        own.

        The caller owns the connection; use it as a context manager to
        commit, which is what the write here does.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            with connection:
                connection.executescript(_SCHEMA)
        except ForwardError:
            # A refusal already in this member's vocabulary — re-raised
            # untouched (and the connection closed) rather than re-framed,
            # for the reason :meth:`forward.record.ForwardRecords._connect`
            # states.
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise ForwardStoreError(
                f"{FORWARD_RECONCILIATION_ERROR_CODE}: the database at "
                f"{path} could not be brought to the shape a fill-cost "
                f"reconciliation needs: {exc}. "
                f"{FORWARD_COST_RECONCILIATION_TABLE} is created by this "
                "member alone (feature 340's own table — the migration "
                "tree declares the signal-day grain, not the per-rebalance "
                "one), so a failure here is a fact about the database "
                "rather than about the row (feature 340)"
            ) from exc
        return connection

    # -- Feature 340: the reconciliation ------------------------------------

    def reconcile(
        self,
        book_id: Any,
        *,
        rebalance_ts: Any,
        realized_cost_bps: Any,
        modeled_cost_bps: Any,
    ) -> tuple[CostReconciliation, bool]:
        """Reconcile one rebalance's fill costs — 340's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the book as non-empty text, the
           rebalance's instant as an aware datetime, both figures as finite
           reals — *before* anything is opened, so a malformed
           reconciliation is refused without touching a database and a
           refused call leaves no row and no file behind.
        2. **Compute the difference** — ``realized − modeled``, in basis
           points.  This is the reconciliation itself, and it happens here
           or nowhere: the caller states the two sides (the execution path
           watched the fills; §6.2's shared library priced them), and a
           caller-stated difference would be an unreconciled claim this
           table persisted on trust.
        3. **Answer the retry, or refuse the disagreement, or write.**  A
           standing row for *this* rebalance carrying *these* figures is
           the same reconciliation arriving twice — returned untouched,
           with ``created=False``.  A standing row carrying *different*
           figures is refused (:class:`~forward.errors.
           ForwardIdentityError`): the divergence of a rebalance is that
           rebalance's fact, and last-wins would revise it after feature
           338's β₄ recalibration may already have consumed it.  An absent
           rebalance takes the insert — one row, its sequence minted.
        4. **Read back and answer with the row**, inside the same
           transaction as the write, so the minted ``sequence`` and every
           figure in the answer are the table's own.

        **The answer is drawn from the row, not from the arguments.**  The
        ``difference_bps`` the returned reconciliation carries is the
        table's own copy read back, and the ``bool`` says whether *this*
        call landed the row — ``False`` is a retry answered by the standing
        reconciliation.

        **What this act never does.**  It never states a difference (there
        is no parameter for one, at any spelling); it never touches the
        record table or its observation rows (a reconciliation is
        per rebalance — a grain no column of that table names — and the
        signal-day ``realized_cost_bps`` column stays NULL for whoever owns
        that aggregation); it never reads the book, order or cost-model
        members (the figures arrive from the paths that hold them, and this
        member reaches no sibling); and it never judges the divergence —
        whether a model needs reconciling is §15's β₄ monitor's verdict,
        and this row is the fact that verdict is reached from.

        Refuses, in this order, each naming what it is about: a malformed
        book, instant or figure
        (:class:`~forward.errors.ForwardReconciliationError`, the ask
        face); a store this member cannot speak, a row that could not be
        written or read back, or a standing row in a spelling this store
        cannot read (:class:`~forward.errors.ForwardStoreError`); and a
        rebalance that already holds a different reconciliation
        (:class:`~forward.errors.ForwardIdentityError`).
        """
        book = _validated_book_id(book_id)
        instant = _validated_rebalance_instant(rebalance_ts)
        realized = _validated_bps(realized_cost_bps, "realized_cost_bps")
        modeled = _validated_bps(modeled_cost_bps, "modeled_cost_bps")
        moment = _isoformat_utc(instant)
        difference = realized - modeled
        recorded_at = utc_now()
        with closing(self._connect()) as connection, connection:
            standing = self._row_at(connection, book, moment)
            if standing is not None:
                return (
                    self._answer_standing(
                        standing, book, moment, realized, modeled
                    ),
                    False,
                )
            try:
                connection.execute(
                    _INSERT_SQL,
                    (
                        book,
                        moment,
                        realized,
                        modeled,
                        difference,
                        _isoformat_utc(recorded_at),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                # The UNIQUE fired after this store read no standing row —
                # the constraint doing exactly what it is on the table for.
                # The honest visitor is the concurrent one: a second writer
                # landed this rebalance between the read and the insert,
                # and SQLite's write lock means its row is committed — so
                # the answer is the law's, rather than a corruption report:
                # re-read, and answer the retry or refuse the disagreement
                # exactly as the checked path would have.
                #
                # The re-read runs on a fresh *plain* connection rather
                # than this store's own ``_connect()`` on purpose: the
                # bootstrap would take a write lock this failed transaction
                # may still hold, and the only question here is *what
                # stands* — a read, on a connection that starts nothing.
                # The table already exists; the constraint just fired on
                # it.
                with closing(sqlite3.connect(self.path)) as other:
                    row = other.execute(_READ_ONE_SQL, (book, moment)).fetchone()
                after = None if row is None else self._from_row(row)
                if after is None:  # pragma: no cover - UNIQUE equality is text equality
                    raise ForwardStoreError(
                        f"{FORWARD_RECONCILIATION_ERROR_CODE}: the "
                        "reconciliation for book "
                        f"{book!r} at {moment} was refused by the table's "
                        "own UNIQUE (book_id, rebalance_ts) after this "
                        "store read no standing row for that pair, and no "
                        "row in this store's spelling holds it: a row "
                        "another tool wrote in another spelling has taken "
                        f"this rebalance. {FORWARD_COST_RECONCILIATION_TABLE}"
                        ".rebalance_ts is one UTC ISO-8601 spelling by "
                        "construction — every row this store writes goes "
                        "through one rendering — so the standing row cannot "
                        "be answered as a retry and must not be "
                        "double-written. The repair is to the table: repair "
                        "the row's spelling, then reconcile (feature 340)"
                    ) from exc
                return (
                    self._answer_standing(
                        after, book, moment, realized, modeled
                    ),
                    False,
                )
            written = self._row_at(connection, book, moment)
        if written is None:
            raise ForwardStoreError(
                f"{FORWARD_RECONCILIATION_ERROR_CODE}: the reconciliation "
                f"for book {book!r} at {moment} could not be read back after "
                "the write. A divergence has to be accounted for — §13.4's "
                "recalibration and §16's live metric read these rows, and "
                "§15's repair (*reconcile the cost model*) starts from them "
                "— and a row that cannot be re-read is a reconciliation "
                "this store cannot vouch for (feature 340)"
            )
        return written, True

    # -- The reads -----------------------------------------------------------

    def get(
        self, *, book_id: Any, rebalance_ts: Any
    ) -> CostReconciliation | None:
        """One rebalance's standing reconciliation, or ``None``.

        The point read — the answer to *what did this rebalance's fills
        cost against its model?* for an operator holding one rebalance.
        ``None`` is the honest absent answer (the rebalance was never
        reconciled), not an error, for the same reason
        :meth:`forward.record.ForwardRecords._node_records` asserts no
        uniqueness: presence is the write path's law to hold.
        """
        book = _validated_book_id(book_id)
        moment = _isoformat_utc(_validated_rebalance_instant(rebalance_ts))
        with closing(self._connect()) as connection:
            return self._row_at(connection, book, moment)

    def history(self, book_id: Any) -> tuple[CostReconciliation, ...]:
        """One book's reconciliations, oldest rebalance first.

        The operator path for *is this book's cost model drifting?* — one
        book's divergences in the order its rebalances happened, which is
        the order a drift appears in.  Refuses a book that states nothing
        rather than answering an empty tuple for it, because an empty
        history and an unaskable one are different facts an operator must
        not have to tell apart by re-reading their own argument.
        """
        book = _validated_book_id(book_id)
        with closing(self._connect()) as connection:
            rows = connection.execute(_READ_BOOK_SQL, (book,)).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def reconciliations(self) -> tuple[CostReconciliation, ...]:
        """Every reconciliation on record, oldest rebalance first — the
        sweep the loop reads.

        §13.4's recalibration consumes these rows in the order the
        rebalances happened, so that is the order this answers in: by the
        rebalance's own moment, with the ledger's sequence breaking
        same-instant ties in the order the rows were written.  A
        reconciliation computed late — the fills settled, the accounting
        batched — still takes its place at its rebalance's moment, not at
        the moment of the write, because the sweep answers *when did
        trading diverge from its model*, not *when did we find out*.

        Fails with :class:`~forward.errors.ForwardStoreError` when the
        ledger could not be read, and with
        :class:`~forward.errors.ForwardReconciliationError` when a stored
        row is not a reconciliation this store could have written — the
        refusal, not a skip: a skipped row is a divergence wearing a
        shrug, and completeness is what a recalibration trusts this table
        for.
        """
        with closing(self._connect()) as connection:
            rows = connection.execute(_READ_ALL_SQL).fetchall()
        return tuple(self._from_row(row) for row in rows)

    # -- The row plumbing ----------------------------------------------------

    def _row_at(
        self, connection: sqlite3.Connection, book: str, moment: str
    ) -> CostReconciliation | None:
        """The standing row for one rebalance, in this store's spelling.

        Reached through :data:`_READ_ONE_SQL` on the caller's connection —
        inside the write's transaction on the write path, on its own on the
        read path — so there is one reading of a rebalance's row in this
        module and the check and the write cannot disagree about what
        stands.
        """
        row = connection.execute(_READ_ONE_SQL, (book, moment)).fetchone()
        return None if row is None else self._from_row(row)

    def _answer_standing(
        self,
        standing: CostReconciliation,
        book: str,
        moment: str,
        realized: float,
        modeled: float,
    ) -> CostReconciliation:
        """Resolve a rebalance that already holds a row: retry or refusal.

        The two outcomes are the same rebalance read two ways and the
        difference is the figures.  The *same* reconciliation arriving
        twice — the worker died after the row landed but before the
        response made it back, and the worker that takes over reconciles
        again — is not an error and moves nothing: the standing row is
        returned exactly as it is, sequence and stamps included.  A
        *different* pair of figures is two claims about one rebalance's
        costs, and the store refuses to choose between them: last-wins
        would revise a divergence that feature 338's β₄ recalibration may
        already have consumed — the outer loop quietly re-learning from a
        number nobody measured — and first-wins would leave the caller
        holding a response whose figures contradict the fills it just
        watched, which is worse than a refusal because it looks like
        success.
        """
        if (
            standing.realized_cost_bps == realized
            and standing.modeled_cost_bps == modeled
        ):
            return standing
        raise ForwardIdentityError(
            f"{FORWARD_IDENTITY_ERROR_CODE}: book {book!r} already holds a "
            f"cost reconciliation for the rebalance at {moment} — realized "
            f"{standing.realized_cost_bps!r} bps against "
            f"{standing.modeled_cost_bps!r} bps modeled, difference "
            f"{standing.difference_bps!r} bps (reconciliation "
            f"{standing.sequence}) — and this request would reconcile the "
            f"same rebalance at realized {realized!r} bps against "
            f"{modeled!r} bps modeled. A rebalance happened once and its "
            "divergence is one fact: last-wins would revise it after "
            "feature 338's β₄ recalibration may already have consumed it, "
            "and §15's repair (*reconcile the cost model*) starts from "
            "these rows. Nothing is wrong with the figures or the store: "
            "the repair is to reconcile the two measurements offline, not "
            "to move the one the ledger holds (feature 340)"
        )

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> CostReconciliation:
        """Rebuild one stored row, refusing a value no reconciliation can be.

        The refusal is the point: this table is written by this store, but
        SQLite will accept anything another tool inserts, and a row wearing
        a moment no parser accepts, a sequence the ledger never minted, or
        a difference that disagrees with the sides beside it would
        otherwise reach β₄'s recalibration and §16's metric as a
        divergence nobody measured.  The refusal names the row it came
        from, so an operator gets the row to repair rather than a
        complaint about a value with no address — the discipline
        :meth:`risk.halt_events.RiskHaltEventStore._event_from_row` states
        for its own ledger, restated in this member's vocabulary.
        """
        sequence = row[0]
        book_id, rebalance_raw, realized, modeled, difference, recorded_raw = row[1:]
        moments: dict[str, datetime] = {}
        for what, raw in (("rebalance_ts", rebalance_raw), ("recorded_at", recorded_raw)):
            try:
                moments[what] = datetime.fromisoformat(raw)
            except (TypeError, ValueError) as exc:
                raise ForwardReconciliationError(
                    f"{FORWARD_RECONCILIATION_ERROR_CODE}: the cost "
                    f"reconciliation row numbered {sequence!r} carries "
                    f"{what} {raw!r}, which is not an ISO 8601 moment this "
                    "store can order the sweep by (feature 340)"
                ) from exc
        try:
            return CostReconciliation(
                sequence=sequence,
                book_id=book_id,
                rebalance_ts=moments["rebalance_ts"],
                realized_cost_bps=realized,
                modeled_cost_bps=modeled,
                difference_bps=difference,
                recorded_at=moments["recorded_at"],
            )
        except ForwardReconciliationError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: the value sees one row and
            # cannot know which one, while a reader holding the ledger can
            # name the number and the book the bad row came from — so an
            # operator gets the row to repair rather than a complaint about
            # a value with no address.
            raise ForwardReconciliationError(
                f"{refusal} — the row this came from is cost reconciliation "
                f"{sequence!r} for book {book_id!r}, recorded at "
                f"{recorded_raw!r} (feature 340)"
            ) from refusal

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The module-level spellings ---------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardCostReconciliations:
    """The store the module-level spelling writes through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering nothing —
    the same seam :func:`forward.record._resolved_store` resolves for the
    opening act.  The silence would be the dangerous failure here and not
    the refusal: a deployment that could not say where the reconciliations
    live would drop the divergence on the floor at exactly the moment it
    was measured, and a fill that already happened cannot be re-measured —
    §13.4's loop would recalibrate β₄ from a record with a piece missing
    and never know.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardStoreError(
            f"{FORWARD_RECONCILIATION_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the fill-cost reconciliation cannot be "
            "persisted. A rebalance's divergence from its cost model is a "
            "fact about a fill that already happened, and a store resolved "
            "from nothing is a refusal rather than a silent answer of the "
            "caller's own choosing (feature 340)"
        )
    return ForwardCostReconciliations(url)


def reconcile_fill_costs(
    book_id: Any,
    *,
    rebalance_ts: Any,
    realized_cost_bps: Any,
    modeled_cost_bps: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> CostReconciliation:
    """Reconcile one rebalance's fill costs — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — the execution path's settlement step, an
    operator reconciling a rebalance whose row never landed, a test.  The
    store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`forward.record.forward_record`
    resolves the opening act's, so a caller writing through one spelling
    and reading through the other is writing and reading the same
    database.

    The answer is the **row the table holds** rather than a
    ``(reconciliation, created)`` pair, for the reason the sibling acts'
    own module-level spellings state: an act asked for as one call has
    nobody to tell about a retry, and the row it returns is the same value
    either way.  A caller that needs to know whether *this* call landed
    the row asks the store (:meth:`ForwardCostReconciliations.reconcile`).
    """
    return _resolved_store(database_url, env).reconcile(
        book_id,
        rebalance_ts=rebalance_ts,
        realized_cost_bps=realized_cost_bps,
        modeled_cost_bps=modeled_cost_bps,
    )[0]


def reconciled_fill_costs(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[CostReconciliation, ...]:
    """The fill-cost reconciliations on record — the reader's spelling.

    Every reconciliation the named ledger holds, oldest rebalance first
    (see :meth:`ForwardCostReconciliations.reconciliations`).  A deployment
    that names no store answers an empty tuple: writing refuses without a
    store, so a deployment that names none holds no divergences, and the
    empty answer is the truthful one — the *"no store, no status"* stance
    :func:`risk.recorded_halt_events` takes — kept distinct because a
    caller that mistook an unconfigured deployment for an emptied ledger
    would recalibrate β₄ against nothing and call the cost model honest.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return ()
    return ForwardCostReconciliations(url).reconciliations()
