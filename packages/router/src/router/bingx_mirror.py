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
  its code.  It exits 0 when every order was placed or was already placed,
  and 1 otherwise.
* When a POST /trade/order times out or its connection drops, the outcome
  is unknown.  The mirror then queries that ``clientOrderID`` before doing
  anything else.  A found order is recorded as placed, and only a
  ``not_found`` answer is re-posted, so a blind retry never meets BingX's
  duplicate-``clientOrderID`` refusal for an order that actually landed.
* ``--status`` prints feature 3's read-back, and ``--cancel`` cancels the
  rebalance's open orders.

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
from pathlib import Path
from typing import Any

from .bingx_client import BingXClient, RouterBingXTransportError
from .bingx_dry_run import dry_run_plan
from .bingx_order import BingXOrder, BingXRefusedLeg
from .bingx_orders import (
    VST_ORDER_NOT_FOUND,
    cancel_rebalance_orders,
    read_back_orders,
)
from .bingx_preflight import run_bingx_preflight
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
    "PLACEMENT_FIELD",
    "RATE_LIMIT_RETRIES",
    "REPOST_LIMIT",
    "VST_MIRROR_WEIGHT_SCHEDULE",
    "MirrorLeg",
    "RouterBingXMirrorError",
    "build_mirror_plan",
    "live_positions",
    "main",
    "mirror_place",
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
    ``None`` for the two outcomes that are not refusals.  Frozen and
    hashable, so a caller can key a report on it.
    """

    symbol: str
    outcome: str
    code: str | None = None

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
        elif self.code is not None:
            raise RouterBingXMirrorError(
                f"{MIRROR_CODE}: a {self.outcome!r} leg carries no refusal "
                f"code, got {self.code!r}; an order that was placed (or "
                "already was) was refused by nothing (feature 4)"
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


def _amount(value: Any, symbol: str) -> Any:
    """One position's size, as the sizer's own decimal law will read it.

    The venue spells a position's size as a decimal string and both
    ``positionAmt`` and the older ``position`` field carry it; an exact
    :class:`int` names the same value.  A ``float`` is refused by name here
    as it is everywhere in this member — a binary approximation of a decimal
    no venue ever sent, and a position read approximately would size a delta
    nobody chose — and a boolean is refused as the gate-fact it is.  The
    value is handed downstream verbatim, because the vocabulary for a
    malformed position is :func:`router.sizing.size_contract_deltas`' own.
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
        return value
    if isinstance(value, int):
        return value
    raise RouterBingXMirrorError(
        f"{MIRROR_CODE}: the venue reports the position in {symbol!r} as "
        f"{value!r} ({type(value).__name__}); a size must be a decimal string "
        "or a whole number, because a float is a binary approximation of a "
        "decimal no venue ever sent (feature 4)"
    )


def live_positions(client: Any) -> dict[str, Any]:
    """The account's live VST positions, as the book's own field spells them.

    Feature 4's second clause: *replaces the book's positions with the
    account's live VST positions*.  The venue's position document answers
    ``data`` as an array of position objects (both endpoint versions agree),
    each carrying its ``symbol`` and its signed size under ``positionAmt``
    (``position`` is accepted as the older spelling of the same fact), so
    the answer here is the book's own shape — a mapping of symbol to the
    signed quantity held.

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
        held[symbol.strip()] = _amount(raw, symbol.strip())
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


def _place_one(
    *,
    client: Any,
    order: BingXOrder,
    store: Any,
    limiter: Any,
    book: Mapping[str, Any],
    retries: int,
    reposts: int,
    sleep: Callable[[timedelta], Any],
    jitter_rng: Any,
    on_retry: Any,
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

    A refusal that survives the backoff propagates out of the attempt, so
    the store's transaction rolls back and nothing is recorded — the order
    path keeps the retry it is entitled to make — and is answered here as a
    ``refused`` leg carrying its code.
    """
    def _send() -> None:
        _post_order(client=client, order=order, reposts=reposts)

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
        # the weight and re-claims before re-sending.
        result = retry_rate_limited(_attempt, **retry_kwargs)
    except RouterError as refusal:
        return MirrorLeg(
            symbol=order.symbol,
            outcome=MIRROR_OUTCOME_REFUSED,
            code=_refusal_code(refusal),
        )
    outcome = MIRROR_OUTCOME_PLACED if result.appended else MIRROR_OUTCOME_PRIOR
    return MirrorLeg(symbol=order.symbol, outcome=outcome)


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

    Runs :func:`router.bingx_preflight.run_bingx_preflight` over the symbols
    the plan will order — so a killed order layer, a skewed clock, a
    hedge-mode account or an unfunded one refuses here, before a single
    order leaves — and then places each order leg in the plan's own order
    through the store, the limiter and the backoff (see :func:`_place_one`).

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
    if "equity_usdt" not in book:
        raise RouterBingXMirrorError(
            f"{MIRROR_CODE}: the book document states no equity_usdt; the "
            "preflight compares the account's available balance against the "
            "book's own equity before anything is placed (feature 2)"
        )
    preflight_kwargs: dict[str, Any] = {
        "equity_usdt": book["equity_usdt"],
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
            retries=retries,
            reposts=reposts,
            sleep=sleep,
            jitter_rng=jitter_rng,
            on_retry=on_retry,
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
    """One placed line: the plan's own parameters beside the placement word."""
    line: dict[str, Any] = dict(leg.parameters())
    line[PLACEMENT_FIELD] = outcome.outcome
    if outcome.code is not None:
        line["code"] = outcome.code
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
    rebalance's open orders.

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
            plan = build_mirror_plan(book=book, client=client)
            for status in read_back_orders(client=client, orders=plan):
                print(json.dumps(status.as_dict()))
            return 0

        if arguments.cancel:
            plan = build_mirror_plan(book=book, client=client)
            for identifier in cancel_rebalance_orders(client=client, orders=plan):
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
