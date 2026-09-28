"""The route table: the composed application's HTTP surface, spelled once.

app_spec.xml's ``<api_endpoints_summary>`` promises ten routes, and every
one of them already exists in-process — an endpoint object owned by the
member whose data it answers, registered under its own component name
(``ops-fdr-deploy``, ``ledger-debit``, ``risk-halt``, …).  This module
is the *only* place that spells which composed component serves which
HTTP route, so the transport, the spec's summary and the members' own
``.route`` constants cannot drift apart on the pairing — the same
"spelled once" law :data:`ops.FDR_DEPLOY_ROUTE` states for the route
names themselves, lifted one level to the composition.

Two of the ten arrive differently, and the difference is composition
fact, not accident: the promotion and forward members register their
*stores* (``promotion`` answers feature 291's
:class:`~promotion.pre_register.PreRegistrations`, ``forward`` feature
332's :class:`~forward.record.ForwardRecords`), because those members'
route objects wrap a store rather than own one.  The transport does the
wrapping at resolution time — :func:`resolve_routes` turns the composed
store into the member's own :class:`~promotion.pre_register.
PreRegisterEndpoint` and :class:`~forward.record.PromoteEndpoint` — so
the HTTP layer serves every route through the member's endpoint, never
by calling a store directly.  The wrap is duck-checked both ways: a
component that already speaks the route's verb method passes through
unwrapped, so a member that ever hands the endpoint itself is served
rather than refused.

Resolution is *discovery*, not construction: an unconfigured store
composes ``None`` (the degrade-don't-break stance every builder takes),
and the table records that as an endpoint-less route the server answers
with the unconfigured refusal — never by silently omitting the route,
because a caller must be able to tell *nowhere configured* from
*configured and empty* (the same distinction the members draw between
no store and an empty one).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "API_ROUTES",
    "PRE_REGISTER_WRAP",
    "PROMOTE_WRAP",
    "ApiRoute",
    "ResolvedRoute",
    "resolve_routes",
    "routes_by_path",
]

#: The wrap marker for the promotion component: its composed value is
#: feature 291's store, served through the member's own endpoint.
PRE_REGISTER_WRAP = "pre-register"

#: The wrap marker for the forward component: its composed value is
#: feature 332's store, served through the member's own endpoint.
PROMOTE_WRAP = "promote"

#: The environment variable the store-bound members' builders resolve
#: — named in the unconfigured refusal so the message names the one
#: repair the operator can act on.
_DATABASE_URL = "DATABASE_URL"


@dataclass(frozen=True)
class ApiRoute:
    """One row of the route table: an HTTP route and its component.

    ``path`` and ``verb`` are the HTTP spellings app_spec.xml's summary
    states; ``component`` is the composed name the factory registered
    the serving endpoint (or store) under; ``wrap`` names the
    store-to-endpoint wrap when the component arrives as a store
    (:data:`PRE_REGISTER_WRAP`, :data:`PROMOTE_WRAP`), ``None`` when it
    arrives as the endpoint itself; ``configuration`` names the
    environment the component resolves from, for the unconfigured
    refusal's message.
    """

    path: str
    verb: str
    component: str
    wrap: str | None = None
    configuration: str = _DATABASE_URL


#: The whole HTTP surface this transport serves — app_spec.xml's
#: ``<api_endpoints_summary>`` restated as composition facts.  Ordered
#: by path then verb, so the table (and anything derived from it, such
#: as the index the spec's later features serve at ``GET /``) reads
#: deterministically regardless of who asks.
API_ROUTES: tuple[ApiRoute, ...] = (
    ApiRoute("/forward/decay", "GET", "forward-decay"),
    ApiRoute("/forward/promote", "POST", "forward", wrap=PROMOTE_WRAP),
    ApiRoute("/ledger/debit", "POST", "ledger-debit"),
    ApiRoute("/ledger/k-effective", "GET", "ledger-k-effective"),
    ApiRoute("/metrics/fdr-deploy", "GET", "ops-fdr-deploy"),
    ApiRoute("/metrics/instrument-status", "GET", "ops-instrument-status"),
    ApiRoute("/metrics/regime-coverage", "GET", "ops-regime-coverage"),
    ApiRoute("/promotion/pre-register", "POST", "promotion", wrap=PRE_REGISTER_WRAP),
    ApiRoute(
        "/target",
        "POST",
        "nulloracle-target-route",
        configuration="the null sidecar location (NULL_SIDECAR_PATH)",
    ),
    ApiRoute("/risk/halt", "POST", "risk-halt"),
)


@dataclass(frozen=True)
class ResolvedRoute:
    """One table row after the composed application answered for it.

    ``endpoint`` is the object the server serves the route through —
    the composed endpoint, or the member's own endpoint wrapped around
    the composed store — or ``None`` when the component resolved to
    nothing (an unconfigured store: the discoverable deployment state,
    answered with the unconfigured refusal rather than by omission).
    """

    route: ApiRoute
    endpoint: Any


def routes_by_path() -> Mapping[str, tuple[ApiRoute, ...]]:
    """The table grouped by path — every route a path serves, any verb.

    A path with both a GET and a POST row groups once with both, so a
    wrong-verb refusal can state its ``Allow`` set from the group rather
    than from a second spelling of the table.
    """
    grouped: dict[str, tuple[ApiRoute, ...]] = {}
    for route in API_ROUTES:
        grouped.setdefault(route.path, ())
        grouped[route.path] = (*grouped[route.path], route)
    return grouped


def resolve_routes(application: Any) -> tuple[ResolvedRoute, ...]:
    """Answer the whole table for one composed application.

    Every component is looked up with the application's own ``get``
    (the :class:`~app.module_loader.Application` access the factory
    hands out) — the one door the composed application offers, used
    once per route, so what this member serves is exactly what
    composition built and nothing it re-derived.  Stores are wrapped
    through their member's own endpoint classes, imported here rather
    than at module scope for the reason the members state at their own
    seams: a module-scope cross-member import would make importing this
    package depend on the sibling being importable first, which the
    workspace's scan order never promises.

    Never raises for an absent component — ``None`` is the honest
    unconfigured state, recorded and answered as such.
    """
    return tuple(
        ResolvedRoute(route=route, endpoint=_resolve_one(application, route))
        for route in API_ROUTES
    )


def _resolve_one(application: Any, route: ApiRoute) -> Any:
    """Resolve one row's endpoint — lookup, then the wrap if it needs one."""
    component = application.get(route.component)
    if component is None:
        return None
    if route.wrap is None or callable(getattr(component, "post", None)):
        # No wrap named, or the component already speaks the route's
        # verb itself — serve it as composed.  The duck check keeps a
        # member that ever registers its endpoint directly from being
        # double-wrapped into a refusal.
        return component
    if route.wrap == PRE_REGISTER_WRAP:
        from promotion import PreRegisterEndpoint  # deferred past module scope

        return PreRegisterEndpoint(component)
    if route.wrap == PROMOTE_WRAP:
        from forward import PromoteEndpoint  # deferred past module scope

        return PromoteEndpoint(component)
    raise TypeError(
        f"route {route.verb} {route.path} names an unknown wrap "
        f"{route.wrap!r}; the table spells "
        f"{PRE_REGISTER_WRAP!r} and {PROMOTE_WRAP!r}"
    )
