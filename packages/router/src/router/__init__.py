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

Feature 319 adds a fifth: :mod:`router.retry` — the clause after the comma
in that §13.2 line, *"with exponential backoff and jitter"*, answering the
limiter's refusal by waiting and re-sending, and emitting one
:class:`~router.retry.RateLimitRetryEvent` per attempt it makes.  It holds
no table (a pacing is not a fact the next process must agree on — the
bucket it paces against already is), and no component either, for the
reason :func:`discovery.retry.retry_interrupted` states for its own retry:
it exists for the length of one call and takes its whole policy from the
caller on each ask, so a builder would have to bake a budget no deployment
stated.  The member still registers exactly one component, and the order
path reaches the verb by calling it.

Feature 316 adds a sixth: :mod:`router.client_order_id` — the order's own
name, hashed out of the book, the rebalance and the symbol exactly as
§13.2's one line fixes it (``client_order_id = hash(book_id, rebalance_ts,
symbol)``).  It is the category's purest verb: no table (the key is a
function of the order, not a fact to store — feature 317's store will key
its rows *on* this value), no component, no clock read (a key that depended
on when it was computed would be the generated name it exists to replace),
and the same three terms in any process answer the same key — which is the
"idempotent resubmission key" the sentence returns and the property 317's
duplicate answer and 320's health join are built on.  Two of the three
terms are the rebalance record's own identity (feature 309 keyed its table
on ``(book_id, rebalance_ts)`` so the order path would hash from the
record's own key), and the third is the leg — one order per symbol per
rebalance per book.

