"""Feature 325: new orders refused until a manual reset, on a breached
daily loss limit.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 325: *"System
rejects new orders until a manual reset once the configured daily loss
limit is breached."*  ``docs/nullius-tech-architecture.md`` §13.3's
trigger table gives the row its response: daily loss limit breached —
*"Flatten, halt until manual reset"* — and ``docs/alpha-engine-prd.md``
C10's bullet says the same two words: *"Daily loss limit → flatten and
halt."*

Read on its own four nouns, the sentence makes a narrower demand than
*"stop trading when the day goes badly"*, and the narrowing is the
whole design:

* **The configured daily loss limit.**  A number the deployment states,
  never one this module guesses: the sentence says *configured*, so the
  limit is a required keyword with no default — a halt fired on a limit
  nobody chose is a halt nobody asked for.  The limit must be a finite
  positive real: a limit of zero or less would refuse the day's first
  trade, and ``NaN`` compares false against everything, so a
  non-finite limit would answer *inside the limit* for a loss of any
  size — the one direction this feature must never fail in.  Every
  near-miss (``bool``, non-finite, non-positive, non-number) is refused
  by name rather than judged against.
* **Is breached.**  The comparison is strict — ``daily_loss >
  daily_loss_limit`` — and §13.3's trigger tables are read strictly the
  way the member's other thresholds already are (feature 328 pinned its
  staleness band to the same convention): a day sitting exactly at its
  limit is a day at the line, not past it, and the smallest possible
  step past it halts.  The day's loss figure is **handed over, never
  derived**: computing a PnL is another member's act on another
  member's rows, and a limit-keeper that quietly derived its own loss
  would be a second book wearing a risk manager's name.  The figure
  must be a finite non-negative real — negative is a *gain* wearing the
  loss's name, and a sign error arriving here would silently disable
  the halt exactly when the day went badly.
* **Rejects new orders.**  A guard over this feature's own standing
  state — :meth:`RiskDailyLossHaltStore.require_orders_allowed`, and
  the module-level :func:`require_within_daily_loss_limit` — read from
  the table, not from a flag the last process left in memory.  The
  refusal is composed by :func:`orders_halted_error` in
  :class:`~risk.errors.RiskOrdersHaltedError`, a *sibling* of the
  killed and stale receipts, and it carries the record it was taken
  from — the loss, the limit, the breach moment — so a caller reaching
  for the order learns which day, which line and which process, without
  a second query.
* **Until a manual reset.**  The clause that decides the architecture.
  Feature 322's kill channel is monotone by its own pinned law — the
  row never lifts, no surface writes it away — and a halt sent through
  it would refuse orders *forever*, which is a different feature from
  one that ends at an operator's hand.  So the breach is **not** routed
  through the channel and no flatten rides the halt either: the flatten
  is an act §13.3 assigns to this trigger's *response*, and the door
  that performs it is feature 323's composed halt, which the
  end-to-end story (feature 370) drives from a breach exactly once; a
  module that flattened on its own would be two features wearing one
  verb.  This feature owns its standing state, its guard and its reset
  door, and nothing else lifts it — not the calendar, not a restart,
  not the loss figure getting better, and not time.

**The state is a row, and the reset is a column on it.**  A breach
lands as one row in :data:`RISK_DAILY_LOSS_HALT_TABLE` — the day's
loss, the limit it broke, the breach moment and the supervisor
process's ``<host>/<pid>`` — and a manual reset writes ``reset_at`` and
``reset_by`` onto that row.  The breach facts never change: which loss
broke which limit, when, as recorded by whom, are the facts the halt
stands on, and a reset that rewrote them would leave the record
disagreeing with the refusal it justified.  At most one halt stands at
a time, by the schema — a partial unique index over the un-reset rows,
the belt under the value layer — and the retry law is
first-write-wins: a supervisor that sweeps again, or restarts and
re-halts, finds the standing halt unchanged and writes nothing.  A
*new* breach after a reset is a new row, and it stands on its own: the
law is at most one standing halt, not at most one halt ever, because a
deployment that breaches twice on two resets must refuse orders the
second time too.

**Like the channel, this is a table two processes share, and for the
category's own reason.**  The supervisor process that judges the day
and the order layer that refuses under the halt are different processes
(§13.3's first clause), and §17 leaves no port to serve a socket on;
the relational store both already hold is the medium, and it is the
medium that survives the failure this category is for — an order layer
that restarts mid-halt reads the same standing halt its predecessor
refused under.  Each operation opens its own connection, and the
member's suite proves the cross-process case against an actual second
interpreter: a halt a separate supervisor opens is one this process's
guard refuses under, and a reset that process performs is one this
process's guard passes after.

**The reset door is one verb, and it is an operator's act.**
:meth:`RiskDailyLossHaltStore.reset` — and the module-level
:func:`manual_reset` — refuses when nothing stands (a caller that
believes it re-opened the order layer must not be told it did), and
first-reset-wins under a race: the ``WHERE … AND reset_at IS NULL``
guard in the UPDATE means the operator whose write lands second
re-reads the winner's facts rather than re-stamping them.  The moment
and the actor default to the truth — the instant of the call, this
process's kernel-read identity — and are keyword-only to override, the
one spelling of each a replay of a recorded reset needs.

**The store's absence cuts asymmetrically, the channel's own split.**
:func:`halt_on_daily_loss` — the supervisor's spelling — judges the
day *before* demanding a store: a day inside its limit answers ``None``
with no database named at all, and a day past it refuses *by name*
when nothing names a store, because a halt that silently went nowhere
would leave an order layer believing itself stopped while it traded.
:func:`manual_reset` refuses on the same absence for the mirrored
reason — a reset that went nowhere leaves an operator believing the
order layer is open while every submission path still refuses.
:func:`require_within_daily_loss_limit` passes *vacuously* on it — the
*"no store, no status"* stance :func:`risk.require_orders_allowed`
takes: a deployment that names no store has no halt standing in one.
:func:`recorded_daily_loss_halts` — the reconciler's spelling, the one
feature 331's sweep reads for the daily-loss word — answers the empty
tuple on it: recording refuses without a store, so a deployment that
names none holds no halts to reconcile.

**What this module deliberately does not do.**  It does not *send a
kill* (feature 322's channel is monotone and this halt must lift; the
end-to-end door that drives the pair is feature 323's, fired by the
breach once, in the feature that composes them).  It does not
*flatten* (§13.3's response is the door's act, not the limit-keeper's;
a module that sold the book would skip a row of the trigger table).
It does not *derive* the day's loss (the figure is handed over; the
member that owns the book owns the number).  It does not *record a
halt event* (feature 331 owns the ledger, and the halt events it
reconciles are the halts that happened — this module's state is the
one the guard reads, the same split the kill channel already states).
It does not *reset itself* — no calendar, no clock, no loss recovered:
nothing lifts the halt but the reset door, because "until a manual
reset" is the sentence's own clock.

Storage is the workspace's relational store, addressed by
``DATABASE_URL`` exactly as the channel beside it is, and the schema is
created idempotently on connect, so no migration step is needed.  A URL
whose scheme is not ``sqlite`` is refused by name — as an *address*
fault, in :class:`~risk.errors.RiskStoreError`, the vocabulary that
fault already belongs to — while the halt's own terms (a loss that is
not a loss, a limit that is not a limit, a row no halt can be
reconstructed as, more than one halt standing where the law allows
one) are refused in this feature's own class,
:class:`~risk.errors.RiskDailyLossError`.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._identity import process_identity
from .errors import (
    DAILY_LOSS_CODE,
    ORDERS_HALTED_CODE,
    RiskDailyLossError,
    RiskOrdersHaltedError,
    RiskStoreError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "RISK_DAILY_LOSS_HALT_TABLE",
    "DailyLossHalt",
    "RiskDailyLossHaltStore",
    "halt_on_daily_loss",
    "manual_reset",
    "orders_halted_error",
    "recorded_daily_loss_halts",
    "require_within_daily_loss_limit",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: This feature's own table — one row per breach, the standing state the
#: guard reads and the reset door closes.  It is deliberately not the kill
#: channel's table and not a column on it: ``risk_order_kill`` is a
#: *monotone* state (one row, forever — the instruction that never lifts),
#: while a daily-loss halt is a *standing* state that an operator's reset
#: closes so the next breach can stand; forcing one law onto the other's
#: table would either make the kill liftable or the halt permanent, and
#: the sentence's *"until a manual reset"* is the clause that decides
#: which law lives where.
RISK_DAILY_LOSS_HALT_TABLE = "risk_daily_loss_halt"

#: ``risk_daily_loss_halt``'s DDL, created idempotently beside the code
#: that reads it — the same member-owned-table stance :mod:`risk.kill`
#: takes for the channel — and deliberately *not* a migration: this table
#: has exactly one writer and one reader, both in this module.
#:
#: The partial unique index is the at-most-one-standing law stated where
#: a raw INSERT from another tool cannot quietly break it: two un-reset
#: rows cannot coexist, so an order layer never has to arbitrate between
#: two standing halts.  The index keys on the *constant* ``1`` over the
#: un-reset partition — not on ``sequence``, which the primary key
#: already holds unique, so an index over it would state nothing — which
#: is the SQLite spelling of "at most one row where ``reset_at`` is
#: NULL": every un-reset row lands on the same key, and the second one
#: is the collision.  The ``CHECK``s are the belt under the value
#: layer's law — the limit positive, the loss non-negative, the breach
#: strict, the reset's two halves never apart — the split this member
#: already states: the value layer is the law because a ``CHECK`` can be
#: switched off, the schema is the belt because the value layer can be
#: bypassed by another tool's INSERT.
_SCHEMA = f"""
-- Feature 325: one row per breach of the configured daily loss limit,
-- refused-until-manual-reset.  The breach facts (daily_loss,
-- daily_loss_limit, breached_at, supervisor_process_id) are written once
-- and never rewritten: they are what the standing refusal justifies, and a
-- reset that rewrote them would leave the record disagreeing with the
-- halt it explained.  The reset facts (reset_at, reset_by) arrive only
-- through the reset door, and only together -- the CHECK keeps a row from
-- carrying half a reset.
CREATE TABLE IF NOT EXISTS {RISK_DAILY_LOSS_HALT_TABLE} (
    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_loss            REAL NOT NULL,
    daily_loss_limit      REAL NOT NULL,
    breached_at           TEXT NOT NULL,
    supervisor_process_id TEXT NOT NULL,
    reset_at              TEXT,
    reset_by              TEXT,
    CHECK (daily_loss_limit > 0),
    CHECK (daily_loss >= 0),
    CHECK (daily_loss > daily_loss_limit),
    CHECK ((reset_at IS NULL) = (reset_by IS NULL))
);

