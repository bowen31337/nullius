"""The router plugin's error taxonomy.

One base class (:class:`RouterError`) so a caller — the order path built on
this member, an operator tool — can catch every failure of this package
with a single ``except``.  The subclasses split by *which contract* was
violated, not by which line of code failed:

* :class:`RouterFilterError` — the fetched-document contract.  Feature 310
  persists *the fetched exchangeInfo version*, and a payload that
  :mod:`nullius_ingest.exchange_info` will not parse as one (not JSON, no
  ``symbols`` list, a symbol with no filters, a duplicated symbol) is not a
  version at all.  Raised at the seam that receives the fetch, translated
  from :class:`nullius_ingest.exchange_info.ExchangeInfoParseError` rather
  than let through by name — a caller catching this package's one
  vocabulary must not have to also import the ingest member's own errors to
  catch a bad document (see the "error vocabulary at member seams"
  discipline this workspace follows elsewhere: a shared parser raising its
  own module's error type defeats the caller's ``except``).
* :class:`RouterStoreError` — the persisted-record contract.  Feature 310
  says the fetched version is *persisted*, so a store that was configured
  and then failed to take the row is an error rather than a shrug: the
  alternative is an exchangeInfo version that resolved but never landed,
  which is exactly the "hardcoded venue constant" state feature 311 exists
  to prevent downstream. A store that was never configured at all is not
  this error — see :mod:`router.store` for the stance that separates the
  two.
* :class:`RouterSubmissionHealthError` — feature 320's persisted-health
  contract, and a *sibling* of the three classes above rather than a child
  of any of them.  Its noun is the router's own liveness, not a fetched
  document (:class:`RouterFilterError`) and not a stored filter version
  (:class:`RouterStoreError`): a submission observation that cannot be
  recorded — because the identity it names states no process, the moment it
  names states no time, the window it is read against cannot be a window, or
  the row that came back states something a submission outcome cannot be —
  is none of those repairs, so a caller catching it must not be told it is.
  This is the same split :mod:`regime.errors` states for its own category
  (*"a caller catching them together would read the wrong repair"*), and the
  same vocabulary :mod:`regime.origins` inherits: a bad *address*
  (a ``DATABASE_URL`` this member cannot speak) stays
  :class:`RouterStoreError` in both features, because that fault and its
  repair — point the deployment at a database this store can open — are one
  fact the member already names once.

Every message names the offending value and the contract it broke, because
these are operational signals for a pipeline the order path trusts for its
step size and tick size, not debugging aids.
"""

from __future__ import annotations

__all__ = [
    "ORDER_SUBMISSION_UNHEALTHY_CODE",
    "RouterError",
    "RouterFilterError",
    "RouterStoreError",
    "RouterSubmissionHealthError",
]

#: The greppable one word every :class:`RouterSubmissionHealthError` message
#: opens with, following the ``pool_frozen`` (feature 270) /
#: ``illegal_theme`` (feature 241) / ``no_origin`` (feature 288) precedent:
#: an operator scanning a log for submission-health refusals greps one token
#: rather than a sentence.  It deliberately does not spell ``feed`` — the
#: whole point of feature 320 is that this health is not the feed's — and it
#: does not spell ``live``, which is feature 321's authority vocabulary and a
#: different refusal with a different repair.
ORDER_SUBMISSION_UNHEALTHY_CODE = "order_submission_unhealthy"


class RouterError(Exception):
    """Base class for every failure of the router package."""


class RouterFilterError(ValueError, RouterError):
    """A fetched payload is not a well-formed exchangeInfo document.

    Dual-inherited: a malformed fetch is a :class:`ValueError` the way the
    ingest member's own parse failures are, and it is also a
    :class:`RouterError`, so a caller catching this package's single
    vocabulary catches a bad document along with a failed persist.

    Raised for the document's own defects — not JSON, no ``symbols`` list, a
    symbol with no filters, a duplicated symbol, a filter with no type — and
    never for a store failure, which is :class:`RouterStoreError`.
    """


class RouterStoreError(RouterError):
    """The fetched exchangeInfo version could not be persisted or read back.

    Feature 310: *"System persists the fetched exchangeInfo version carrying
    lot size, notional, price filter, step size and tick size."*  This is
    the failure of that sentence's verb: the document parsed, and the
    version that records it did not land (or a persisted version could not
    be read back).  Raised rather than swallowed — a version that resolved
    but was never persisted is exactly the gap the feature closes.

    A store that is merely *absent* (no ``DATABASE_URL``, and no explicit
    URL passed) is not this error: this package treats "no relational store
    configured" as a supported state and refuses the operation with this
    error only at the moment a caller actually asks for one, naming the
    variable that would have named the store.
    """


class RouterSubmissionHealthError(RouterError):
    """The router's own submission health could not be recorded or read back.

    app_spec.xml, "Order Routing & Venue Filters", feature 320: *"System
    persists order submission health independently of feed health, running
    the router in its own process."*  This is the failure of that sentence's
    verb, and it is deliberately **not** a failure of the venue or of the
    order path: a submission observation the router's own process took and
    could not write down is a fact about the router's bookkeeping, not a bad
    fetch (:class:`RouterFilterError`) and not a filter version that failed
    to land (:class:`RouterStoreError`).  The noun is *the router's own
    liveness*, which is the one noun feature 320 adds.

    Raised for the ask (an identity that names no process, a moment that is
    naive, a window that cannot be a window), for the row (a stored outcome
    that is not one of the two a submission can have) and for the read (a
    window read out of a store this member cannot open).  A store that is
    merely *absent* is not this error, for the same reason it is not
    :class:`RouterStoreError`: no configured store is a supported deployment
    state, and the refusal belongs to the caller that demands an observation
    anyway.

    Every message opens with :data:`ORDER_SUBMISSION_UNHEALTHY_CODE` so an
    operator greps one token, and names the process and the moment it is
    about, because a health record that cannot be attributed to a process and
    an instant is not a health record — which is the whole subject of this
    feature.
    """