Feature 317 adds a seventh: :mod:`router.submission_result` — the
*idempotent* half of §13.2's one line, *"Idempotent order submission keyed
by* ``client_order_id = hash(book_id, rebalance_ts, symbol)``*.  Feature
316 derives the key; this module is what the key is *for*.  It is a fourth
table in the same relational store, keyed by feature 316's identifier
itself, holding one row per order the router placed — so a re-sending
process (a reclaimed spot instance, a restart, feature 319's backoff) is
answered by the first send's record instead of reaching the venue again.
The check, the venue call and the insert happen inside one transaction, so
a venue refusal leaves no row behind and a concurrent duplicate is answered
from the committed row rather than racing the venue; and because a
*rejection* placed nothing, this table's vocabulary admits only a
placement.  Like features 310's, 320's and 318's stores it is addressed by
``DATABASE_URL`` and never composed — the member still registers exactly
one component — and the member's suite pins that.

Feature 315 adds an eighth: :mod:`router.margin` — *isolated margin per
book*, the arrangement a book's positions settle under, and this system's
refusal to trade one that would merge them.  ``docs/nullius-tech-
architecture.md`` §13.2 and ``docs/alpha-engine-prd.md`` C9 state the rule
and its reason in one line each: *"Isolated margin per book. Cross margin
converts N independent positions into one position with N legs, and a single
leg's liquidation cascades into the rest."*  It is the category's only
feature whose noun is a *deployment's configuration* rather than an order,
a key, a document or a log — the order path builds exactly the same orders
under either arrangement, against the same filters and the same keys, so
nothing downstream can detect the difference and the gate has to stand
before the first order.  It adds no table (a margin mode is a property of
one process's startup configuration, not a fact the next process must agree
on) and no component, and the member still registers exactly one, feature
310's exchangeInfo store.

Feature 314 adds a ninth: :mod:`router.posture` — *how an order crosses*,
the choice §13.2 fixes as *"Post-only by default; aggressive only when
the signal's decay horizon is shorter than the expected fill time"* and
C9 repeats as *"taker only when signal decay horizon < expected fill
time"*.  It is the member's per-order decision — :mod:`router.margin`
names it exactly that, one paragraph over — and the sentence's *only
when* is structural in it: the verb takes **no posture argument**, so
the single door to an aggressive order is the comparison itself, made
inside the one act that resolves a posture.  No table (the posture is
derived per order as it is built, and two processes agree on it the way
they agree on feature 316's key, by deriving it rather than by
consulting one), no component (the member still registers exactly one,
feature 310's exchangeInfo store), no clock and no I/O — a posture that
depended on when it was computed would be a second posture for one
order between the decision and the send.

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
from .client_order_id import (
    CLIENT_ORDER_ID_LENGTH,
    ClientOrderId,
    client_order_digest,
    derive_client_order_id,
    normalize_client_order_id,
)
from .errors import (
    CLIENT_ORDER_ID_CODE,
    CROSS_MARGIN_CODE,
    ORDER_POSTURE_CODE,
    ORDER_SUBMISSION_UNHEALTHY_CODE,
    RATE_LIMITED_CODE,
    RETRY_BACKOFF_CODE,
    SUBMISSION_RESULT_CODE,
    WEIGHT_BUCKET_CODE,
    WEIGHT_SCHEDULE_CODE,
    RouterClientOrderIdError,
    RouterCrossMarginError,
    RouterError,
    RouterFilterError,
    RouterOrderPostureError,
    RouterRateLimitedError,
    RouterRateLimitError,
    RouterRetryError,
    RouterStoreError,
    RouterSubmissionHealthError,
    RouterSubmissionResultError,
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
from .margin import (
    CROSS_MARGIN,
    ISOLATED_MARGIN,
    MARGIN_MODES,
    BookMargin,
    MarginScope,
    require_isolated_margin,
)
from .posture import (
    AGGRESSIVE_ORDER,
    ORDER_POSTURES,
    PASSIVE_ORDER,
    OrderPosture,
    resolve_order_posture,
)
from .retry import (
    DEFAULT_BACKOFF_SCHEDULE,
    RATE_LIMIT_RETRY_EVENT,
    BackoffSchedule,
    RateLimitRetryEvent,
    RetryEventLog,
    retry_rate_limited,
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
from .submission_result import (
    ORDER_PLACEMENT_OUTCOMES,
    ORDER_PLACEMENT_TABLE,
    OrderPlacement,
    PlacementOrder,
    PlacementResult,
    RouterOrderPlacementStore,
)

__all__ = [
    "AGGRESSIVE_ORDER",
    "CLIENT_ORDER_ID_CODE",
    "CLIENT_ORDER_ID_LENGTH",
    "COMPONENT_NAME",
    "CROSS_MARGIN",
    "CROSS_MARGIN_CODE",
    "DATABASE_URL_ENV",
    "DEFAULT_BACKOFF_SCHEDULE",
    "DEFAULT_VENUE_WEIGHT_SCHEDULE",
    "DEFAULT_WEIGHT_SCOPE",
    "ISOLATED_MARGIN",
    "MARGIN_MODES",
    "OPERATION_ACCOUNT",
    "OPERATION_CANCEL_ORDER",
    "OPERATION_CANCEL_REPLACE_ORDER",
    "OPERATION_EXCHANGE_INFO",
    "OPERATION_OPEN_ORDERS",
    "OPERATION_PLACE_ORDER",
    "OPERATION_QUERY_ORDER",
    "ORDER_PLACEMENT_OUTCOMES",
    "ORDER_PLACEMENT_TABLE",
    "ORDER_POSTURES",
    "ORDER_POSTURE_CODE",
    "ORDER_SUBMISSION_ACCEPTED",
    "ORDER_SUBMISSION_HEALTH_TABLE",
    "ORDER_SUBMISSION_OUTCOMES",
    "ORDER_SUBMISSION_REJECTED",
    "ORDER_SUBMISSION_UNHEALTHY_CODE",
    "PASSIVE_ORDER",
    "RATE_LIMITED_CODE",
    "RATE_LIMIT_RETRY_EVENT",
    "RETRY_BACKOFF_CODE",
    "ROUTER_EXCHANGE_INFO_FILTER_TABLE",
    "ROUTER_EXCHANGE_INFO_VERSION_TABLE",
    "SUBMISSION_HEALTH_FAILURE_RATIO",
    "SUBMISSION_HEALTH_WINDOW",
    "SUBMISSION_RESULT_CODE",
    "VENUE_WEIGHT_ALLOWANCE",
    "VENUE_WEIGHT_BUCKET_TABLE",
    "VENUE_WEIGHT_WINDOW",
    "WEIGHT_BUCKET_CODE",
    "WEIGHT_LIMIT_TYPE",
    "WEIGHT_SCHEDULE_CODE",
    "BackoffSchedule",
    "BookMargin",
    "ClientOrderId",
    "MarginScope",
    "OrderPlacement",
    "OrderPosture",
    "PlacementOrder",
    "PlacementResult",
    "RateLimitHeadroom",
    "RateLimitRetryEvent",
    "RetryEventLog",
    "RouterClientOrderIdError",
    "RouterCrossMarginError",
    "RouterError",
    "RouterExchangeInfoStore",
    "RouterExchangeInfoVersion",
    "RouterFilterError",
    "RouterOrderPlacementStore",
    "RouterOrderPostureError",
    "RouterRateLimitError",
    "RouterRateLimitedError",
    "RouterRateLimiter",
    "RouterRetryError",
    "RouterStoreError",
    "RouterSubmissionHealthError",
    "RouterSubmissionHealthStore",
    "RouterSubmissionResultError",
    "RouterSymbolFilters",
    "RouterWeightBucketError",
    "RouterWeightScheduleError",
    "SubmissionHealth",
    "SubmissionObservation",
    "VenueWeightSchedule",
    "client_order_digest",
    "derive_client_order_id",
    "normalize_client_order_id",
    "process_identity",
    "require_isolated_margin",
    "resolve_order_posture",
    "resolve_router_filters",
    "retry_rate_limited",
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

#: Feature 317's placement store is the fourth table and takes the same road,
#: with an argument that is 316's rather than 320's: the duplicate this
#: feature answers arrives *from another process* — a reclaimed spot instance,
#: a restarted router — and that process derives feature 316's key for itself
#: without speaking to the first.  A store composed into one application would
#: be a record only that application could consult, which is exactly the state
#: "returns the prior result ... rather than placing a second order" has to be
#: true *across* processes to mean anything.  So it is resolved from
#: ``DATABASE_URL`` for whoever is asking, and no second ``@register`` builder
#: is added here — the member still registers exactly one component (feature
#: 310's exchangeInfo store).