-- The at-most-one-standing law: at most one un-reset row, ever, so the
-- guard never arbitrates between two halts and the retry law stays
-- first-write-wins per episode.  Every un-reset row carries the same key
-- (the constant 1 -- the sequences are already unique by the primary
-- key, so keying the index on them would state nothing), and the second
-- un-reset row is the collision the index refuses.
CREATE UNIQUE INDEX IF NOT EXISTS {RISK_DAILY_LOSS_HALT_TABLE}_standing
    ON {RISK_DAILY_LOSS_HALT_TABLE} ((1)) WHERE reset_at IS NULL;

-- The reconciler's sweep orders by the breach's own moment (feature
-- 331's read of this table anchors the same way), so that is the indexed
-- column; the sequence tiebreak rides the same scan.
CREATE INDEX IF NOT EXISTS {RISK_DAILY_LOSS_HALT_TABLE}_breached_at
    ON {RISK_DAILY_LOSS_HALT_TABLE} (breached_at);
"""

#: The columns of :data:`RISK_DAILY_LOSS_HALT_TABLE`, in the order the
#: insert names them and the order the read-back unpacks them.  Spelled
#: once so the write and the read cannot drift apart on a column order —
#: the failure a positional ``SELECT *`` invites.  ``sequence`` is
#: deliberately absent from the write and present in the read: it is the
#: row's own number, minted by the insert, never supplied by the caller;
#: ``reset_at``/``reset_by`` are absent from the insert and present in
#: the read: a breach lands un-reset, and only the reset door sets them.
_COLUMNS = "daily_loss, daily_loss_limit, breached_at, supervisor_process_id, reset_at, reset_by"


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`risk.kill` and every other store in this
    workspace states, in this module's own words, for the reason each of
    them restates it: a store reaches into no sibling's private helper, so
    a later change to one table's address handling cannot silently move
    another's.  ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.

    Raises :class:`~risk.errors.RiskStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault
    with an address repair — point the deployment at a database this
    store can open — which is the face :class:`~risk.errors.RiskStoreError`
    exists for, the split the kill channel already states.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RiskStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "daily loss halt speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
            "the daily loss halts stand in (feature 325)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 325)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a halt that vanished would re-open an order layer "
            "that was never re-opened (feature 325)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this store writes goes through here — one UTC offset, one
    format, one width policy — and the read path parses what
    :func:`datetime.fromisoformat` accepts and refuses the rest, so a row
    another tool wrote in another spelling never survives into a guard
    or a sweep unparsed.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* the limit was
    breached, and a halt whose moment cannot be ordered cannot take its
    place in the sweep this feature's record exists for — the same
    discipline :mod:`risk.kill` holds its ``sent_at`` to, and the reason
    it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 325)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be timezone-aware; a daily "
            "loss halt must say unambiguously when the limit was breached, "
            "or the reconciliation that orders halts cannot order this one "
            "(feature 325)"
        )
    return moment


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    The supervisor's identity is a *statement* — the one name the record
    pins its breach to — and a label that states nothing is a halt no
    reconciliation can attribute.  Near-miss rule included: a
    whitespace-only label would file as a second spelling of nothing.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a daily loss halt that "
            "cannot name the process that judged the day is unauditable at "
            "exactly the moment a reconciliation asks (feature 325)"
        )
    return value.strip()


def _require_loss(value: object, what: str) -> float:
    """Return ``value`` as the day's loss figure, or refuse it by name.

    The figure is handed over by whoever owns the book and is held to
    three terms, each its own refusal: a real number (``bool`` refused
    before the numeric checks — ``isinstance(True, int)`` is true, and a
    loss of one wearing a boolean's name is a default nobody chose),
    finite (``NaN`` compares false against every limit, so a non-finite
    loss would sit *inside* the limit for any number configured — the
    one direction this feature must never fail in), and non-negative (a
    negative loss is a gain wearing the loss's name, and a sign error
    arriving here would silently disable the halt exactly when the day
    went badly).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be a number, got {value!r} "
            f"({type(value).__name__}); the day's loss is a figure the "
            "caller that owns the book hands over, and a halt judged on "
            "anything else is a halt judged on nothing (feature 325)"
        )
    loss = float(value)
    if math.isnan(loss) or math.isinf(loss):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be finite, got {value!r}; a "
            "non-finite figure cannot be compared against a limit, and a "
            "comparison that quietly answered 'within' for it would be the "
            "one failure this feature exists to prevent (feature 325)"
        )
    if loss < 0:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: {what} must be non-negative, got "
            f"{value!r}; a negative loss is a gain wearing the loss's "
            "name, and the sign error it would carry into the comparison "
            "is the one that silently disables the halt (feature 325)"
        )
    return loss


