"""Stage 1's command: mirror a book onto the BingX VST venue.

``additions_spec_bingx_vst_mirror.xml``, "BingX VST Mirror", feature 4:
*System mirrors a book onto VST from* ``python -m router.bingx_mirror --book
BOOK``.  *It fetches the contracts and premiumIndex documents from VST,
replaces the book's positions with the account's live VST positions, and
builds the plan with dry_run_plan.*

* Without ``--place`` it prints the plan in Stage 0's JSON-lines format and
  exits 0 while placing nothing.
* With ``--place`` it requires ``DATABASE_URL`` and runs the preflight.
  Then it places each order through
  :meth:`router.submission_result.RouterOrderPlacementStore.place`,
  acquiring :class:`~router.limiter.RouterRateLimiter` weight and retrying
  429s with :func:`router.retry.retry_rate_limited`.  It prints one JSON
  line per leg: ``placed``, ``prior`` (already placed), or ``refused`` with
  its code and the venue's own message.  It exits 0 when every order was
  placed or was already placed, and 1 otherwise.
* When a POST /trade/order times out or its connection drops, the outcome
  is unknown.  The mirror then queries that ``clientOrderID`` before doing
  anything else.  A found order is recorded as placed, and only a
  ``not_found`` answer is re-posted, so a blind retry never meets BingX's
  duplicate-``clientOrderID`` refusal for an order that actually landed.
* ``--status`` prints feature 3's read-back, and ``--cancel`` cancels the
  rebalance's open orders.  Both address the rebalance's orders **by
  identity**, never by today's plan: for every symbol the book's weights
  name, the ``clientOrderID`` derived from ``(book_id, rebalance_ts,
  symbol)`` exactly as placement derives it (see
  :func:`rebalance_order_identities`).  The plan is re-sized against the
  account's live positions, so a symbol whose position has reached its
  target, or whose leg a gate refused, has no leg in it — while its placed
  order still sits on the venue's book.  ``--status`` therefore prints one
  line per book symbol, in the book's order (a symbol never placed or
  refused answers ``not_found``), with the decimals in plain positional
  notation; ``--cancel`` cancels every open order whose identifier belongs
  to that set, whatever today's plan says.  Neither command needs
  ``DATABASE_URL``, places anything or reads the venue's quote documents.

**The command reads its documents from the venue, not from paths.**  Stage
0's dry run takes three files; this command takes one book and fetches the
two venue documents through feature 1's client
(:meth:`~router.bingx_client.BingXClient.contracts` and
:meth:`~router.bingx_client.BingXClient.premium_index`), so the plan the
mirror places is built over *this instant's* venue state — the whole point
of a mirror, as the capture fixture's own note says: VST's filters differed
from the live venue's for hundreds of shared symbols, so a VST mirror must
read VST's own document.  The plan itself is built by
:func:`router.bingx_dry_run.dry_run_plan`, unchanged: this module re-weights
and re-positions the book, and re-implements no gate, no document reader and
no gate order.

**Only the positions are replaced, and only with what the account holds.**
The book's ``positions`` read the Stage 0 way is a *signed contract quantity
per symbol currently held*; on the live venue the truth of that field is the
account's own position document, so the mirror reads
:meth:`~router.bingx_client.BingXClient.positions` and answers a shallow
copy of the book with exactly that one field replaced.  Every other term —
the identity feature 316 folds, the weights feature 305 publishes, the
equity, the decay horizons, the margin arrangement — reaches the plan
verbatim, and the caller's document is never mutated (the fixtures are
inputs, and a book that reported positions it did not hold would size a
delta against a position the account never took).  A flat account answers no
positions at all, which is the empty mapping: every leg is sized from flat,
which is the state the end-to-end stand-in holds.

**Passive legs are priced at the book, never at the mark.**  The plan's
prices are Stage 0's own rule — the mark rounded onto the tick grid away
from crossing — written for an *offline* dry run that has no book to ask.
At placement the venue is under no obligation to trade at its mark: the
live capture's book for ETH-USDT quotes a best bid of 2665.89 and a best
ask of 2673.27 while the premiumIndex mark is 2685.87, several ticks
*above* the ask, so a PostOnly BUY priced at the mark crosses the book and
the venue refuses it (BingX 101215 — three of the four orders in the live
smoke test).  Just before placing, the mirror therefore reads the symbol's
book through :meth:`~router.bingx_client.BingXClient.depth` and prices each
passive leg at **its own side of that book** — a BUY at the best bid, a
SELL at the best ask, on the tick grid — by handing the book-side quote to
:func:`router.bingx_order.assemble_bingx_order` as the mark, the one door
that owns the gates and the grid rounding, with the leg's identity terms
unchanged (the repriced order keeps the plan's ``clientOrderID`` and the
store keeps its key, because feature 316 folds identity, never price).  The
repriced order is re-judged gate for gate — grids, notional floor, minimum
quantity — and a gate that closes it refuses the leg with that gate's own
code word; a side with no quote on it refuses the leg as
:data:`NO_BOOK_CODE`.  Aggressive (MARKET) legs carry no price and are sent
verbatim, and Stage 0's offline dry run keeps mark pricing, since it has no
book.  Repricing lives *inside the store's send*: a leg the store answers
``prior`` is never repriced — the venue already holds it at the price it
was placed at — and a repriced leg the gates refuse raises through the
send, so the store's claim rolls back and nothing is recorded for an order
that never left.

**The preflight judges the margin the plan's orders need, never the
book's whole equity.**  The second live VST run refused the rebalance
of a book that already held two of its five legs: the account answered
availableMargin 7503.07 — the margin those held positions use (2496.28)
already subtracted — and the preflight compared that against the book's
equity_usdt 10000, a comparison no holding book can pass without
funding beyond its own equity (and comparing the account's *equity*
would have refused too, an unrealised loss putting it below the book's).
The sufficiency term is therefore computed here, from the orders this
run is about to send: each contributes its *position-increasing*
quantity times a reference price at the preflight's own leverage of one
— a passive leg at its limit price, a MARKET leg at its symbol's mark —
with reducing legs free, crossing legs counted only beyond zero, and
the total carrying half a percent of headroom for taker fees and drift
(:func:`plan_required_margin`).  The book's ``equity_usdt`` keeps its
one job: sizing the orders through Stage 0's sizer, unchanged.

**The venue's ``clientOrderID`` is 40 characters; the store's key is 64.**
:class:`~router.bingx_order.BingXOrder` carries only the projection feature 3
applies at the boundary, and feature 317's placement store keys its
idempotency on the **full** 64-hex identifier the integration points name.
The projection is a prefix of the identifier and is not reversible, so the
mirror re-derives the identifier from the very terms the plan derived it
from — the book's ``book_id``, its ``rebalance_ts`` and the leg's symbol —
through :func:`router.client_order_id.derive_client_order_id`, rather than
reading it back off the order.  One derivation, two spellings of one name.

**Placement is one transaction per leg, and the store owns the duplicate
decision.**  ``RouterOrderPlacementStore.place`` either performs the
placement it is handed or answers a prior row — the check and the claim are
one statement on one connection — and the callable it performs is this
module's own, so a re-run of the same book rebalances under the same
feature 316 identifiers, finds the rows already held, sends nothing and
prints ``prior`` for every leg.  That is the feature's *"a re-run never
places an order twice"*, and it is structural rather than advisory: the
mirror cannot place a duplicate by forgetting to look first, because it does
not look first at all.

**The weight is acquired per request, and the 429 is absorbed.**  Every
placement attempt prices itself through :meth:`RouterRateLimiter.acquire`
under :data:`VST_MIRROR_WEIGHT_SCHEDULE` (weight one per request, ten per
second, conservative against BingX's published limits) *inside* the attempt
:func:`router.retry.retry_rate_limited` re-enters, so every re-send
re-acquires rather than re-sending on a weight it never spent.  The meter
runs *before* the placement store opens its transaction — the store's claim
and the limiter's bucket row are writes in the same store, and metering
inside that transaction would have the two contend for one write lock —
which is also the honest order: a request prices itself before it is made.
The limiter is a second meter beside the venue's own: a real HTTP 429 from
the venue is raised by feature 1 as
:class:`~router.errors.RouterRateLimitedError` and absorbed by the same
backoff, which reads the wait off the refusal's own headroom rather than
from a number this module invented.  An exhausted budget re-raises the
standing refusal, which the leg reports as ``refused``.

**The unknown outcome is resolved by asking, never by guessing.**  Feature
1's client raises :class:`~router.bingx_client.RouterBingXTransportError`
with ``outcome_unknown`` true for a write whose response never arrived.
A blind re-send of that order is exactly what BingX's
duplicate-``clientOrderID`` refusal exists to punish, so the mirror does
what the sentence says: it queries that ``clientOrderID`` first
(:func:`router.bingx_orders.read_back_orders`, feature 3's own read), records
a found order as placed, and re-posts only a ``not_found`` answer.  The
re-post is bounded — a venue that keeps dropping the connection cannot be
re-sent forever — and the *only* path that re-posts is the one a
``not_found`` answer opened.

**Nothing is placed without ``--place``, and ``--place`` refuses to start
without a store.**  ``DATABASE_URL`` is required because every placement is
recorded and idempotent: a placement this process cannot write down is a
placement a re-run would make a second time.  Without the flag the command
reads the venue's documents through the client it was handed, prints the
plan and exits 0.

**The credentials are never rendered.**  The key and the secret are read
from ``BINGX_VST_API_KEY``/``BINGX_VST_SECRET_KEY`` through feature 1's
client, which redacts both in its ``repr`` and names only the *variable* in
a refusal; nothing here prints, logs or stores either value, and the
placement store's row carries feature 316's identifier and the leg alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .bingx_client import BingXClient, RouterBingXTransportError
from .bingx_client_order_id import project_bingx_client_order_id
from .bingx_documents import (
    RouterMarkPriceError,
    RouterNotTradableError,
    resolve_bingx_filters,
    resolve_bingx_mark_prices,
)
from .bingx_dry_run import dry_run_plan
from .bingx_order import (
    BINGX_BUY,
    BINGX_LIMIT_ORDER,
    BINGX_MARKET_ORDER,
    BingXOrder,
    BingXRefusedLeg,
    assemble_bingx_order,
)
from .bingx_orders import (
    CLIENT_ORDER_ID_FIELD,
    SYMBOL_FIELD,
    VST_ORDER_NOT_FOUND,
    cancel_rebalance_orders,
    read_back_orders,
)
from .bingx_preflight import PREFLIGHT_LEVERAGE, run_bingx_preflight
from .client_order_id import derive_client_order_id
from .errors import RouterError
from .limiter import (
    OPERATION_ACCOUNT,
    OPERATION_CANCEL_ORDER,
    OPERATION_OPEN_ORDERS,
    OPERATION_PLACE_ORDER,
    OPERATION_QUERY_ORDER,
    RouterRateLimiter,
    VenueWeightSchedule,
)
from .retry import _sleep, retry_rate_limited
from .submission_result import PlacementOrder, RouterOrderPlacementStore

__all__ = [
    "DATABASE_URL_ENV",
    "DATABASE_URL_MISSING_CODE",
    "MIRROR_CODE",
    "MIRROR_OUTCOME_PLACED",
    "MIRROR_OUTCOME_PRIOR",
    "MIRROR_OUTCOME_REFUSED",
    "NO_BOOK_CODE",
    "PLACEMENT_FIELD",
    "RATE_LIMIT_RETRIES",
    "REPOST_LIMIT",
    "REQUIRED_MARGIN_HEADROOM",
    "VST_MIRROR_WEIGHT_SCHEDULE",
    "MirrorLeg",
    "RouterBingXMirrorError",
    "build_mirror_plan",
    "live_positions",
    "main",
    "mirror_place",
    "plan_required_margin",
    "rebalance_order_identities",
    "reprice_passive_order",
]

#: The greppable token this command's own faults open with — a book that
#: will not read, a positions payload the venue shaped wrong, a client or a
#: store this process cannot address.  Coined on the module's own name, the
#: convention :data:`router.bingx_dry_run.BINGX_DRY_RUN_CODE` states and
#: :data:`router.bingx_preflight.BINGX_PREFLIGHT_CODE` repeats: an operator
#: greps one word and lands on the module that refused.
MIRROR_CODE = "bingx_mirror"

#: The code word for ``--place`` without an addressable store.  The
#: constraint is the feature's own — *nothing is placed without ``--place``,
#: and ``--place`` refuses to start without ``DATABASE_URL``, so every
#: placement is recorded and idempotent* — and a mirror that placed without
#: recording would place the same order again on its next run.
DATABASE_URL_MISSING_CODE = "database_url_missing"

#: The workspace-wide environment variable naming the relational store.
#: Restated here rather than imported from a sibling store, the discipline
#: every store in this member keeps for its own address.
DATABASE_URL_ENV = "DATABASE_URL"

#: The code word for a passive leg whose symbol's book quotes nothing on
#: the leg's own side — no bids for a BUY, no asks for a SELL — so there is
#: no price on that side for a PostOnly order to rest against.  A leg-level
#: fact and a *value* (a refused leg in the placements report), never an
#: error: the venue's book for a freshly listed symbol can legitimately be
#: empty on one side, and the leg is skipped while its siblings place.
NO_BOOK_CODE = "no_book"

#: The three placement outcomes a leg can print, one word each: the order
#: did not exist in the store and the venue was asked; the store already
#: held it and the venue was not asked; the venue (or the transport, or the
#: weight budget) refused it.
MIRROR_OUTCOME_PLACED = "placed"
MIRROR_OUTCOME_PRIOR = "prior"
MIRROR_OUTCOME_REFUSED = "refused"

#: The key a placed leg's plan object carries its placement outcome under.
#: Every other key of that object is the request's own parameter spelling,
#: so the outcome rides beside the plan rather than replacing it.
PLACEMENT_FIELD = "placement"

#: The number of rate-limit re-sends one request may make.  §13.2 gives no
#: number and :func:`router.retry.retry_rate_limited` deliberately has no
#: default, so the mirror states its own: three re-sends, which with the
#: schedule's one-second window is well inside a minute of pacing.
RATE_LIMIT_RETRIES = 3

#: How many times a write whose outcome is unknown may be re-posted after a
#: ``not_found`` query.  One: the first transport failure is resolved by
#: asking, and a second failure after a *confirmed* absence is the one case
#: a re-post is entitled to.  Bounded, because a venue that keeps dropping
#: the connection must not be re-sent forever.
REPOST_LIMIT = 1

#: The headroom the plan's required margin carries over the bare notional
#: of its position-increasing parts: half a percent, for the taker fees a
#: crossing leg pays and the drift a resting price absorbs between the
#: plan and its fill.  A multiplier rather than a spread, stated as an
#: exact :class:`~decimal.Decimal` because the term it scales is one —
#: the same money law every amount in this member keeps.
REQUIRED_MARGIN_HEADROOM = Decimal("1.005")

#: The value the mirror's limiter is matched to: weight one per request
#: against an allowance of ten per second, the numbers feature 1's client
#: states for its own 429 reading and the integration points name
#: (*weight 1 per request and allowance 10 per second, conservative against
#: BingX's limits*).  Declared here, as a module constant, because the
#: mirror owns the shared bucket; the client holds none.
VST_MIRROR_WEIGHT_SCHEDULE = VenueWeightSchedule(
    allowance=10,
    window=timedelta(seconds=1),
    weights={
        OPERATION_ACCOUNT: 1,
        OPERATION_CANCEL_ORDER: 1,
        OPERATION_OPEN_ORDERS: 1,
        OPERATION_PLACE_ORDER: 1,
        OPERATION_QUERY_ORDER: 1,
    },
)


class RouterBingXMirrorError(RouterError):
    """The mirror cannot answer the ask it was given.

    Raised for a fault of *the ask* rather than a fact about an order: a
    book document that will not read or is not the Stage 0 shape, a
    positions payload the venue shaped in a way this module cannot read, a
    client or store that does not expose the verb the command needs, a
    ``--place`` with nowhere to record what it places.  A leg the venue, a
    gate or the weight budget refused is a *value* the plan and the
    placements carry, never this error.

    Every message opens with :data:`MIRROR_CODE` (or the one other code
    word this module coins, :data:`DATABASE_URL_MISSING_CODE`) and names the
    one repair, the discipline every class in this member's vocabulary
    keeps.
    """


@dataclass(frozen=True)
class MirrorLeg:
    """One placed leg's outcome: which leg, and what became of its order.

    ``symbol`` is BingX's own hyphenated spelling; ``outcome`` is one of
    :data:`MIRROR_OUTCOME_PLACED`, :data:`MIRROR_OUTCOME_PRIOR` or
    :data:`MIRROR_OUTCOME_REFUSED`; ``code`` is the refusing vocabulary's
    own code word — the venue's ``code`` field for a venue refusal — and is
    ``None`` for the two outcomes that are not refusals; ``message`` is the
    venue's own ``msg`` for a venue refusal, verbatim, and is ``None`` for
    a refusal that words nothing (a transport failure, an exhausted
    backoff) and for the two outcomes that are not refusals; ``order`` is
    the order the venue was actually asked to take — a passive leg as it
    was repriced at the book, an aggressive leg verbatim — and is ``None``
    whenever nothing was sent for this leg *this run* (a ``prior`` leg the
    store answered from its row, or a refusal), because in those cases the
    order that was placed, or never placed, is not this run's to report.
    Frozen and hashable, so a caller can key a report on it.
    """

    symbol: str
    outcome: str
    code: str | None = None
    message: str | None = None
    order: BingXOrder | None = None

    def __post_init__(self) -> None:
        if self.outcome not in (
            MIRROR_OUTCOME_PLACED,
            MIRROR_OUTCOME_PRIOR,
            MIRROR_OUTCOME_REFUSED,
        ):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: a leg's placement outcome is one of "
                f"{MIRROR_OUTCOME_PLACED!r}, {MIRROR_OUTCOME_PRIOR!r} or "
                f"{MIRROR_OUTCOME_REFUSED!r}, got {self.outcome!r}; the "
                "three words are the whole of what a run of the mirror "
                "reports about an order (feature 4)"
            )
        if self.outcome == MIRROR_OUTCOME_REFUSED:
            if not isinstance(self.code, str) or not self.code.strip():
                raise RouterBingXMirrorError(
                    f"{MIRROR_CODE}: a refused leg carries the refusing "
                    f"vocabulary's code word, got {self.code!r}; the code is "
                    "what an operator greps to learn why the order did not "
                    "land (feature 4)"
                )
            if self.message is not None and (
                not isinstance(self.message, str) or not self.message.strip()
            ):
                raise RouterBingXMirrorError(
                    f"{MIRROR_CODE}: a refused leg's message is the venue's "
                    f"own msg verbatim, got {self.message!r}; a message that "
                    "states nothing is not a reason — a refusal the venue "
                    "worded carries its msg, and one it did not carries no "
                    "message at all (feature 4)"
                )
        elif self.code is not None or self.message is not None:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: a {self.outcome!r} leg carries no refusal "
                f"code or message, got code {self.code!r} and message "
                f"{self.message!r}; an order that was placed (or already "
                "was) was refused by nothing (feature 4)"
            )
        if self.order is not None and not isinstance(self.order, BingXOrder):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: a leg's sent order is a "
                f"BingXOrder, got {type(self.order).__name__}; the leg "
                "reports the request the venue was asked to take, and "
                "nothing else spells those parameters (feature 4)"
            )


# -- Reading the ask -----------------------------------------------------------


def _read_document(path: Path) -> Any:
    """Read and decode the book document from ``path``, or refuse it.

    The one ``--`` path is the command's only filesystem interface: the two
    venue documents are *fetched*, so a path that will not read or a file
    that is not JSON is a fault of the ask, refused here with the path
    named rather than surfacing as a bare :class:`OSError` mid-plan.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document at {str(path)!r} cannot be "
            f"read: {exc}; the mirror reads the book it is handed and fetches "
            "everything else from the venue"
        ) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document at {str(path)!r} is not JSON: "
            f"{exc}; the plan reads one decoded Stage 0 book and a document "
            "that will not parse has no plan in it"
        ) from exc


