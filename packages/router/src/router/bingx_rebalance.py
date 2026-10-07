"""Stage 2's scheduled rebalance: one slot of the recurring mirror.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 4:
*System runs one scheduled rebalance slot from* ``python -m
router.bingx_rebalance --book BOOK`` *and prints one JSON summary line.
The slot is the current UTC time floored to a 4-hour boundary, and
rebalance_ts is the slot start, so a second run in the same slot prints
prior for every order and places nothing new.*  In the spec's own order a
slot:

1. **runs feature 2's daily-loss guard** —
   :func:`router.bingx_risk.guard_daily_loss` — before anything is placed;
   a breach raises :class:`~router.bingx_risk.RouterBingXDailyLossHaltError`
   and the command exits 3.
2. **cancels resting orders left by this book's earlier slots in the last
   24 hours**, using :func:`router.bingx_mirror.rebalance_order_identities`
   per slot: the slots are the six 4-hour boundaries whose *identities* lie
   in the trailing day, and each slot's own order set is cancelled.
3. **reconciles the previous slot through feature 3** —
   :func:`router.bingx_reconcile.reconcile_rebalance_fill_costs` — read from
   the terms placement recorded, never from a rebuilt plan.
4. **builds and places the plan** through
   :func:`router.bingx_mirror.build_mirror_plan` and
   :func:`router.bingx_mirror.mirror_place`, idempotently: the slot stamps
   ``rebalance_ts``, so a second run in the same slot prints ``prior`` for
   every order and places nothing new.
5. **persists the rebalance** into the book member's
   :class:`book.RebalanceTargetWeightsStore` **when the book names
   ``originating_signal_ids``**, so the record is written only for a book
   that carries its provenance.

The command exits **0** when every order is ``placed`` or ``prior``, **1**
when any leg is ``refused``, and **3** on a daily-loss refusal.  It refuses
to start without ``DATABASE_URL``, because every step above reads or writes
that store: the guard records the day's opening equity in it, the cancel
and the reconcile read what earlier slots wrote, and the placement records
its terms there.

**After a slot finishes it is recorded and reported, never changed.**
Feature 2 of ``additions_spec_bingx_vst_alerts.xml``: once the summary line
is emitted — or the halt's reason printed, for exit 3 — the slot's
completion (``book_id``, ``slot``, ``finished_at``, ``exit_code``) is
appended to this module's own :data:`ROUTER_SLOT_COMPLETION_TABLE` in the
same ``DATABASE_URL`` store, and then one of feature 1's alerts follows:
**urgent** on exit 3, naming the day's loss, the limit and the manual
reset; **warning** on exit 1, listing each refused symbol with its code and
message; **info** on exit 0, summarising the orders placed, prior and
skipped, the orders cancelled, whether the previous slot was reconciled,
and the day's loss.  The record comes first so the heartbeat that reads it
(feature 3) cannot miss a finish because a phone was unreachable.  Both
acts are best-effort: a slot that cannot be recorded, and an alert that
returns ``False`` or raises, is one log line each — the JSON summary line,
the exit code and every order are identical whether alerting succeeds,
fails or is unconfigured, which is that spec's own constraint.

``deploy/systemd/`` holds the user service that runs one slot as a oneshot
and the timer that fires it at 00:05, 04:05, 08:05, 12:05, 16:05 and 20:05
UTC.  Writing those units is this feature's deliverable; enabling them is an
operator step, and nothing here installs or starts anything.

**The slot's floor is the whole of the idempotence.**  ``rebalance_ts`` is
the current UTC instant floored to a 4-hour boundary (``00:00``, ``04:00``,
…), so two runs inside one slot derive the *same* feature 316 identifier
per symbol, the placement store answers the second run from the row the
first wrote, and no order is placed twice.  The timer's five-minute offset
(``:05``) is chosen against that floor: a slot's work always stamps the
slot it belongs to, never the next one.

**Everything is injectable but nothing is required.**  ``client``,
``transport``, ``store``, ``limiter``, ``now``, ``book_store`` and the two
retry seams are seams for the suite; a deployment that injects nothing gets
feature 1's real client built from the environment, the real placement
store and limiter at ``DATABASE_URL``, and the instant of the call.  No
test opens a socket: the doubles stand in for the venue and every BingX
response the suite feeds is a recorded fixture from
``packages/router/tests/fixtures/bingx_vst/live/``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .bingx_alert import INFO, URGENT, WARNING, scrub_bot_path, send_alert
from .bingx_client import BingXClient
from .bingx_mirror import (
    MIRROR_OUTCOME_PLACED,
    MIRROR_OUTCOME_PRIOR,
    MIRROR_OUTCOME_REFUSED,
    VST_MIRROR_WEIGHT_SCHEDULE,
    build_mirror_plan,
    mirror_place,
    rebalance_order_identities,
)
from .bingx_order import BingXRefusedLeg
from .bingx_orders import cancel_rebalance_orders
from .bingx_reconcile import reconcile_rebalance_fill_costs
from .bingx_risk import (
    DATABASE_URL_ENV,
    RouterBingXDailyLossHaltError,
    RouterBingXOrdersHaltedError,
    guard_daily_loss,
)
from .errors import RouterError
from .fidelity import FIDELITY_LEG_REJECTED, FidelitySlot, reconcile_fidelity
from .limiter import RouterRateLimiter
from .retry import _sleep
from .submission_health import ORDER_SUBMISSION_REJECTED, RouterSubmissionHealthStore
from .submission_result import RouterOrderPlacementStore

__all__ = [
    "BINGX_REBALANCE_CODE",
    "DATABASE_URL_MISSING_CODE",
    "EXIT_DAILY_LOSS_HALT",
    "EXIT_OK",
    "EXIT_REFUSED",
    "REBALANCE_SLOT_HOURS",
    "ROUTER_SLOT_COMPLETION_TABLE",
    "SLOT_LOOKBACK_HOURS",
    "RebalanceReport",
    "RouterBingXRebalanceError",
    "RouterSlotCompletionStore",
    "SlotCompletion",
    "floor_to_slot",
    "main",
]

#: The greppable token this command's own faults open with — a book that
#: will not read, no store named, a slot that cannot be derived.  Coined on
#: the module's own name, the convention
#: :data:`router.bingx_mirror.MIRROR_CODE` states and every Stage 2 module
#: repeats: an operator greps one word and lands on the module that refused.
BINGX_REBALANCE_CODE = "bingx_rebalance"

#: The code word for a run asked to start with no store named.  Every step
#: of a slot reads or writes ``DATABASE_URL`` — the guard's opening equity,
#: the cancel's earlier identities, the reconcile's recorded terms, the
#: placement's rows — so a run with nowhere to keep them would be a
#: rebalance nobody could re-run idempotently.
DATABASE_URL_MISSING_CODE = "database_url_missing"

#: The width of one slot: the spec's own *"floored to a 4-hour boundary"*.
REBALANCE_SLOT_HOURS = 4

#: How far back the cancel sweeps for a book's earlier resting orders: the
#: spec's own *"earlier slots in the last 24 hours"*, which is six 4-hour
#: slots.
SLOT_LOOKBACK_HOURS = 24

#: The three exit codes the spec's sentence names, spelled once so the
#: command and its suite cannot disagree about which number means what: 0
#: when every order is placed or prior, 1 when any leg is refused, and 3 on
#: a daily-loss refusal.  (2 is deliberately unused — it is ``argparse``'s
#: own usage-error exit, and a run refused for its arguments is not a
#: rebalance outcome.)
EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_DAILY_LOSS_HALT = 3

#: The table this module's own slot-completion record lands in — the "its own
#: table" of feature 2 in ``additions_spec_bingx_vst_alerts.xml``, held in the
#: same ``DATABASE_URL`` store every other step of a slot shares so a second
#: process (the heartbeat feature 3 will add) reads what this one wrote
#: without any coordination but the database itself.
ROUTER_SLOT_COMPLETION_TABLE = "router_bingx_slot_completion"

#: The completion table's DDL, created idempotently beside the code that
#: reads it — the discipline every store in this workspace follows.  One row
#: per slot that *finished*, appended and never rewritten: a re-run inside
#: one slot is a second completion of the same slot, and what reads the
#: table wants the newest finish, not the unique one.  The exit codes are
#: pinned to the spec's own three by the table itself, so a row wearing any
#: other number is a row this store did not write.
_SLOT_COMPLETION_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {ROUTER_SLOT_COMPLETION_TABLE} (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id     TEXT NOT NULL,     -- the book the slot ran for
    slot        TEXT NOT NULL,     -- the slot's own 4-hour UTC start, ISO 8601
    finished_at TEXT NOT NULL,     -- the instant the slot finished, ISO 8601 UTC
    exit_code   INTEGER NOT NULL,  -- the spec's own three: 0 placed-or-prior, 1 refused, 3 halted
    CHECK (exit_code IN (0, 1, 3))
);
"""

