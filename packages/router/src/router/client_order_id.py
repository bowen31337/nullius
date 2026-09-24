"""The client order identifier — feature 316's idempotent resubmission key.

app_spec.xml, "Order Routing & Venue Filters", feature 316: *System derives
a client order identifier by hashing book id, rebalance timestamp and
symbol, which returns an idempotent resubmission key.*
``docs/nullius-tech-architecture.md`` §13.2 states the whole formula as one
line of the execution engine's — *"Idempotent order submission keyed by
``client_order_id = hash(book_id, rebalance_ts, symbol)``."* — and this
module is that key's one derivation.

**Why the key exists, and why it is *derived* rather than generated.**  The
order path will send the same order more than once, legitimately: a
reclaimed spot instance re-runs its rebalance step, a router restart
re-sends what the last process was sending, feature 319's backoff re-sends
a request the venue's weight budget refused.  A *generated* name — a
counter, a uuid — would differ between the process that first sent the
order and the process retrying it, and the venue would book two positions
for one rebalance.  A name two processes can agree on without speaking to
each other has to be a function of the order itself, and §13.2 names the
three facts that function reads.  That is what makes the key the
resubmission answer's foundation: feature 317's *"returns the prior result
for a duplicate client order identifier rather than placing a second
order"* is a statement about this module's output, and feature 320's
submission-health rows carry the same key (their ``client_order_id``
column, "for joining only") so an operator can walk a rejection rate back
to the order that earned it.

**Each term names one axis** on which otherwise-identical orders are not
the same order:

* ``book_id`` — *whose* rebalance.  The deployment runs more than one book
  (§C9), and two books holding the same symbol at the same instant are two
  orders.  It is the deployment's own name, and the book member's
  rebalance table (feature 309) is keyed on the same one — its docstring
  keys the pair ``(book_id, rebalance_ts)`` precisely so the order path
  "hashes into its ``client_order_id``" from the record's own identity, and
  hands this feature the term by name.
* ``rebalance_ts`` — *which* rebalance of that book.  A book rebalanced
  twice to the same symbol places two orders, and the instant is what
  tells them apart.  It is the rebalance's own instant, never the write's
  or the send's: the book member states the law one step upstream ("a
  default of *now* would make the row's identity the moment somebody
  happened to call, so a retry would land under a different identity —
  which is the one property idempotence rests on"), and the same law holds
  here, which is why all three arguments are **required keywords with no
  default**.
* ``symbol`` — *which leg* of that rebalance.  A rebalance is a *set* of
  weights (feature 309 persists it as one JSON object because coverage is
  a property of the set), and each symbol's order is one leg with its own
  key — the venue quotes, filters and fills per symbol, so the leg is the
  unit the venue can duplicate.

**Idempotence is a canonicalisation law before it is a hash.**  sha256 is
deterministic for free; what has to be *made* deterministic is the bytes
each term contributes.  Two spellings of one rebalance instant must fold
identically — ``12:00+02:00`` and ``10:00+00:00`` are one instant and one
order — so the instant is normalised to UTC and folded through the one ISO
8601 spelling :func:`_instant_term` writes (the same canonical form the
book member's rebalance table stores, for the same reason: what makes the
pair an identity rather than a pair of spellings).  The two names are
stripped and otherwise left **verbatim**: a case-folded or re-spelled
symbol would silently rename what the venue lists — the ingest member
keeps venue spellings verbatim and the exchangeInfo store keys its filters
by them — and a re-spelled ``book_id`` would rename the deployment's own
configuration.  A trailing newline in a pasted config copy is stripped
rather than honoured, the near-miss rule every name in this member holds
itself to; a whole-cloth blank is refused, because a book or a leg that
states nothing names no order a key could stand for.  A naive
``rebalance_ts`` is refused for the reason the whole workspace refuses
one: it names an offset nobody agreed on, and two books' rebalances would
fold into one key or none.

**The byte-level spelling is the format.**  A hash over under-specified
bytes is a hash over nothing, so the preimage is pinned exactly: the three
canonical terms, as one JSON array, tightest separators, UTF-8, hashed
once with sha256.  The framing is a separability guarantee, not
punctuation — the same argument the evaluator (§6's two terms) and
snapshot (§4.2's three) members make for their newline joins, taken one
step further because two of this formula's terms are caller-held *names*:
a book id may legitimately carry a character those modules' terms are
refused for carrying, so rather than join on a separator a term could
contain, the terms are folded through canonical JSON, whose string
encoding is injective — ``json.dumps`` escapes control characters rather
than emitting them, so two triples that differ in any term always fold to
different preimages, whatever the deployment named its book.  One fold,
one spelling, one home (:func:`_fold`), so a caller recomputing an
identity and this module deriving it cannot drift.

**The full 64 hex characters, never a truncation.**  A sha256 hexdigest is
the workspace's own identity convention — ``evaluator_hash`` is a
``CHAR(64)`` column, the snapshot and code hashes are full digests, and
feature 310's version envelope carries ``source_sha256`` whole.  A venue's
own client-order field may cap what it accepts, but that cap is a venue
constant this module refuses to hardcode: exchangeInfo — the one surface
feature 310 persists — does not publish it, and feature 311's sentence,
*rejects any hardcoded venue constant in the order path*, is the law of
this category.  The key returned here is the *system's* key — what feature
317 dedupes on and feature 320 joins on — and the full digest is the
strongest such key there is; shortening it would spend collision
resistance to obey a number nobody in this workspace owns.

**The terms ride beside the key.**  A hash is one-way: a row holding only
the key can say *that* two submissions differed, never *how*.  So
:class:`ClientOrderId` carries the triple it folded next to the digest it
folded them to — the shape :class:`~evaluator.EvaluatorIdentity` states
for itself — so a collision a caller ever has to act on can name the book,
the rebalance and the symbol that produced it, and an operator reading a
health row can read the order off the key without guessing.  The value is
frozen, and a stated digest that disagrees with its own terms is refused:
an identity whose hash contradicts its inputs would persist a row that
lies.

**No table, no component, no clock, no I/O.**  The derivation is a pure
function of the three terms — the same triple yields the same key in any
process, on any machine, on any day, which is the whole point — so there
is nothing to persist and nothing to compose: feature 317's store will key
its rows on this value, and no ``@register`` is added (the member still
registers exactly one component, feature 310's exchangeInfo store).  No
clock is read anywhere above, which is not a convenience but the feature:
a key that depended on when it was computed would be a second spelling of
the generated name the key exists to replace.  Stdlib only, and
import-cheap — ``hashlib``, ``json`` and the datetime machinery — so the
factory's scan pays nothing for the identity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .errors import CLIENT_ORDER_ID_CODE, RouterClientOrderIdError

__all__ = [
    "CLIENT_ORDER_ID_LENGTH",
    "ClientOrderId",
    "client_order_digest",
    "derive_client_order_id",
    "normalize_client_order_id",
]

#: The length of a derived client order identifier: a sha256 hex digest.
#: The full digest, deliberately never truncated — see the module docstring
#: for why a venue's own field cap is not this module's to hardcode — and
#: the same 64-hex spelling ``evaluator_hash``, the snapshot hashes and
#: feature 310's ``source_sha256`` keep across the workspace, so a reader
#: who has met one identity column has met this one.
CLIENT_ORDER_ID_LENGTH = 64

#: The alphabet of a derived identifier: lowercase hex, the one spelling
#: :meth:`hashlib.Hash.hexdigest` emits.  Declared once so
#: :func:`normalize_client_order_id` and the refusal messages cannot
#: disagree about what a derived key is made of.
_HEX = frozenset("0123456789abcdef")


def _validated_book_id(value: Any) -> str:
    """Return ``value`` as a book identity, or refuse what cannot be one.

    Non-empty text, stripped — the near-miss a trailing newline or an
    indented copy of the deployment's configuration would otherwise fold
    into a *second* key for every order one book placed, the same rule
    :func:`book._rebalance._validated_book_id` holds the same term to one
    step upstream.  Nothing else is normalised, for the reason that module
    gives: a book's identity is its deployment's configuration, and a
    derivation that case-folded or re-spelled one would be silently
    renaming the book against a table whose key says otherwise.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: book_id must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); the key names whose "
            "rebalance this order is, and a name that states nothing "
            "derives a key that names no book (feature 316)"
        )
    return value.strip()