#: The three values BingX's position document carries for ``positionSide``.
#: A one-way account labels its positions ``LONG`` and ``SHORT`` too — the
#: live smoke test caught that — and a hedge-mode ``BOTH`` row keeps the
#: amount's own sign.  Anything outside this vocabulary is a response fault
#: and is refused rather than assumed to be long.
_POSITION_SIDES = frozenset({"LONG", "SHORT", "BOTH"})


def _decimal_amount(value: Any, symbol: str) -> Decimal:
    """One position's size as an exact :class:`~decimal.Decimal`.

    The venue spells a position's size as a decimal string and both
    ``positionAmt`` and the older ``position`` field carry it; an exact
    :class:`int` names the same value.  A ``float`` is refused by name here
    as it is everywhere in this member — a binary approximation of a decimal
    no venue ever sent, and a position read approximately would size a delta
    nobody chose — and a boolean is refused as the gate-fact it is.
    """
    if isinstance(value, bool):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the venue reports the position in {symbol!r} as "
            f"{value!r} (bool); a true/false spelling is not a quantity the "
            "account holds (feature 4)"
        )
    if isinstance(value, str):
        if not value.strip():
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue reports the position in {symbol!r} "
                "as an empty string; a size that states nothing is not a "
                "position the account holds (feature 4)"
            )
        try:
            number = Decimal(value)
        except InvalidOperation as exc:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue reports the position in {symbol!r} "
                f"as {value!r}, which is not a decimal; a size the sizer "
                "cannot read is not a quantity the account holds (feature 4)"
            ) from exc
    elif isinstance(value, int):
        number = Decimal(value)
    else:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the venue reports the position in {symbol!r} as "
            f"{value!r} ({type(value).__name__}); a size must be a decimal "
            "string or a whole number, because a float is a binary "
            "approximation of a decimal no venue ever sent (feature 4)"
        )
    return number