#: The level each of the spec's three exits alerts at — the mapping feature 2's
#: own sentence states (*urgent for exit 3, warning for exit 1, info for exit
#: 0*), spelled once so the command and its suite cannot disagree about which
#: word means what.
_ALERT_LEVEL_BY_EXIT: Mapping[int, str] = {
    EXIT_DAILY_LOSS_HALT: URGENT,
    EXIT_REFUSED: WARNING,
    EXIT_OK: INFO,
}

#: The module's logger.  One line per best-effort fault — a completion that
#: could not be recorded, an alert that raised — carrying the greppable
#: module code, and never a token.
log = logging.getLogger("router.bingx_rebalance")


class RouterBingXRebalanceError(RouterError):
    """A scheduled slot this command cannot run.

    Raised for a fault of the *ask* — a book that will not read, a book
    that cannot name its rebalance, no store named, a slot that cannot be
    derived from the clock — never for a fact about the market.  A daily
    loss breach is *not* this class's spelling: it is feature 2's own
    :class:`~router.bingx_risk.RouterBingXDailyLossHaltError`, caught by
    the command and turned into exit 3, because the spec gives the breach
    its own exit code rather than a general failure.  Every message opens
    with :data:`BINGX_REBALANCE_CODE` and names the one repair.
    """


def floor_to_slot(moment: datetime) -> datetime:
    """Floor an aware instant to its 4-hour UTC slot's start, or refuse it.

    The spec's own *"current UTC time floored to a 4-hour boundary"*: the
    hour is truncated to a multiple of :data:`REBALANCE_SLOT_HOURS` and the
    minute, second and microsecond zeroed, so ``12:37`` floors to ``12:00``
    and ``15:59`` to ``12:00``.  The answer is the slot's **start**, which
    is exactly the ``rebalance_ts`` a slot stamps, so two runs in one slot
    derive one identifier per symbol and the second is answered ``prior``.

    A naive instant is refused: a slot is a UTC boundary, and an instant
    that names no timezone names no boundary to floor to.  The conversion
    to UTC is applied first, so the slot boundary is the venue's day rather
    than the host's.
    """

    if not isinstance(moment, datetime):
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the slot's clock answers a datetime, "
            f"got {moment!r} ({type(moment).__name__}); a slot is a UTC "
            "boundary, and a value that names no instant names no boundary "
            "(feature 4)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the slot's clock answered {moment!r}, "
            "which names no timezone; a slot is a UTC 4-hour boundary and a "
            "naive instant names no boundary to floor to (feature 4)"
        )
    utc = moment.astimezone(UTC)
    hours = (utc.hour // REBALANCE_SLOT_HOURS) * REBALANCE_SLOT_HOURS
    return utc.replace(hour=hours, minute=0, second=0, microsecond=0)


def _slot_identities(
    book: Mapping[str, Any], slots: Sequence[datetime]
) -> list[dict[str, str]]:
    """Every symbol's order name for each slot in ``slots``, flattened.

    The cancel's operand set: the spec's own *"using
    rebalance_order_identities per slot"*.  Each slot is the book's own
    identity with only its ``rebalance_ts`` replaced by the slot's start,
    so :func:`~router.bingx_mirror.rebalance_order_identities` derives one
    name per symbol the way placement derived it — the identity law feature
    316 pins — and the union over the trailing day is the set of orders
    this book could have resting from any of them.
    """

    identities: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    book_id = book.get("book_id")
    for slot in slots:
        candidate = dict(book)
        candidate["rebalance_ts"] = slot.isoformat()
        try:
            orders = rebalance_order_identities(candidate)
        except RouterError as refusal:
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: the book {book_id!r} cannot name "
                f"its orders for the slot starting {slot.isoformat()} — "
                f"{refusal}; the slot's identities are derived from the "
                "book's own identity and the slot's instant, and a book "
                "that cannot be asked names no orders to cancel (feature 4)"
            ) from refusal
        for order in orders:
            key = (order["symbol"], order["clientOrderID"])
            if key in seen:
                continue
            seen.add(key)
            identities.append(order)
    return identities


