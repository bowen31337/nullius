"""The prior result of a duplicate submission — feature 317's answer.

app_spec.xml, "Order Routing & Venue Filters", feature 317: *System returns
the prior result for a duplicate client order identifier rather than placing
a second order.*  The sentence has one noun it does not define and one it
does: the *client order identifier* is feature 316's derived key
(:mod:`router.client_order_id`, ``hash(book_id, rebalance_ts, symbol)``,
whole and never truncated), and the *prior result* is what this module
stores and hands back.

**Why the router sends one order twice, and why that is not a bug.**  The
order path re-sends legitimately: a reclaimed spot instance re-runs its
rebalance step (§14's eval workers are spot-eligible, and a router restart
re-sends whatever the last process was sending), and feature 319's backoff
re-sends a request the venue's weight budget refused.  Feature 316's
docstring states why its key is *derived* rather than generated — two
processes that never speak can still agree on it — and this module is the
other half of that bargain: the agreement is worth something only if the
second send is *answered* from the first send's record instead of reaching
the venue again.  A venue books a fill, not an intention, so a duplicate
that gets through is a position the book never decided to hold.

**The record is the placement, and the placement is a fact to store.**  One
row per client order identifier, in this member's own table in the
workspace's relational store (``DATABASE_URL``) — which leg was placed, how
the venue answered, and when.  The row's address *is* feature 316's key, so
a second process deriving the same key (the same book, the same rebalance
instant, the same leg) reaches the same row without having spoken to the
first.  That is the whole of this module's idempotence, and it is why the
record is a table rather than a map this process holds: the reclamation and
the restart that produce the second send are exactly what would empty an
in-process memo.

**Check, place, insert — one transaction, and the order of those three is
the feature.**  Two routers recovered from one spot reclamation can derive
one key at the same instant, and the window that matters is the one between
*"the key has no row"* and *"the row is written"*: a second placement
slipping through it is the failure this feature exists to make impossible.
So the guard is ``INSERT … SELECT … WHERE NOT EXISTS (… client_order_id =
?)`` on the one connection the operation opens — the discipline
:meth:`ledger.store.TrialLedger.debit` states for its own idempotent charge,
and for the same reason: concurrent asks for one key serialise on the
database's write lock, and every caller after the first is answered by the
first's row without holding a lock of its own.

The *callable* runs inside that same transaction, between the claim and the
commit, and that placement is load-bearing in both directions:

* **A venue refusal must leave no row.**  The callable raises when the venue
  refuses, the transaction rolls back, and the claim row goes with it — so
  the next attempt for that order takes the fresh path again.  If the row
  were committed before the venue spoke, one transient refusal would be
  recorded as a placement and every later attempt would be answered
  *"already placed"* for an order that was never placed at all.
* **A concurrent duplicate must not race the venue.**  The second router
  blocks on the write lock until the first commits, then reads the
  committed row and is answered from it without a second send — which is
  precisely *"rather than placing a second order"*, under concurrency
  rather than only in sequence.

**Only a placement is recorded; a refusal is not a result.**  The table's
outcome vocabulary is exactly ``{accepted}``, and the way a caller states a
refusal is by raising from the callable — a return from it *is* the venue's
acceptance.  The reason is the sentence's own: a duplicate of a placement
would place a second order, while a venue *rejection* placed nothing — a
second attempt at a refused order is not a duplicate, it is the retry the
order path is entitled to make, and a row saying otherwise would make one
transient refusal permanent.  So a rejection propagates out of
:meth:`RouterOrderPlacementStore.place` untouched and unrecorded, and this
module owns no rejection handling at all: recording how submissions are
going is feature 320's table, and this one never restates it.  A caller that
wants the refusal written down records it there, from its own ``except``.

**The vocabulary is one spelling of the venue's answer.**  The outcome token
is feature 320's ``accepted`` constant, imported rather than respelled, for
the reason a member keeps one vocabulary for one fault: an operator joining
a placement to the submission-health row that describes it (feature 320's
``client_order_id`` column, *"for joining only"*) must not have to know that
two of this member's tables spelled the venue's answer differently.  The
*refusal* this module raises is a different fact with a different repair, so
it is its own class in this member's error tree — see :mod:`router.errors`.

**The store is addressed, never composed.**  ``DATABASE_URL``, exactly as
this member's exchangeInfo log, its submission-health log and its weight
bucket are; :meth:`RouterOrderPlacementStore.resolve` answers ``None`` for a
deployment that named no database, the deploy-without-a-store stance every
store here takes.  No ``@register`` — the member still registers exactly one
component (feature 310's exchangeInfo store) — no seat edit and no
migration: the member-owned table is created idempotently on connect by the
only module that writes it.

**Two verbs, and the pair is the feature.**  :meth:`~RouterOrderPlacementStore.place`
is feature 317's sentence in full — it answers a duplicate *instead of*
placing, so the skip is not a step a caller can forget — and it returns a
:class:`PlacementResult`: the record that stands, beside ``appended``,
``False`` exactly when this call was answered by a row already held.  That
is the counterpart of feature 95's ``DebitResponse.appended`` and the thing
a caller that must account for what it sent reads; it rides on the *result*
rather than on the placement so that a duplicate's placement compares
**equal** to the first call's, which is what makes *"returns the prior
result"* a comparison a caller can actually make.
:meth:`~RouterOrderPlacementStore.prior_result` answers the same record for
a caller that holds a key and wants it without attempting anything at all.

Stdlib only, and import-cheap — ``sqlite3``, ``os``, ``urllib.parse`` and
``pathlib`` are the interpreter's own — so the factory's scan pays nothing
for this module and a composed deployment that never places an order never
opens the table.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .client_order_id import normalize_client_order_id
from .errors import (
    SUBMISSION_RESULT_CODE,
    RouterStoreError,
    RouterSubmissionResultError,
)
from .submission_health import ORDER_SUBMISSION_ACCEPTED

__all__ = [
    "DATABASE_URL_ENV",
    "ORDER_PLACEMENT_OUTCOMES",
    "ORDER_PLACEMENT_TABLE",
    "ORDER_RECORD_TABLE",
    "OrderPlacement",
    "OrderRecord",
    "PlacementOrder",
    "PlacementResult",
    "RouterOrderPlacementStore",
]

#: The workspace-wide environment variable naming the relational store.
DATABASE_URL_ENV = "DATABASE_URL"

#: One row per placed order: feature 316's key and what the venue did with it.
ORDER_PLACEMENT_TABLE = "router_order_placement"

#: One row per order placement's **terms** — the rebalance's identity, the
#: leg, and the reference price a fill is measured against.  Feature 317's
#: table above holds *that* an order was placed and feature 316's key names
#: it, but a key is a one-way hash of ``(book_id, rebalance_ts, symbol)`` and
#: carries neither the side, the type, the quantity nor the price; and the
#: only plan a later run can rebuild is re-sized against *today's* positions
#: and *today's* marks, so it holds neither every order the rebalance placed
#: nor the prices the venue was actually asked for.
#:
#: This table is where placement records what it sent, keyed by the same
#: full 64-hex identifier, so the fill-cost reconciliation of a *finished*
#: rebalance reads the terms back rather than rebuilding a plan that has
#: nothing to say about them (the defect the reconciliation bug spec names).
#: It sits beside feature 317's table because both are facts about a
#: placement and both are written by the same act, but the tables stay
#: distinct: feature 317's is the app-owned idempotency claim whose key is
#: its whole content, and this one is the router's record of the *terms* a
#: fill is priced against, whose content is exactly what a hash cannot carry.
ORDER_RECORD_TABLE = "router_order_record"

#: The closed outcome vocabulary this table admits — exactly the states a
#: *placement* can be in, which is one: the venue took the order.  A
#: rejection is deliberately absent, because a refused order is not a
#: placement and a second attempt at one is not a duplicate; see the module
#: docstring, and :meth:`RouterOrderPlacementStore.place` for why a rejection
#: is stated by raising rather than by a value.
ORDER_PLACEMENT_OUTCOMES = frozenset({ORDER_SUBMISSION_ACCEPTED})

#: The ``CHECK`` constraint the outcome column carries, built from
#: :data:`ORDER_PLACEMENT_OUTCOMES` in sorted order so the DDL is
#: deterministic and an outcome added to the set cannot land a table that
#: accepts it while the value layer refuses it — the discipline feature 320's
#: own schema keeps for its wider vocabulary.
_OUTCOME_CHECK = ", ".join(
    f"'{outcome}'" for outcome in sorted(ORDER_PLACEMENT_OUTCOMES)
)

_SCHEMA = f"""
-- Feature 317: one row per order the router placed.
--
-- The key IS feature 316's derived identifier rather than a surrogate beside
-- it: the row a resubmission is answered from is addressed by exactly the
-- value the re-sending process derives for itself, so two processes that
-- never speak reach the same row.  PRIMARY KEY is what makes that address
-- unique, declared here as well as guarded at the seam for the reason the
-- member states everywhere: SQLite accepts a raw INSERT from any tool, and a
-- table that could hold two rows for one order would answer a duplicate with
-- whichever row it happened to read first.
CREATE TABLE IF NOT EXISTS {ORDER_PLACEMENT_TABLE} (
    client_order_id TEXT NOT NULL PRIMARY KEY,  -- feature 316's 64 hex chars
    symbol          TEXT NOT NULL,              -- the leg that was placed
    outcome         TEXT NOT NULL CHECK (outcome IN ({_OUTCOME_CHECK})),
    placed_at       TEXT NOT NULL               -- ISO 8601 UTC: when it landed
);