def _require_limit(value: object) -> float:
    """Return ``value`` as the configured daily loss limit, or refuse it.

    The sentence says *configured*, so the limit is the deployment's own
    number, held to three terms, each its own refusal: a real number
    (``bool`` refused first, the same trap ``_require_loss`` states), and
    finite and strictly positive — a limit of zero or less would refuse
    the day's first trade before any loss existed, and a ``NaN`` limit
    compares false against every loss, answering *not breached* for a
    day of any size.  There is no default and no fallback figure: a halt
    fired on a limit nobody chose is a halt nobody asked for.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: daily_loss_limit must be a number, got "
            f"{value!r} ({type(value).__name__}); the limit is the "
            "configured figure this feature judges the day against, and "
            "the sentence's own word for it is *configured* — a number "
            "nobody stated is not one (feature 325)"
        )
    limit = float(value)
    if math.isnan(limit) or math.isinf(limit):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: daily_loss_limit must be finite, got "
            f"{value!r}; a non-finite limit cannot be breached, and a "
            "guard that quietly answered 'within' for every day against "
            "it would be a daily loss limit that never once fired "
            "(feature 325)"
        )
    if limit <= 0:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: daily_loss_limit must be greater than "
            f"zero, got {value!r}; a non-positive limit is breached by the "
            "day's first trade — a refusal somebody configured rather "
            "than a tolerance anybody chose (feature 325)"
        )
    return limit


def _breached(daily_loss: float, daily_loss_limit: float) -> bool:
    """The sentence's own comparison: strict, so the line itself is inside.

    §13.3's trigger is read the way the member's other thresholds read
    it (feature 328's staleness band, pinned the same way): a day at
    exactly its limit is a day at the line, not past it, and the
    smallest possible step past the line halts.  Kept as its own named
    step so the strictness is stated once, beside the tests that pin it,
    rather than scattered through every caller as a bare ``>``.
    """
    return daily_loss > daily_loss_limit


def _require_sequence(value: object) -> int:
    """Return ``value`` as a halt sequence, or refuse it by name.

    The sequence is the row's ``AUTOINCREMENT`` number — minted by the
    insert, monotone, never reused — so a caller never supplies one and a
    row carrying ``0``, a negative, a bool dressed as an int, or anything
    that is not an ``int`` is a row this store did not write.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: a daily loss halt's sequence is the "
            f"number the table minted, an int, got {value!r} "
            f"({type(value).__name__}); the number is how an operator "
            "cites one halt in a reconciliation report, and a value that "
            "cannot be one is a row no reader filed (feature 325)"
        )
    if value < 1:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: a daily loss halt's sequence is numbered "
            f"from 1 upward, got {value!r}; AUTOINCREMENT never mints 0 or "
            "a negative, and a row wearing one is a row this store did "
            "not write (feature 325)"
        )
    return value


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class DailyLossHalt:
    """One breach of the configured daily loss limit, and its reset if any.

    A *value* — frozen, self-describing — carrying the whole of feature
    325's sentence: the day's ``loss`` broke the configured ``limit`` at
    ``breached_at``, the halt was judged by ``supervisor_process_id``, it
    stands until ``reset_at`` names the moment an operator closed it
    (``reset_by`` naming who), and it holds the row's own number in
    ``sequence``.  It is what :meth:`RiskDailyLossHaltStore.halt_on_loss`
    writes and returns, what :meth:`RiskDailyLossHaltStore.standing`
    reads back and what :meth:`RiskDailyLossHaltStore.reset` closes — one
    type for all three, so the record a guard refuses under and the row
    the table holds cannot be two things that disagree.

    Validated in :meth:`__post_init__` rather than only where it is
    built, because the read path reconstructs one from every stored row:
    a row edited outside this package — a loss that is not a loss, a
    limit that is not a limit, a moment no parser accepts, a breach the
    row's own two figures deny — fails to reconstruct rather than
    loading as a plausible-looking halt, the same defence
    :class:`~risk.kill.KillInstruction` applies to its own row, and for
    the same reason: what a guard refuses under is the stored record,
    and a store that could hand back a halt disagreeing with its own
    row would launder a tampered halt into a refusal nobody justified.

    The breach is *re-derived, never trusted*: ``loss > limit`` is
    checked against the record's own two figures, so a row whose loss
    was edited down to sit inside its own limit — the one tamper that
    would re-open the order layer — cannot reconstruct.  The reset's
    two halves are checked for never being apart, the pairing the
    schema's own ``CHECK`` states and the value layer re-states.

    ``changed`` is the one field that is not a fact of the row: it
    answers *did this call write it?* — ``True`` from the halt that
    landed and the reset that closed, ``False`` from the re-halt that
    found one standing, the reset that lost the race, and every read —
    so a caller logging the day can tell the act from the observation
    without a second query.
    """

    #: The halt's number in the table — the ``AUTOINCREMENT`` key of the
    #: row it landed in.  Monotone, never reused, and the number an
    #: operator cites when a reconciliation report must point at one
    #: halt; two breaches of two episodes are told apart by it.
    sequence: int
    #: The day's loss figure at the moment of the breach — handed over
    #: by the caller that owns the book, never derived here.  Carried on
    #: the row beside the limit it broke, so the judgement is re-derived
    #: from the row's own two figures rather than trusted from a bit.
    loss: float
    #: The configured daily loss limit the day's loss was judged
    #: against.  Carried, not looked up: a later retune of the
    #: configuration cannot re-judge a halt already standing — the
    #: refusal is justified by the limit that was configured when it
    #: fired.
    limit: float
    #: When the breach was judged — the sentence's own clock, and the
    #: datum the reconciler's sweep orders by.  The caller's to state
    #: (a breach observed late is still recorded at its own moment),
    #: timezone-aware, stored in the table's one canonical UTC spelling.
    breached_at: datetime
    #: The identity of the process that judged the day (see
    #: :func:`risk.process_identity`) — read from the kernel rather than
    #: accepted from the caller, keyword-only to override, so the record
    #: names the process that wrote it exactly as the kill channel's
    #: rows do.
    supervisor_process_id: str
    #: The moment an operator closed this halt through the reset door —
    #: ``None`` while the halt stands, which is the sentence's whole
    #: second half: the refusal holds until this field names a moment.
    reset_at: datetime | None
    #: Who closed it — the operator's own label for the act, filed
    #: beside the moment it happened, and never apart from it: a reset
    #: states *when* and *who* or neither at all.
    reset_by: str | None
    #: Whether *this call* wrote the row: ``True`` from the halt that
    #: landed and the reset that closed, ``False`` from a re-halt that
    #: found one standing, a reset that lost the race, and every read.
    changed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _require_sequence(self.sequence))
        object.__setattr__(self, "loss", _require_loss(self.loss, "daily_loss"))
        object.__setattr__(self, "limit", _require_limit(self.limit))
        _require_aware(self.breached_at, "breached_at")
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )
        if self.reset_at is not None:
            _require_aware(self.reset_at, "reset_at")
        if self.reset_by is not None:
            object.__setattr__(
                self, "reset_by", _require_text(self.reset_by, "reset_by")
            )
        if (self.reset_at is None) != (self.reset_by is None):
            raise RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: a daily loss halt's reset states both "
                f"its moment and its actor or neither; got reset_at="
                f"{self.reset_at!r}, reset_by={self.reset_by!r} — half a "
                "reset is a halt an operator cannot read, and a row "
                "wearing one is a row the reset door never wrote "
                "(feature 325)"
            )
        if not _breached(self.loss, self.limit):
            raise RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: a daily loss halt is a *breaching* "
                f"record — the day's loss must exceed the limit it was "
                f"judged against, and daily_loss={self.loss!r} does not "
                f"exceed daily_loss_limit={self.limit!r}; a row wearing a "
                "halt it does not justify would be a refusal with no "
                "breach behind it (feature 325)"
            )
        if not isinstance(self.changed, bool):
            raise RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: a daily loss halt's changed bit must "
                f"be a bool, got {self.changed!r} ({type(self.changed).__name__}); "
                "the bit tells a caller whether the act wrote the row, and "
                "a value that cannot be one tells it nothing (feature 325)"
            )

    @property
    def standing(self) -> bool:
        """Whether this halt still refuses new orders.

        The sentence's own state: a halt stands until its reset names a
        moment, so ``standing`` is exactly ``reset_at is None`` —
        re-derived from the record's own field rather than stored as a
        second bit, because two spellings of one state are two things to
        keep in sync with nothing but care.
        """
        return self.reset_at is None

    @property
    def summary(self) -> str:
        """One sentence: what broke what, when, and whether it still stands.

        Composed rather than stored, because every part of it is already
        a field — a stored copy would be a second place for the record's
        own facts to live, and an edited row would then disagree with
        its own summary.  The moments are in the table's own ISO form
        and the figures in full, so an operator reading a log line can
        grep the table by either — and the closing clause says which of
        the sentence's two halves the record is in.
        """
        opened = (
            f"the configured daily loss limit was breached at "
            f"{_isoformat_utc(self.breached_at)}: the day's loss "
            f"{self.loss!r} exceeded the configured limit {self.limit!r}, "
            f"recorded by {self.supervisor_process_id}"
        )
        if self.reset_at is None:
            return f"{opened}; orders are refused until a manual reset"
        return f"{opened}; reset at {_isoformat_utc(self.reset_at)} by {self.reset_by}"