def _trailing_slots(rebalance_ts: datetime) -> list[datetime]:
    """The six slot starts in the 24 hours *before* ``rebalance_ts``.

    The spec's *"earlier slots in the last 24 hours"*: the window includes
    the rebalance's own instant only through the slots strictly before it,
    because the current slot's orders are the ones this run is about to
    place, not the ones it is clearing.  Ordered oldest-first, so the
    cancels the run makes read in the order the slots happened.
    """

    step = timedelta(hours=REBALANCE_SLOT_HOURS)
    count = SLOT_LOOKBACK_HOURS // REBALANCE_SLOT_HOURS
    return [rebalance_ts - step * (offset + 1) for offset in range(count)][::-1]


def _previous_slot(rebalance_ts: datetime) -> datetime:
    """The slot start one boundary before ``rebalance_ts``.

    The rebalance feature 3 reconciles: the slot that has just finished, so
    its fills are settled while the current slot is placed.
    """

    return rebalance_ts - timedelta(hours=REBALANCE_SLOT_HOURS)


def _read_document(path: Path) -> Any:
    """Read and decode the book document from ``path``, or refuse it.

    The one ``--`` path is the command's only filesystem interface; a path
    that will not read or a file that is not JSON is a fault of the ask,
    refused here with the path named rather than surfacing mid-slot.
    """

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document at {str(path)!r} "
            f"cannot be read: {exc}; the rebalance reads the book it is "
            "handed and fetches everything else from the venue (feature 4)"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document at {str(path)!r} is "
            f"not JSON: {exc}; the plan reads one decoded Stage 0 book and a "
            "document that will not parse has no plan in it (feature 4)"
        ) from exc


def _book_identity(book: Mapping[str, Any]) -> tuple[str, datetime]:
    """The book's ``(book_id, rebalance_ts)``, or refuse a book that names neither.

    Both terms are read the way :func:`router.bingx_dry_run.dry_run_plan`
    reads them: the id as non-empty text, the instant as an ISO 8601 string
    with an offset.  The instant is *this slot's* start, which the caller
    substitutes into the book before placing; the check here is what makes a
    book that states no identity a fault of the ask rather than a plan built
    over a nameless rebalance.
    """

    book_id = book.get("book_id")
    if not isinstance(book_id, str) or not book_id.strip():
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document states "
            f"book_id={book_id!r}; every order's name folds the book's "
            "identity, and a book that names none names no rebalance "
            "(feature 4)"
        )
    raw = book.get("rebalance_ts")
    if not isinstance(raw, str) or not raw.strip():
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document states "
            f"rebalance_ts={raw!r} ({type(raw).__name__}); the rebalance is "
            "an instant spelled as ISO 8601 text, and it is folded into every "
            "order's own name (feature 4)"
        )
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document states "
            f"rebalance_ts={raw!r}, which is not an ISO 8601 instant "
            "(feature 4)"
        ) from exc
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book document states "
            f"rebalance_ts={raw!r}, which names no timezone; a naive instant "
            "folds into the orders' keys an offset nobody agreed on, and one "
            "rebalance would answer two names (feature 4)"
        )
    return book_id.strip(), moment


def _slot_book(book: Mapping[str, Any], rebalance_ts: datetime) -> dict[str, Any]:
    """The book with its ``rebalance_ts`` replaced by this slot's start.

    A shallow copy with exactly one field replaced — the slot's own instant
    — so every order the run places or cancels is named for *this* slot
    while every other term (the weights, the equity, the horizons, the
    account) reaches the plan verbatim.  The caller's document is never
    mutated.
    """

    stamped = dict(book)
    stamped["rebalance_ts"] = rebalance_ts.isoformat()
    return stamped


@dataclass(frozen=True)
class RebalanceReport:
    """One slot's outcome, as the command prints and returns it.

    ``rebalance_ts`` is the slot start; ``book_id`` the book it was run for;
    ``guard`` the :class:`~router.bingx_risk.DailyLossCheck` the daily-loss
    guard answered; ``cancelled`` the identifiers the sweep cancelled;
    ``reconciled`` whether feature 3 recorded a fill-cost reconciliation for
    the previous slot; ``orders`` one entry per order leg with its placement
    outcome; ``refused`` one entry per leg the *venue or a gate* refused —
    a gate-closed plan leg under ``plan``, a placement refusal under
    ``placement``; ``skipped`` the gate-closed plan legs that are neither an
    order nor a refusal (a symbol with no mark, a non-tradable contract),
    which Stage 1's mirror reports informationally; ``persisted`` whether the
    rebalance was written into the book member's store, and ``persist_skipped``
    the reason it was not (a book naming no ``originating_signal_ids``).
    ``exit_code`` is the number the command returns — 0, 1 or 3, the spec's
    own three.

    The exit is driven by the spec's clause — *"0 when every order is placed
    or prior, 1 when any leg is refused"*.  A plan leg the gates closed is
    *not an order* (it names no venue order to place), so it is reported but
    never moves the exit; a shallow-symbol ``skipped`` leg is a fact the
    venue's own documents stated and is reported the same way.  Only a
    *placement* refusal — ``mirror_place`` answering ``refused`` for an
    order it tried to send — makes the exit 1.
    """

    book_id: str
    rebalance_ts: datetime
    guard: Any
    cancelled: tuple[str, ...]
    reconciled: bool
    orders: tuple[dict[str, Any], ...]
    refused: tuple[dict[str, str], ...]
    skipped: tuple[dict[str, str], ...]
    persisted: bool
    persist_skipped: str | None
    exit_code: int

    def as_line(self) -> dict[str, Any]:
        """The one JSON summary line's object, in the print's own key order."""
        return {
            "book_id": self.book_id,
            "rebalance_ts": self.rebalance_ts.isoformat(),
            "slot": floor_to_slot(self.rebalance_ts).isoformat(),
            "opening_equity": _decimal_text(self.guard.opening_equity),
            "current_equity": _decimal_text(self.guard.current_equity),
            "daily_loss": _decimal_text(self.guard.daily_loss),
            "daily_loss_limit": _decimal_text(self.guard.daily_loss_limit),
            "cancelled": list(self.cancelled),
            "reconciled": self.reconciled,
            "orders": list(self.orders),
            "refused": list(self.refused),
            "skipped": list(self.skipped),
            "persisted": self.persisted,
            "persist_skipped": self.persist_skipped,
            "exit_code": self.exit_code,
        }


