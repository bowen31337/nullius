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
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .bingx_client import BingXClient
from .bingx_mirror import (
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
from .limiter import RouterRateLimiter
from .retry import _sleep
from .submission_result import RouterOrderPlacementStore

__all__ = [
    "BINGX_REBALANCE_CODE",
    "DATABASE_URL_MISSING_CODE",
    "EXIT_DAILY_LOSS_HALT",
    "EXIT_OK",
    "EXIT_REFUSED",
    "REBALANCE_SLOT_HOURS",
    "SLOT_LOOKBACK_HOURS",
    "RebalanceReport",
    "RouterBingXRebalanceError",
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
    env: Mapping[str, str] | None = None,
    database_url: str | None = None,
    now: Callable[[], datetime] | None = None,
    clock: Callable[[], int] | None = None,
    sleep: Callable[[timedelta], Any] = _sleep,
    jitter_rng: Any = None,
    on_retry: Any = None,
    emit: Callable[[str], None] = print,
) -> int:
    """One scheduled rebalance slot: ``python -m router.bingx_rebalance --book BOOK``.

    Reads the book, floors the current UTC time to its 4-hour boundary, runs
    the five steps of the spec's sentence in order, prints one JSON summary
    line, and returns the spec's own exit code: 0 when every order was placed
    or prior, 1 when any leg was refused, 3 on a daily-loss refusal.  It
    refuses to start without ``DATABASE_URL``.

    The seams — ``client``, ``transport``, ``store``, ``limiter``,
    ``book_store``, ``env``, ``database_url``, ``now`` and the retry pair —
    are injectable so the suite drives the command against a recording double
    with no environment variable that could change the host; a caller that
    injects nothing gets feature 1's real client built from the environment.
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
        _book_identity(book)

        if now is not None and not callable(now):
            raise RouterBingXRebalanceError(
                f"{BINGX_REBALANCE_CODE}: now must be callable answering the "
                f"slot's moment, got {now!r} ({type(now).__name__}); the "
                "moment is floored to its slot, and a value that is not a "
                "callable names no moment (feature 4)"
            )
        moment = (now if now is not None else (lambda: datetime.now(UTC)))()
        rebalance_ts = floor_to_slot(moment)

        if client is None:
            client = BingXClient.from_env(env=env, transport=transport)
        if store is None:
            store = RouterOrderPlacementStore(url)
        if limiter is None:
            limiter = RouterRateLimiter(url, schedule=VST_MIRROR_WEIGHT_SCHEDULE)
        if book_store is None:
            book_store = _resolve_book_store(env, url)

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
            return EXIT_DAILY_LOSS_HALT

        emit(json.dumps(report.as_line()))
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
