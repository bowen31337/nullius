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

from .errors import RouterError, RouterFilterError, RouterStoreError
from .exchange_info import RouterSymbolFilters, resolve_router_filters
from .store import (
    DATABASE_URL_ENV,
    ROUTER_EXCHANGE_INFO_FILTER_TABLE,
    ROUTER_EXCHANGE_INFO_VERSION_TABLE,
    RouterExchangeInfoStore,
    RouterExchangeInfoVersion,
)

__all__ = [
    "COMPONENT_NAME",
    "DATABASE_URL_ENV",
    "ROUTER_EXCHANGE_INFO_FILTER_TABLE",
    "ROUTER_EXCHANGE_INFO_VERSION_TABLE",
    "RouterError",
    "RouterExchangeInfoStore",
    "RouterExchangeInfoVersion",
    "RouterFilterError",
    "RouterStoreError",
    "RouterSymbolFilters",
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