def _signed_amount(entry: Mapping[str, Any], symbol: str) -> Decimal:
    """One position row's *signed* size, as BingX's own document spells it.

    The live smoke test's root cause: BingX reports the size **unsigned**,
    with the direction in ``positionSide``.  A one-way account labelled a
    short of 5402 ``{"positionSide": "SHORT", "positionAmt": "5402"}`` — a
    positive amount — and a reader that trusted the amount alone answered
    ``+5402``, so the next placement would size ``target - held`` as
    ``-5402 - (+5402)`` and double the short.  The direction is therefore
    read from the side and applied to the amount:

    * ``SHORT`` — the magnitude is negative, so the symbol's signed
      quantity is ``-|amount|``;
    * ``LONG`` — the signed quantity is ``+|amount|``;
    * ``BOTH`` — the amount is already signed and is kept verbatim (a
      hedge-mode row states its direction in the amount itself).

    A row whose ``positionSide`` and a *negative* ``positionAmt`` disagree —
    ``SHORT`` with a negative amount, or ``LONG`` with a negative amount —
    is refused naming the symbol rather than guessed, because the two facts
    the venue stated contradict each other and either reading would size a
    delta nobody chose.  A row carrying no ``positionSide`` is read by the
    amount's own sign, the older shape whose direction is in the amount.
    """
    if "positionAmt" in entry:
        raw = entry["positionAmt"]
    elif "position" in entry:
        raw = entry["position"]
    else:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the venue's position row for {symbol!r} "
            "carries no size — neither 'positionAmt' nor 'position' — so "
            "the account's holding in that leg cannot be read (feature 4)"
        )
    amount = _decimal_amount(raw, symbol)
    side = entry.get("positionSide")
    if side is None:
        return amount
    if not isinstance(side, str) or side.strip() not in _POSITION_SIDES:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the venue's position row for {symbol!r} states "
            f"positionSide {side!r}, which is not one of "
            f"{sorted(_POSITION_SIDES)}; the direction of the account's "
            "holding is read from that field, and a side this cannot judge "
            "would have the short read as a long (feature 4)"
        )
    side = side.strip()
    if amount < 0:
        # A negative amount is BingX's *signed* spelling, but a LONG or
        # SHORT label is the *unsigned* spelling (a SHORT is reported
        # positive, with the direction only in the label).  A negative
        # amount beside either label is therefore two contradictory facts,
        # and the direction cannot be read from them.
        if side in ("LONG", "SHORT"):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue's position row for {symbol!r} "
                f"states positionSide {side!r} with the negative amount "
                f"{amount!r}; a {side.lower()} spelled this way carries an "
                "unsigned amount, so the side and the amount disagree — a "
                "row whose direction cannot be read is refused rather than "
                "guessed (feature 4)"
            )
        return amount
    if side == "SHORT":
        return -amount
    return amount


def live_positions(client: Any) -> dict[str, Any]:
    """The account's live VST positions, as the book's own field spells them.

    Feature 4's second clause: *replaces the book's positions with the
    account's live VST positions*.  The venue's position document answers
    ``data`` as an array of position objects (both endpoint versions agree),
    each carrying its ``symbol`` and its size under ``positionAmt``
    (``position`` is accepted as the older spelling of the same fact), so
    the answer here is the book's own shape — a mapping of symbol to the
    **signed** quantity held, an exact :class:`~decimal.Decimal`.

    **The size is signed by the row's own direction.**  BingX reports the
    size unsigned, with the direction in ``positionSide`` — the live smoke
    test caught a short of 5402 spelled ``{"positionSide": "SHORT",
    "positionAmt": "5402"}`` — so a reader that trusted the amount alone
    read every short as a long and would double it on the next rebalance.
    :func:`_signed_amount` applies the side: ``SHORT`` negates the
    magnitude, ``LONG`` keeps it positive, ``BOTH`` keeps the amount's own
    sign, a row with no side is read by its amount's sign, and a row whose
    side and a negative amount disagree is refused naming the symbol.

    ``None`` counts as *no positions* — the flat account the end-to-end
    stand-in holds — rather than a malformed answer, the same reading
    :func:`router.bingx_preflight._venue_positions` gives the same field.  A
    row that names no symbol, or a payload that is not the venue's array, is
    refused: a silently dropped row would be a position the account holds
    and the plan does not know about, which is exactly the delta the mirror
    exists to compute.
    """
    method = getattr(client, "positions", None)
    if not callable(method):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the injected client exposes no callable "
            "positions(); the mirror reads the account's live positions "
            "through feature 1's client, and a client without this method "
            "cannot be asked (feature 4)"
        )
    payload = method()
    if payload is None:
        return {}
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the positions payload is the venue's array of "
            f"position objects, got {payload!r} ({type(payload).__name__}); "
            "the book's positions field is replaced by what the account "
            "holds, and a value that is not the array names nothing held "
            "(feature 4)"
        )
    held: dict[str, Any] = {}
    for entry in payload:
        if not isinstance(entry, Mapping):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: each entry in the positions payload is one "
                f"of the venue's position objects, got {entry!r} "
                f"({type(entry).__name__}) (feature 4)"
            )
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: a position row names the symbol it is for, "
                f"got {symbol!r} ({type(symbol).__name__}); a row naming no "
                "leg cannot replace a position in the book's own mapping "
                "(feature 4)"
            )
        held[symbol.strip()] = _signed_amount(entry, symbol.strip())
    return held