-- Feature 317's placement terms, one row per placed order, beside the row
-- above and keyed by the same identifier.  Every value is TEXT and every
-- decimal is the string the router *sent* (the venue's own spelling, or a
-- Decimal rendered positionally), for the reason every store in this member
-- states: a decimal re-rendered by a store would be a decimal nobody sent.
-- The reference price is NOT NULL for every row: a LIMIT order carries the
-- limit it was priced at, and a MARKET order carries the mark read in the
-- same run, so a filled order always has a reference to be measured against.
CREATE TABLE IF NOT EXISTS {ORDER_RECORD_TABLE} (
    client_order_id TEXT NOT NULL PRIMARY KEY,  -- feature 316's 64 hex chars
    book_id         TEXT NOT NULL,              -- the rebalance's book
    rebalance_ts    TEXT NOT NULL,              -- ISO 8601 UTC: the slot start
    symbol          TEXT NOT NULL,              -- the leg that was placed
    side            TEXT NOT NULL,              -- BUY / SELL
    type            TEXT NOT NULL,              -- LIMIT / MARKET
    quantity        TEXT NOT NULL,              -- the sent order's size
    reference_price TEXT NOT NULL,              -- limit price, or run's mark
    placed_at       TEXT NOT NULL               -- ISO 8601 UTC: when it landed
);
"""

#: The one write this module makes: claim the key iff it has no row yet.
#: ``WHERE NOT EXISTS`` rather than a bare ``INSERT`` so the check and the
#: claim are one statement on one connection — see the module docstring on
#: what the transaction it runs in is holding.
_INSERT_SQL = f"""
INSERT INTO {ORDER_PLACEMENT_TABLE} (
    client_order_id, symbol, outcome, placed_at
)
SELECT ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM {ORDER_PLACEMENT_TABLE} WHERE client_order_id = ?
)
"""

#: The one row this module reads, by the canonical key the write landed.
_READ_SQL = f"""
SELECT client_order_id, symbol, outcome, placed_at
FROM {ORDER_PLACEMENT_TABLE}
WHERE client_order_id = ?
"""

#: The columns the terms read-back unpacks, in the order :class:`OrderRecord`
#: names them — spelled once so the write and the read cannot drift apart on
#: a column order, the failure a positional ``SELECT *`` invites.
_RECORD_COLUMNS = (
    "client_order_id, book_id, rebalance_ts, symbol, side, type, "
    "quantity, reference_price, placed_at"
)

#: The terms write: claim the key iff it has no row yet, the same
#: ``WHERE NOT EXISTS`` shape feature 317's write uses and for the same
#: reason — the check and the claim are one statement, so the row a
#: resubmission reads is the row the first placement wrote rather than a
#: second row for one order.  A row already held is *not* restated: an order
#: placed once has one set of terms, and re-recording them would let a
#: re-send rewrite the reference a fill is measured against.
_RECORD_INSERT_SQL = f"""
INSERT INTO {ORDER_RECORD_TABLE} (
    {_RECORD_COLUMNS}
)
SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
WHERE NOT EXISTS (
    SELECT 1 FROM {ORDER_RECORD_TABLE} WHERE client_order_id = ?
)
"""

#: Every term this module recorded for one rebalance, in the order the rows
#: landed.  Read by ``(book_id, rebalance_ts)`` — the rebalance's identity,
#: §13.2's own pair — because that is the whole of what the reconciliation
#: of a finished rebalance is given.
_RECORD_READ_SQL = f"""
SELECT {_RECORD_COLUMNS}
FROM {ORDER_RECORD_TABLE}
WHERE book_id = ? AND rebalance_ts = ?
ORDER BY rowid
"""


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :func:`router.store._sqlite_path` and
    :func:`router.submission_health._sqlite_path` state, in this module's own
    words, for the reason every store in this member restates it: a store
    reaches into no sibling's private helper, so a later change to one
    table's address handling cannot silently move another's.
    ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is absolute, and
    any other scheme is refused by name.

    Raises :class:`~router.errors.RouterStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault with
    an address repair — point the deployment at a database this store can
    open — which is the face that class already carries for this variable.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RouterStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "router's order-placement store speaks sqlite:/// (the spec's "
            "single-machine allowance); point "
            f"{DATABASE_URL_ENV} at the sqlite database the router's placed "
            "orders are recorded in (feature 317)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 317)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path:
        raise RouterStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path (feature 317)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    UTC, ISO 8601 — the same spelling feature 316's :func:`_instant_term`
    folds into the key one module over, and the same one the book member's
    rebalance table stores.  Nothing here depends on this string ordering
    rows: the key is a hash rather than a tuple, so no read sorts by it, and
    it is one form only so that two readers of the column compare it the
    same way.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* an order landed, and a
    placement record whose moment named an offset nobody agreed on would be
    a record two operators read differently — the same discipline this
    member's submission-health store holds its own moments to.
    """
    if not isinstance(moment, datetime):
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__}; a placement happened at an instant "
            "(feature 317)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: {what} must be timezone-aware, got "
            f"{moment!r}; the placement record says when the order was "
            "written down, and a naive moment names an offset nobody agreed "
            "on (feature 317)"
        )
    return moment