# -- The store ------------------------------------------------------------------


class RiskDailyLossHaltStore:
    """Opens, holds, guards and closes the daily loss halt's standing state.

    Bound to a database URL at construction; construction performs no
    I/O, so composing an application never touches the database and a
    store costs nothing until a halt is judged, read, guarded or reset.
    Each operation opens its own connection (creating the schema
    idempotently if absent), the discipline every store in this
    workspace follows — which is what makes a halt a *separate
    supervisor process* opens readable from the order-layer process
    that refuses under it: the database, not any process's memory, is
    the coordination point, and §17 leaves no other channel to try.

    Four faces, one object: the supervisor process judges the day
    (:meth:`halt_on_loss`); the order layer asks the one question its
    submission path needs answered (:meth:`require_orders_allowed`,
    with :meth:`standing` and :meth:`halted` for the callers that want
    the state without the refusal); the operator closes the halt
    (:meth:`reset`); the reconciler sweeps the record
    (:meth:`halts`).  None of the faces holds state of its own beyond
    the URL and this process's identity, so a restarted anything reads
    the same standing halt its predecessor refused under — the whole
    point of refusing *until* rather than *while*.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RiskStoreError(f"{DATABASE_URL_ENV} must be a non-empty database URL")
        self._database_url = database_url.strip()
        self._process_id: str | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RiskDailyLossHaltStore | None:
        """The halt's store as ``DATABASE_URL`` names it, or ``None``.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance every
        store in this workspace takes.  What a caller does with the
        ``None`` is the caller's direction to decide, and the four
        directions this feature cuts are deliberately split in this
        module: halting and resetting refuse on it, guarding passes
        vacuously on it, sweeping answers empty on it (see the module
        docstring for why the asymmetry is the feature, not an accident).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this halt's state stands in."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The filesystem path behind the URL — for a caller backing the
        file up before an operator's retune, the same door
        :class:`~risk.demotion.RiskDemotionStore` leaves open."""
        return _sqlite_path(self._database_url)

    @property
    def process_id(self) -> str:
        """This process's identity — the label its halt rows file under.

        Resolved once, on first use, rather than at construction, so a
        store built during composition does not read the host or the pid
        before a caller has asked it anything; the value cannot change
        for the life of the process, so caching it is a fact about the
        process rather than about the store — and it is the same
        :func:`risk.process_identity` the kill switch files its rows
        under, so one operator grep splits both tables' labels the same
        way.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    def _open(self) -> sqlite3.Connection:
        """The store's connection, refusing a table that breaks its own law.

        The bootstrap re-creates the standing index over whatever rows
        are there, and that is a *check*: an ``IntegrityError`` here can
        only mean the table holds two un-reset rows — the belt unbuckled
        by another tool that dropped the index and inserted past the
        value layer — and re-creating the law over a table that breaks
        it is the moment to refuse in this feature's own class, naming
        the count, rather than handing the caller a
        :class:`~risk.errors.RiskStoreError` that reads like an address
        fault while the order layer's real question — *what stands?* —
        goes unanswered.
        """
        try:
            return self._connect()
        except sqlite3.IntegrityError as exc:
            raise self._standing_law_broken(exc) from exc

    def _standing_law_broken(self, exc: sqlite3.IntegrityError) -> Exception:
        """The refusal for a table whose standing law another tool broke.

        Counts the un-reset rows on a *plain* connection — a bootstrap
        here would deadlock against the very breakage it is measuring —
        and answers this feature's own refusal naming the count when
        there is more than one.  Any other count means the bootstrap
        refused for a reason this store cannot name, and the honest
        answer is the store's own fault class, not a guess.
        """
        with closing(sqlite3.connect(self.path)) as plain:
            (count,) = plain.execute(
                f"""
                SELECT COUNT(*) FROM {RISK_DAILY_LOSS_HALT_TABLE}
                WHERE reset_at IS NULL
                """
            ).fetchone()
        if count > 1:
            return RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: the daily loss halt table holds "
                f"{count} un-reset halts where the standing law allows "
                "one — the partial unique index that enforces it has been "
                "dropped or disabled by another tool, and no guard may "
                "arbitrate between two halts by picking one; the table "
                "needs an operator's eye before the order layer's state "
                "is answerable again (feature 325)"
            )
        return RiskStoreError(f"could not prepare the daily loss halt table: {exc}")

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads, idempotently.

        Public so a caller that reaches this store through another
        store's composition, and a test seeding a halt into exactly the
        schema the store will read, can prepare the table without
        reaching for the private :meth:`_connect` — the same door
        :mod:`risk.kill` leaves open, for the same reason.  Every
        statement is ``CREATE … IF NOT EXISTS``, so a fresh database and
        one this member already prepared take the same path.  A table
        that already breaks the standing law is refused in this
        feature's own class, not silently repaired: two standing halts
        are a fact an operator broke, not one a seeding pass should
        bless.
        """
        self._open().close()

    # -- The supervisor process's face ----------------------------------------

    def halt_on_loss(
        self,
        *,
        daily_loss: float,
        daily_loss_limit: float,
        supervisor_process_id: str | None = None,
        breached_at: datetime | None = None,
    ) -> DailyLossHalt | None:
        """Judge the day against the configured limit, and halt on a breach.

        The supervisor's one call.  The day's loss figure is handed over
        — this store derives nothing — and the comparison is strict: a
        day at exactly its limit answers ``None`` without the store even
        being opened, because a day at the line is not this feature's
        business, and the smallest possible step past it halts.  The
        limit is required: the sentence's own word for it is
        *configured*, and a halt fired on a number nobody chose is a
        halt nobody asked for.

        ``supervisor_process_id`` and ``breached_at`` are keywords
        rather than defaults for the reason feature 320's ``record``
        keeps its ``process_id`` one: a caller on the supervisor's own
        path should not pass them at all — the identity is read from
        the kernel and the moment is the instant of the call — and the
        one caller that *does* (an operator re-pronouncing a breach
        observed before the store was reachable, a replay of a recorded
        session) has to say so explicitly.

        **First-write-wins, per episode.**  A breach over an
        already-standing halt writes nothing and answers the standing
        record with ``changed=False`` — which loss of the day's was the
        worst is not this table's question; *that the line was crossed,
        when, by whose judgement* is, and a re-halt that moved those
        facts would quietly shrink the record of how long the order
        layer has been obliged to stop.  A *new* breach after a reset
        stands on its own row, and the at-most-one-standing law is the
        schema's, stated in a partial unique index over the un-reset
        rows — so even two supervisors sweeping the same breached day
        from two processes land one row between them, whichever writes
        first.

        Returns the record that stands after the call, or ``None``
        when the day is inside its limit.  Fails with
        :class:`~risk.errors.RiskStoreError` when the configured store
        could not take the row, and with
        :class:`~risk.errors.RiskDailyLossError` when the day's own
        terms cannot be judged — the refusal vocabulary the module
        docstring splits.
        """
        loss = _require_loss(daily_loss, "daily_loss")
        limit = _require_limit(daily_loss_limit)
        if not _breached(loss, limit):
            # The day at or inside its line: not this feature's business,
            # and not a reason to touch the store either — the guard's
            # own question is answered by what stands, not by how close
            # the day came.
            return None
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        standing = self.standing()
        if standing is not None:
            return standing
        moment = _require_aware(
            datetime.now(UTC) if breached_at is None else breached_at, "breached_at"
        )
        # Opened outside the try: an IntegrityError from the bootstrap is
        # the standing law refusing to be re-created over a broken table,
        # not this insert's race, and the two must not be confused.
        connection = self._open()
        try:
            with closing(connection), connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {RISK_DAILY_LOSS_HALT_TABLE} (
                        daily_loss, daily_loss_limit, breached_at,
                        supervisor_process_id
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (loss, limit, _isoformat_utc(moment), sender),
                )
                sequence = cursor.lastrowid
                row = self._row_for(connection, sequence)
        except sqlite3.IntegrityError as exc:
            # The one integrity fault this path can meet is the race the
            # standing index exists for: another supervisor wrote the
            # standing halt between this store's read and its insert.
            # The re-read below is deliberately on a *plain* connection
            # -- a bootstrap here would deadlock against the write lock
            # the winner is still holding -- and the loser's answer is
            # the winner's record, changed=False, because that is what
            # now stands.
            with closing(sqlite3.connect(self.path)) as plain:
                raced = self._standing_row(plain)
            if raced is None:
                raise RiskDailyLossError(
                    f"{DAILY_LOSS_CODE}: the breach landed and vanished "
                    "inside its own write — the insert refused and no "
                    "standing halt can be re-read, which is a state this "
                    "store cannot reconcile; the day stands unjudged and "
                    f"the supervisor must sweep again ({exc}; feature 325)"
                ) from exc
            return self._halt_from_row(raced, changed=False)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not record the daily loss halt for {loss!r} "
                f"against {limit!r} from {sender}: {exc}"
            ) from exc
        if row is None or sequence is None:
            # The insert reported success and the row it names is not
            # there to be read back -- the one state a committed insert
            # cannot be in, and the one a halt must never shrug past:
            # an unaddressable row is a halt no guard can refuse under.
            raise RiskStoreError(
                "the daily loss halt landed without leaving a row to "
                "read back; a halt that cannot be read is a halt no "
                "order layer can refuse under (feature 325)"
            )
        return self._halt_from_row(row, changed=True)

    # -- The order layer's face ------------------------------------------------

    def standing(self) -> DailyLossHalt | None:
        """The halt that stands, or ``None`` when the order layer is open.

        The guard's own datum, read from the table rather than from any
        process's memory — the state a restarted order layer must find
        exactly as its predecessor left it.  One halt stands at most, by
        the schema's partial unique index; a table found holding more
        than one un-reset row is *refused* rather than arbitrated,
        because whichever row a reader picked would be a refusal the
        other row did not justify, and the tamper that made two is the
        fact an operator needs to see.
        """
        try:
            with closing(self._open()) as connection:
                row = self._standing_row(connection)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the standing daily loss halt: {exc}"
            ) from exc
        if row is None:
            return None
        return self._halt_from_row(row, changed=False)

    def halted(self) -> bool:
        """Whether new orders are refused right now — the one-bit read.

        The bit a dashboard or a health row wants, priced as one query
        and stated as one word, with the record behind it one call away
        in :meth:`standing`.  Refuses a tampered table rather than
        answering it, the same direction :meth:`standing` refuses in:
        a ``False`` read off a broken state would be a clean bill
        nobody could justify.
        """
        return self.standing() is not None

    def require_orders_allowed(self) -> None:
        """Refuse while a halt stands — the submission path's one question.

        The sentence's own verb: *rejects new orders*.  Passes while
        nothing stands (the day never breached, or an operator reset
        it); raises :class:`~risk.errors.RiskOrdersHaltedError` while a
        halt stands, carrying the record the refusal was taken from so
        the caller learns which day, which line, which breach moment
        and which door lifts it — without a second query.  Reads and
        refuses; never writes, because a guard that wrote on the hot
        path of every submission would be a store call, not a question.

        The refusal does not lift by itself and nothing else lifts it:
        no calendar, no clock, no recovery in the day's loss figure —
        only :meth:`reset`, which is what *until a manual reset* means.
        """
        standing = self.standing()
        if standing is not None:
            raise orders_halted_error(standing)

    # -- The operator's face ---------------------------------------------------

    def reset(
        self,
        *,
        reset_at: datetime | None = None,
        reset_by: str | None = None,
    ) -> DailyLossHalt:
        """Close the standing halt — the one door that lifts the refusal.

        The operator's one call, and the sentence's own clock: the
        refusal held from the breach moment to this one, and no other
        surface ends it.  The breach facts on the row are never
        rewritten — which loss broke which limit, when, as judged by
        whom stay exactly as they landed, because they are what the
        refusal justified and what a later reconciliation reads — only
        the reset's two halves arrive, and only together.

        The moment and the actor default to the truth: the instant of
        the call and this process's kernel-read identity,
        keyword-only to override — the one spelling of each a replay
        of a recorded reset needs, and the only way a caller could
        forge them, stated at the signature.

        **First-reset-wins.**  The write is an ``UPDATE … WHERE
        reset_at IS NULL``, so under a race — two operators, or an
        operator against an automation — the write that lands second
        changes nothing and answers the winner's facts with
        ``changed=False``: the halt closes once, at one moment, by one
        actor, and the record says whose.  Refuses in
        :class:`~risk.errors.RiskDailyLossError` when nothing stands,
        because a caller that believes it re-opened the order layer
        must not be told it did.
        """
        moment = _require_aware(
            datetime.now(UTC) if reset_at is None else reset_at, "reset_at"
        )
        who = (
            self.process_id if reset_by is None else _require_text(reset_by, "reset_by")
        )
        # Opened outside the try, for the reason the halt's insert is: a
        # bootstrap IntegrityError is a broken standing law, not a reset
        # race, and the two must not be confused.
        connection = self._open()
        try:
            with closing(connection), connection:
                row = self._standing_row(connection)
                if row is None:
                    raise RiskDailyLossError(
                        f"{DAILY_LOSS_CODE}: manual_reset closes a standing "
                        "daily loss halt and nothing stands to close — the "
                        "order layer is already open, and a caller that "
                        "believed it had re-opened it a second time would "
                        "be holding a reset that closed nothing (feature 325)"
                    )
                sequence = row[0]
                cursor = connection.execute(
                    f"""
                    UPDATE {RISK_DAILY_LOSS_HALT_TABLE}
                    SET reset_at = ?, reset_by = ?
                    WHERE sequence = ? AND reset_at IS NULL
                    """,
                    (_isoformat_utc(moment), who, sequence),
                )
                changed = cursor.rowcount == 1
                closed = self._row_for(connection, sequence)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not reset the standing daily loss halt as {who}: {exc}"
            ) from exc
        if closed is None:
            # The standing row was read, the update ran, and the row it
            # names is gone -- a committed reset cannot leave less than
            # it found, and the order layer's state is not answerable
            # until an operator looks at the table.
            raise RiskStoreError(
                "the standing daily loss halt vanished inside its own "
                "reset; the order layer's state is not answerable from "
                "here and the table needs an operator's eye (feature 325)"
            )
        return self._halt_from_row(closed, changed=changed)

    # -- The reconciler's face ---------------------------------------------------

    def halts(self, *, since: datetime | None = None) -> tuple[DailyLossHalt, ...]:
        """Every daily loss halt on record, oldest first — the sweep.

        Without ``since``, the whole record — the breaches and their
        resets, the story the day told; with it, the suffix from the
        anchor, the read a reconciler performs against feature 322's
        ``sent_at`` or feature 331's events.  The bound is inclusive,
        the workspace's window convention, so a halt breached at
        exactly the anchor instant is part of the story the anchor
        begins.

        Ordering is by the breach's own moment, with the row's sequence
        breaking same-instant ties in the order the halts were
        recorded — because the sweep answers *when did the breaches
        happen*, not *when did we find out*.  **The window is a filter
        over the stored spelling**, compared against the string the
        table holds, which is correct exactly because every row *this
        store* writes goes through :func:`_isoformat_utc`; a row
        another tool wrote in another spelling may sort outside a
        window it "should" fall in, and that is the safe direction —
        not counted, rather than counted on a comparison the reader
        cannot justify.  Rows that *are* inside are reconstructed
        through :class:`DailyLossHalt`'s own validation, so nothing
        survives into a reconciliation unparsed.
        """
        clause = ""
        parameters: list[object] = []
        if since is not None:
            clause = " WHERE breached_at >= ?"
            parameters.append(_isoformat_utc(_require_aware(since, "since")))
        try:
            with closing(self._open()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT sequence, {_COLUMNS}
                    FROM {RISK_DAILY_LOSS_HALT_TABLE}{clause}
                    ORDER BY breached_at, sequence
                    """,
                    parameters,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(f"could not read the daily loss halts: {exc}") from exc
        return tuple(self._halt_from_row(row, changed=False) for row in rows)

    # -- The row plumbing ----------------------------------------------------

    def _standing_row(self, connection: sqlite3.Connection) -> tuple | None:
        """The one un-reset row, read on the connection given, or ``None``.

        Refuses — rather than arbitrates — a table holding more than one
        un-reset row: the schema's partial unique index is what keeps
        that state unreachable, so finding it means the belt was
        unbuckled by another tool, and whichever row a reader picked
        would be a refusal the other did not justify.  The refusal
        names the count, so an operator knows what to look for.
        """
        rows = connection.execute(
            f"""
            SELECT sequence, {_COLUMNS}
            FROM {RISK_DAILY_LOSS_HALT_TABLE}
            WHERE reset_at IS NULL
            ORDER BY sequence
            """
        ).fetchall()
        if len(rows) > 1:
            raise RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: the daily loss halt table holds "
                f"{len(rows)} un-reset halts where the standing law allows "
                "one — the partial unique index that enforces it has been "
                "dropped or disabled by another tool, and no guard may "
                "arbitrate between two halts by picking one; the table "
                "needs an operator's eye before the order layer's state "
                "is answerable again (feature 325)"
            )
        return rows[0] if rows else None

    @staticmethod
    def _row_for(connection: sqlite3.Connection, sequence: int | None) -> tuple | None:
        """One row by its number, on the connection given, or ``None``."""
        if sequence is None:
            return None
        return connection.execute(
            f"""
            SELECT sequence, {_COLUMNS}
            FROM {RISK_DAILY_LOSS_HALT_TABLE}
            WHERE sequence = ?
            """,
            (sequence,),
        ).fetchone()

    @staticmethod
    def _halt_from_row(row: tuple, *, changed: bool) -> DailyLossHalt:
        """Rebuild one stored row, refusing a value no halt can be.

        The refusal is the point: this table is written by this store,
        but SQLite will accept anything another tool inserts, and a row
        wearing a moment no parser accepts, a loss that is not a loss,
        or a breach its own two figures deny would otherwise stand as a
        halt nobody recorded — or fail to stand as one somebody did.
        The refusal names the row it came from, so an operator gets the
        row to repair rather than a complaint about a value with no
        address.
        """
        (
            sequence,
            loss_raw,
            limit_raw,
            breached_at_raw,
            sender,
            reset_at_raw,
            reset_by_raw,
        ) = row
        try:
            breached_at = datetime.fromisoformat(breached_at_raw)
        except (TypeError, ValueError) as exc:
            raise RiskDailyLossError(
                f"{DAILY_LOSS_CODE}: the daily loss halt row numbered "
                f"{sequence!r} carries breached_at {breached_at_raw!r}, "
                "which is not an ISO 8601 moment this store can order the "
                "sweep by (feature 325)"
            ) from exc
        reset_at: datetime | None = None
        if reset_at_raw is not None:
            try:
                reset_at = datetime.fromisoformat(reset_at_raw)
            except (TypeError, ValueError) as exc:
                raise RiskDailyLossError(
                    f"{DAILY_LOSS_CODE}: the daily loss halt row numbered "
                    f"{sequence!r} carries reset_at {reset_at_raw!r}, which "
                    "is not an ISO 8601 moment a manual reset can be "
                    "ordered by (feature 325)"
                ) from exc
        try:
            return DailyLossHalt(
                sequence=sequence,
                loss=loss_raw,
                limit=limit_raw,
                breached_at=breached_at,
                supervisor_process_id=sender,
                reset_at=reset_at,
                reset_by=reset_by_raw,
                changed=changed,
            )
        except RiskDailyLossError as refusal:
            # The value layer validates the row, and this re-raise is what
            # makes the refusal *findable*: ``DailyLossHalt`` sees one row
            # and cannot know which one, while a reader holding the table
            # can name the number and the moments the bad row came from —
            # so an operator gets the row to repair rather than a
            # complaint about a value with no address.
            raise RiskDailyLossError(
                f"{refusal} — the row this came from is daily loss halt "
                f"{sequence!r}, recorded by {sender!r} at "
                f"{breached_at_raw!r} (feature 325)"
            ) from refusal