def _with_positions(
    book: Mapping[str, Any], positions: Mapping[str, Any]
) -> dict[str, Any]:
    """A shallow copy of ``book`` with only its ``positions`` field replaced.

    The book is never mutated: the document a caller handed in (a fixture, a
    published rebalance) is an input, and a plan that edited it in place
    would leave the caller holding a book that reports positions the account
    does not have.  Replacing exactly one field — rather than rebuilding the
    Stage 0 terms here — is what keeps every other term (the identity, the
    weights, the equity, the horizons, the margin arrangement) reaching the
    plan verbatim, through :func:`router.bingx_dry_run.dry_run_plan`'s own
    reading of them.
    """
    replaced = dict(book)
    replaced["positions"] = dict(positions)
    return replaced


def _document(fetched: Any, what: str) -> dict[str, Any]:
    """A fetched payload as the document Stage 0's readers read.

    Feature 1's client answers the venue envelope's ``data`` field — for the
    two quote endpoints, the list of contract rows or mark rows — while
    :func:`router.bingx_dry_run.dry_run_plan` reads the *documents* Stage 0
    is handed from disk, which carry that list under ``data``.  The gap is
    the envelope the client already unwrapped, so this rejoins it: a payload
    that is already a document (a mapping carrying ``data``) passes through
    untouched — the shape a double or a recorded read may answer — and a
    bare list is wrapped under ``data``, the key the readers look for.  The
    envelope's ``code`` is deliberately not restated: the readers judge no
    code (feature 1 owns the venue's answer), so inventing one would be a
    fact this module has no basis for.
    """
    if isinstance(fetched, Mapping) and "data" in fetched:
        return dict(fetched)
    return {"data": fetched}


def build_mirror_plan(
    *, book: Any, client: Any
) -> list[BingXOrder | BingXRefusedLeg]:
    """Feature 4's plan: the book, re-positioned from the venue, sized by Stage 0.

    The three steps of the feature's first sentence, in order: the two venue
    documents are fetched through feature 1's client (the contracts
    document, then the premiumIndex document — both public, both unsigned),
    the book's ``positions`` field is replaced with
    :func:`live_positions`' answer for the account, and the plan is built by
    :func:`router.bingx_dry_run.dry_run_plan` exactly as Stage 0 builds it.
    Nothing here re-implements a gate or a document reader.

    The plan is the plan Stage 0 would print — one leg per symbol the book
    holds, an order or a refused leg, in the book's sorted symbol order —
    over *this instant's* venue documents and *this account's* positions.
    """
    if not isinstance(book, Mapping):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document is a JSON object — got "
            f"{type(book).__name__}; the Stage 0 book states its identity, "
            "its equity, its weights, its decay horizons and its positions "
            "as one object (feature 4)"
        )
    for name in ("contracts", "premium_index"):
        if not callable(getattr(client, name, None)):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the injected client exposes no callable "
                f"{name}(); the mirror fetches the venue's own documents "
                "through feature 1's client, and a client without this "
                "method cannot be asked (feature 4)"
            )
    contracts = _document(client.contracts(), "BingX contracts")
    marks = _document(client.premium_index(), "BingX premiumIndex")
    positions = live_positions(client)
    return dry_run_plan(
        book=_with_positions(book, positions),
        contracts=contracts,
        marks=marks,
    )


# -- Identity ------------------------------------------------------------------


def _identity_terms(book: Mapping[str, Any]) -> tuple[str, datetime]:
    """The two book terms feature 316's key folds, read off the document.

    The mirror re-derives each leg's **full** 64-hex identifier here rather
    than reading it back off the order, because
    :class:`~router.bingx_order.BingXOrder` carries only the venue's
    40-character projection and the placement store keys its idempotency on
    the whole digest.  The book's identity and its rebalance instant are the
    terms, read exactly as :func:`router.bingx_dry_run.dry_run_plan` reads
    them; the instant must be timezone-aware, because a naive one folds an
    offset nobody agreed on into an order's name.
    """
    book_id = book.get("book_id")
    if not isinstance(book_id, str) or not book_id.strip():
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states book_id={book_id!r} "
            f"({type(book_id).__name__}); the book's identity is one of the "
            "three terms every order's own name is derived from, and a book "
            "that states none names no order (feature 316)"
        )
    raw = book.get("rebalance_ts")
    if not isinstance(raw, str):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states rebalance_ts={raw!r} "
            f"({type(raw).__name__}); the rebalance is an instant spelled as "
            "ISO 8601 text, and it is folded into every order's own name"
        )
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states rebalance_ts={raw!r}, "
            "which is not an ISO 8601 instant"
        ) from exc
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states rebalance_ts={raw!r}, "
            "which names no timezone; a naive instant folds into the orders' "
            "keys an offset nobody agreed on, and one rebalance would answer "
            "two names (feature 316)"
        )
    return book_id, moment


def _full_identifier(book: Mapping[str, Any], symbol: str) -> str:
    """The router's full 64-hex identifier for ``symbol``'s leg of ``book``."""
    book_id, moment = _identity_terms(book)
    return derive_client_order_id(
        book_id=book_id, rebalance_ts=moment, symbol=symbol
    ).client_order_id


def rebalance_order_identities(book: Mapping[str, Any]) -> list[dict[str, str]]:
    """This rebalance's orders by identity: one name per symbol the weights name.

    The order set ``--status`` and ``--cancel`` address — and the repair for
    the defect both shared: the CLI used to hand the two verbs the legs of
    :func:`build_mirror_plan`, a plan re-sized against the account's live
    positions, so it held only the legs *today* still wants.  A symbol
    whose position has already reached its target sizes to no leg at all,
    and a leg a gate refused is a refused leg the verbs skip, so a filled
    order vanished from ``--status`` and a resting order the plan dropped
    was never cancelled.  The rebalance's orders are not a property of
    today's sizing, though: a ``clientOrderID`` is a *function* of
    ``(book_id, rebalance_ts, symbol)`` (feature 316), so the set of orders
    this rebalance may own on the venue is exactly one name per symbol the
    book's weights name — derived here through the same derivation and the
    same 40-character projection (Stage 0 feature 3) placement named the
    orders with, never read off a plan that no longer holds them.

    The answer is the shape a written plan holds — ``{"symbol": ...,
    "clientOrderID": ...}`` in the venue's own field spellings — one entry
    per weight, in the book's own order, which is the order ``--status``
    prints.  Both verbs read it through their own order reader, so the
    read-back answers one status per book symbol (a symbol never placed or
    gate-refused answers ``not_found``) and the cancel owns every
    identifier the rebalance could ever have placed, while the orders of
    any other book or rebalance — different terms, different digest — stay
    untouched.  Pure computation: no client, no store, no clock, so neither
    command needs ``DATABASE_URL``, places anything, or even reads the
    venue's documents to learn what to ask about.
    """
    weights = book.get("weights")
    if not isinstance(weights, Mapping) or not weights:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states no weights mapping "
            f"(got {weights!r}); every order this rebalance owns is named "
            "for a symbol the weights name, and a book that names no "
            "symbols owns no orders to look up or cancel (feature 316)"
        )
    book_id, moment = _identity_terms(book)
    orders: list[dict[str, str]] = []
    for symbol in weights:
        if not isinstance(symbol, str) or not symbol.strip():
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the book's weights must be keyed by "
                f"non-empty symbol names — got {symbol!r}; an order's "
                "clientOrderID is derived from its symbol, and a weight "
                "keyed by no name names no order (feature 316)"
            )
        name = symbol.strip()
        orders.append(
            {
                SYMBOL_FIELD: name,
                CLIENT_ORDER_ID_FIELD: project_bingx_client_order_id(
                    derive_client_order_id(
                        book_id=book_id, rebalance_ts=moment, symbol=name
                    )
                ),
            }
        )
    return orders


# -- The balance door's term: the plan's required margin ------------------------