def _decimal_text(value: Any) -> str:
    """Render a decimal in plain positional notation, or ``str`` it."""
    try:
        return format(value, "f")
    except (TypeError, ValueError):
        return str(value)


# -- The slot-completion record (alerts feature 2) -------------------------------


@dataclass(frozen=True)
class SlotCompletion:
    """One slot that finished, as this module records and reads it back.

    The four fields feature 2's own sentence names — the ``book_id`` the
    slot ran for, the ``slot`` (the 4-hour UTC start the run stamped as its
    ``rebalance_ts``), the ``finished_at`` instant and the ``exit_code`` —
    and nothing else: the record is the heartbeat's operand, not a second
    summary line, so it carries what a reader must know to judge *when the
    bot last finished a slot* and no more.  The moments are timezone-aware
    in the table's one canonical UTC spelling.
    """

    book_id: str
    slot: datetime
    finished_at: datetime
    exit_code: int


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`router.bingx_risk` and :mod:`router.store`
    each restate in their own words, for the reason each of them does: a
    store reaches into no sibling's private helper.  ``sqlite:///foo.db``
    is relative, ``sqlite:////foo.db`` is absolute, and any other scheme
    is refused by name in this module's own vocabulary — an address this
    record cannot speak holds no table to complete a slot in.
    """

    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: unsupported {DATABASE_URL_ENV} scheme "
            f"{parsed.scheme!r}: the slot-completion record is kept in the "
            "sqlite store the spec's single-machine allowment names "
            "(sqlite:///), and an address this module cannot speak holds no "
            "table to record a finished slot in (alerts feature 2)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (alerts feature 2)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: sqlite {DATABASE_URL_ENV} carries no "
            "database path: an in-memory store would die with the connection "
            "that opened it, and a slot whose completion vanished would leave "
            "the heartbeat alerting about a bot that is running (alerts "
            "feature 2)"
        )
    return Path(path)


def _utc_text(moment: datetime) -> str:
    """The table's one canonical moment spelling: aware, UTC, ISO 8601."""

    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: Any, what: str) -> datetime:
    """An aware instant, or a refusal naming the field it was read from."""

    if not isinstance(moment, datetime) or (
        moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None
    ):
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: a slot completion's {what} is an "
            f"aware instant, got {moment!r}; the record is what the "
            "heartbeat measures an age against, and an instant that names "
            "no timezone names no age (alerts feature 2)"
        )
    return moment


def _completion_from_row(row: Sequence[Any]) -> SlotCompletion:
    """Reconstruct one completion from its row, or refuse a row this store
    could not have written.

    The same defence :meth:`router.bingx_risk.RouterDailyOpeningEquityStore`
    makes of its own rows: what a reader refuses under is the stored record,
    so a row edited outside this package — an exit code outside the spec's
    three, a moment no parser accepts — fails to reconstruct rather than
    loading as a plausible-looking finish.
    """

    book_id, slot_text, finished_text, exit_code = row
    if not isinstance(book_id, str) or not book_id.strip():
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: {ROUTER_SLOT_COMPLETION_TABLE} holds "
            f"book_id={book_id!r}; a slot ran for a named book, and a row "
            "that names none is a row this store did not write (alerts "
            "feature 2)"
        )
    try:
        slot = datetime.fromisoformat(str(slot_text))
        finished_at = datetime.fromisoformat(str(finished_text))
    except ValueError as exc:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: {ROUTER_SLOT_COMPLETION_TABLE} holds "
            f"slot={slot_text!r}, finished_at={finished_text!r}, which is "
            "not ISO 8601 text; the record's moments are the heartbeat's "
            "clock, and a row that states none is a row this store did not "
            "write (alerts feature 2)"
        ) from exc
    if exit_code not in _ALERT_LEVEL_BY_EXIT or isinstance(exit_code, bool):
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: {ROUTER_SLOT_COMPLETION_TABLE} holds "
            f"exit_code={exit_code!r}; a slot finishes on one of the spec's "
            "own three exits (0, 1, 3), and a row wearing any other number "
            "is a row this store did not write (alerts feature 2)"
        )
    return SlotCompletion(
        book_id=book_id,
        slot=_require_aware(slot, "slot"),
        finished_at=_require_aware(finished_at, "finished_at"),
        exit_code=int(exit_code),
    )


