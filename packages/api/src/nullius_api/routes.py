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

Each row also states the *scope* a caller must hold to reach it
(feature 18), so the pairing of route to credential is spelled once
here beside the pairing of route to component, and the dispatch checks
the scope off the row it is about to serve rather than a second table
that could drift from it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .auth import EVALUATOR, METRICS_READ, RESEARCH, RISK

__all__ = [
    "API_ROUTES",
    "INDEX_SCOPE",
    "PRE_REGISTER_WRAP",
    "PROMOTE_WRAP",
    "ApiRoute",
    "ResolvedRoute",
    "resolve_routes",
    "routes_by_path",
]

#: The scope the index answers under.  ``GET /`` is a *meta* route (see
#: :mod:`nullius_api.server`), not a row of :data:`API_ROUTES`, so its
#: required scope cannot live in a table row — but it must still be
#: stated somewhere the transport can read, because feature 18's
#: constraint is that *no route other than GET /healthz* answers without
#: a valid token, and ``/`` is a route.  It carries ``metrics:read``
#: because that is the scope over the transport's own surface: the page
#: describes the composition an operator reads, and the journeys that
#: open it (J8, J14) hold a ``metrics:read`` token.  ``/healthz`` alone
#: has no scope, which is the whole of its exemption.
INDEX_SCOPE = METRICS_READ

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

    ``scope`` is the credential a caller must hold to reach the row —
    one of feature 18's four words, spelled once per row so the
    *pairing* of route to scope is as greppable and as drift-proof as
    the pairing of route to component above.  It is the same "spelled
    once" law this module exists for, lifted to the authorization
    surface: a scope written here and checked in the dispatch could
    otherwise disagree about which credential reaches
    ``POST /risk/halt``, and that disagreement would be a hole rather
    than a bug report.  The rows below assign the four words along the
    journey documents' own actor lines — the actor who reads a metric
    holds ``metrics:read``, the researcher holds ``research``, the
    frozen evaluator service holds ``evaluator`` and the risk
    supervisor holds ``risk`` — so the token a journey's precondition
    names is the token its steps use.

    ``scope`` carries **no default**, deliberately, and it sits between
    the required fields and the defaulted ones for exactly that reason:
    an authorization gate whose unstated value is a working credential
    is one a future row can widen by omission.  Every row states its
    scope, so adding a route to the table is also a decision about who
    may reach it, and the missing-argument error is the reminder.
    """

    path: str
    verb: str
    component: str
    scope: str
    wrap: str | None = None
    configuration: str = _DATABASE_URL


#: The whole HTTP surface this transport serves — app_spec.xml's
#: ``<api_endpoints_summary>`` restated as composition facts.  Ordered
#: by path then verb, so the table (and anything derived from it, such
#: as the index the spec's later features serve at ``GET /``) reads
#: deterministically regardless of who asks.
API_ROUTES: tuple[ApiRoute, ...] = (
    ApiRoute("/forward/decay", "GET", "forward-decay", RESEARCH),
    ApiRoute("/forward/promote", "POST", "forward", RESEARCH, wrap=PROMOTE_WRAP),
    ApiRoute("/ledger/debit", "POST", "ledger-debit", EVALUATOR),
    ApiRoute("/ledger/k-effective", "GET", "ledger-k-effective", EVALUATOR),
    ApiRoute("/metrics/fdr-deploy", "GET", "ops-fdr-deploy", METRICS_READ),
    ApiRoute("/metrics/instrument-status", "GET", "ops-instrument-status", METRICS_READ),
    ApiRoute("/metrics/regime-coverage", "GET", "ops-regime-coverage", METRICS_READ),
    ApiRoute(
        "/promotion/pre-register",
        "POST",
        "promotion",
        RESEARCH,
        wrap=PRE_REGISTER_WRAP,
    ),
    ApiRoute(
        "/target",
        "POST",
        "nulloracle-target-route",
        EVALUATOR,
        configuration="the null sidecar location (NULL_SIDECAR_PATH)",
    ),
    ApiRoute("/risk/halt", "POST", "risk-halt", RISK),
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