def _increasing_size(order: BingXOrder, held: Decimal) -> Decimal:
    """The part of ``order`` that grows the symbol's position, if any.

    The sufficiency question the corrected preflight asks is *can the
    account fund the orders about to be sent*, and an order that shrinks
    a holding funds itself: the margin it releases is at least the margin
    the smaller position needs.  Three shapes, then — an order from flat
    or growing the side already held is new margin in full; an order
    against the held side but no larger than it releases more than it
    binds and needs none; and an order that crosses through zero needs
    margin only for the part beyond it, the part that lands as a new
    position on the other side.  ``held`` is the symbol's signed quantity
    exactly as :func:`live_positions` read it, and the answer is the
    unsigned quantity that counts, never a signed delta — margin binds
    magnitude, not direction.
    """
    size = Decimal(order.quantity)
    if held == 0 or (held > 0) == (order.side == BINGX_BUY):
        # Flat, or growing the side already held: the whole order is
        # new margin.
        return size
    beyond = size - abs(held)
    # Reducing orders need no new margin; a crossing one needs only the
    # quantity beyond zero.
    return beyond if beyond > 0 else Decimal(0)


def plan_required_margin(
    *, client: Any, orders: Sequence[BingXOrder]
) -> Decimal:
    """The margin the plan's orders need, as one exact decimal.

    The term the preflight's ``insufficient_balance`` check judges
    against, computed here — the mirror's own verb — because the
    question is about the orders this run is about to send, and only the
    mirror knows them beside the account that will fund them:

    * each order contributes its position-increasing quantity (see
      :func:`_increasing_size`) times a reference price, divided by the
      leverage the preflight itself sets (:data:`PREFLIGHT_LEVERAGE`,
      one — the mirror's sizing assumes the account funds the notional
      itself);
    * the reference price is the order's own limit price for a passive
      leg and the symbol's mark price for a MARKET leg, which carries no
      price of its own — read from the venue's premiumIndex document,
      the same read the plan was sized through;
    * the total carries :data:`REQUIRED_MARGIN_HEADROOM`, the half
      percent for taker fees and price drift.

    The account's positions are re-read through :func:`live_positions`
    and the premiumIndex document only when a MARKET leg needs it, so an
    all-passive plan costs the one positions read and an empty plan
    costs nothing at all — an empty or all-reducing plan answers zero,
    which passes the balance door on any account, the boundary the bug
    spec names.  Every term is an exact
    :class:`~decimal.Decimal` built from the venue's own strings and the
    order's own spelling; no float enters the arithmetic.
    """
    if not orders:
        # An empty plan places nothing and needs nothing: zero, which
        # the door judges as funded on any account.
        return Decimal(0)
    held = live_positions(client)
    market_symbols = sorted(
        {
            order.symbol
            for order in orders
            if order.type == BINGX_MARKET_ORDER
        }
    )
    marks: dict[str, Decimal] = {}
    if market_symbols:
        if not callable(getattr(client, "premium_index", None)):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the injected client exposes no callable "
                "premium_index(); a MARKET leg carries no price of its "
                "own, so the margin it needs is read at its symbol's mark "
                "price, and a client that cannot ask for the document "
                "cannot be asked to fund one (feature 2)"
            )
        try:
            marks = resolve_bingx_mark_prices(
                _document(client.premium_index(), "BingX premiumIndex"),
                market_symbols,
            )
        except RouterMarkPriceError as refusal:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue's premiumIndex document states "
                f"no mark price for {refusal.symbol!r}; a MARKET leg's "
                "required margin is read at its symbol's mark price, and a "
                "leg the plan ordered cannot be priced for funding by a "
                "document that does not price it (feature 2)"
            ) from refusal
    total = Decimal(0)
    for order in orders:
        reference = (
            Decimal(order.price)
            if order.type == BINGX_LIMIT_ORDER
            else marks[order.symbol]
        )
        total += (
            _increasing_size(order, held.get(order.symbol, Decimal(0)))
            * reference
            / PREFLIGHT_LEVERAGE
        )
    return total * REQUIRED_MARGIN_HEADROOM


# -- Passive repricing ---------------------------------------------------------


