"""Stage 2's flatten: cancel every order, close every position, prove it.

``additions_spec_bingx_vst_stage2.xml``, "BingX VST Stage 2", feature 1:
*System flattens the VST sub-account from* ``python -m router.bingx_flatten
--confirm``: *it cancels every open order on the account, then closes every
position with one reduce-only MARKET order per symbol (side opposite to
positionSide, quantity the unsigned positionAmt, positionSide BOTH,
reduceOnly true).  It prints one JSON line per cancelled order and per
close, and returns exit 0 only when a final read shows no open orders and
no positions.  Without* ``--confirm`` *it prints what it would do and
changes nothing.  A close the venue refuses is printed with its code and
message, and the run exits 1.*

**Two doors, and only two, can close a position.**  The category's own
constraint is a sentence: *"Flatten acts only through --confirm or through
the daily-loss guard.  Nothing else can close positions."*  So the module
is built as one verb that acts — :func:`flatten_account`, the door feature
2's daily-loss guard calls when it trips — and a command that reaches it
only through ``--confirm``: :func:`main` without the flag reads the
account, prints the same lines a confirmed run would print, and sends
nothing.  There is no third spelling: no flag, no setting and no
environment variable in this module closes a position, because the only
function that places a close is the one the guard and the flag share.

**Every open order on the account — the whole account, not a rebalance's.**
Stage 1's cancel (:func:`router.bingx_orders.cancel_rebalance_orders`)
cancels exactly the orders whose ``clientOrderID`` belongs to one book's
one rebalance, because a mirror owns its own orders and nobody else's.  A
flatten is the opposite ask: the account is being emptied, so *ownership
is no filter at all* — every row of the venue's open-orders listing is
cancelled, including an order this system never placed (a probe left by an
operator, another book's resting order).  The listing is read in the shape
the live recording pins — rows under ``data.orders``, the identifier
spelled ``clientOrderId``, the placement spelling ``clientOrderID``
accepted as the alternative (:data:`router.bingx_orders.IDENTIFIER_FIELDS`)
— and a row that names no identifier under either spelling is refused
rather than skipped: every row is a target here, so a row this module
cannot address is a row it cannot flatten, and skipping it silently would
print a successful-looking run over an order the account still holds.

**Cancels first, then closes — the sentence's own order, and the safe
one.**  A resting order is a promise the account may still keep: a limit
buy left on the book can fill a moment after a close runs and re-open the
position the close just emptied.  Cancelling every open order *first*
retires those promises before any position is closed, so each close is the
final word on its symbol — and the final read below, not this module's own
bookkeeping, is what certifies that the word held.

**The close is read off the account's own position document.**  The
positions are read through Stage 1's :func:`router.bingx_mirror.
live_positions` — the reader the mirror already trusts to spell the
account's holdings as a signed quantity per symbol — and each non-zero
holding becomes exactly one close: the side is *opposite to* the row's
``positionSide`` (a short — a negative signed amount — is closed by a
``BUY``, a long by a ``SELL``), the quantity is the unsigned
``positionAmt`` in plain positional notation (a ``"5402"`` stays
``"5402"``, a ``"0.0236"`` keeps its scale, and no value is re-serialised
through a float or spelled in exponent form a venue never sent),
``positionSide`` is the one-way :data:`~router.bingx_order.
BINGX_POSITION_SIDE_BOTH`, the type is ``MARKET`` — the flatten crosses,
because its purpose is to be *finished*, not to make a price — and
``reduceOnly`` is true, so a close can never open what it means to close.
A holding of zero closes nothing: there is no position to close, and an
order for zero units is not one any venue books.

**``reduceOnly`` is spelled the way the venue spells its booleans.**  The
close's parameters are signed by feature 1's client with
:func:`urllib.parse.urlencode`, and ``urlencode`` renders a Python
``True`` as ``"True"`` — a capitalised spelling the venue's own documents
never carry (the recorded position-mode answer spells the fact
``"dualSidePosition": "false"``, lowercase, as its strings do).  The
parameter is therefore sent as the exact string ``"true"``: the JSON
spelling the venue's own documentation uses and the spelling the feature's
sentence itself writes.

**The close carries no ``clientOrderID``, on purpose.**  The sentence
lists the close's parameters exactly — the symbol, the side, the quantity,
``positionSide``, ``reduceOnly`` — and the identity feature 316 folds
belongs to *book* orders: it is a function of ``(book_id, rebalance_ts,
symbol)``, and a flatten holds no book and names no rebalance.  Inventing
a second naming scheme here (a flatten-flavoured digest, a prefix) would
be exactly the second spelling of one order's name that feature 316 exists
to prevent, so the close is sent with the parameters the sentence names
and the venue assigns its own order id.

**One JSON line per cancelled order and per close, refusals included.**
A cancelled order prints ``{"clientOrderID": ...}`` — the same line the
mirror's ``--cancel`` prints, so an operator's tooling reads one shape —
and a close prints its own parameters as sent.  A cancel or a close the
venue refused prints that same line *with* the refusing ``code`` and the
venue's own ``message`` beside it, the mirror's placed-line convention:
one leg's refusal never unwinds its siblings, so a flatten keeps closing
what it can and states, per line, what the venue declined.  Any other
:class:`~router.errors.RouterError` on one target — a transport that
dropped mid-write, an exhausted backoff — is folded into that target's
refused line the same way (the code column carries the refusal's own
token), while a fault in the *reads* propagates: a listing or a positions
payload this module cannot read is a fault of the ask, and a run that
guessed past it would flatten an account it never saw.

**Exit 0 is the final read's to give, not the walk's to claim.**  After
the last close, the command re-reads the open-orders listing and the
positions, and exits 0 only when the first shows no rows and the second
no non-zero holding — and only when no target was refused, per the
sentence's own clause that a refused close exits 1 even if the account
somehow ended flat around it.  What remains is named on stderr, because a
run that exits 1 owes the operator the *which*.

**No store, no clock, no I/O, no network of this module's own.**  The
client is injected — feature 1's :class:`~router.bingx_client.BingXClient`
in a deployment, a recording double in the suite — so nothing here opens a
socket, reads a credential, consults an environment variable or writes a
row.  Cancelling and closing are the only writes the verb makes, and both
are the venue's to execute; the command records nothing because the
account's own next read is the record.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .bingx_client import BingXClient
from .bingx_client_order_id import BINGX_CLIENT_ORDER_ID_LENGTH
from .bingx_mirror import live_positions
from .bingx_order import (
    BINGX_BUY,
    BINGX_MARKET_ORDER,
    BINGX_POSITION_SIDE_BOTH,
    BINGX_SELL,
    BINGX_SIDES,
)
from .bingx_orders import IDENTIFIER_FIELDS, OPEN_ORDERS_FIELD, SYMBOL_FIELD
from .errors import RouterError

__all__ = [
    "BINGX_FLATTEN_CODE",
    "BINGX_REDUCE_ONLY_TRUE",
    "FLATTEN_OUTCOME_CANCELLED",
    "FLATTEN_OUTCOME_CLOSED",
    "FLATTEN_OUTCOME_REFUSED",
    "REDUCE_ONLY_FIELD",
    "FlattenCancel",
    "FlattenCancelOutcome",
    "FlattenClose",
    "FlattenCloseOutcome",
    "FlattenPlan",
    "FlattenReport",
    "RouterBingXFlattenError",
    "flatten_account",
    "open_order_cancel_targets",
    "plan_flatten",
    "position_close_orders",
]

#: The greppable token this module's refusals open with, coined on the
#: module's own name the way :mod:`router.bingx_orders` coins
#: ``bingx_orders`` and :mod:`router.bingx_mirror` coins ``bingx_mirror``,
#: so an operator greps one word and lands on the flatten that refused.
#: A refusal here is a fault of the *ask* or of a response this module
#: cannot read — the venue's own refusals keep feature 1's class, are
#: folded into the refused target's line, and never propagate out of the
#: walk.
BINGX_FLATTEN_CODE = "bingx_flatten"

#: The venue's own spelling of the close order's one flag, as a field name.
#: Declared once at the venue boundary, never spelled at a call site.
REDUCE_ONLY_FIELD = "reduceOnly"

#: ``reduceOnly``'s value on a close, spelled exactly as the venue spells
#: its booleans: lowercase text.  :func:`urllib.parse.urlencode` renders a
#: Python ``True`` as ``"True"``, a capitalised spelling the venue's own
#: documents never carry (the recorded position-mode answer spells the
#: fact ``"dualSidePosition": "false"``), so the parameter carries the
#: string the venue's documentation and this feature's sentence both
#: write.  A close is *only ever* reduce-only — a close that could open a
#: position is not a close — so the one spelling is a constant of this
#: order shape rather than a decision made per close.
BINGX_REDUCE_ONLY_TRUE = "true"

#: The outcome words a run reports, one vocabulary for the two acts, the
#: same shape the mirror's ``placed``/``prior``/``refused`` takes: a
#: cancelled order, a closed position, and the one refusal word both acts
#: share.  A refused target is a fact the run states on its own line —
#: with the refusing code and the venue's own message — never an exception
#: that unwinds the targets behind it.
FLATTEN_OUTCOME_CANCELLED = "cancelled"
FLATTEN_OUTCOME_CLOSED = "closed"
FLATTEN_OUTCOME_REFUSED = "refused"


class RouterBingXFlattenError(RouterError):
    """The flatten cannot be read or answered at all.

    Raised for a fault of the *ask* or of a response this module cannot
    read, never for a fact the venue stated: an open-orders listing that
    is not an array of order objects, a listing row that names no
    identifier under either spelling the venue uses (every row is a
    target here, so a row that cannot be addressed cannot be skipped), a
    client that does not expose the method a verb needs, or a
    :class:`FlattenClose` built by hand with a side, a type, a quantity
    or a ``reduceOnly`` spelling no close carries.  The venue's own
    refusal of a cancel or a close is *not* one of these — it is folded
    into that target's refused line and the walk continues.

    Every message opens with :data:`BINGX_FLATTEN_CODE` and names the one
    repair, the discipline every class in this member's vocabulary keeps.
    """


@dataclass(frozen=True)
class FlattenCancel:
    """One open order the flatten will cancel: its identifier and symbol.

    * ``client_order_id`` — the row's identifier under whichever spelling
      the venue's listing used (:data:`router.bingx_orders.
      IDENTIFIER_FIELDS` — the listing's own ``clientOrderId`` first, the
      placement spelling ``clientOrderID`` accepted as the alternative),
      at most :data:`~router.bingx_client_order_id.
      BINGX_CLIENT_ORDER_ID_LENGTH` characters, because that is the field
      the venue's own cancel is addressed by.
    * ``symbol`` — the row's own symbol when it names one, and ``None``
      when it does not; the cancel is addressed by identifier either way,
      and a symbol the row never carried is not one to invent.

    Frozen and hashable, so a report can hold its targets in any
    structure the caller wants.  There is deliberately no ownership test:
    a flatten cancels *every* open order on the account, which is the one
    difference between this target and the rebalance-scoped set Stage 1's
    :func:`router.bingx_orders.cancel_rebalance_orders` cancels.
    """

    client_order_id: str
    symbol: str | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.client_order_id, str)
            or not self.client_order_id.strip()
            or len(self.client_order_id.strip())
            > BINGX_CLIENT_ORDER_ID_LENGTH
        ):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: an open-order target carries the "
                "clientOrderID the venue's cancel is addressed by — at "
                f"most {BINGX_CLIENT_ORDER_ID_LENGTH} characters — got "
                f"{self.client_order_id!r}; the listing's row names no "
                "order, and an order that cannot be named cannot be "
                "cancelled"
            )
        if self.symbol is not None and (
            not isinstance(self.symbol, str) or not self.symbol.strip()
        ):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: an open-order target carries its "
                "symbol as non-empty text or not at all, got "
                f"{self.symbol!r} ({type(self.symbol).__name__}); a blank "
                "name is not a leg the venue recognises"
            )
        object.__setattr__(
            self, "client_order_id", self.client_order_id.strip()
        )
        if self.symbol is not None:
            object.__setattr__(self, "symbol", self.symbol.strip())


@dataclass(frozen=True)
class FlattenClose:
    """One position's close order: the parameters the venue would receive.

    The value :func:`position_close_orders` answers for each non-zero
    holding, in the venue's own field spellings and the exact decimal
    spelling the position document carried:

    * ``symbol`` — the leg, BingX's own hyphenated spelling end to end.
    * ``side`` — :data:`~router.bingx_order.BINGX_BUY` or
      :data:`~router.bingx_order.BINGX_SELL`: opposite to the position's
      own ``positionSide``, because a close trades *against* the holding
      (a short is closed by a buy, a long by a sell).
    * ``quantity`` — the unsigned ``positionAmt``, the exact magnitude
      the position document spelled, in plain positional notation.
    * ``position_side`` — :data:`~router.bingx_order.
      BINGX_POSITION_SIDE_BOTH`: the account is one-way (verified live,
      ``dualSidePosition`` false), so the close states the one-way mode
      the feature's sentence names.
    * ``type`` — :data:`~router.bingx_order.BINGX_MARKET_ORDER`: a
      flatten crosses, because its purpose is to be finished.
    * ``reduce_only`` — :data:`BINGX_REDUCE_ONLY_TRUE`, the venue's own
      lowercase spelling, and no other value: a close that could open a
      position is not a close.

    All fields are canonicalised at construction, so a value built by
    hand in a test and one the verb answered get the same judgment.
    Frozen and hashable.
    """

    symbol: str
    side: str
    quantity: str
    position_side: str = BINGX_POSITION_SIDE_BOTH
    type: str = BINGX_MARKET_ORDER
    reduce_only: str = BINGX_REDUCE_ONLY_TRUE

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close names the symbol it is "
                f"closing as non-empty text, got {self.symbol!r} "
                f"({type(self.symbol).__name__}); a close that names no "
                "leg closes no position"
            )
        symbol = self.symbol.strip()
        if self.side not in BINGX_SIDES:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's side is one of "
                f"{sorted(BINGX_SIDES)} — opposite to the position's own "
                f"positionSide — got {self.side!r} "
                f"({type(self.side).__name__}); a side outside the "
                "vocabulary is a direction that does not close the "
                "holding"
            )
        if self.type != BINGX_MARKET_ORDER:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close is a "
                f"{BINGX_MARKET_ORDER} order — a flatten crosses, because "
                f"its purpose is to be finished — got {self.type!r}; a "
                "resting close would leave the account holding the "
                "position it was asked to empty"
            )
        if self.position_side != BINGX_POSITION_SIDE_BOTH:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's positionSide is "
                f"{BINGX_POSITION_SIDE_BOTH!r} in the one-way position "
                f"mode the account holds (verified live), got "
                f"{self.position_side!r}; the feature's sentence names "
                "the one-way spelling and the account is not in hedge "
                "mode"
            )
        if self.reduce_only != BINGX_REDUCE_ONLY_TRUE:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close is reduce-only — "
                f"{REDUCE_ONLY_FIELD} {BINGX_REDUCE_ONLY_TRUE!r}, the "
                f"venue's own spelling — got {self.reduce_only!r}; a "
                "close that could open a position is not a close"
            )
        if not isinstance(self.quantity, str):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's quantity is the exact "
                "decimal spelling the position document carried, got "
                f"{self.quantity!r} ({type(self.quantity).__name__}); a "
                "number re-serialised at the send would be a second "
                "spelling of a magnitude the venue already chose"
            )
        try:
            amount = Decimal(self.quantity)
        except InvalidOperation as exc:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's quantity {self.quantity!r} "
                f"for {symbol!r} is not a decimal a close can carry"
            ) from exc
        if not amount.is_finite() or amount <= 0:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's quantity for {symbol!r} "
                f"must be a positive finite decimal, got "
                f"{self.quantity!r}; a position with nothing held closes "
                "nothing, and a size at or below zero is not one any "
                "venue books"
            )
        object.__setattr__(self, "symbol", symbol)

    def parameters(self) -> dict[str, str]:
        """The close's parameters, in the venue's own field spellings.

        One line of a confirmed run's output is ``json.dumps`` of this
        answer.  The keys are the endpoint's own — ``symbol``, ``side``,
        ``positionSide``, ``type``, ``quantity``, ``reduceOnly`` — every
        value a string, and no ``clientOrderID``: the identity feature 316
        folds belongs to book orders (a function of the book, the
        rebalance and the symbol), a flatten holds no book, and the
        venue assigns its own order id.
        """
        return {
            SYMBOL_FIELD: self.symbol,
            "side": self.side,
            "positionSide": self.position_side,
            "type": self.type,
            "quantity": self.quantity,
            REDUCE_ONLY_FIELD: self.reduce_only,
        }


@dataclass(frozen=True)
class FlattenCancelOutcome:
    """What became of one cancel: the target, the word, the refusal.

    ``outcome`` is :data:`FLATTEN_OUTCOME_CANCELLED` or
    :data:`FLATTEN_OUTCOME_REFUSED`; a refused cancel carries the
    refusing vocabulary's ``code`` (the venue's own ``code`` for a venue
    refusal, the refusal's class name otherwise — the mirror's one
    discipline, so the column always carries a token an operator can
    grep) and, when the venue worded it, its ``message`` verbatim.  A
    cancelled order carries neither, because there is nothing to explain.
    """

    target: FlattenCancel
    outcome: str
    code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in (
            FLATTEN_OUTCOME_CANCELLED,
            FLATTEN_OUTCOME_REFUSED,
        ):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a cancel's outcome is one of "
                f"{FLATTEN_OUTCOME_CANCELLED!r} or "
                f"{FLATTEN_OUTCOME_REFUSED!r}, got {self.outcome!r}; the "
                "two words are the whole of what a run reports about a "
                "cancelled order (feature 1)"
            )
        _require_outcome_terms(
            self.outcome,
            FLATTEN_OUTCOME_REFUSED,
            self.code,
            self.message,
            what="a cancel",
        )


@dataclass(frozen=True)
class FlattenCloseOutcome:
    """What became of one close: the order, the word, the refusal.

    ``outcome`` is :data:`FLATTEN_OUTCOME_CLOSED` or
    :data:`FLATTEN_OUTCOME_REFUSED`; a refused close carries the refusing
    vocabulary's ``code`` and, when the venue worded it, its ``message``
    verbatim — the sentence's own clause: *"A close the venue refuses is
    printed with its code and message."*  A closed position carries
    neither.
    """

    close: FlattenClose
    outcome: str
    code: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.outcome not in (
            FLATTEN_OUTCOME_CLOSED,
            FLATTEN_OUTCOME_REFUSED,
        ):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a close's outcome is one of "
                f"{FLATTEN_OUTCOME_CLOSED!r} or "
                f"{FLATTEN_OUTCOME_REFUSED!r}, got {self.outcome!r}; the "
                "two words are the whole of what a run reports about a "
                "closed position (feature 1)"
            )
        _require_outcome_terms(
            self.outcome,
            FLATTEN_OUTCOME_REFUSED,
            self.code,
            self.message,
            what="a close",
        )


@dataclass(frozen=True)
class FlattenPlan:
    """What a flatten would do: every cancel, then every close.

    The value :func:`plan_flatten` answers and an unconfirmed run prints —
    the same lines a confirmed run prints, from the same reads, with
    nothing sent.  ``cancels`` is in the venue's listing order and
    ``closes`` in the venue's positions order, because that is the order
    a confirmed run performs them in.
    """

    cancels: tuple[FlattenCancel, ...]
    closes: tuple[FlattenClose, ...]


@dataclass(frozen=True)
class FlattenReport:
    """What a confirmed flatten did, and what the final read still shows.

    * ``cancel_outcomes`` / ``close_outcomes`` — one per target, in the
      order the walk performed them.
    * ``remaining_open_orders`` / ``remaining_positions`` — what the
      final read answered, as targets and closes again (the same readers,
      the same shapes): the honest statement of what is still on the
      account, judged by the venue's own documents and never by this
      module's bookkeeping.

    :attr:`flat` is the final read's verdict; :attr:`refused` is whether
    any target was refused; and :attr:`succeeded` — what the command's
    exit 0 stands on — is both, because the sentence gives exit 0 only to
    a run whose final read shows no open orders and no positions *and*
    hands a refused close exit 1 even if the account ended flat around
    it.
    """

    cancel_outcomes: tuple[FlattenCancelOutcome, ...]
    close_outcomes: tuple[FlattenCloseOutcome, ...]
    remaining_open_orders: tuple[FlattenCancel, ...]
    remaining_positions: tuple[FlattenClose, ...]

    @property
    def cancelled_ids(self) -> tuple[str, ...]:
        """The identifiers the venue took the cancel for, in walk order."""
        return tuple(
            outcome.target.client_order_id
            for outcome in self.cancel_outcomes
            if outcome.outcome == FLATTEN_OUTCOME_CANCELLED
        )

    @property
    def refused(self) -> bool:
        """Whether any cancel or close was refused."""
        return any(
            outcome.outcome == FLATTEN_OUTCOME_REFUSED
            for outcome in (*self.cancel_outcomes, *self.close_outcomes)
        )

    @property
    def flat(self) -> bool:
        """The final read's verdict: no open orders and no positions."""
        return not self.remaining_open_orders and not self.remaining_positions

    @property
    def succeeded(self) -> bool:
        """Exit 0's own condition: flat, with nothing refused."""
        return self.flat and not self.refused


# -- Readers -------------------------------------------------------------------


def _require_method(client: Any, name: str) -> Any:
    """Return ``client``'s callable ``name``, or refuse a client that lacks it.

    The same judgment :mod:`router.bingx_orders` makes for its verbs: a
    client that does not expose the method the flatten needs is a wiring
    fault worth naming rather than a bare :class:`AttributeError` from the
    middle of a walk that cancels orders.
    """
    method = getattr(client, name, None)
    if not callable(method):
        raise RouterBingXFlattenError(
            f"{BINGX_FLATTEN_CODE}: the injected client exposes no callable "
            f"{name}(); the flatten speaks to the venue only through "
            "feature 1's client, and a client without this method cannot "
            "be asked (feature 1)"
        )
    return method


def _row_identifier(entry: Mapping) -> str | None:
    """A listing row's identifier, under either spelling the venue uses.

    The venue's open-orders listing spells a row's identifier
    ``clientOrderId`` — the spelling ``live/open_orders_one_resting.json``
    records, one letter off the placement parameter — with the plan's own
    ``clientOrderID`` the alternative, exactly
    :data:`router.bingx_orders.IDENTIFIER_FIELDS`.  ``None`` means the row
    named no order under either spelling, and the caller refuses it: every
    row of the listing is a target of this act, so a row that cannot be
    addressed is a row this module cannot flatten — never one to skip.
    """
    for field in IDENTIFIER_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def open_order_cancel_targets(*, client: Any) -> list[FlattenCancel]:
    """The account's open orders, one cancel target per row of the listing.

    Reads the venue's open-orders listing through feature 1's
    ``open_orders()`` — the account-wide read, no symbol — and answers one
    :class:`FlattenCancel` per row, in the venue's own order, whatever
    order it is: this book's, another book's, an operator's probe.  The
    listing is read in the shape the live recording pins (rows under
    ``data.orders``, or a bare array), each row must be an object, and a
    row naming no identifier under either spelling is refused — the one
    difference from Stage 1's rebalance-scoped cancel, which skips such a
    row as foreign because it cannot belong to the rebalance; here every
    row is the ask, so a row that cannot be addressed cannot be dropped
    silently.
    """
    method = _require_method(client, "open_orders")
    data = method()
    entries = data
    if isinstance(data, Mapping):
        entries = data.get(OPEN_ORDERS_FIELD)
    if (
        entries is None
        or isinstance(entries, (str, bytes))
        or not isinstance(entries, Sequence)
    ):
        raise RouterBingXFlattenError(
            f"{BINGX_FLATTEN_CODE}: the venue's open-orders answer is an "
            f"array of orders (or {{'orders': [...]}}), got {data!r} "
            f"({type(data).__name__}); the flatten cancels every open "
            "order on the account, and an answer that is not the listing "
            "names nothing to cancel"
        )
    targets: list[FlattenCancel] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: the venue's open-orders listing "
                f"holds an order object per row, got {entry!r} "
                f"({type(entry).__name__}); a row that is not an object "
                "cannot name the order it is"
            )
        identifier = _row_identifier(entry)
        if identifier is None:
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: an open-orders row carries its "
                f"identifier under one of {list(IDENTIFIER_FIELDS)}, got "
                f"{entry!r}; every row of the listing is a target of the "
                "flatten, and an order this module cannot address is an "
                "order it cannot cancel — never one to skip silently"
            )
        raw_symbol = entry.get(SYMBOL_FIELD)
        symbol = (
            raw_symbol.strip()
            if isinstance(raw_symbol, str) and raw_symbol.strip()
            else None
        )
        targets.append(
            FlattenCancel(client_order_id=identifier, symbol=symbol)
        )
    return targets


def position_close_orders(*, client: Any) -> list[FlattenClose]:
    """The account's positions, one close order per symbol that holds one.

    Reads the account's positions through Stage 1's
    :func:`router.bingx_mirror.live_positions` — the reader that spells
    the venue's unsigned ``positionAmt`` and its ``positionSide`` as one
    signed quantity per symbol — and answers one :class:`FlattenClose`
    per non-zero holding, in the venue's own order.  The side is opposite
    to the position's own direction (a negative signed amount — a short —
    is closed by a ``BUY``, a positive one by a ``SELL``), and the
    quantity is the position's magnitude in plain positional notation,
    the exact scale the venue's document spelled.  A holding of zero
    closes nothing: there is no position behind it, and an order for zero
    units is not one any venue books.
    """
    held = live_positions(client)
    closes: list[FlattenClose] = []
    for symbol, amount in held.items():
        if amount == 0:
            continue
        closes.append(
            FlattenClose(
                symbol=symbol,
                side=BINGX_BUY if amount < 0 else BINGX_SELL,
                quantity=format(abs(amount), "f"),
            )
        )
    return closes


def plan_flatten(*, client: Any) -> FlattenPlan:
    """What a flatten of this account would do: every cancel, every close.

    The two reads a confirmed run makes before it acts — the account's
    open orders and its positions — answered as one value, in the order
    the run would perform them.  Nothing is sent, nothing is cancelled
    and nothing is closed: this is the plan an unconfirmed run prints and
    changes nothing over, the same reads through the same reader, so the
    lines a dry run prints and the lines a confirmed run prints are one
    shape from one source.
    """
    return FlattenPlan(
        cancels=tuple(open_order_cancel_targets(client=client)),
        closes=tuple(position_close_orders(client=client)),
    )


# -- The walk ------------------------------------------------------------------


def _refusal_code(refusal: BaseException) -> str:
    """The greppable code for a refusal that stopped a cancel or a close.

    The venue's own ``code`` for a ``bingx_refused`` answer — what the
    feature's *"printed with its code"* names — and, for a refusal
    carrying none (a transport that dropped mid-write, an exhausted
    backoff), the class name of the refusal, the same discipline the
    mirror's ``_refusal_code`` keeps, so one column always carries a
    token an operator can grep.
    """
    code = getattr(refusal, "code", None)
    if code is not None:
        return str(code)
    return type(refusal).__name__


def _refusal_message(refusal: BaseException) -> str | None:
    """The venue's own ``msg`` for a refusal, verbatim, or ``None``.

    Read off :attr:`RouterBingXRefusedError.msg` — the venue's envelope
    text, the **only** ``msg`` any vocabulary in this member holds — so
    the message a refused line prints is the venue's own words and never
    a request URL, query string, signature or credential.  A refusal that
    carries none answers ``None``: the code column is that refusal's
    token, and a message invented here would be a fact no venue stated.
    """
    msg = getattr(refusal, "msg", None)
    if isinstance(msg, str) and msg.strip():
        return msg
    return None


def _cancel_line(
    target: FlattenCancel, *, code: str | None = None, message: str | None = None
) -> str:
    """One cancelled order's JSON line — a refused cancel's, with its code.

    ``{"clientOrderID": ...}``, the same line the mirror's ``--cancel``
    prints, so an operator's tooling reads one shape; a cancel the venue
    refused adds the refusing ``code`` and the venue's own ``message``
    beside it, the mirror's placed-line convention.
    """
    line: dict[str, Any] = {"clientOrderID": target.client_order_id}
    if code is not None:
        line["code"] = code
    if message is not None:
        line["message"] = message
    return json.dumps(line)


def _close_line(
    close: FlattenClose, *, code: str | None = None, message: str | None = None
) -> str:
    """One close's JSON line: the order as sent — a refused one, with its code.

    The close's own parameters, which are what the venue was asked to
    take; a close the venue refused adds the refusing ``code`` and the
    venue's own ``message`` beside them, which is the sentence's own
    clause: *"A close the venue refuses is printed with its code and
    message."*
    """
    line: dict[str, Any] = close.parameters()
    if code is not None:
        line["code"] = code
    if message is not None:
        line["message"] = message
    return json.dumps(line)


def flatten_account(
    *,
    client: Any,
    emit: Callable[[str], None] = print,
) -> FlattenReport:
    """Feature 1's verb: cancel every open order, then close every position.

    The one function in this module that closes positions, and therefore
    the one door feature 2's daily-loss guard reaches the flatten through;
    the command reaches it only behind ``--confirm``, and nothing else
    calls it.  The walk is the sentence's own order: read the listing and
    cancel every open order on the account, then read the positions and
    close each non-zero holding with one reduce-only ``MARKET`` order.
    Each target's outcome is emitted as one JSON line the moment it is
    known (``emit``, printing by default, so an operator watching a long
    flatten watches it happen), a refused target — the venue's own
    refusal, or any other :class:`~router.errors.RouterError` that
    stopped that one cancel or close — prints its line with the refusing
    code and the venue's own message and the walk continues with the
    remaining targets, and no refusal unwinds what came before it.

    The report's final terms are the venue's to answer, not this walk's
    to claim: after the last close the account is read again — the
    open-orders listing and the positions, through the same readers — and
    :attr:`FlattenReport.succeeded` is true only when that read shows no
    open orders and no non-zero position and no target was refused.

    A pure function of the injected client apart from the cancels and the
    closes it performs: no store, no clock, no credential, no socket of
    its own.  Refuses :class:`RouterBingXFlattenError` for faults of the
    ask (an unreadable listing, a client missing a method); a fault in a
    single target is that target's refused line, never the walk's end.
    """
    cancel = _require_method(client, "cancel_order")
    place = _require_method(client, "place_order")

    cancel_outcomes: list[FlattenCancelOutcome] = []
    for target in open_order_cancel_targets(client=client):
        try:
            cancel(target.client_order_id, symbol=target.symbol)
        except RouterError as refusal:
            code = _refusal_code(refusal)
            message = _refusal_message(refusal)
            cancel_outcomes.append(
                FlattenCancelOutcome(
                    target=target,
                    outcome=FLATTEN_OUTCOME_REFUSED,
                    code=code,
                    message=message,
                )
            )
            emit(_cancel_line(target, code=code, message=message))
        else:
            cancel_outcomes.append(
                FlattenCancelOutcome(
                    target=target, outcome=FLATTEN_OUTCOME_CANCELLED
                )
            )
            emit(_cancel_line(target))

    close_outcomes: list[FlattenCloseOutcome] = []
    for close in position_close_orders(client=client):
        try:
            place(close.parameters())
        except RouterError as refusal:
            code = _refusal_code(refusal)
            message = _refusal_message(refusal)
            close_outcomes.append(
                FlattenCloseOutcome(
                    close=close,
                    outcome=FLATTEN_OUTCOME_REFUSED,
                    code=code,
                    message=message,
                )
            )
            emit(_close_line(close, code=code, message=message))
        else:
            close_outcomes.append(
                FlattenCloseOutcome(close=close, outcome=FLATTEN_OUTCOME_CLOSED)
            )
            emit(_close_line(close))

    return FlattenReport(
        cancel_outcomes=tuple(cancel_outcomes),
        close_outcomes=tuple(close_outcomes),
        remaining_open_orders=tuple(open_order_cancel_targets(client=client)),
        remaining_positions=tuple(position_close_orders(client=client)),
    )


# -- Value helpers ---------------------------------------------------------------


def _require_outcome_terms(
    outcome: str,
    refusal_word: str,
    code: str | None,
    message: str | None,
    *,
    what: str,
) -> None:
    """Judge an outcome's code/message pair against its own word.

    A refused target carries a code — what an operator greps to learn why
    — and carries a message only when the venue worded one; a target that
    was not refused carries neither, because an order the venue took has
    nothing to explain.  The same judgment :class:`router.bingx_mirror.
    MirrorLeg` makes of its own three words, stated here for this
    module's two.
    """
    if outcome == refusal_word:
        if not isinstance(code, str) or not code.strip():
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: {what} refused by the venue "
                "carries the refusing vocabulary's code word, got "
                f"{code!r}; the code is what an operator greps to learn "
                "why the target did not land (feature 1)"
            )
        if message is not None and (
            not isinstance(message, str) or not message.strip()
        ):
            raise RouterBingXFlattenError(
                f"{BINGX_FLATTEN_CODE}: a refused target's message is the "
                f"venue's own msg verbatim, got {message!r}; a message "
                "that states nothing is not a reason — a refusal the "
                "venue worded carries its msg, and one it did not carries "
                "no message at all (feature 1)"
            )
    elif code is not None or message is not None:
        raise RouterBingXFlattenError(
            f"{BINGX_FLATTEN_CODE}: {what} the venue took carries no "
            f"refusal code or message, got code {code!r} and message "
            f"{message!r}; a target that landed has nothing to explain "
            "(feature 1)"
        )


# -- The command ----------------------------------------------------------------


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    transport: Any = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """The command: ``python -m router.bingx_flatten [--confirm]``.

    Without ``--confirm`` it prints what it would do — one JSON line per
    open order it would cancel and one per close it would send, the same
    lines a confirmed run prints — and changes nothing, sending no cancel
    and no close, then exits 0.  With ``--confirm`` it flattens the
    account through :func:`flatten_account` — cancelling every open order
    on it, then closing every position — prints one JSON line per
    cancelled order and per close, and exits 0 only when the final read
    shows no open orders and no positions and nothing was refused; a
    refused cancel or close prints its line with the venue's own code and
    message and the run exits 1, and what the final read still shows is
    named on stderr.

    The ``client``, ``transport`` and ``env`` are injectable so the suite
    drives the command against a recording double without any environment
    variable that could change the host — a caller that injects nothing
    gets feature 1's real client built from the environment.  There is no
    store to configure: the flatten records nothing, because the
    account's own next read is the record.
    """
    parser = argparse.ArgumentParser(
        prog="python -m router.bingx_flatten",
        description=(
            "Flatten the BingX VST sub-account: cancel every open order on "
            "it, then close every position with one reduce-only MARKET "
            "order per symbol. Without --confirm, print what would be done "
            "and change nothing."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="cancel every open order and close every position; without it "
        "the command prints what it would do and changes nothing",
    )
    arguments = parser.parse_args(argv)

    try:
        if client is None:
            client = BingXClient.from_env(env=env, transport=transport)

        if not arguments.confirm:
            plan = plan_flatten(client=client)
            for target in plan.cancels:
                print(_cancel_line(target))
            for close in plan.closes:
                print(_close_line(close))
            return 0

        report = flatten_account(client=client)
        if not report.flat:
            still_open = ", ".join(
                target.client_order_id
                for target in report.remaining_open_orders
            )
            still_held = ", ".join(
                close.symbol for close in report.remaining_positions
            )
            print(
                f"{BINGX_FLATTEN_CODE}: the final read still shows "
                + (
                    f"open orders ({still_open})"
                    if report.remaining_open_orders
                    else "no open orders"
                )
                + " and "
                + (
                    f"positions ({still_held})"
                    if report.remaining_positions
                    else "no positions"
                )
                + "; re-run the flatten for what remains (feature 1)",
                file=sys.stderr,
            )
        return 0 if report.succeeded else 1
    except RouterError as exc:
        message = str(exc)
        prefix = f"{BINGX_FLATTEN_CODE}: "
        if not message.startswith(prefix):
            message = prefix + message
        print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
