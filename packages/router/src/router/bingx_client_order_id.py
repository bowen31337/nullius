"""BingX's clientOrderID — feature 316's identifier at the venue's own cap.

additions_spec_bingx_dry_run.xml, "BingX VST Dry Run", feature 3: *System
projects the 64-hex client order identifier from feature 316 onto BingX's
40-character clientOrderID as the identifier's first 40 lowercase hex
characters, returning the same projection for the same book_id,
rebalance_ts and symbol and a client_order_id refusal for any value that is
not a 64-hex identifier.*  This module is that sentence's one function, and
it is the *only* place in the workspace where an order's name is spelled
short.

**Why a projection has to exist at all.**  BingX's swap order endpoint
(POST /openApi/swap/v2/trade/order) accepts a caller-chosen
``clientOrderID`` of at most 40 characters, while the identifier feature
316 derives is 64 hex characters by construction — a whole sha256 digest,
kept whole deliberately.  :mod:`router.client_order_id` names the mismatch
and refuses to resolve it itself: *"a venue's own client-order field may
cap what it accepts, but that cap is a venue constant this module refuses
to hardcode"*, because feature 311's sentence — *rejects any hardcoded
venue constant in the order path* — makes the cap nobody's to hardcode but
the venue boundary's own.  So the cap lives here, as
:data:`BINGX_CLIENT_ORDER_ID_LENGTH`, in a module whose own name says
which venue it is for; the venue-neutral derivation never learns that BingX
exists, which is what keeps it free of the hardcoded constant.

**The system's key stays the whole digest.**  The 40 characters this
function returns are the *venue field's payload*, never the system's own
name for the order: feature 317's placement store keys its idempotency on
the full 64-hex identifier and feature 320's health rows join on the same
whole value, exactly as this addition's integration points state (*the
placement store's idempotency key stays the full 64-hex identifier*).  A
prefix is not reversible — two identifiers can share their first 40
characters — so nothing downstream may *join* on the projection: the
answer to *which order was this* is always the full identifier the
projection was taken from, and the caller that projected it still holds
it.

**Why the first 40, and why that is enough.**  The sentence pins the slice,
and a prefix of a hash is as uniform as the hash — any 40 of the 64
characters would discriminate as well — so the one spelling the spec names
is the one taken, and two implementations of this projection cannot
disagree.  What the venue side needs from the field is the property the
system side needs from the key: BingX treats ``clientOrderID`` as the
caller's idempotency name for the order, so a resubmission — a reclaimed
spot instance re-running its rebalance, a restarted router, feature 319's
backoff — must carry the same 40 characters the first send carried.  It
does, because feature 316 already answers one digest for one
``(book_id, rebalance_ts, symbol)`` triple in any process, and the first 40
characters of one digest are one prefix: *the same projection for the same
book_id, rebalance_ts and symbol* is inherited from the derivation, not
re-earned here.  Forty hex characters are 160 bits of a sha256 digest —
more discriminating power than one deployment's lifetime of orders will
ever ask a name to carry.

**The refusal is feature 316's own, read not re-implemented.**  The value
is read through :func:`router.client_order_id.normalize_client_order_id`
— the seam that already refuses it, for the reason :mod:`router.errors`
states of feature 317's store: *"a key that is not 64 hex characters is
refused in that class by feature 316's own validation, which this module
reads rather than re-implements"*.  So this module defines **no** error
class of its own: the fault the sentence names is the ``client_order_id``
fault, :class:`~router.errors.RouterClientOrderIdError` in that
vocabulary, raised by the validator that owns it — and a caller catching
the identifier's fault by name catches this projection's refusals too.  The
near-miss this projection especially must refuse is its own output: 40 hex
characters are not 64, and a projection fed back in would project a
*projection* — a value naming no order any process ever derived.  That the
validator's own message already refuses *a short value, a truncated key or
a non-hex token* is the marker that it was written for exactly this shape
of near-miss.

**What the function accepts.**  The addition's integration points state the
shape: *Feature 3's projection is a separate function over a
``ClientOrderId``* — the value feature 316's verb returns, whose ``str()``
is documented as the spelling a venue field payload carries.  A bare
64-hex identifier is accepted too — a key read back from feature 317's row
or pasted from a log line, upper-cased by a database's collation or not —
because the projection is a function of the *identifier*, not of the
object carrying it, and both spellings normalise to the one answer.
Anything else, text or not, meets the refusal above.

**No state, no clock, no network.**  A pure function of its argument, like
the derivation it reads: nothing to persist, no ``@register`` added (the
member still registers exactly one component), and — Stage 0's own law —
no import of ``socket``, ``ssl``, ``http.client``, ``urllib.request``,
``hmac`` or any HTTP client.  Nothing here signs, connects or reads a
credential, because nothing here sends.
"""

from __future__ import annotations

from typing import Any

from .client_order_id import ClientOrderId, normalize_client_order_id

__all__ = [
    "BINGX_CLIENT_ORDER_ID_LENGTH",
    "project_bingx_client_order_id",
]

#: The BingX swap order endpoint's own cap on its ``clientOrderID``
#: parameter: 40 characters.  A *venue* constant — the one thing
#: :mod:`router.client_order_id` names and refuses to hardcode, feature
#: 311's law — so it is declared here, in the BingX-specific module at the
#: BingX boundary, and nowhere else: the venue-neutral derivation stays
#: whole precisely because the cap was never its constant to carry.
BINGX_CLIENT_ORDER_ID_LENGTH = 40


def project_bingx_client_order_id(value: Any) -> str:
    """Project ``value`` onto BingX's ``clientOrderID``: its first 40 characters.

    The sentence's own shape — feature 316's 64-hex identifier folded to
    the venue's 40-character cap as its *first* 40 lowercase hex
    characters.  ``value`` is the
    :class:`~router.client_order_id.ClientOrderId` the derivation returns
    (its ``str()`` is the spelling a venue field payload carries) or a bare
    64-hex identifier read from a row or a log line; the answer is the same
    either way, because the projection is a function of the identifier
    rather than of the object carrying it.

    Deterministic by inheritance: the same ``(book_id, rebalance_ts,
    symbol)`` triple derives the same 64-hex identifier in any process
    (feature 316's own contract), and the first 40 characters of one
    identifier are one projection — which is the whole of what BingX
    treating ``clientOrderID`` as the caller's idempotency name needs: a
    resubmitted order carries the 40 characters the first send carried.

    Refuses :class:`~router.errors.RouterClientOrderIdError` — the
    ``client_order_id`` refusal, raised by
    :func:`router.client_order_id.normalize_client_order_id` rather than
    re-implemented here — for any value that is not a 64-hex identifier:
    this function's own 40-character output included, which names no order
    any process ever derived.
    """
    identifier = str(value) if isinstance(value, ClientOrderId) else value
    return normalize_client_order_id(identifier)[:BINGX_CLIENT_ORDER_ID_LENGTH]
