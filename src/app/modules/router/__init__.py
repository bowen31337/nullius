"""The router member's seat in the ``app`` package namespace — feature 310.

app_spec.xml, "Order Routing & Venue Filters", feature 310: *System persists
the fetched exchangeInfo version carrying lot size, notional, price filter,
step size and tick size.*  The store that persists those versions lives in
:mod:`router.store`; this module is how the app package reaches the
composed store without importing the member at module scope.

The category's later features (311's daily refresh, 312's step/tick
rounding, 313's minimum notional, and onward) reach the same store through
this seat rather than through a second component — the one question this
module answers is *what is the composed exchangeInfo version store?*

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is
none, mirroring the factory's own "degrade, don't break" stance toward
absent components.  It deliberately does not re-export
``RouterSymbolFilters`` or ``resolve_router_filters``: a caller who has the
store reaches ``record()``, ``current()`` and ``filters_for()`` on it, and
a second spelling here would be a second thing to keep in sync.

**Construction touches no database.**  The store resolves its path on
first use and opens nothing until an operation needs it, so asking for the
component is always safe — the same promise the member's own builder makes
— and the first :meth:`~router.store.RouterExchangeInfoStore.record` is
where a version is actually written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from router import RouterExchangeInfoStore

__all__ = ["COMPONENT_NAME", "router_exchange_info_component"]

#: The component name the router member registers under.  Kept here as
#: well as in the member — every seat in this workspace spells its own
#: name twice for the same reason — so the two cannot drift apart silently.
COMPONENT_NAME = "router"


def router_exchange_info_component(
    app: Application | None = None,
) -> RouterExchangeInfoStore | Any:
    """Return the composed exchangeInfo version store (feature 310's store).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared workspace).
    Returns ``None`` when no ``router`` component is registered — either
    because the member was not scanned, or because its builder found no
    ``DATABASE_URL`` to resolve.

    That ``None`` is a statement about the deployment, and a caller that
    must record or read an exchangeInfo version has to treat it as a
    refusal to proceed rather than as an empty version log — there is
    deliberately no fallback here that opens a default database, because a
    version persisted into a database nobody named would be invisible to
    every order-path feature that reads this seat.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)
