"""``router`` — Order Routing & Venue Filters: the fetched exchangeInfo version.

app_spec.xml, "Order Routing & Venue Filters", feature 310: *System persists
the fetched exchangeInfo version carrying lot size, notional, price filter,
step size and tick size.*  ``docs/alpha-engine-prd.md`` C9 fixes why: *"Read
``LOT_SIZE``, ``NOTIONAL``, ``PRICE_FILTER``, ``stepSize``, ``tickSize``
from ``exchangeInfo`` at startup and daily. Never hardcode."*  This member
is where those constants live once fetched, so the order-path features that
follow (311's daily refresh, 312's step/tick rounding, 313's minimum
notional, and onward through 321's shadow-mode default) have something to
read instead of a literal in the order path.

The category's other features arrive as their own modules rather than as
fields on this one, and the two below are the shape the rest take.

Two pieces:

* :mod:`router.exchange_info` — the fetched-document contract.  A fetch is
  parsed through the ingest member's own parser
  (:func:`nullius_ingest.exchange_info.parse_exchange_info`, see
  :func:`~router.exchange_info.require_ingest`) rather than a second
  implementation of the same venue response, and narrowed to
  :class:`~router.exchange_info.RouterSymbolFilters` — the five fields
  feature 310 names, per symbol.
* :mod:`router.store` — the persisted-record contract.  Every fetch lands
  as a new :class:`~router.store.RouterExchangeInfoVersion`, never
  overwriting a prior one, in the workspace's relational store
  (``DATABASE_URL``); :meth:`~router.store.RouterExchangeInfoStore.
  filters_for` is the order path's fast, symbol-keyed read of the current
  version.

Feature 320 adds a third: :mod:`router.submission_health` — the router's
*own* liveness, persisted independently of the market-data feed, so a
router that is wedged or dead is still visible to a reader in another
process (docs §13.2's *"separate process for the order router"*, §14's
separate live host).  It is a second table in the same relational store and
**not** a second component: the member registers one component (below), and
a store addressed by ``DATABASE_URL`` is never composed, exactly as
feature 310's own store is reached by construction rather than by
``@register``.  Its reading is three-valued — ``True``, ``False``, or
``None`` for a window that holds no submissions — and its identity
(:func:`router.submission_health.process_identity`) is what makes
*independently* checkable rather than merely asserted.

Feature 318 adds a fourth: :mod:`router.limiter` — the token bucket matched
to the venue's weight schedule, which is docs §13.2's *"Token-bucket rate
limiter matched to the venue's weight schedule"* and §16's *"rate-limit
headroom"* live metric.  It is a third table in the same relational store
and, like feature 320's, **not** a component, and for the same reason pushed
one step further: the venue meters weight per *API key*, so the bucket is
shared by every process behind that key and a bucket composed into one
router's application would be a budget that process alone was tracking —
exactly the double-spend a shared budget must not have.  So
:class:`~router.limiter.RouterRateLimiter` arrives by construction from
``DATABASE_URL``, and the member still registers exactly one component.

This package also *is* a component of the composed application: importing
it registers a builder with the application factory
(``app.module_loader.register``), so the module loader discovers it by
scanning the workspace members the root pyproject.toml declares.  No
central registry, router table or app factory is edited to wire it in —
registration happens as an import side effect right here.

The registration lives in this module and deliberately not in a submodule:
``app.module_loader._import_package`` re-executes a package's
``__init__.py`` on every ``create_app()`` call, but a submodule already
cached in ``sys.modules`` under the loader's synthetic name is not
re-executed — so a ``@register`` in a submodule would fire on the first
composition of a process and silently drop out of every later one (the
same discipline :mod:`cost_model` and :mod:`ledger` state for themselves).
"""

from __future__ import annotations

from app.module_loader import register