def _validated_rebalance_ts(value: Any) -> datetime:
    """Return ``value`` as the rebalance's instant, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* the rebalance was
    for, and a key folded from one could collide two books' rebalances or
    split one book's retry into two orders — the same discipline
    :func:`router.submission_health._require_aware` holds its own moments
    to.  The instant is the rebalance's, never the call's; that law is
    restated in the module docstring and enforced by the required keyword.
    """
    if not isinstance(value, datetime):
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: rebalance_ts must be a datetime, not "
            f"{type(value).__name__}; the key names which rebalance of the "
            "book this order is, and the rebalance is an instant (feature "
            "316)"
        )
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: rebalance_ts must be timezone-aware, "
            f"got {value!r}; the instant is folded in UTC so that one "
            "rebalance has one key, and a naive timestamp names an offset "
            "nobody agreed on (feature 316)"
        )
    return value


def _validated_symbol(value: Any) -> str:
    """Return ``value`` as a venue symbol, or refuse what cannot be one.

    Non-empty text, stripped, otherwise verbatim: the venue's own spelling
    is the key the exchangeInfo filters are filed under
    (:meth:`~router.store.RouterExchangeInfoStore.filters_for`), and a
    derivation that upper-cased or re-spelled a symbol would derive a key
    for an instrument the order path could not then look a filter up for.
    """
    if not isinstance(value, str) or not value.strip():
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: symbol must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); the key names which leg "
            "of the rebalance this order is, and the venue fills per "
            "symbol — a leg that states nothing names no order (feature "
            "316)"
        )
    return value.strip()