# -- The one spelling of the refusal ----------------------------------------------


def orders_halted_error(halt: DailyLossHalt) -> RiskOrdersHaltedError:
    """The refusal a standing halt raises, composed in one place.

    One spelling for the message, so the log line an operator reads and
    the record the guard read say the same thing: the summary names the
    loss, the limit, the breach moment and the process that judged the
    day, and the closing clause names the door — *until a manual
    reset* — because the operator's next question is always "how do I
    re-open the order layer?", and the answer is the feature's own
    second half.  Refuses anything but a halt record, because a refusal
    with no breach behind it is a stop nobody justified.
    """
    if not isinstance(halt, DailyLossHalt):
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: orders_halted_error composes the refusal "
            f"from a daily loss halt record, got {halt!r} "
            f"({type(halt).__name__}); a refusal with no breach behind it "
            "is a stop nobody justified (feature 325)"
        )
    return RiskOrdersHaltedError(
        f"{ORDERS_HALTED_CODE}: {halt.summary} — the halt stands until an "
        "operator closes it through the manual reset "
        "(risk.manual_reset, feature 325); no other door lifts this "
        "refusal, and nothing lifts it by itself",
        halt,
    )


# -- The module-level spellings ----------------------------------------------------


def halt_on_daily_loss(
    *,
    daily_loss: float,
    daily_loss_limit: float,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    supervisor_process_id: str | None = None,
    breached_at: datetime | None = None,
) -> DailyLossHalt | None:
    """Judge the day against the configured limit, opening the store from
    the environment.

    The supervisor's one call: resolve the halt's store from
    ``database_url``, else from ``DATABASE_URL``, and judge.  The day is
    judged *before* the store is demanded — a day inside its limit
    answers ``None`` with no database named at all, because a day that
    never approached the line is not a reason to open one — and a day
    past it is refused *by name* when nothing names a store, because a
    halt that silently went nowhere would leave an order layer
    believing itself stopped while it traded: the one failure this
    feature cannot afford.  The order layer's direction passes
    vacuously on the same absence (:func:`require_within_daily_loss_limit`)
    and the reconciler's answers empty (:func:`recorded_daily_loss_halts`)
    — the split the module docstring states.  Everything after the
    judgement is :meth:`RiskDailyLossHaltStore.halt_on_loss`'s, whose
    refusal vocabulary and first-write-wins semantics this spelling
    inherits rather than restates.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    loss = _require_loss(daily_loss, "daily_loss")
    limit = _require_limit(daily_loss_limit)
    if not _breached(loss, limit):
        return None
    if not url:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: halt_on_daily_loss judges feature 325's "
            f"configured daily loss limit and nothing names a store: "
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the breach could not be recorded. The day's "
            "loss has exceeded the configured limit, and a halt that left "
            "no record of it is one no order layer could refuse under "
            "after a restart"
        )
    return RiskDailyLossHaltStore(url).halt_on_loss(
        daily_loss=daily_loss,
        daily_loss_limit=daily_loss_limit,
        supervisor_process_id=supervisor_process_id,
        breached_at=breached_at,
    )


def require_within_daily_loss_limit(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Refuse while a daily loss halt stands — the order layer's spelling.

    Resolves the halt's store from ``database_url``, else from
    ``DATABASE_URL``, and asks the submission path's one question.  A
    deployment that names no store passes *vacuously* — the *"no store,
    no status"* stance :func:`risk.require_orders_allowed` takes on the
    channel's own absence: a deployment with no store holds no halt
    standing in one, and a guard that refused (or answered) on the
    absence would be guarding a state nobody could ever have set.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return
    RiskDailyLossHaltStore(url).require_orders_allowed()


def manual_reset(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    reset_at: datetime | None = None,
    reset_by: str | None = None,
) -> DailyLossHalt:
    """Close the standing halt — the operator's spelling of the one door.

    Resolves the halt's store from ``database_url``, else from
    ``DATABASE_URL``, and closes what stands.  A deployment that names
    no store is refused *by name* — the mirrored reason the halting
    direction refuses: a reset that silently went nowhere would leave
    an operator believing the order layer had been re-opened while
    every submission path still refused, which is the one failure the
    reset direction cannot afford.  The moment and the actor are the
    store's own defaults unless stated, keyword-only either way.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise RiskDailyLossError(
            f"{DAILY_LOSS_CODE}: manual_reset closes feature 325's "
            f"standing daily loss halt and nothing names a store: "
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the reset could not be performed. A reset that "
            "silently went nowhere would leave an operator believing the "
            "order layer had been re-opened while every submission path "
            "still refused"
        )
    return RiskDailyLossHaltStore(url).reset(reset_at=reset_at, reset_by=reset_by)


def recorded_daily_loss_halts(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    since: datetime | None = None,
) -> tuple[DailyLossHalt, ...]:
    """The daily loss halts on record — the reconciler's spelling.

    Every halt the named store holds, oldest first, or the suffix from
    ``since`` (see :meth:`RiskDailyLossHaltStore.halts`) — the read
    feature 331's sweep joins against for the daily-loss word.  A
    deployment that names no store answers an empty tuple: halting
    refuses without a store, so a deployment that names none holds no
    halts to reconcile, and the empty answer is the truthful one — a
    caller that mistook an unconfigured deployment for an emptied
    table would reconcile against nothing and call it a clean record.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return ()
    return RiskDailyLossHaltStore(url).halts(since=since)