def _require_moment(value: object, what: str) -> datetime:
    """Return ``value`` as a timezone-aware instant, from a datetime or ISO text.

    A rebalance's instant reaches this member in two spellings: as a
    :class:`~datetime.datetime` a caller built, or as the ISO 8601 string the
    *book file* carries (``"2026-09-30T00:00:00+00:00"``).  Both are read
    here — a string is parsed before anything else is touched — so a caller
    handing the book's own spelling is not refused deep inside a store for a
    value the book legitimately holds, and a naive or unparsable value is
    refused up front naming itself.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise RouterSubmissionResultError(
                f"{SUBMISSION_RESULT_CODE}: {what}={value!r} is not an ISO "
                "8601 instant; the rebalance's instant is the second half of "
                "the pair that names every order, and a string that will not "
                "parse names no rebalance (feature 317)"
            ) from exc
    return _require_aware(value, what)


def _placement_moment(now: datetime | None) -> datetime:
    """The instant a placement record is stamped with: ``now``, or the clock.

    The one door both writes in this member take their moment through — the
    placement row (feature 317) and its terms (this bug's fix) — so the
    module reads the wall clock in exactly one place and a caller that hands
    a ``now`` (the suite, and a caller staging a deterministic moment) is
    honoured identically by both.  The clock read is a *label*: it says when
    the order was written down, and no identity in this member is hashed
    from it — feature 316's key is the rebalance's own instant, taken from
    the book — so a retry that lands under a later reading cannot change an
    order's name.
    """
    if now is None:
        now = datetime.now(UTC)
    return _require_aware(now, "now")


def _require_symbol(value: object) -> str:
    """Return ``value`` as a venue symbol, or refuse what cannot be one.

    Non-empty text, stripped, otherwise verbatim: the venue's own spelling is
    the key the exchangeInfo filters are filed under
    (:meth:`~router.store.RouterExchangeInfoStore.filters_for`), so a record
    that case-folded or re-spelled a symbol would name a leg no filter could
    be looked up for — the rule feature 316 holds the same term to one module
    over.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: symbol must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); a placement record names "
            "the leg the order was for, and a leg that states nothing names "
            "no order the venue could have taken (feature 317)"
        )
    return value.strip()