def _instant_term(moment: datetime) -> str:
    """``moment`` in the one canonical form the formula folds.

    UTC, ISO 8601, the same spelling :func:`book._rebalance._isoformat_utc`
    persists one step upstream — deliberately the same form, because the
    rebalance table's key and this formula's term are one identity, and two
    spellings of it would be two identities.  Deterministic per instant:
    ``12:00+02:00`` and ``10:00+00:00`` normalise to the same string, so
    one rebalance folds to one term whatever tzinfo the caller held.
    """
    return moment.astimezone(UTC).isoformat()


def _fold(book_id: str, rebalance_ts: str, symbol: str) -> str:
    """Hash the three framed terms once, as UTF-8.

    The single place the formula's byte-level spelling lives, so the
    digest-computing path, the value-verifying path and a caller
    recomputing an identity cannot drift apart — a verification that
    reassembled the preimage its own way would recompute a different value
    from the same terms and report a match as a mismatch.  The terms are
    folded as one canonical JSON array (see the module docstring for why a
    separator join would put a restriction on the deployment's book names
    that this feature has no reason to make).
    """
    payload = json.dumps(
        (book_id, rebalance_ts, symbol),
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def client_order_digest(
    *,
    book_id: Any,
    rebalance_ts: Any,
    symbol: Any,
) -> str:
    """Compute §13.2's ``client_order_id`` over the three terms.

    Each argument is a required keyword with no default — see the module
    docstring for why an instant that defaulted to *now* would break the
    one property the feature exists for.  The terms are canonicalised and
    folded exactly as :class:`ClientOrderId` folds them, and the answer is
    the same value that class carries: 64 lowercase hex characters.

    Refuses :class:`~router.errors.RouterClientOrderIdError` for a
    ``book_id`` or ``symbol`` that is not non-empty text and a
    ``rebalance_ts`` that is not a timezone-aware datetime.
    """
    return _fold(
        _validated_book_id(book_id),
        _instant_term(_validated_rebalance_ts(rebalance_ts)),
        _validated_symbol(symbol),
    )


def derive_client_order_id(
    *,
    book_id: Any,
    rebalance_ts: Any,
    symbol: Any,
) -> ClientOrderId:
    """Derive the client order identifier — feature 316's verb.

    The sentence's own shape: *System derives a client order identifier by
    hashing book id, rebalance timestamp and symbol.*  Returns the frozen
    :class:`ClientOrderId` carrying the triple it folded beside the key it
    folded them to, so a caller that must act on a collision — or join a
    submission-health row back to its order — holds the facts the hash
    compressed away.

    Deterministic by construction: the same three terms return the same
    key in any process, on any machine, on any day, with no clock read and
    no state consulted.  That is the "idempotent resubmission key" of the
    sentence, and it is the whole contract — a caller that needs the bare
    string asks :func:`client_order_digest`, and the two answers agree
    because they fold through the one :func:`_fold`.
    """
    return ClientOrderId(
        book_id=book_id,
        rebalance_ts=rebalance_ts,
        symbol=symbol,
    )


def normalize_client_order_id(value: Any) -> str:
    """Validate a client order identifier, returning it in canonical hex.

    Accepts 64 hexadecimal characters in either case — a key pasted from a
    log line, a database row or a report is commonly uppercase, means the
    same value, and is normalized away rather than refused — matching the
    treatment :func:`evaluator.normalize_evaluator_hash` gives the sibling
    identity column.  Rejects a ``sha256:``-prefixed digest (that spelling
    belongs to an image reference, and accepting it here would let a caller
    compare a digest against a key), and anything of the wrong length or
    alphabet.  This is the seam feature 317's store will read a presented
    key through, so a value that is *almost* an order's name is refused
    here rather than silently missing every row it should have matched.
    """
    if not isinstance(value, str):
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: a client order identifier is "
            f"{CLIENT_ORDER_ID_LENGTH} hex characters, got "
            f"{type(value).__name__}; a resubmission answer keyed on a "
            "value that is not text names no order (feature 316)"
        )
    text = value.strip()
    if ":" in text:
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: the identifier {value!r} carries an "
            "algorithm prefix; a sha256:<hex> spelling is an *image "
            "reference*, not the key hashed over the book, the rebalance "
            "and the symbol — pass the 64 hex characters themselves "
            "(feature 316)"
        )
    if len(text) != CLIENT_ORDER_ID_LENGTH or not set(text.lower()) <= _HEX:
        raise RouterClientOrderIdError(
            f"{CLIENT_ORDER_ID_CODE}: the identifier {value!r} is not "
            f"{CLIENT_ORDER_ID_LENGTH} hex characters; a short value, a "
            "truncated key or a non-hex token names no order this system "
            "derived, and a resubmission answer keyed on it would miss "
            "the very row it exists to return (feature 316)"
        )
    return text.lower()