class _RepriceRefusal(Exception):
    """A repriced leg the gates closed, carrying the refusing code word.

    Deliberately *not* a :class:`~router.errors.RouterError`: this is
    plumbing between the store's send callable and :func:`_place_one`, not
    part of the module's vocabulary, and it must travel a path
    :class:`~router.errors.RouterRateLimitedError` cannot — through
    :func:`router.retry.retry_rate_limited`, which re-raises every other
    exception untouched — because a repricing refusal is final (there is
    nothing to wait out and no re-send that would answer it) and the store's
    claim must roll back so nothing is recorded for an order that never
    left.  Folded into the leg's ``refused`` report here, never printed or
    raised past :func:`_place_one`.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _book_quote(depth: Any, side: str, symbol: str) -> Decimal | None:
    """The book's own quote on ``side`` of ``symbol``'s depth answer.

    ``depth`` is what :meth:`~router.bingx_client.BingXClient.depth` answers
    — the venue envelope's ``data``, a mapping of ``bids`` and ``asks``
    arrays of ``[price, quantity]`` decimal-string pairs.  A BUY rests on
    the bid side and a SELL on the ask side, so the quote is the *best*
    price on that side: the greatest bid, the least ask — read as a
    maximum/minimum over the stated levels rather than as "the first row",
    because nothing obliges the venue to order its rows.  A side that is
    absent or holds no level answers ``None``: that is
    :data:`NO_BOOK_CODE`, a fact about the book the leg carries as a value.
    A side this module cannot *read* — a payload that is not the document
    shape, a level that is not a pair, a price that is not a decimal — is a
    fault of the ask and refuses here, the same reading
    :func:`live_positions` gives a positions payload it cannot parse; a
    ``float`` price is refused by name as everywhere in this member, a
    binary approximation of a decimal no venue ever sent.
    """
    if not isinstance(depth, Mapping):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the depth answer for {symbol!r} is the "
            f"venue's book, an object of 'bids' and 'asks' arrays, got "
            f"{type(depth).__name__}; a book that is not the document shape "
            "cannot be priced against (feature 4)"
        )
    field = "bids" if side == BINGX_BUY else "asks"
    levels = depth.get(field)
    if levels is None or (isinstance(levels, (list, tuple)) and not levels):
        return None
    if not isinstance(levels, (list, tuple)):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the depth answer for {symbol!r} carries "
            f"{field!r} as {type(levels).__name__}, not an array of "
            "[price, quantity] pairs; a side this module cannot read is not "
            "a side of the book (feature 4)"
        )
    prices: list[Decimal] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or not level:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the depth answer for {symbol!r} carries a "
                f"{field!r} level of {level!r}, which is not a "
                "[price, quantity] pair; a level without a price states no "
                "quote the order could rest against (feature 4)"
            )
        price = level[0]
        if isinstance(price, bool) or not isinstance(price, (str, int)):
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the depth answer for {symbol!r} carries a "
                f"{field!r} price of {price!r} ({type(price).__name__}); a "
                "price must be a decimal string or a whole number, because "
                "a float is a binary approximation of a decimal no venue "
                "ever sent (feature 4)"
            )
        try:
            number = Decimal(price)
        except InvalidOperation as exc:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the depth answer for {symbol!r} carries a "
                f"{field!r} price of {price!r}, which is not a decimal; a "
                "price the tick grid cannot read is not a quote the order "
                "could rest on (feature 4)"
            ) from exc
        if not number.is_finite():
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the depth answer for {symbol!r} carries a "
                f"{field!r} price of {price!r}, which is not a finite "
                "decimal; a price that is not a number cannot be rounded "
                "onto the tick grid (feature 4)"
            )
        prices.append(number)
    return max(prices) if side == BINGX_BUY else min(prices)


def _duration_terms(book: Mapping[str, Any], symbol: str) -> tuple[timedelta, timedelta]:
    """The book's two posture durations for ``symbol``, re-read as the plan read them.

    The posture gate (feature 314) compares the symbol's decay horizon with
    the book's expected fill time, and both terms reach the plan from the
    book document; the repricing re-assembles the leg through the same
    gate, so it re-reads the same two durations from the same document
    rather than inventing a default a posture could hide behind.  The plan
    was built from this book, so the terms are present and readable; the
    refusals here exist so a fault stays legible instead of surfacing as a
    bare :class:`KeyError` or :class:`TypeError` mid-placement.
    """
    horizons = book.get("decay_horizon_seconds")
    if not isinstance(horizons, Mapping) or symbol not in horizons:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states no decay horizon for "
            f"{symbol!r}; the posture gate reads the symbol's horizon and "
            "the repriced leg must be judged through it (feature 314)"
        )
    fill = book.get("expected_fill_seconds")
    if isinstance(fill, bool) or not isinstance(fill, (int, float)):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states no expected fill time "
            f"as a number of seconds, got {fill!r} ({type(fill).__name__}); "
            "the posture gate compares the symbol's horizon against it and "
            "the repriced leg must be judged through it (feature 314)"
        )
    horizon = horizons[symbol]
    if isinstance(horizon, bool) or not isinstance(horizon, (int, float)):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states the decay horizon for "
            f"{symbol!r} as {horizon!r} ({type(horizon).__name__}), not a "
            "number of seconds; the posture gate compares it against the "
            "book's fill time and the repriced leg must be judged through "
            "it (feature 314)"
        )
    return timedelta(seconds=horizon), timedelta(seconds=fill)


def reprice_passive_order(
    *,
    order: BingXOrder,
    depth: Any,
    filters: Any,
    book: Mapping[str, Any],
) -> BingXOrder | BingXRefusedLeg:
    """Price one passive leg at its own side of the book, not at the mark.

    The defect's repair, stated as a verb: the plan's ``order`` was priced
    by Stage 0's offline rule — the mark rounded onto the tick grid — which
    crosses the book whenever the mark sits on the far side of it (the live
    capture: ETH-USDT's mark 2685.87 above its best ask 2673.27), and a
    PostOnly order that crosses is refused by the venue (BingX 101215).
    The answer is the same order priced at :func:`_book_quote`'s best quote
    on the leg's own side — a BUY at the best bid, a SELL at the best ask —
    and the pricing itself is not re-implemented here: the quote is handed
    to :func:`router.bingx_order.assemble_bingx_order` as the mark, the one
    door that owns the tick-grid rounding (away from crossing, so a
    book-side quote stays non-crossing by construction) and every gate, so
    the repriced leg is re-judged gate for gate — posture, the step and
    tick grids, the notional floor, the minimum quantity, isolated margin —
    against the *repriced* price, and a gate that closes it answers the
    refused leg with that gate's own code word, never an exception.

    The identity is the plan's own: ``assemble_bingx_order`` derives the
    ``clientOrderID`` from the book's ``book_id``, ``rebalance_ts`` and the
    symbol — terms that exclude price — so the repriced order keeps the
    plan's identifier, the store keeps its key, and a re-run of the same
    book still finds the row.  ``delta`` is re-signed off the leg's own
    side and quantity, the same sign the sizer chose; ``book`` supplies the
    posture durations and the margin arrangement verbatim.
    """
    quote = _book_quote(depth, order.side, order.symbol)
    if quote is None:
        return BingXRefusedLeg(symbol=order.symbol, code=NO_BOOK_CODE)
    book_id, moment = _identity_terms(book)
    size = Decimal(order.quantity)
    delta = size if order.side == BINGX_BUY else -size
    horizon, fill = _duration_terms(book, order.symbol)
    answer = assemble_bingx_order(
        symbol=order.symbol,
        delta=delta,
        mark=quote,
        filters=filters,
        signal_decay_horizon=horizon,
        expected_fill_time=fill,
        client_order_id=derive_client_order_id(
            book_id=book_id, rebalance_ts=moment, symbol=order.symbol
        ),
        book_id=book_id,
        account=book.get("account"),
        mode=book.get("margin_mode"),
    )
    if isinstance(answer, BingXOrder) and answer.type != BINGX_LIMIT_ORDER:
        # The leg being repriced is passive, so the posture gate reading
        # these same durations answered LIMIT when the plan was built; a
        # different answer now means the book changed under the plan, and
        # that disagreement is a fault of the ask, not a leg the mirror
        # can place.
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: repricing the passive {order.type} leg for "
            f"{order.symbol!r} answered a {answer.type} order; the book's "
            "durations judge the posture, and a posture that changes "
            "between the plan and its placement is a book the plan no "
            "longer describes (feature 314)"
        )
    return answer


def _passive_repricer(
    *, client: Any, book: Mapping[str, Any], orders: Sequence[BingXOrder]
) -> Callable[[BingXOrder], BingXOrder] | None:
    """The per-leg repricing closure for a placement run, or ``None``.

    ``None`` — no repricing at all, every leg sent verbatim — when the run
    holds no passive leg: an all-market plan has no price to reprice and
    its client need not expose a ``depth`` face at all.  Otherwise the
    client must expose one, and the filters the repriced legs are re-judged
    against are fetched and translated **once per run** (a public read,
    side-effect-free) here rather than per leg, so five legs cost one
    contracts document — and here rather than inside the send so a wiring
    fault refuses before the preflight performs its first venue POST.

    The closure reprices exactly the passive legs; a MARKET leg passes
    through verbatim (it carries no price to reprice), and the depth of
    *only* the leg being sent is read — inside the send — so no leg reads a
    book it may never be placed against.  A leg the gates closed answers a
    :class:`_RepriceRefusal` carrying the gate's code word, which escapes
    the backoff and rolls the store's claim back.
    """
    if not any(order.type == BINGX_LIMIT_ORDER for order in orders):
        return None
    depth = getattr(client, "depth", None)
    if not callable(depth):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the injected client exposes no callable "
            "depth(); a passive leg is priced at its own side of the "
            "symbol's order book just before placing, because the mark "
            "can sit on the far side of the book and a PostOnly order "
            "priced at it crosses (feature 1)"
        )
    contracts = resolve_bingx_filters(
        _document(client.contracts(), "BingX contracts")
    )

    def reprice(order: BingXOrder) -> BingXOrder:
        if order.type != BINGX_LIMIT_ORDER:
            return order
        try:
            filters = contracts[order.symbol]
        except KeyError as exc:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue's contracts document states no "
                f"filters for {order.symbol!r}; a leg the plan ordered "
                "cannot be re-judged against filters the venue does not "
                "publish for it (feature 4)"
            ) from exc
        except RouterNotTradableError as refusal:
            # Impossible for a leg the plan ordered — the plan's own
            # translation refused those — but if the venue's document
            # changed under the run, the leg is refused, not placed blind.
            raise _RepriceRefusal(str(refusal.code)) from refusal
        answer = reprice_passive_order(
            order=order, depth=depth(order.symbol), filters=filters, book=book
        )
        if isinstance(answer, BingXRefusedLeg):
            raise _RepriceRefusal(answer.code)
        return answer

    return reprice


# -- Placement -----------------------------------------------------------------


def _require_store_place(store: Any) -> Any:
    """``store.place``, refused by name when the store cannot be asked."""
    place = getattr(store, "place", None)
    if not callable(place):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the placement store exposes no callable "
            "place(); every placement is recorded and idempotent through "
            "feature 317's store, and a store that cannot be asked is one "
            "that could place the same order twice (feature 4)"
        )
    return place


def _query_found(*, client: Any, order: BingXOrder) -> bool:
    """Whether the venue holds ``order`` — asked before anything else.

    The resolution of feature 4's third clause: a write whose response never
    arrived may or may not have landed, and the venue's only honest answer
    is its own record of that ``clientOrderID``.  Answered through feature
    3's own read-back, so the ``not_found`` translation (feature 1's
    ``ORDER_NOT_FOUND_CODE`` judged against every other refusal) is made in
    the one module that owns it; anything the read-back cannot judge
    propagates as itself.
    """
    status = read_back_orders(client=client, orders=[order])[0]
    return status.status != VST_ORDER_NOT_FOUND


def _post_order(*, client: Any, order: BingXOrder, reposts: int) -> None:
    """POST one order, resolving an unknown outcome by asking first.

    Feature 4's third clause, as one function.  The order is posted; a
    transport failure whose ``outcome_unknown`` is true means the venue may
    already hold it, so the mirror *queries that ``clientOrderID`` before
    doing anything else*: a found order returns (the store records it as
    placed, and the venue is never asked to book it twice), and only a
    ``not_found`` answer re-posts.  The re-posts are bounded by ``reposts``,
    so a venue that keeps dropping the connection is refused rather than
    re-sent forever.  A transport failure on a *read* — whose outcome is
    known and safe — and every other failure propagate untouched, exactly
    as feature 1 raised them.

    Returning is the venue's acceptance, which is what the store's callable
    contract requires.
    """
    remaining = reposts
    while True:
        try:
            client.place_order(order)
            return
        except RouterBingXTransportError as failure:
            if not failure.outcome_unknown:
                raise
            if _query_found(client=client, order=order):
                # The order landed: recorded as placed, never re-posted.
                return
            if remaining <= 0:
                raise
            remaining -= 1


def _refusal_code(refusal: BaseException) -> str:
    """The greppable code for a refusal that stopped a placement.

    The venue's own ``code`` for a ``bingx_refused`` answer — what the
    feature's *"refused with its code"* names — and, for a refusal carrying
    none (an exhausted backoff's standing rate-limit reading, a transport
    this module could not resolve even by asking), the class name of the
    refusal, so one column always carries a token an operator can grep.
    """
    code = getattr(refusal, "code", None)
    if code is not None:
        return str(code)
    return type(refusal).__name__


def _refusal_message(refusal: BaseException) -> str | None:
    """The venue's own ``msg`` for a refusal that stopped a placement.

    Read off :attr:`RouterBingXRefusedError.msg` — the venue's envelope
    text carried verbatim, and the **only** ``msg`` any vocabulary in this
    member holds — so the message a refused leg prints is the venue's own
    words and never a request URL, query string, signature or credential.
    A refusal that carries none (an exhausted backoff's standing
    rate-limit reading, a transport this module could not resolve even by
    asking) answers ``None``: the code column is that refusal's token, and
    a message invented here would be a fact no venue stated.  A blank msg
    counts as no message, the same reading the code column gives a blank
    code.
    """
    msg = getattr(refusal, "msg", None)
    if isinstance(msg, str) and msg.strip():
        return msg
    return None


def _order_recorder(
    *,
    store: Any,
    book: Mapping[str, Any],
    client: Any,
    orders: Sequence[BingXOrder],
) -> Callable[[BingXOrder], None] | None:
    """The callable that records each placed leg's terms, or ``None``.

    Returns ``None`` — recording nothing — unless the store carries the
    terms write (``record_order``).  That absence is deliberate and not a
    fault: the placement store's *contract* is
    :meth:`~router.submission_result.RouterOrderPlacementStore.place`, and a
    deployment (or a Stage 1 test double) that supplies only that contract
    must keep placing orders exactly as it did before this recording
    existed.  The real store carries both, so a deployment records; a double
    without the terms write is an explicit opt-out.

    For a MARKET leg the recorder reads its symbol's mark **once**, from the
    same premiumIndex document the plan already fetched through, and hands
    that mark to every aggressive leg — because the fill-cost reconciliation
    measures a MARKET fill against the mark read *in the run that placed it*,
    never against a mark re-read later.  The document is fetched only when
    the plan actually holds a MARKET leg, so an all-passive rebalance costs
    no extra read.
    """
    record_order = getattr(store, "record_order", None)
    if not callable(record_order):
        return None
    book_id, moment = _identity_terms(book)

    marks: dict[str, Decimal] = {}
    market_symbols = sorted(
        {
            order.symbol
            for order in orders
            if order.type == BINGX_MARKET_ORDER
        }
    )
    if market_symbols:
        try:
            marks = resolve_bingx_mark_prices(
                _document(client.premium_index(), "BingX premiumIndex"),
                market_symbols,
            )
        except RouterMarkPriceError as refusal:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: the venue's premiumIndex document states no "
                f"mark price for {refusal.symbol!r}; a MARKET leg's recorded "
                "reference price is its symbol's mark read in the same run, "
                "and a document that does not price the leg cannot record the "
                "reference its fill is measured against (feature 3)"
            ) from refusal

    def recorder(order: BingXOrder) -> None:
        reference = (
            Decimal(order.price)
            if order.type == BINGX_LIMIT_ORDER
            else marks[order.symbol]
        )
        record_order(
            client_order_id=_full_identifier(book, order.symbol),
            book_id=book_id,
            rebalance_ts=moment,
            symbol=order.symbol,
            side=order.side,
            order_type=order.type,
            quantity=order.quantity,
            reference_price=reference,
        )

    return recorder


def _place_one(
    *,
    client: Any,
    order: BingXOrder,
    store: Any,
    limiter: Any,
    book: Mapping[str, Any],
    repricer: Callable[[BingXOrder], BingXOrder] | None = None,
    retries: int = RATE_LIMIT_RETRIES,
    reposts: int = REPOST_LIMIT,
    sleep: Callable[[timedelta], Any] = _sleep,
    jitter_rng: Any = None,
    on_retry: Any = None,
    on_placed: Callable[[BingXOrder], None] | None = None,
) -> MirrorLeg:
    """Place one order through the store, the limiter and the backoff.

    The whole of feature 4's second clause for one leg.  Each attempt first
    prices itself through the limiter and then hands the store a callable
    that sends the order; ``store.place`` decides whether this is a fresh
    placement or a prior result and owns the one transaction per leg, and
    the whole attempt is wrapped by
    :func:`router.retry.retry_rate_limited`, so a weight-budget refusal —
    this process's bucket, or the venue's own HTTP 429 raised inside the
    send — is absorbed by the backoff and the attempt is re-entered rather
    than re-sent unmetered.

    **The weight is acquired before the store's transaction opens.**  That
    ordering is load-bearing, not incidental: ``store.place`` claims the
    key and holds one write transaction across the venue call, and the
    limiter's own bucket row is a write in the *same* store, so acquiring
    inside that transaction would have the meter contend with the claim for
    one write lock — a deadlock on a single sqlite file.  Metering first
    also states the honest order: a request prices itself before it is
    made.

    **A passive leg is repriced inside the send, never before it.**  The
    store invokes its callable only for a fresh placement — a leg it
    answers ``prior`` was never this run's to price — so the repricing (and
    the depth read it stands on) lives in ``_send`` itself, where it runs
    exactly when the order is about to leave, and the order actually sent
    is carried out in ``sent`` for the leg's report.  A repricing refusal
    (a gate closing the repriced leg, a side with no quote on it) raises
    :class:`_RepriceRefusal` out of the send: not a
    :class:`~router.errors.RouterError`, so the backoff does not retry it —
    there is nothing to wait out — and it is answered here, under the
    store's rollback, as a ``refused`` leg carrying the refusing code word.

    A refusal that survives the backoff propagates out of the attempt, so
    the store's transaction rolls back and nothing is recorded — the order
    path keeps the retry it is entitled to make — and is answered here as a
    ``refused`` leg carrying its code and, when the venue worded it, its
    message.
    """
    sent: list[BingXOrder] = []

    def _send() -> None:
        to_send = order
        if repricer is not None:
            to_send = repricer(order)
        sent.append(to_send)
        _post_order(client=client, order=to_send, reposts=reposts)

    def _attempt() -> Any:
        # The weight is acquired *before* the store opens its transaction:
        # a placement is one transaction spanning the venue call, and the
        # limiter's own write (its bucket row) must not contend with the
        # store's claim for the same store's write lock.  Acquiring here
        # puts the meter a hair ahead of the claim, which is also the
        # honest order — a request prices itself before it is made, and a
        # re-send (this attempt, re-entered by the backoff below) prices
        # itself again rather than re-sending on a weight already spent.
        limiter.acquire(OPERATION_PLACE_ORDER)
        return store.place(
            PlacementOrder(
                client_order_id=_full_identifier(book, order.symbol),
                symbol=order.symbol,
            ),
            _send,
        )

    retry_kwargs: dict[str, Any] = {
        "retries": retries,
        "on_retry": on_retry,
        "sleep": sleep,
    }
    # Only name the jitter seam when the caller named one: the retry's
    # own default is the system's random source, and passing `None`
    # through would be an ask this module never meant to make.
    if jitter_rng is not None:
        retry_kwargs["jitter_rng"] = jitter_rng

    try:
        # The backoff wraps the whole placement, so a weight-budget refusal
        # — this process's bucket, or the venue's own HTTP 429 raised inside
        # the send — is absorbed and the *placement* is re-entered: the
        # store's claim rolls back on the raise (nothing is recorded for an
        # order the venue did not take), and the next attempt re-acquires
        # the weight and re-claims before re-sending.  A repricing refusal
        # is the one exception: not a RouterRateLimitedError, so the backoff
        # re-raises it untouched and the leg is answered below.
        result = retry_rate_limited(_attempt, **retry_kwargs)
    except _RepriceRefusal as refusal:
        return MirrorLeg(
            symbol=order.symbol,
            outcome=MIRROR_OUTCOME_REFUSED,
            code=refusal.code,
        )
    except RouterError as refusal:
        return MirrorLeg(
            symbol=order.symbol,
            outcome=MIRROR_OUTCOME_REFUSED,
            code=_refusal_code(refusal),
            message=_refusal_message(refusal),
        )
    if not result.appended:
        # The store answered this leg from a row a prior run wrote; the
        # venue already holds the order at the price it was placed at, so
        # nothing was sent this run and the plan's own leg is the report.
        return MirrorLeg(symbol=order.symbol, outcome=MIRROR_OUTCOME_PRIOR)
    placed_order = sent[-1] if sent else None
    if placed_order is not None and on_placed is not None:
        # The placement's terms are recorded here, from the order the venue
        # was *actually* asked to take — a passive leg as it was repriced at
        # the book, an aggressive leg verbatim — and only for a leg this run
        # placed.  A `prior` leg returned above never reaches this, so the
        # row that records where an order was placed at is the first
        # placement's and no replay can move it.
        on_placed(placed_order)
    return MirrorLeg(
        symbol=order.symbol,
        outcome=MIRROR_OUTCOME_PLACED,
        order=placed_order,
    )


def mirror_place(
    *,
    client: Any,
    book: Mapping[str, Any],
    plan: Sequence[BingXOrder | BingXRefusedLeg],
    store: Any,
    limiter: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    clock: Callable[[], int] | None = None,
    retries: int = RATE_LIMIT_RETRIES,
    reposts: int = REPOST_LIMIT,
    sleep: Callable[[timedelta], Any] = _sleep,
    jitter_rng: Any = None,
    on_retry: Any = None,
) -> dict[str, MirrorLeg]:
    """Feature 4's placement half: preflight, then place every order once.

    Runs :func:`router.bingx_preflight.run_bingx_preflight` over the
    symbols the plan will order and the margin those orders need (see
    :func:`plan_required_margin`) — so a killed order layer, a skewed
    clock, a hedge-mode account or an unfunded one refuses here, before
    a single order leaves — and then places each order leg in the plan's
    own order through the store, the limiter and the backoff (see
    :func:`_place_one`), repricing every passive leg at its own side of
    the live book just before it leaves (see :func:`_passive_repricer`).
    The repricer and the margin are built *before* the preflight runs:
    their client face checks and their public reads are
    side-effect-free, so a wiring fault refuses before the preflight's
    first venue POST rather than after it.

    Returns one :class:`MirrorLeg` per *order* leg, keyed by symbol.  A leg
    the plan itself refused (a gate's code word, a document's) is not an
    order and is not placed, so it is not in the answer: the caller prints
    it from the plan, exactly as Stage 0 does.  The preflight's own
    refusals propagate untouched, and any fault of the ask is a
    :class:`RouterBingXMirrorError`.
    """
    _require_store_place(store)
    if not callable(getattr(limiter, "acquire", None)):
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the limiter exposes no callable acquire(); every "
            "request the mirror sends prices itself against the venue's "
            "weight budget (feature 318), and a limiter that cannot be asked "
            "would spend the budget unmetered (feature 4)"
        )
    orders = [leg for leg in plan if isinstance(leg, BingXOrder)]
    repricer = _passive_repricer(client=client, book=book, orders=orders)
    recorder = _order_recorder(store=store, book=book, client=client, orders=orders)
    preflight_kwargs: dict[str, Any] = {
        "required_usdt": plan_required_margin(client=client, orders=orders),
        "symbols": [order.symbol for order in orders],
        "database_url": database_url,
        "env": env,
    }
    if clock is not None:
        preflight_kwargs["clock"] = clock
    run_bingx_preflight(client, **preflight_kwargs)

    outcomes: dict[str, MirrorLeg] = {}
    for order in orders:
        outcomes[order.symbol] = _place_one(
            client=client,
            order=order,
            store=store,
            limiter=limiter,
            book=book,
            repricer=repricer,
            retries=retries,
            reposts=reposts,
            sleep=sleep,
            jitter_rng=jitter_rng,
            on_retry=on_retry,
            on_placed=recorder,
        )
    return outcomes


# -- The command ---------------------------------------------------------------


def _print_leg(leg: BingXOrder | BingXRefusedLeg) -> None:
    """One plan line, in Stage 0's own JSON-lines format."""
    if isinstance(leg, BingXRefusedLeg):
        print(json.dumps({"symbol": leg.symbol, "refusal": leg.code}))
    else:
        print(json.dumps(leg.parameters()))