def _require_book_id(value: object) -> str:
    """Return ``value`` as a rebalance's book id, or refuse what cannot be one.

    Non-empty text, stripped, otherwise verbatim: the book id is half of the
    ``(book_id, rebalance_ts)`` pair feature 316 folds into every order's
    name, so a record that re-spelled it would name a rebalance no order
    belongs to.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a recorded order's book_id must be "
            f"non-empty text, got {value!r} ({type(value).__name__}); the "
            "rebalance a fill belongs to is named by the pair (book_id, "
            "rebalance_ts), and a record that names no book cannot be "
            "reconciled (feature 317)"
        )
    return value.strip()


#: The venue's two order sides, restated here rather than imported from
#: :mod:`router.bingx_order` so this module's own record vocabulary is
#: self-standing (the discipline every store keeps for its own terms).  The
#: spellings are the venue's own — a record that carried ``buy`` would name a
#: side no order was placed with.
_ORDER_SIDES = frozenset({"BUY", "SELL"})

#: The venue's two order types.  ``LIMIT``/``MARKET`` is exactly the pair the
#: fee rule turns on — maker for a passive limit, taker for an aggressive
#: market — so a record outside it names no fee the reconciliation could
#: read.
_ORDER_TYPES = frozenset({"LIMIT", "MARKET"})


def _require_side(value: object) -> str:
    """Return ``value`` as a venue order side, or refuse it by name."""
    if not isinstance(value, str) or value not in _ORDER_SIDES:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a recorded order's side is one of "
            f"{sorted(_ORDER_SIDES)}, got {value!r}; a fill's signed slippage "
            "is adverse-positive only against a known side, so a record "
            "outside the venue's own vocabulary is one no order was placed "
            "with (feature 317)"
        )
    return value


def _require_type(value: object) -> str:
    """Return ``value`` as a venue order type, or refuse it by name."""
    if not isinstance(value, str) or value not in _ORDER_TYPES:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a recorded order's type is one of "
            f"{sorted(_ORDER_TYPES)}, got {value!r}; the fee a fill paid is "
            "the maker rate for a LIMIT and the taker rate for a MARKET, so a "
            "record outside that pair names neither (feature 317)"
        )
    return value


def _require_positive(value: object, what: str) -> Decimal:
    """Return ``value`` as an exact positive :class:`~decimal.Decimal`, or refuse it.

    ``str``, ``int`` and :class:`~decimal.Decimal` are read (a JSON number
    reaches here as its shortest ``str`` spelling, the same reading
    :func:`router.bingx_reconcile._rate` takes of a document's rate); a
    ``bool``, a float, a non-finite or non-positive value is refused.  A
    quantity or reference price of zero is not a term any order was sent
    with — the venue refuses a zero-size order — so a record holding one is a
    fault of the ask rather than a fact to store.
    """
    if isinstance(value, (bool, float)) or value is None:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a recorded order's {what} must be an "
            f"exact decimal (a string, an int or a Decimal), got {value!r} "
            f"({type(value).__name__}); money and size are never binary "
            "approximations (feature 317)"
        )
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (str, int)):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            number = None
    else:
        number = None
    if number is None or not number.is_finite() or number <= 0:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a recorded order's {what} must be a "
            f"finite positive decimal, got {value!r}; an order is sent with a "
            "size and (for the reconciliation) a reference price it is "
            "measured against, and a value that is not positive names neither "
            "(feature 317)"
        )
    return number


def _decimal_text(value: Decimal) -> str:
    """Render a :class:`~decimal.Decimal` in plain positional notation.

    ``str(Decimal("1E+3"))`` is ``'1E+3'``, which a plain positional reader
    (the venue's own documents, an operator at a sqlite prompt) would not read
    as one thousand; ``format(value, 'f')`` renders the same value as
    ``'1000'``.  Every decimal this table stores goes through here, so what
    lands is what the router sent.
    """
    return format(value, "f")


def _require_outcome(value: object) -> str:
    """Return ``value`` as a placement outcome, or refuse it by name.

    Membership is tested against the *string* the value would have to be
    rather than against the value itself, because ``frozenset`` membership
    raises :class:`TypeError` on an unhashable argument — a ``[]`` here is a
    crash, not a ``False`` — and a caller offering a list to a column of
    tokens deserves this member's refusal naming the value.  A venue
    *rejection* lands in this refusal too, deliberately: it is the one value
    a caller is most likely to reach for, and the repair it needs — record
    the placement you actually made, and let a refusal raise — is the
    module's whole stance.
    """
    if not isinstance(value, str) or value not in ORDER_PLACEMENT_OUTCOMES:
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: a placement outcome is one of "
            f"{sorted(ORDER_PLACEMENT_OUTCOMES)}, got {value!r}; this table "
            "records orders the venue *took*, and a refusal placed nothing — "
            "a second attempt at a refused order is the retry the order path "
            "is entitled to make rather than a duplicate, so the refusal "
            "belongs in feature 320's submission-health log, not here "
            "(feature 317)"
        )
    return value


def _require_callable(value: object) -> Callable[[], Any]:
    """Return ``value`` as the placement itself, or refuse it by name.

    Refused eagerly, before the store is read at all: a caller that hands
    this store something it cannot call has asked for a placement nobody
    could perform, and answering it *"already placed"* from a prior row
    would be this module pretending an ask it never understood had been
    honoured — the same eagerness
    :func:`router.retry.retry_rate_limited` shows its own request.
    """
    if not callable(value):
        raise RouterSubmissionResultError(
            f"{SUBMISSION_RESULT_CODE}: the placement must be callable taking "
            f"no arguments, got {value!r} ({type(value).__name__}); this "
            "store either answers an order from a prior row or performs the "
            "placement it was handed, and an ask it cannot perform is not a "
            "duplicate (feature 317)"
        )
    return value


@dataclass(frozen=True)
class PlacementOrder:
    """One order the router wants placed, named by feature 316's key.

    The ask :meth:`RouterOrderPlacementStore.place` is handed, and the whole
    of what this module needs in order to know whether a placement is a
    duplicate: ``client_order_id`` *is* the identity the sentence names, and
    ``symbol`` is the leg, carried so the record can say which instrument a
    prior placement was for without a caller holding only the key having to
    re-derive the terms.

    Both fields are validated at construction — the key through feature 316's
    :func:`~router.client_order_id.normalize_client_order_id`, which accepts
    64 hex characters in either case and answers the lowercase spelling, and
    the symbol as non-empty stripped text — so two asks built from one order
    compare equal however the caller came by the spellings, and the store
    never compares an uppercase key against the lowercase one its write
    landed.
    """

    client_order_id: str
    symbol: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            normalize_client_order_id(self.client_order_id),
        )
        object.__setattr__(self, "symbol", _require_symbol(self.symbol))

    @property
    def key(self) -> str:
        """The identity this ask is answered by — feature 316's key.

        Spelled as its own name because the sentence's clause — *"for a
        duplicate client order identifier"* — is a statement about this one
        value, and the duplicate test reads off it: two asks with one key are
        one order.
        """
        return self.client_order_id


@dataclass(frozen=True)
class OrderPlacement:
    """One placed order: its key, its leg, the venue's answer, its instant.

    The *prior result* feature 317's sentence returns — the record a
    duplicate is answered by, and the record a first placement lands.  Each
    field is the smallest thing that makes it an answer rather than a
    receipt:

    * ``client_order_id`` — feature 316's key, the row's address, and the
      value a re-sending process derives for itself.  64 lowercase hex
      characters; this module validates it through feature 316's own
      function rather than re-spelling the rule, so a key this store cannot
      address is refused as the identifier's own fault.
    * ``symbol`` — the leg that was placed, so an operator reading a
      placement off its key (a hash is one-way) can see which instrument it
      was for without a second query.
    * ``outcome`` — the venue's answer, from
      :data:`ORDER_PLACEMENT_OUTCOMES`.  One member today, and the field
      exists rather than being implied because the venue *does* answer
      differently: a rejection placed nothing, and that difference is the
      feature's own reason for existing.
    * ``placed_at`` — when the row was written, timezone-aware.

    **Nothing about the call that produced it is on this value.**  Whether
    *this* call placed the order or was answered from a row already held is
    a fact about the call, not about the order — see
    :class:`PlacementResult`, which carries it — and that separation is
    exactly what makes *"returns the prior result"* checkable: a duplicate's
    placement compares **equal** to the placement the first call returned,
    so a caller that stores the answer and compares it later is comparing
    the order rather than the history of asking for it.  Keeping the bit on
    this value would make two reads of one row unequal, which would be the
    record misreporting itself.
    """

    client_order_id: str
    symbol: str
    outcome: str
    placed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            normalize_client_order_id(self.client_order_id),
        )
        object.__setattr__(self, "symbol", _require_symbol(self.symbol))
        object.__setattr__(self, "outcome", _require_outcome(self.outcome))
        object.__setattr__(
            self, "placed_at", _require_aware(self.placed_at, "placed_at")
        )

    @property
    def key(self) -> str:
        """The placement's identity — feature 316's key, spelled out."""
        return self.client_order_id


@dataclass(frozen=True)
class PlacementResult:
    """Feature 317's answer: the placement, and which side of it this call was.

    ``placement`` is the record that stands — the row this call landed, or
    the prior row a duplicate is answered by, and those two are *the same
    value* when the order is the same one.  ``appended`` is whether *this*
    call placed it: ``True`` when the check-and-insert took the claim and the
    venue was called, ``False`` exactly when the answer came from a row
    already held, in which case the venue's callable was never invoked and
    this answer changed nothing.

    The same pair, the same names and the same reason as
    :class:`ledger.debit.DebitResponse`, which carries ``appended`` beside
    the record it answers with: *"a caller that posts the same request twice
    and compares responses finds the sequence equal and only ``appended``
    differs"*.  That sentence is this class, with one word changed.

    :attr:`replayed` is the same bit read as the question the feature is
    actually about — *was this call answered by a placement already held?* —
    because a caller writing ``if result.replayed:`` is stating the
    sentence, while one writing ``if not result.appended:`` is stating its
    negation.
    """

    #: Whether this call placed the order — ``False`` on a duplicate.
    appended: bool
    #: The record that stands: freshly placed, or the prior result.
    placement: OrderPlacement

    def __post_init__(self) -> None:
        if not isinstance(self.appended, bool):
            raise RouterSubmissionResultError(
                f"{SUBMISSION_RESULT_CODE}: a placement result's appended flag "
                f"must be a genuine bool, got {self.appended!r} "
                f"({type(self.appended).__name__}); the flag is the whole "
                "difference between a placement and a duplicate, and a "
                "near-miss value would make the two indistinguishable "
                "(feature 317)"
            )

    @property
    def replayed(self) -> bool:
        """Whether this call was answered by a row already held."""
        return not self.appended

    @property
    def key(self) -> str:
        """The identity this result is about — feature 316's key."""
        return self.placement.key

    def __iter__(self):
        """Unpack as ``placement, appended`` — the order feature 317 says it in.

        The sentence puts the prior *result* first and the second placement
        second, and a caller reading the answer line by line writes
        ``placement, appended = store.place(...)``.  Provided so that reading
        is available without this value having to *be* a tuple, which would
        lose :attr:`replayed` and :attr:`key`.
        """
        return iter((self.placement, self.appended))


@dataclass(frozen=True)
class OrderRecord:
    """One placed order's terms, as :meth:`RouterOrderPlacementStore.record_order` wrote them.

    The record a fill's cost is measured against, read back by a *later*
    process that never held the plan: the rebalance's identity
    (``book_id``, ``rebalance_ts``), the leg (``symbol``, ``side``,
    ``type``, ``quantity``) and the ``reference_price`` the fill's signed
    slippage is a fraction of.

    ``reference_price`` is the price the venue was *actually* asked at — the
    limit price a passive leg was repriced to at the book, or the mark read
    in the same run for a ``MARKET`` leg — never a price re-derived at
    reconciliation time.  It is stored as text and read back as an exact
    :class:`~decimal.Decimal`, so the format the reconciliation arithmetic
    speaks and the format the column holds are one fact.

    ``quantity`` is the size the order was sent with, carried so a record
    is self-describing to an operator; the reconciliation prices fills from
    the venue's own ``executedQty`` (the part of the order that actually
    traded) rather than from this figure, which is the order's ask.
    """

    client_order_id: str
    book_id: str
    rebalance_ts: datetime
    symbol: str
    side: str
    type: str
    quantity: Decimal
    reference_price: Decimal
    placed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "client_order_id",
            normalize_client_order_id(self.client_order_id),
        )
        object.__setattr__(self, "book_id", _require_book_id(self.book_id))
        object.__setattr__(
            self, "rebalance_ts", _require_aware(self.rebalance_ts, "rebalance_ts")
        )
        object.__setattr__(self, "symbol", _require_symbol(self.symbol))
        object.__setattr__(self, "side", _require_side(self.side))
        object.__setattr__(self, "type", _require_type(self.type))
        object.__setattr__(
            self, "quantity", _require_positive(self.quantity, "quantity")
        )
        object.__setattr__(
            self,
            "reference_price",
            _require_positive(self.reference_price, "reference_price"),
        )
        object.__setattr__(
            self, "placed_at", _require_aware(self.placed_at, "placed_at")
        )

    @property
    def key(self) -> str:
        """The record's identity — feature 316's key, spelled out."""
        return self.client_order_id

    def row(self) -> dict[str, Any]:
        """The record as a store-shaped mapping — the column names, verbatim."""
        return {
            "client_order_id": self.client_order_id,
            "book_id": self.book_id,
            "rebalance_ts": _isoformat_utc(self.rebalance_ts),
            "symbol": self.symbol,
            "side": self.side,
            "type": self.type,
            "quantity": _decimal_text(self.quantity),
            "reference_price": _decimal_text(self.reference_price),
            "placed_at": _isoformat_utc(self.placed_at),
        }


class RouterOrderPlacementStore:
    """Reads and appends the router's placed orders — feature 317's store.

    Bound to a database URL at construction; construction performs no I/O, so
    composing a deployment never touches the database and a store costs
    nothing until an order is placed.  Each operation opens its own
    connection (creating the schema idempotently if absent), the discipline
    every store in this workspace follows — which is what makes the record
    reachable from the process that *reclaims* a router's work rather than
    only from the one that placed the order.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RouterStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RouterOrderPlacementStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, and composes no
        placement store at all, the stance this member's exchangeInfo store,
        its submission-health store and its limiter take.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and writes."""
        return self._database_url

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    # -- Feature 317's verb ---------------------------------------------------

    def place(
        self,
        order: Any,
        place: Any,
        *,
        now: datetime | None = None,
    ) -> PlacementResult:
        """Feature 317's verb: place ``order``, or return its prior result.

        app_spec.xml, "Order Routing & Venue Filters", feature 317: *System
        returns the prior result for a duplicate client order identifier
        rather than placing a second order.*  This is that sentence as one
        call, and the *rather than* is structural rather than advisory: this
        store holds the callable and decides whether to call it, so there is
        no way for a caller to place a duplicate by forgetting to look first.

        ``order`` is a :class:`PlacementOrder` — feature 316's key and the
        leg.  ``place`` is the placement itself: a zero-argument callable
        that sends the order to the venue, the same shape
        :func:`router.retry.retry_rate_limited` takes its request in, so the
        caller composes the venue call and this store owns the decision.  Its
        return value is ignored, and deliberately: **returning is the
        venue's acceptance**.  A venue *refusal* is stated by raising, which
        is the caller's contract because the caller is the only one that
        knows the venue's refusal vocabulary — and it is also what makes the
        refusal record nothing (see below).

        ``now`` is when the order was written down, and defaults to this
        instant.  Unlike feature 316's ``rebalance_ts`` — and unlike feature
        309's own required keyword, which is required for exactly that reason
        — this moment is not part of any identity: the key was hashed from
        the *rebalance's* instant, and this is merely when this store wrote
        the row.  A caller holding the venue's own timestamp should pass it;
        a caller with nothing to say gets the honest one, and no retry can
        change a key by landing under a different clock reading.

        **What happens, in the order it must happen.**  The ask is settled
        and one connection is opened with one transaction begun.  The claim
        is inserted *iff* the key has no row.  A key that already had a row
        is read and answered immediately — ``appended`` is ``False``, the
        callable is never invoked, and that is the sentence.  A key with no
        row has just been claimed by *this* call, and the callable runs from
        inside that same transaction.  The row is then read back and
        returned.

        **A callable that raises rolls the claim back.**  That is not a
        detail of the implementation but the feature's other half: a venue
        rejection placed nothing, so a row recording it would make the next
        attempt for that order be answered *"already placed"* — permanently,
        on the strength of one transient refusal.  So the refusal propagates
        untouched, nothing is written, and the order path keeps the retry it
        is entitled to make; recording how submissions are going is feature
        320's table, and a caller that wants the refusal written down records
        it there, from its own ``except``.

        **And a concurrent duplicate cannot race the venue.**  The second
        router blocks on the database's write lock until this transaction
        resolves, then reads the committed row and is answered from it
        without a second send — the venue is spoken to once per key however
        many processes arrive at it at once.  See the module docstring for
        both halves of that argument.

        Returns a :class:`PlacementResult` — the record that stands beside
        whether *this* call placed it.  On a duplicate the placement is
        returned **untouched** and compares equal to the value the first call
        returned: the symbol, the outcome and the instant the first write
        produced, not the spellings or the clock of the ask that replayed it,
        because this table is append-only and a placement is never restated —
        the rule :meth:`ledger.store.TrialLedger.debit` states for its own
        retry.  The result unpacks as ``placement, appended``.

        Refuses :class:`~router.errors.RouterSubmissionResultError` — eagerly,
        before the store is read, so a malformed ask can never be answered
        *"already placed"* — for a ``place`` that is not callable, for an
        ``order`` that is not a :class:`PlacementOrder`, and for a ``now``
        that is naive or not a moment.  Fails with
        :class:`~router.errors.RouterStoreError` when the configured store
        could not take the row: an order the router placed and did not write
        down is exactly the gap this feature closes.
        """
        if not isinstance(order, PlacementOrder):
            raise RouterSubmissionResultError(
                f"{SUBMISSION_RESULT_CODE}: an order to place is a "
                f"PlacementOrder, got {order!r} ({type(order).__name__}); the "
                "duplicate test is a comparison over feature 316's key, so an "
                "ask this store cannot name by a key is one it cannot answer "
                "from a prior result (feature 317)"
            )
        performed = _require_callable(place)
        moment = _placement_moment(now)
        key = order.key
        # The transaction is run by hand rather than through ``with
        # connection`` because the callable sits *inside* it and its
        # exceptions must not pass through a handler this method owns: a
        # venue rejection stated as a ``ConnectionError`` is an ``OSError``,
        # and so is a sqlite failure, so a single ``except OSError`` around
        # both would report the venue's dead socket as a failing database
        # *and* record the refusal.  Each region below therefore catches
        # exactly its own fault.
        connection = self._connect()
        try:
            try:
                cursor = connection.execute(
                    _INSERT_SQL,
                    (
                        key,
                        order.symbol,
                        ORDER_SUBMISSION_ACCEPTED,
                        _isoformat_utc(moment),
                        key,
                    ),
                )
            except sqlite3.Error as exc:
                connection.rollback()
                raise RouterStoreError(
                    f"could not record the placement of order {key} for "
                    f"{order.symbol!r}: {exc}"
                ) from exc
            # Read off the cursor before anything else can move it: this one
            # bit is the whole difference between a placement and a
            # duplicate, and the claim below is what decides it.
            appended = cursor.rowcount == 1
            if appended:
                # This call claimed the key, so the venue has not been asked
                # yet -- this is the only path that asks it, and the call is
                # inside the transaction on purpose.  A raise from here rolls
                # the claim back and reaches the caller as itself; see the
                # module docstring on why a refusal must leave no row.
                try:
                    performed()
                except BaseException:
                    connection.rollback()
                    raise
            try:
                row = connection.execute(_READ_SQL, (key,)).fetchone()
            except sqlite3.Error as exc:
                connection.rollback()
                raise RouterStoreError(
                    f"could not read back the placement of order {key} for "
                    f"{order.symbol!r}: {exc}"
                ) from exc
            # The read succeeded, so the row can be handed back whatever the
            # commit does next: the claim is already written and a commit
            # failure is not a failure of the record, so it is not allowed to
            # turn a placement that happened into a raise -- which would make
            # the order path retry an order the venue has already accepted.
            try:
                connection.commit()
            except sqlite3.Error as exc:  # pragma: no cover - needs a broken disk
                connection.rollback()
                raise RouterStoreError(
                    f"the placement of order {key} for {order.symbol!r} was "
                    f"read back and could not be committed: {exc}; the row "
                    "may or may not have reached the file, so an operator "
                    "must look before this key is asked again (feature 317)"
                ) from exc
        finally:
            connection.close()
        if row is None:  # pragma: no cover - claimed or read on one connection
            raise RouterStoreError(
                f"the placement of order {key} for {order.symbol!r} was "
                "claimed and could not be read back in the transaction that "
                "claimed it; the row is the only evidence this feature "
                "produces, so a write that cannot be read is not one this "
                "store can report (feature 317)"
            )
        return PlacementResult(appended=appended, placement=self._from_row(row))

    # -- Reading ------------------------------------------------------------

    def prior_result(self, client_order_id: Any) -> OrderPlacement | None:
        """The placement recorded under ``client_order_id``, or ``None``.

        The read a caller takes when it holds a key and wants the record
        without attempting anything — *has this order already been placed,
        and how did the venue answer?*  ``None`` is the honest answer for a
        key this table has never recorded: deliberately not a default or an
        empty placement, since an order that was never placed is a different
        fact from one that was, and the whole point of the feature is that
        the second is evidence and the first is a gap.

        The key is validated here rather than only inside
        :class:`PlacementOrder`, so a malformed ask is refused as the ask's
        own fault whether or not a row exists to read — and in feature 316's
        own terms, because a value that is not 64 hex characters names no
        order this system derived.
        """
        key = normalize_client_order_id(client_order_id)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(_READ_SQL, (key,)).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the placement recorded for order {key}: {exc}"
            ) from exc
        if row is None:
            return None
        return self._from_row(row)

    def _from_row(self, row: tuple) -> OrderPlacement:
        """Rebuild one stored row, refusing a value no placement can be.

        The refusal is the point, and it is the one feature 320's own row
        reader makes: SQLite columns are dynamically typed and this table is
        writable by any tool, so a raw ``INSERT`` can land an outcome this
        module never writes or a moment no parser accepts.  An unrecognised
        outcome is refused rather than quietly counted, because the value
        layer's reading of it — *was this order placed?* — is the question a
        duplicate is decided by, and a row that cannot answer it must not be
        handed out as though it had.

        The refusal names the key, so an operator can find the offending row
        without a second query — the same reason feature 320's reader names
        the process and the moment of the row it refused.
        """
        client_order_id, symbol, outcome, placed_at_raw = row
        try:
            moment = datetime.fromisoformat(placed_at_raw)
        except (TypeError, ValueError) as exc:
            raise RouterSubmissionResultError(
                f"{SUBMISSION_RESULT_CODE}: the placement filed under order "
                f"{client_order_id!r} carries {placed_at_raw!r}, which is not "
                "an ISO 8601 moment this store can report a placement at "
                "(feature 317)"
            ) from exc
        try:
            return OrderPlacement(
                client_order_id=client_order_id,
                symbol=symbol,
                outcome=outcome,
                placed_at=moment,
            )
        except RouterSubmissionResultError as refusal:
            # The value layer validates the row and cannot know which one it
            # saw; this re-raise is what makes the refusal *findable*, so the
            # operator gets the row to repair rather than a complaint about a
            # value with no address.
            raise RouterSubmissionResultError(
                f"{refusal} — the row this came from is the placement filed "
                f"under order {client_order_id!r} at {placed_at_raw!r} "
                "(feature 317)"
            ) from refusal

    # -- The placement's terms: what a fill is measured against ---------------

    def record_order(
        self,
        *,
        client_order_id: Any,
        book_id: Any,
        rebalance_ts: Any,
        symbol: Any,
        side: Any,
        order_type: Any,
        quantity: Any,
        reference_price: Any,
        now: datetime | None = None,
    ) -> OrderRecord:
        """Record one placed order's terms, so a later reconciliation can price it.

        The write that closes the gap the reconciliation defect names: a
        hash names an order but carries none of its terms, and the only plan
        a later run can rebuild is re-sized against *today's* positions and
        marks — so the side, the type, the size and, above all, the reference
        price a fill's slippage is a fraction of are written down at
        placement time and read back by :meth:`records_for`.

        ``reference_price`` is the price the venue was actually asked at: a
        passive leg's limit price **after repricing at the book**, or a
        ``MARKET`` leg's symbol mark read in the same run.  A caller records
        the order it *sent*, never the plan's pre-repricing price — a fill is
        measured against what it was placed at, and a plan price the venue
        never saw would measure it against a price nobody offered.

        The write is idempotent by the key, exactly as :meth:`place` is: a
        re-send whose order already has a row changes nothing, because an
        order placed once has one set of terms and a rewritable reference
        would let a replay move the figure a fill is judged against.  The
        row that stands is returned.

        Refuses :class:`~router.errors.RouterSubmissionResultError` eagerly,
        before the store is touched, for any malformed term (a missing book,
        a naive instant, a side or type outside the venue's vocabulary, a
        non-positive size or price).  Fails with
        :class:`~router.errors.RouterStoreError` when the store could not
        take the row: an order placed and not recorded is exactly the gap
        that would make its fill-cost reconciliation wrong again.
        """
        # The ask is settled whole before a connection is opened, the
        # ordering every act in this workspace states: a malformed record is
        # refused without touching a database.
        instant = _require_moment(rebalance_ts, "rebalance_ts")
        moment = _placement_moment(now)
        record = OrderRecord(
            client_order_id=normalize_client_order_id(client_order_id),
            book_id=_require_book_id(book_id),
            rebalance_ts=instant,
            symbol=_require_symbol(symbol),
            side=_require_side(side),
            type=_require_type(order_type),
            quantity=_require_positive(quantity, "quantity"),
            reference_price=_require_positive(
                reference_price, "reference_price"
            ),
            placed_at=moment,
        )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _RECORD_INSERT_SQL,
                    (
                        record.client_order_id,
                        record.book_id,
                        _isoformat_utc(record.rebalance_ts),
                        record.symbol,
                        record.side,
                        record.type,
                        _decimal_text(record.quantity),
                        _decimal_text(record.reference_price),
                        _isoformat_utc(record.placed_at),
                        record.client_order_id,
                    ),
                )
                row = connection.execute(
                    _RECORD_READ_SQL,
                    (record.book_id, _isoformat_utc(record.rebalance_ts)),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not record the placement terms for order "
                f"{record.client_order_id} of book {record.book_id!r} at "
                f"{_isoformat_utc(record.rebalance_ts)}: {exc}"
            ) from exc
        # The standing row for this key — the one just claimed, or the one a
        # prior placement wrote — is the answer, so a re-issue reports the
        # terms that actually stand rather than the ones it offered.
        for stored in row:
            if stored[0] == record.client_order_id:
                return self._record_from_row(stored)
        # The insert claimed the key but its own row did not read back inside
        # the transaction that wrote it: a write that cannot be read is not
        # one this store can report.
        raise RouterStoreError(
            f"the placement terms for order {record.client_order_id} were "
            "written and could not be read back in the transaction that wrote "
            "them; a record that cannot be read is not one this store can "
            "report (feature 317)"
        )

    def records_for(
        self, book_id: Any, rebalance_ts: Any
    ) -> tuple[OrderRecord, ...]:
        """Every term this store recorded for one rebalance, in the order they landed.

        The read the fill-cost reconciliation takes, addressed by the
        rebalance's own identity — ``(book_id, rebalance_ts)``, the pair
        feature 316 folds and §13.2 names — so a *later* process reads back
        the orders a finished rebalance placed without holding the plan that
        built them.  An empty tuple is the honest answer for a rebalance this
        table has never recorded: no orders recorded is a different fact from
        orders recorded with no fill, and the reconciliation tells them apart
        by first asking whether any row exists at all.

        Both terms are validated here, so a malformed ask is refused as the
        ask's own fault rather than answered with an empty read.
        """
        wanted_book = _require_book_id(book_id)
        instant = _require_moment(rebalance_ts, "rebalance_ts")
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    _RECORD_READ_SQL, (wanted_book, _isoformat_utc(instant))
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RouterStoreError(
                f"could not read the placement terms recorded for book "
                f"{wanted_book!r} at {_isoformat_utc(instant)}: {exc}"
            ) from exc
        return tuple(self._record_from_row(row) for row in rows)

    def _record_from_row(self, row: tuple) -> OrderRecord:
        """Rebuild one stored term row, refusing a value no record can be.

        The same stance :meth:`_from_row` takes for feature 317's table: this
        table is writable by any tool and SQLite columns are dynamically
        typed, so a raw ``INSERT`` can land a side, a type or a decimal this
        module never writes.  The value layer
        (:class:`OrderRecord`) validates every field, and the refusal is
        re-raised naming the row's key so an operator can find it.
        """
        (
            client_order_id,
            book_id,
            rebalance_ts_raw,
            symbol,
            side,
            order_type,
            quantity_raw,
            reference_raw,
            placed_at_raw,
        ) = row
        try:
            instant = datetime.fromisoformat(rebalance_ts_raw)
            placed = datetime.fromisoformat(placed_at_raw)
        except (TypeError, ValueError) as exc:
            raise RouterSubmissionResultError(
                f"{SUBMISSION_RESULT_CODE}: the placement terms filed under "
                f"order {client_order_id!r} carry a moment this store cannot "
                f"read ({rebalance_ts_raw!r}, {placed_at_raw!r}); the row is "
                "repairable and its key names it (feature 317)"
            ) from exc
        try:
            return OrderRecord(
                client_order_id=client_order_id,
                book_id=book_id,
                rebalance_ts=instant,
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity_raw,
                reference_price=reference_raw,
                placed_at=placed,
            )
        except RouterSubmissionResultError as refusal:
            raise RouterSubmissionResultError(
                f"{refusal} — the row this came from is the placement terms "
                f"filed under order {client_order_id!r} (feature 317)"
            ) from refusal