@dataclass(frozen=True)
class ClientOrderId:
    """One order's own name: the three terms and the key they fold to.

    The value feature 316's sentence returns — *an idempotent resubmission
    key* — together with the inputs it was computed over, because the hash
    is one-way and a caller that ever has to act on the identity (feature
    317's duplicate answer, feature 320's health join, an operator's grep)
    needs the *which book, which rebalance, which symbol* the key names.
    The same shape :class:`~evaluator.EvaluatorIdentity` takes, for the
    reason its docstring gives: a row holding only the hash can say *that*
    two submissions differed but never *how*.

    Build with :func:`derive_client_order_id`, or construct directly —
    ``__post_init__`` applies the same canonicalisation the derivation
    applies, so both paths answer one value for one triple:

    * ``book_id`` and ``symbol`` are stripped and otherwise kept verbatim;
    * ``rebalance_ts`` is normalised to UTC, so two values for one instant
      are equal as values and not merely as keys;
    * ``client_order_id`` — the 64-hex sha256 over the canonical terms —
      is computed when omitted, and when stated, is normalized and checked
      against the terms it rides beside: a stated key that disagrees with
      its own inputs is refused, because that value would persist as a row
      that lies about which order it names.

    Frozen, and hashable through the same terms: the value can stand as
    its own key in a dedupe map, and :func:`str` answers the digest —
    ``f"{key}"`` is the 64 hex characters, the spelling a log line, a
    venue field payload or feature 317's row carries.
    """

    book_id: str
    rebalance_ts: datetime
    symbol: str
    client_order_id: str = ""

    def __post_init__(self) -> None:
        # Normalize rather than trust: a record built by hand in a test or
        # reconstructed from a row gets the same canonicalisation the
        # formula applies, and the stated digest — if any — is verified
        # against the terms it travels with before the value exists.
        book = _validated_book_id(self.book_id)
        moment = _validated_rebalance_ts(self.rebalance_ts)
        symbol = _validated_symbol(self.symbol)
        expected = _fold(book, _instant_term(moment), symbol)
        object.__setattr__(self, "book_id", book)
        object.__setattr__(self, "rebalance_ts", moment.astimezone(UTC))
        object.__setattr__(self, "symbol", symbol)
        if not self.client_order_id:
            object.__setattr__(self, "client_order_id", expected)
            return
        normalized = normalize_client_order_id(self.client_order_id)
        if normalized != expected:
            raise RouterClientOrderIdError(
                f"{CLIENT_ORDER_ID_CODE}: the stated identifier "
                f"{normalized!r} does not match the value computed over "
                f"book {book!r}, rebalance {_instant_term(moment)} and "
                f"symbol {symbol!r} ({expected}); an identity whose key "
                "disagrees with its own terms would name an order it does "
                "not describe (feature 316)"
            )
        object.__setattr__(self, "client_order_id", normalized)

    def __str__(self) -> str:
        """The 64 hex characters — the value's own spelling is its key."""
        return self.client_order_id