def _print_placed(leg: BingXOrder, outcome: MirrorLeg) -> None:
    """One placed line: the sent order's parameters beside the placement word.

    The parameters printed are the order the venue was asked to take —
    ``outcome.order``, a passive leg repriced at the book — falling back to
    the plan's own leg when this run sent nothing (a ``prior`` leg the
    store answered from its row) or when no repricer ran.  A refused leg
    adds its code and, when the venue worded the refusal, its own ``msg``
    verbatim under ``"message"`` — the one fact that says why an
    undocumented code refused the order.
    """
    line: dict[str, Any] = dict(
        (outcome.order if outcome.order is not None else leg).parameters()
    )
    line[PLACEMENT_FIELD] = outcome.outcome
    if outcome.code is not None:
        line["code"] = outcome.code
    if outcome.message is not None:
        line["message"] = outcome.message
    print(json.dumps(line))


def _resolve_database_url(
    database_url: str | None, env: Mapping[str, str] | None
) -> str | None:
    """The store's address from the argument, else ``DATABASE_URL``.

    ``None`` when neither names one; the caller turns that into
    :data:`DATABASE_URL_MISSING_CODE` for ``--place`` and tolerates it
    otherwise, because a plan printed without placing needs no store.
    """
    if database_url is not None:
        return database_url.strip() or None
    source = os.environ if env is None else env
    raw = source.get(DATABASE_URL_ENV, "")
    return raw.strip() or None


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    transport: Any = None,
    store: Any = None,
    limiter: Any = None,
    env: Mapping[str, str] | None = None,
    database_url: str | None = None,
    clock: Callable[[], int] | None = None,
    sleep: Callable[[timedelta], Any] = _sleep,
    jitter_rng: Any = None,
    on_retry: Any = None,
) -> int:
    """The command: read the book, fetch the venue's documents, act on the plan.

    ``python -m router.bingx_mirror --book BOOK [--place | --status |
    --cancel]``.  Without ``--place`` (and without ``--status`` or
    ``--cancel``) it prints the plan in Stage 0's JSON-lines format and
    exits 0 while placing nothing.  ``--place`` requires ``DATABASE_URL``,
    preflights, places each order once and prints one line per leg; it exits
    0 when every order was placed or already was, and 1 otherwise.
    ``--status`` prints feature 3's read-back and ``--cancel`` cancels this
    rebalance's open orders — both over the rebalance's orders **by
    identity** (see :func:`rebalance_order_identities`), one name per
    symbol the book's weights name, so a filled order or a resting one the
    plan no longer wants is still looked up and still cancelled.

    The ``client``, ``transport``, ``store``, ``limiter``, ``env`` and the
    two retry seams are injectable so the suite can drive the command
    against a loopback stand-in and a recording double **without any
    environment variable that could change the host** — the client still
    names :data:`~router.bingx_client.VST_HOST` on every request and its
    guard has already run by the time an injected transport sees the URL.
    A caller that injects nothing gets feature 1's real client built from
    the environment.
    """
    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_mirror",
        description=(
            "Mirror a Stage 0 book onto the BingX VST venue: read the "
            "account's live positions, build the plan over the venue's own "
            "contracts and premiumIndex, and (with --place) place each order "
            "once, idempotently."
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
    parser.add_argument(
        "--place",
        action="store_true",
        help="place the plan's orders (requires DATABASE_URL); without it "
        "the command prints the plan and places nothing",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print each of the book's VST orders as the venue reports it",
    )
    parser.add_argument(
        "--cancel",
        action="store_true",
        help="cancel this rebalance's open orders and print the identifiers",
    )
    arguments = parser.parse_args(argv)

    try:
        book = _read_document(arguments.book)
        if client is None:
            client = BingXClient.from_env(env=env, transport=transport)

        if arguments.status:
            # Addressed by identity, never by today's plan: the plan is
            # re-sized against the account's live positions, so a symbol
            # already at its target has no leg in it while its placed order
            # still sits on the venue's book — and a leg the gates refused
            # never named one at all.
            orders = rebalance_order_identities(book)
            for status in read_back_orders(client=client, orders=orders):
                print(json.dumps(status.as_dict()))
            return 0

        if arguments.cancel:
            orders = rebalance_order_identities(book)
            for identifier in cancel_rebalance_orders(client=client, orders=orders):
                print(json.dumps({"clientOrderID": identifier}))
            return 0

        if not arguments.place:
            for leg in build_mirror_plan(book=book, client=client):
                _print_leg(leg)
            return 0

        url = _resolve_database_url(database_url, env)
        if url is None:
            raise RouterBingXMirrorError(
                f"{DATABASE_URL_MISSING_CODE}: --place records every "
                "placement and answers a re-run from the row it wrote, so it "
                f"cannot start without {DATABASE_URL_ENV}; set "
                f"{DATABASE_URL_ENV} to the sqlite database the router's "
                "placed orders are recorded in, or run without --place to "
                "print the plan and place nothing (feature 4)"
            )
        plan = build_mirror_plan(book=book, client=client)
        if store is None:
            store = RouterOrderPlacementStore(url)
        if limiter is None:
            limiter = RouterRateLimiter(url, schedule=VST_MIRROR_WEIGHT_SCHEDULE)

        outcomes = mirror_place(
            client=client,
            book=book,
            plan=plan,
            store=store,
            limiter=limiter,
            database_url=url,
            env=env,
            clock=clock,
            sleep=sleep,
            jitter_rng=jitter_rng,
            on_retry=on_retry,
        )
        every_landed = True
        for leg in plan:
            if isinstance(leg, BingXRefusedLeg):
                _print_leg(leg)
                continue
            outcome = outcomes[leg.symbol]
            _print_placed(leg, outcome)
            if outcome.outcome == MIRROR_OUTCOME_REFUSED:
                every_landed = False
        return 0 if every_landed else 1
    except RouterError as exc:
        message = str(exc)
        prefix = f"{MIRROR_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
