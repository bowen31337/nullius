"""The router member's seat in the ``app`` package namespace — features 310, 320.

app_spec.xml, "Order Routing & Venue Filters", feature 310: *System persists
the fetched exchangeInfo version carrying lot size, notional, price filter,
step size and tick size.*  The store that persists those versions lives in
:mod:`router.store`; this module is how the app package reaches the
composed store without importing the member at module scope.

The category's later features (311's daily refresh, 312's step/tick
rounding, 313's minimum notional, and onward) reach the same store through
this seat rather than through a second component — the one question this
module answers is *what is the composed exchangeInfo version store?*

**Feature 320's health store is the second question, and a different kind
of answer.**  app_spec.xml feature 320: *System persists order submission
health independently of feed health, running the router in its own
process.*  That store is deliberately **not** a component (see the router
member's ``__init__``), so this seat does not ask the factory for it:
:func:`router_submission_health_store` resolves it from ``DATABASE_URL``
for whatever process is asking.  The distinction is the feature's own
subject — a reading a *composed application* hands out is a reading that
application's lifetime bounds, and the process that has hung is precisely
the one that cannot answer — so the health accessor is a plain resolver
beside the component accessor, not a second ``get`` on the same registry.

*Which process is asking?* is answered by the store itself, through
:attr:`~router.submission_health.RouterSubmissionHealthStore.process_id`,
and deliberately not by a second accessor here: a caller holding the store
already holds the identity its rows are filed under, and a pass-through
beside it would be a second spelling of one fact with nothing to keep them
in sync but care.

**Composition stays the factory's job.**  This module asks the factory for
the component and answers ``None`` — not an exception — when there is
none, mirroring the factory's own "degrade, don't break" stance toward
absent components.  It deliberately does not re-export
``RouterSymbolFilters`` or ``resolve_router_filters``: a caller who has the
store reaches ``record()``, ``current()`` and ``filters_for()`` on it, and
a second spelling here would be a second thing to keep in sync.  The same
holds for the health store: a caller who has it reaches ``record()``,
``health()``, ``latest_for_process()`` and ``process_id`` on it.

**Construction touches no database.**  The store resolves its path on
first use and opens nothing until an operation needs it, so asking for the
component is always safe — the same promise the member's own builder makes
— and the first :meth:`~router.store.RouterExchangeInfoStore.record` is
where a version is actually written.  Feature 320's store keeps the same
promise, and for a sharper reason: a health accessor that opened a
connection would make *asking about* the router's liveness a way to fail,
which is the one property the feature cannot afford.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from router import RouterExchangeInfoStore, RouterSubmissionHealthStore

__all__ = [
    "COMPONENT_NAME",
    "router_exchange_info_component",
    "router_submission_health_store",
]

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


def router_submission_health_store() -> RouterSubmissionHealthStore | None:
    """Feature 320's order submission health store, or ``None``.

    Resolved from ``DATABASE_URL`` through the member's own
    :meth:`~router.submission_health.RouterSubmissionHealthStore.resolve`
    rather than read out of a composed application, and that is the feature
    rather than an implementation detail: the health log exists so that a
    router which has hung, died or lost its feed is *still readable*, and
    the reader is usually a different process from the writer — an operator
    on the bastion (§17: no inbound ports on the live trading host), a
    supervisor's sweep, a pre-restart check.  A composed application can
    answer only for the process that composed it, which is the one process
    whose health is in question.

    Takes no ``app`` argument for the same reason: there is no registry to
    consult, so accepting one would suggest the answer depended on it.
    ``None`` when no ``DATABASE_URL`` is configured — an unconfigured store
    is a discoverable deployment state, not an exception, the same stance
    :func:`router_exchange_info_component` takes.  Construction performs no
    I/O, so asking about the router's liveness can never itself fail.

    The member is imported at call time rather than at module scope, per
    the workspace rule this seat already follows for the component: a
    module-scope member import here would put the member on ``sys.path``
    during the factory's scan of ``src/app``, which is not a member.
    """
    from router import RouterSubmissionHealthStore

    return RouterSubmissionHealthStore.resolve()