from ._identity import process_identity
from .errors import (
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RATE_LIMITED_CODE,
    WEIGHT_BUCKET_CODE,
    WEIGHT_SCHEDULE_CODE,
    RouterError,
    RouterFilterError,
    RouterRateLimitedError,
    RouterRateLimitError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterWeightBucketError,
    RouterWeightScheduleError,
)
from .exchange_info import RouterSymbolFilters, resolve_router_filters
from .limiter import (
    DEFAULT_VENUE_WEIGHT_SCHEDULE,
    DEFAULT_WEIGHT_SCOPE,
    OPERATION_ACCOUNT,
    OPERATION_CANCEL_ORDER,
    OPERATION_CANCEL_REPLACE_ORDER,
    OPERATION_EXCHANGE_INFO,
    OPERATION_OPEN_ORDERS,
    OPERATION_PLACE_ORDER,
    OPERATION_QUERY_ORDER,
    VENUE_WEIGHT_ALLOWANCE,
    VENUE_WEIGHT_BUCKET_TABLE,
    VENUE_WEIGHT_WINDOW,
    WEIGHT_LIMIT_TYPE,
    RateLimitHeadroom,
    RouterRateLimiter,
    VenueWeightSchedule,
)
from .store import (
    DATABASE_URL_ENV,
    ROUTER_EXCHANGE_INFO_FILTER_TABLE,
    ROUTER_EXCHANGE_INFO_VERSION_TABLE,
    RouterExchangeInfoStore,
    RouterExchangeInfoVersion,
)
from .submission_health import (
    ORDER_SUBMISSION_ACCEPTED,
    ORDER_SUBMISSION_HEALTH_TABLE,
    ORDER_SUBMISSION_OUTCOMES,
    ORDER_SUBMISSION_REJECTED,
    SUBMISSION_HEALTH_FAILURE_RATIO,
    SUBMISSION_HEALTH_WINDOW,
    RouterSubmissionHealthStore,
    SubmissionHealth,
    SubmissionObservation,
)

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "DEFAULT_VENUE_WEIGHT_SCHEDULE",
    "DEFAULT_WEIGHT_SCOPE",
    "OPERATION_ACCOUNT",
    "OPERATION_CANCEL_ORDER",
    "OPERATION_CANCEL_REPLACE_ORDER",
    "OPERATION_EXCHANGE_INFO",
    "OPERATION_OPEN_ORDERS",
    "OPERATION_PLACE_ORDER",
    "OPERATION_QUERY_ORDER",
    "ORDER_SUBMISSION_ACCEPTED",
    "ORDER_SUBMISSION_HEALTH_TABLE",
    "ORDER_SUBMISSION_OUTCOMES",
    "ORDER_SUBMISSION_REJECTED",
    "ORDER_SUBMISSION_UNHEALTHY_CODE",
    "RATE_LIMITED_CODE",
    "ROUTER_EXCHANGE_INFO_FILTER_TABLE",
    "ROUTER_EXCHANGE_INFO_VERSION_TABLE",
    "SUBMISSION_HEALTH_FAILURE_RATIO",
    "SUBMISSION_HEALTH_WINDOW",
    "VENUE_WEIGHT_ALLOWANCE",
    "VENUE_WEIGHT_BUCKET_TABLE",
    "VENUE_WEIGHT_WINDOW",
    "WEIGHT_BUCKET_CODE",
    "WEIGHT_LIMIT_TYPE",
    "WEIGHT_SCHEDULE_CODE",
    "RateLimitHeadroom",
    "RouterError",
    "RouterExchangeInfoStore",
    "RouterExchangeInfoVersion",
    "RouterFilterError",
    "RouterRateLimitError",
    "RouterRateLimitedError",
    "RouterRateLimiter",
    "RouterStoreError",
    "RouterSubmissionHealthError",
    "RouterSubmissionHealthStore",
    "RouterSymbolFilters",
    "RouterWeightBucketError",
    "RouterWeightScheduleError",
    "SubmissionHealth",
    "SubmissionObservation",
    "VenueWeightSchedule",
    "process_identity",
    "resolve_router_filters",
]

__version__ = "0.1.0"

#: The component name this member registers under — unprefixed, following
#: the ``ledger`` / ``regime`` / ``canary`` precedent for a member's first
#: and only component.
COMPONENT_NAME = "router"


@register(COMPONENT_NAME)
def build_router_exchange_info_store() -> RouterExchangeInfoStore | None:
    """Component builder: the exchangeInfo version store bound to ``DATABASE_URL``.

    Takes no arguments — the factory's registration protocol — and resolves
    ``DATABASE_URL`` at build time, so a composed application always carries
    a store for whatever the process is actually pointed at (the shared
    test fixtures set one per test).

    Returns ``None`` when no ``DATABASE_URL`` is configured — an
    unconfigured store is a discoverable deployment state, not an
    exception, the same stance :class:`ledger.store.TrialLedger.resolve`
    and the regime member's coverage ledger take.  Construction performs no
    I/O: the schema is created on the first :meth:`~router.store.
    RouterExchangeInfoStore.record` or read, so composing the application
    never touches a database.
    """
    return RouterExchangeInfoStore.resolve()


#: Feature 318's limiter is not a second component either, and the argument is
#: feature 320's one step further.  A submission-health store is *read* from
#: another process; a weight bucket is *written* from another process, at the
#: same time — the venue meters weight per API key, so two routers behind one
#: key spend one budget concurrently.  A component would hand each of them its
#: own handle composed for its own process, which is the shape that lets two
#: processes each believe they have tracked the other's spend.  So the limiter
#: is resolved from ``DATABASE_URL`` for whatever process is asking, exactly
#: as :meth:`~router.limiter.RouterRateLimiter.resolve` does, and the member
#: still registers exactly one component (feature 310's exchangeInfo store).

#: Feature 320's store is deliberately **not** a second component.  A
#: submission-health log is addressed by ``DATABASE_URL`` and constructed by
#: whoever reads or writes it — the router process on its own path, an
#: operator's health sweep, a supervisor in another process entirely — which
#: is what *"persists ... independently"* requires: a reading a composed
#: application could hand out would be a reading the application's own
#: lifetime bounds, and a process that has hung cannot answer through a
#: component it is no longer running.  The seat in ``app.modules.router``
#: exposes the accessor this module documents for it, and no second
#: ``@register`` builder is added here — the member still registers exactly
#: one component (feature 310's exchangeInfo store).  Feature 318's limiter is
#: the third table reached the same way, and the note above it states why its
#: case is stronger still.