class RouterSlotCompletionStore:
    """Holds and answers this module's own slot-completion table.

    Bound to a database URL at construction; construction performs no I/O,
    so composing a caller never touches the database and the store costs
    nothing until a slot finishes.  Each operation opens its own
    connection, creating the schema idempotently if absent — the
    discipline every store in this workspace follows, which is what makes
    the record readable from a *different* process (the heartbeat's hourly
    check) than the one that wrote it: the database, not any process's
    memory, is the coordination point.

    Two faces, one table: the rebalance appends a finish (:meth:`record`)
    and the heartbeat asks for the newest one (:meth:`newest`) — the
    question feature 3's own sentence asks of this record.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL; a slot's completion is recorded in "
                "the store it names, and an address that states nothing "
                "names no store to record in (alerts feature 2)"
            )
        self._database_url = database_url.strip()

    @property
    def database_url(self) -> str:
        """The database URL this table's completions stand in."""
        return self._database_url

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SLOT_COMPLETION_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the table to the shape this store reads, idempotently.

        Public so a test seeding a finish can prepare the table without
        reaching for the private :meth:`_connect` — the same door
        :class:`router.bingx_risk.RouterDailyOpeningEquityStore` leaves
        open, for the same reason.
        """

        self._connect().close()

    def record(
        self,
        *,
        book_id: str,
        slot: datetime,
        finished_at: datetime,
        exit_code: int,
    ) -> None:
        """Append one slot's completion — the four fields, once each.

        The write is an append, never an upsert: a re-run inside one slot
        is a *second* completion of that slot (the timer's catch-up), and
        the reader asks for the newest finish rather than the unique one,
        so rewriting the row would hide exactly the fact the record exists
        to state.
        """

        if not isinstance(book_id, str) or not book_id.strip():
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: a slot completion names the book "
                f"it ran for, got {book_id!r}; every order's name folds the "
                "book's identity, and a completion that names none names no "
                "slot (alerts feature 2)"
            )
        _require_aware(slot, "slot")
        _require_aware(finished_at, "finished_at")
        if exit_code not in _ALERT_LEVEL_BY_EXIT or isinstance(exit_code, bool):
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: a slot finishes on one of the "
                f"spec's own three exits (0, 1, 3), got {exit_code!r}; the "
                "record is what the heartbeat judges an age against, and an "
                "exit this module cannot take names no outcome (alerts "
                "feature 2)"
            )
        with closing(self._connect()) as connection, connection:
            connection.execute(
                f"INSERT INTO {ROUTER_SLOT_COMPLETION_TABLE} "
                "(book_id, slot, finished_at, exit_code) "
                "VALUES (?, ?, ?, ?)",
                (
                    book_id,
                    _utc_text(slot),
                    _utc_text(finished_at),
                    int(exit_code),
                ),
            )

    def newest(self) -> SlotCompletion | None:
        """The most recently finished slot, or ``None`` when none has.

        "Newest" is judged on ``finished_at`` with the row's own number
        breaking a tie — two runs finishing inside one clock tick are two
        completions, and the heartbeat wants the later of them.
        """

        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"SELECT book_id, slot, finished_at, exit_code "
                    f"FROM {ROUTER_SLOT_COMPLETION_TABLE} "
                    "ORDER BY finished_at DESC, id DESC LIMIT 1"
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: could not read the newest slot "
                f"completion from the store: {exc}; the heartbeat judges "
                "the bot's health on this record, and a store that cannot "
                "be asked about it cannot answer for the bot (alerts "
                "feature 2)"
            ) from exc
        if row is None:
            return None
        return _completion_from_row(row)


# -- The slot's alert (alerts feature 2) -----------------------------------------


def _figure_text(value: Any) -> str:
    """A halt's figure, in the spelling its own record carries.

    The guard's breach measures its figures as exact decimals, while the
    standing halt record carries them as the floats feature 325's store
    reads — ``400.0``, spelled the way that member's own summary spells it.
    A bare :func:`format` on a float would widen it to six places nobody
    sent, so a float is narrowed through its own shortest decimal spelling
    first and everything else passes to :func:`_decimal_text` unchanged.
    """

    if isinstance(value, float):
        return _decimal_text(Decimal(str(value)))
    return _decimal_text(value)


def _halt_alert_text(book_id: str, slot: datetime, halt: BaseException) -> str:
    """The urgent body for exit 3: the loss, the limit, the manual reset.

    Both of feature 2's halt refusals carry the figures the sentence names:
    a fresh breach measures them on its :attr:`check`, and a halt that
    already stands carries them on the record feature 325 wrote when it
    tripped.  The repair is the same door either way — the manual reset —
    because the halt does not lift by itself.
    """

    check = getattr(halt, "check", None)
    if check is not None:
        loss, limit = check.daily_loss, check.daily_loss_limit
    else:
        standing = halt.halt
        loss, limit = standing.loss, standing.limit
    return (
        f"The {slot.isoformat()} slot for book {book_id} exited 3: the "
        "daily-loss guard refused the day.\n"
        f"The day's loss {_figure_text(loss)} USDT passed the daily loss "
        f"limit {_figure_text(limit)} USDT.\n"
        "Orders are refused until an operator closes the halt through the "
        "manual reset (risk.daily_loss.manual_reset)."
    )


def _refusal_alert_text(report: RebalanceReport) -> str:
    """The warning body for exit 1: each refused symbol, code and message.

    The listing is the sentence's own requirement — one line per leg the
    venue would not take, carrying the code and the message exactly as the
    summary line recorded them, so an operator reading the phone and one
    reading the journal see the same refusal.
    """

    opener = (
        f"The {report.rebalance_ts.isoformat()} slot for book "
        f"{report.book_id} exited 1: {len(report.refused)} of its "
        f"{len(report.orders)} order legs were refused."
    )
    lines = [opener]
    for entry in report.refused:
        line = f"- {entry['symbol']}: {entry['placement'] or 'no code'}"
        if entry.get("message"):
            line += f" — {entry['message']}"
        lines.append(line)
    return "\n".join(lines)


def _summary_alert_text(report: RebalanceReport) -> str:
    """The info body for exit 0: the slot's own summary, silently delivered.

    Every clause of the sentence's list — the orders placed, prior and
    skipped, the orders cancelled, whether the previous slot was
    reconciled, and the day's loss — stated as figures, because the alert
    is a summary and the JSON line above it already carries the detail.
    """

    placed = sum(
        1 for order in report.orders if order["outcome"] == MIRROR_OUTCOME_PLACED
    )
    prior = sum(
        1 for order in report.orders if order["outcome"] == MIRROR_OUTCOME_PRIOR
    )
    reconciled = "yes" if report.reconciled else "no"
    opener = (
        f"The {report.rebalance_ts.isoformat()} slot for book "
        f"{report.book_id} exited 0."
    )
    orders = (
        f"Orders: {placed} placed, {prior} prior, "
        f"{len(report.skipped)} skipped by the gates."
    )
    cancelled = (
        f"Cancelled {len(report.cancelled)} resting order(s) left by "
        "earlier slots."
    )
    reconcile = f"The previous slot was reconciled: {reconciled}."
    loss = (
        f"The day's loss is {_decimal_text(report.guard.daily_loss)} USDT "
        f"against the limit {_decimal_text(report.guard.daily_loss_limit)} "
        "USDT."
    )
    return f"{opener}\n{orders}\n{cancelled}\n{reconcile}\n{loss}"


def _complete_slot(
    *,
    book_id: str,
    slot: datetime,
    finished_at: datetime,
    exit_code: int,
    report: RebalanceReport | None,
    halt: BaseException | None,
    env: Mapping[str, str] | None,
    transport: Any,
    completion_store: Any,
    alert: Callable[..., bool],
) -> None:
    """Record the slot's completion, then send its alert — best-effort, both.

    The spec's own order — *records the slot's completion ... then sends
    feature 1's alert* — and its own stance: alerting never alters trading,
    so each act is wrapped separately (a record that could not be written
    is no reason to stay silent about the slot) and a fault in either is
    exactly one log line.  An alert that raises is caught and logged here
    rather than left to the command's own ``except RouterError``, which
    would answer a delivery fault with the wrong exit code — the one way
    alerting could change a slot's outcome, and the one thing this
    feature's constraint forbids.
    """

    try:
        completion_store.record(
            book_id=book_id,
            slot=slot,
            finished_at=finished_at,
            exit_code=exit_code,
        )
    except Exception as exc:  # noqa: BLE001 - the record is best-effort too
        log.warning(
            "%s: the %s slot's completion could not be recorded (%s)",
            BINGX_REBALANCE_CODE,
            slot.isoformat(),
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )
    try:
        if exit_code == EXIT_DAILY_LOSS_HALT:
            text = _halt_alert_text(book_id, slot, halt)
        elif exit_code == EXIT_REFUSED:
            text = _refusal_alert_text(report)
        else:
            text = _summary_alert_text(report)
        alert(_ALERT_LEVEL_BY_EXIT[exit_code], text, env=env, transport=transport)
    except Exception as exc:  # noqa: BLE001 - the alert never alters the slot
        log.warning(
            "%s: the %s slot's %s alert raised and was caught (%s)",
            BINGX_REBALANCE_CODE,
            slot.isoformat(),
            _ALERT_LEVEL_BY_EXIT.get(exit_code, "slot"),
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )


def _persist_target_weights(
    *,
    book: Mapping[str, Any],
    book_id: str,
    rebalance_ts: datetime,
    book_store: Any,
) -> tuple[bool, str | None]:
    """Persist the rebalance when the book names ``originating_signal_ids``.

    Step 5 of the spec's sentence.  The book's ``originating_signal_ids`` is
    the provenance: a list of the promoted signals that weighted it.  When
    the key is absent — the synthetic book today, which carries none — the
    step is skipped and the reason is reported, because a book with no
    provenance is a legitimate deployment state (the spec names the swap to
    real signals as a later input change) rather than a fault.

    When the key *is* present it must be a non-empty list of strings: a book
    that names an empty or malformed provenance is refused, because the
    member's store refuses one and a silent skip would hide a book whose
    signal ids were mistyped.  The signals are handed to the store as small
    values carrying ``signal_id`` — the surface
    :meth:`book.RebalanceTargetWeightsStore.record` reads — so this module
    names no book-member value type of its own.
    """

    if "originating_signal_ids" not in book:
        return False, "no_originating_signal_ids"
    raw = book.get("originating_signal_ids")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or not raw:
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the book names originating_signal_ids="
            f"{raw!r}; a provenance is a non-empty list of the promoted "
            "signals' identifiers, and the rebalance is persisted with it "
            "(feature 4)"
        )
    identifiers: list[str] = []
    for item in raw:
        value = item.get("signal_id") if isinstance(item, Mapping) else item
        if not isinstance(value, str) or not value.strip():
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: the book's originating_signal_ids "
                f"carries {item!r}, which names no signal identifier; the "
                "provenance is a set of the identified signals that weighted "
                "the book (feature 4)"
            )
        identifiers.append(value.strip())
    signals = [_SignalId(identifier) for identifier in identifiers]
    weights = _WeightSet(book.get("weights"))
    book_store.record(
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        target_weights=weights,
        originating_signals=signals,
    )
    return True, None


@dataclass(frozen=True)
class _SignalId:
    """A promoted signal's identifier, as the book member's store reads it.

    The store reads each originating signal's ``signal_id`` duck-typed, so a
    value exposing that surface is a signal there whatever composed it; this
    is the smallest such value, built from the book's own
    ``originating_signal_ids`` list rather than imported from the book
    member, so this module holds no cross-member value type.
    """

    signal_id: str


@dataclass(frozen=True)
class _WeightSet:
    """A target weight set, as the book member's store reads it.

    The store reads ``weights`` duck-typed — the surface feature 305's
    published book carries — so this wraps the book document's own weights
    mapping.  The values are read as ``float`` by the member's own
    validator, which is why they pass through unchanged.
    """

    weights: Mapping[str, Any]


def _reconcile_fidelity(
    *, book_id: str, previous: datetime, database_url: str
) -> None:
    """Feature 5 of the VST fidelity spec, run right after step 3's own
    reconciliation (which it never changes).

    Computes and persists the previous slot's sim-versus-live fidelity
    (:func:`router.fidelity.reconcile_fidelity`) purely from stores this
    slot's own earlier runs already wrote — it never places, cancels or
    closes anything, and opens no socket — then writes the slot's mean gap
    and reject rate to the ops member's live metrics and records each
    rejected leg to this member's own submission-health log.

    **Best-effort, the same stance feature 2's alert takes.**  A fault here
    — the ops member not being importable, a store that cannot be reached —
    is logged and the slot still completes: this step adds a diagnostic
    reading, and a diagnostic that cannot be taken must not turn a placed
    slot into a failed one.
    """

    try:
        fidelity = reconcile_fidelity(
            FidelitySlot(book_id=book_id, rebalance_ts=previous),
            database_url=database_url,
        )
        if fidelity is None:
            return
        if fidelity.gap_bps is not None or fidelity.reject_rate is not None:
            # Deferred past module scope, like every cross-member import in
            # this package: the factory's workspace scan puts one member's
            # src/ on sys.path at a time, so a module-scope import here
            # would make this module's importability depend on scan order.
            from ops.live_metrics import LiveMetricsStore

            metrics = LiveMetricsStore(database_url)
            if fidelity.gap_bps is not None:
                metrics.record("fill_cost_bps", fidelity.gap_bps)
            if fidelity.reject_rate is not None:
                metrics.record("reject_rate", fidelity.reject_rate)
        rejected = [
            order
            for order in fidelity.orders
            if order.leg_state == FIDELITY_LEG_REJECTED
        ]
        if rejected:
            health = RouterSubmissionHealthStore(database_url)
            for order in rejected:
                health.record(
                    outcome=ORDER_SUBMISSION_REJECTED,
                    symbol=order.symbol,
                    client_order_id=order.client_order_id,
                )
    except Exception as exc:  # noqa: BLE001 - fidelity reconciliation is best-effort
        log.warning(
            "%s: the %s slot's fidelity could not be reconciled (%s)",
            BINGX_REBALANCE_CODE,
            previous.isoformat(),
            scrub_bot_path(f"{type(exc).__name__}: {exc}"),
        )


def _run_slot(
    *,
    book: Mapping[str, Any],
    client: Any,
    store: Any,
    limiter: Any,
    database_url: str,
    env: Mapping[str, str] | None,
    rebalance_ts: datetime,
    book_store: Any,
    clock: Callable[[], int] | None,
    sleep: Callable[[timedelta], Any],
    jitter_rng: Any,
    on_retry: Any,
) -> RebalanceReport:
    """Run the five steps of one slot, in the order the spec's sentence gives.

    Raises :class:`~router.bingx_risk.RouterBingXDailyLossHaltError` on step
    1's breach (the command turns it into exit 3) and any other
    :class:`~router.errors.RouterError` a step refuses with; answers the
    :class:`RebalanceReport` otherwise, with ``exit_code`` 0 or 1.
    """

    book_id, _ = _book_identity(book)
    stamped = _slot_book(book, rebalance_ts)

    # 1 — the daily-loss guard, before anything is placed.  A breach raises
    #     feature 2's own refusal, which the command answers with exit 3.
    #     The guard is handed *the slot's own instant* as its moment, never
    #     the wall clock: the day whose opening equity the check measures
    #     against must be the slot's day, or a run near midnight would open
    #     the next day's row with the slot's own floor — the UTC day is the
    #     same fact the slot's boundary is taken from.
    guard = guard_daily_loss(
        client=client,
        book=stamped,
        database_url=database_url,
        env=env,
        now=lambda: rebalance_ts,
    )

    # 2 — cancel the book's resting orders from the trailing day's slots.
    previous = _previous_slot(rebalance_ts)
    trailing = _trailing_slots(rebalance_ts)
    identities = _slot_identities(book, trailing)
    cancelled = tuple(cancel_rebalance_orders(client=client, orders=identities))

    # 3 — reconcile the previous slot, from the terms placement recorded.
    reconciliation = reconcile_rebalance_fill_costs(
        client=client,
        book_id=book_id,
        rebalance_ts=previous,
        database_url=database_url,
        env=env,
    )
    # Feature 5 of the VST fidelity spec: the real sim-versus-live gap,
    # beside the fee-only reconciliation above, which stays unchanged.
    _reconcile_fidelity(
        book_id=book_id, previous=previous, database_url=database_url
    )

    # 4 — build and place this slot's plan, idempotently.
    plan = build_mirror_plan(book=stamped, client=client)
    outcomes = mirror_place(
        client=client,
        book=stamped,
        plan=plan,
        store=store,
        limiter=limiter,
        database_url=database_url,
        env=env,
        clock=clock,
        sleep=sleep,
        jitter_rng=jitter_rng,
        on_retry=on_retry,
    )
    orders: list[dict[str, Any]] = []
    refused: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    every_landed = True
    for leg in plan:
        if isinstance(leg, BingXRefusedLeg):
            # A leg the *gates* closed before anything was sent: it names no
            # venue order, so it is not an order to place and never moves the
            # exit — Stage 1's mirror reports it the same informational way.
            skipped.append({"symbol": leg.symbol, "code": leg.code})
            continue
        outcome = outcomes[leg.symbol]
        orders.append({"symbol": leg.symbol, "outcome": outcome.outcome})
        if outcome.outcome == MIRROR_OUTCOME_REFUSED:
            entry = {"symbol": leg.symbol, "placement": outcome.code or ""}
            if outcome.message is not None:
                entry["message"] = outcome.message
            refused.append(entry)
            every_landed = False

    # 5 — persist the rebalance when the book names its provenance.
    persisted, persist_skipped = _persist_target_weights(
        book=book,
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        book_store=book_store,
    )

    return RebalanceReport(
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        guard=guard,
        cancelled=cancelled,
        reconciled=reconciliation is not None,
        orders=tuple(orders),
        refused=tuple(refused),
        skipped=tuple(skipped),
        persisted=persisted,
        persist_skipped=persist_skipped,
        exit_code=EXIT_OK if every_landed else EXIT_REFUSED,
    )


def _resolve_database_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str | None:
    """The store's address from the argument, else ``DATABASE_URL``."""

    if database_url is not None:
        return database_url.strip() or None
    source = os.environ if env is None else env
    return source.get(DATABASE_URL_ENV, "").strip() or None


def _resolve_book_store(env: Mapping[str, str] | None, database_url: str) -> Any:
    """The book member's target-weight store, imported deferred.

    The store is reached inside the slot, never at module scope, for the
    reason every cross-member import in this package is deferred: a module
    never imports a sibling at import time, so scan order cannot decide
    whether this module loads.  A member that is not importable is named.
    """

    try:
        from book import RebalanceTargetWeightsStore
    except ModuleNotFoundError as exc:  # pragma: no cover - declared dependency
        raise RouterBingXRebalanceError(
            f"{BINGX_REBALANCE_CODE}: the rebalance is persisted into the book "
            "member (book.RebalanceTargetWeightsStore), and that member is not "
            "importable in this environment; run `uv sync --all-packages` in "
            "the workspace root (or put packages/book/src on sys.path) so the "
            "store feature 309 declares can be reached (feature 4)"
        ) from exc
    return RebalanceTargetWeightsStore(database_url)


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    transport: Any = None,
    store: Any = None,
    limiter: Any = None,
    book_store: Any = None,
    completion_store: Any = None,
    env: Mapping[str, str] | None = None,
    database_url: str | None = None,
    now: Callable[[], datetime] | None = None,
    clock: Callable[[], int] | None = None,
    sleep: Callable[[timedelta], Any] = _sleep,
    jitter_rng: Any = None,
    on_retry: Any = None,
    alert: Callable[..., bool] | None = None,
    emit: Callable[[str], None] = print,
) -> int:
    """One scheduled rebalance slot: ``python -m router.bingx_rebalance --book BOOK``.

    Reads the book, floors the current UTC time to its 4-hour boundary, runs
    the five steps of the spec's sentence in order, prints one JSON summary
    line, and returns the spec's own exit code: 0 when every order was placed
    or prior, 1 when any leg was refused, 3 on a daily-loss refusal.  It
    refuses to start without ``DATABASE_URL``.

    Once the slot has an outcome the completion is recorded and the alert
    sent — after the summary line, never instead of it — as
    :func:`_complete_slot` states, so neither act can change the line, the
    orders or the exit code.

    The seams — ``client``, ``transport``, ``store``, ``limiter``,
    ``book_store``, ``completion_store``, ``env``, ``database_url``, ``now``,
    the retry pair, ``alert`` and ``emit`` — are injectable so the suite
    drives the command against a recording double with no environment
    variable that could change the host; a caller that injects nothing gets
    feature 1's real client built from the environment.  ``transport`` is
    the one HTTP door for the whole command — venue and Bot API share its
    ``(method, url, headers, body) -> (status, body)`` contract — and
    ``alert`` defaults to :func:`router.bingx_alert.send_alert`.
    """

    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_rebalance",
        description=(
            "Run one scheduled rebalance slot for a book: guard the day's "
            "loss, cancel the book's resting orders from the last 24 hours, "
            "reconcile the previous slot, then build and place this slot's "
            "plan. rebalance_ts is the current UTC time floored to a 4-hour "
            "boundary, so a second run in the same slot places nothing new."
        ),
    )
    parser.add_argument(
        "--book",
        required=True,
        type=Path,
        help="the book document (JSON): book_id, rebalance_ts, account, "
        "margin_mode, equity_usdt, expected_fill_seconds, weights, "
        "decay_horizon_seconds, positions",
    )
    arguments = parser.parse_args(argv)

    try:
        url = _resolve_database_url(database_url, env)
        if url is None:
            raise RouterBingXRebalanceError(
                f"{DATABASE_URL_MISSING_CODE}: a scheduled slot records the "
                "day's opening equity, cancels by the identities earlier "
                "slots wrote, reconciles the previous slot's recorded terms "
                f"and records its own placements — all in the store the "
                f"{DATABASE_URL_ENV} names — so it cannot start without one; "
                f"set {DATABASE_URL_ENV} to the sqlite database those records "
                "live in and run again (feature 4)"
            )
        book = _read_document(arguments.book)
        if not isinstance(book, Mapping):
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: the book document at "
                f"{str(arguments.book)!r} is a JSON object — got "
                f"{type(book).__name__}; the Stage 0 book states its "
                "identity, equity, weights, horizons and positions as one "
                "object (feature 4)"
            )
        book_id, _ = _book_identity(book)

        if now is not None and not callable(now):
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: now must be callable answering the "
                f"slot's moment, got {now!r} ({type(now).__name__}); the "
                "moment is floored to its slot, and a value that is not a "
                "callable names no moment (feature 4)"
            )
        moment_fn = now if now is not None else (lambda: datetime.now(UTC))
        moment = moment_fn()
        rebalance_ts = floor_to_slot(moment)

        if client is None:
            client = BingXClient.from_env(env=env, transport=transport)
        if store is None:
            store = RouterOrderPlacementStore(url)
        if limiter is None:
            limiter = RouterRateLimiter(url, schedule=VST_MIRROR_WEIGHT_SCHEDULE)
        if book_store is None:
            book_store = _resolve_book_store(env, url)
        if completion_store is None:
            completion_store = RouterSlotCompletionStore(url)
        sender = alert if alert is not None else send_alert

        try:
            report = _run_slot(
                book=book,
                client=client,
                store=store,
                limiter=limiter,
                database_url=url,
                env=env,
                rebalance_ts=rebalance_ts,
                book_store=book_store,
                clock=clock,
                sleep=sleep,
                jitter_rng=jitter_rng,
                on_retry=on_retry,
            )
        except (RouterBingXDailyLossHaltError, RouterBingXOrdersHaltedError) as halt:
            # The spec gives the daily-loss refusal its own exit code.  Both
            # of feature 2's refusals land here: a breach trip (the day's
            # loss passed the limit) and a *standing* halt (a breach earlier
            # in the day that nobody has reset).  Both mean the same thing to
            # the slot — the order layer is halted and nothing is placed —
            # and both take exit 3 rather than being reported as a general
            # placement refusal.  The guard's own message, carrying the day's
            # loss and the halt, goes to stderr so an operator sees why.
            print(str(halt), file=sys.stderr)
            # The halted slot finished too: exit 3 is an outcome, and it is
            # recorded and alerted as one — urgently, naming the loss, the
            # limit and the manual reset — without touching the exit.
            _complete_slot(
                book_id=book_id,
                slot=rebalance_ts,
                finished_at=moment_fn(),
                exit_code=EXIT_DAILY_LOSS_HALT,
                report=None,
                halt=halt,
                env=env,
                transport=transport,
                completion_store=completion_store,
                alert=sender,
            )
            return EXIT_DAILY_LOSS_HALT

        emit(json.dumps(report.as_line()))
        # The summary line is already emitted, so what follows cannot change
        # it: the completion is recorded and the alert sent, best-effort,
        # after the outcome they report is on the record.
        _complete_slot(
            book_id=report.book_id,
            slot=report.rebalance_ts,
            finished_at=moment_fn(),
            exit_code=report.exit_code,
            report=report,
            halt=None,
            env=env,
            transport=transport,
            completion_store=completion_store,
            alert=sender,
        )
        return report.exit_code
    except RouterError as exc:
        message = str(exc)
        prefix = f"{BINGX_REBALANCE_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
