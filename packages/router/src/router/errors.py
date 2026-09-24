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

Every message names the offending value and the contract it broke, because
these are operational signals for a pipeline the order path trusts for its
step size and tick size, not debugging aids.
"""

from __future__ import annotations

__all__ = [
    "RouterError",
    "RouterFilterError",
    "RouterStoreError",
]


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
