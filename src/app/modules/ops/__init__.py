"""The ops module — app-level entrypoint for the ops workspace member.

The implementation lives in the ``ops`` workspace member
(``packages/ops``, import name ``ops``), which self-registers with the
application factory under the component name
:data:`COMPONENT_NAME` — scanning the workspace imports it, its
``@register`` decorator fires, and ``create_app()`` builds feature
341's route: a :class:`~ops.fdr_route.FdrDeployEndpoint` serving GET
/metrics/fdr-deploy over the FDR_deploy store ``DATABASE_URL`` names
(the scoring member's, feature 267's per-campaign rows), answering the
base-rate-reweighted false discovery rate as the top-line figure —
docs §16's *"The top-line dashboard number is ``FDR_deploy``, not
Sharpe"*, prd §11's primary metric, and never the raw in-campaign rate
prd §4.1.3 bars from the dashboard.  Its peer :data:
`DASHBOARD_COMPONENT_NAME` (``ops-dashboard``) is feature 351's
operator surface, the :class:`~ops.dashboard.OperatorDashboard` whose
primary panel renders that same figure rather than an equity curve.

This module is the member's seat inside the ``app`` package namespace
(``src/app/modules/ops/``): it exposes the composed components without
making the ``app`` package depend on any workspace member at import
time.  Composition stays the factory's job — this module only asks the
factory for the component, and a module that cannot reach it (member
not scanned, no ``DATABASE_URL`` configured) gets ``None`` rather than
failing import, mirroring the factory's own "degrade, don't break"
stance toward absent components.

The two ``None``s this seat can answer are different facts that fail
differently, and neither is the other's: ``None`` here means the member
was not scanned *or* nothing named a database — a statement about
composition or about the deployment — while a caller that needs the
top-line figure and resolves ``None`` must refuse to proceed rather
than rendering a numeral nobody measured.  The dashboard this route
feeds is that caller, and it reaches the route through
:func:`fdr_deploy_component` exactly so
(:meth:`ops.dashboard.OperatorDashboard.composed`): an operator surface
that quietly rendered ``0.0`` over an absent store would answer *"a
flawless system"* for one that never ran, which is exactly the
quietly-defaulted number this category exists to rule out.

The helpers below are deliberately the *composition* accessors and
nothing more.  They do not re-export the response type, the route
constant or the error vocabulary: a caller who has the endpoint calls
``get()`` on it and reads the answer off the
:class:`~ops.fdr_route.FdrDeployResponse` it answers — and a second
spelling of any of those here would be a second thing to keep in sync.
This module answers exactly the composition questions — *what is the
composed fdr-deploy route?*, *what is the composed dashboard?*, *what
is the composed live-metrics store?*, *what is the composed
meta-overfit gap store?*, *what is the composed discovery-rate store?*,
*what is the composed Type-B depth store?*
— so the observability features that follow (342's lamps, 343's
coverage, 352's chrome) can ask them without importing the member
directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from ops import (
        DiscoveryRates,
        FdrDeployEndpoint,
        LiveMetricsStore,
        MetaOverfitGaps,
        OperatorDashboard,
        TypeBDepths,
    )

__all__ = [
    "COMPONENT_NAME",
    "DASHBOARD_COMPONENT_NAME",
    "OPS_DISCOVERY_RATE_COMPONENT_NAME",
    "OPS_LIVE_METRIC_COMPONENT_NAME",
    "OPS_META_OVERFIT_COMPONENT_NAME",
    "OPS_TYPE_B_DEPTH_COMPONENT_NAME",
    "dashboard_component",
    "discovery_rate_component",
    "fdr_deploy_component",
    "live_metric_component",
    "meta_overfit_component",
    "type_b_depth_component",
]

#: The component name the ops member registers its fdr-deploy route
#: under (feature 341: GET /metrics/fdr-deploy, the base-rate
#: reweighted false discovery rate as the top-line figure).  Kept here
#: so anything asking the composed application for the route — by way
#: of the app package, not the member — shares one spelling; the
#: member's suite asserts this seat, the member's own
#: :data:`~ops.OPS_COMPONENT_NAME` and the spec's route row cannot
#: drift apart.
COMPONENT_NAME = "ops-fdr-deploy"

#: The component name the ops member registers its dashboard under
#: (feature 351: the Streamlit dashboard whose primary panel displays
#: ``FDR_deploy`` rather than an equity curve), the route component's
#: peer under the same member-first prefix.  The member's suite asserts
#: this seat and the member's own
#: :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` cannot drift apart.
DASHBOARD_COMPONENT_NAME = "ops-dashboard"

#: The component name the ops member registers its live-metrics store
#: under (feature 350: persists the information coefficient ratio, fill
#: cost in basis points, order reject rate and feed staleness into the
#: relational store ``DATABASE_URL`` names), the route and dashboard's
#: peer under the same member-first prefix.  The member's suite asserts
#: this seat and the member's own
#: :data:`~ops.OPS_LIVE_METRIC_COMPONENT_NAME` cannot drift apart.
OPS_LIVE_METRIC_COMPONENT_NAME = "ops-live-metric"

#: The component name the ops member registers its meta-overfit gap store
#: under (feature 347: persists the train-versus-holdout world score gap
#: as the meta-overfitting indicator — docs §16's research metric,
#: *"train-vs-holdout world score gap (meta-overfit)"*), the route,
#: dashboard and live-metrics store's peer under the same member-first
#: prefix.  The member's suite asserts this seat and the member's own
#: :data:`~ops.OPS_META_OVERFIT_COMPONENT_NAME` cannot drift apart.
OPS_META_OVERFIT_COMPONENT_NAME = "ops-meta-overfit"

#: The component name the ops member registers its discovery-rate store
#: under (feature 346: persists discoveries per 1000 budget-charging trials,
#: excluding null nodes from the denominator — docs §16's research metric
#: *"discoveries per 1000 budget-charging trials"* and prd §11's secondary
#: scorecard row *"Discoveries per 1,000 trials charged (nulls excluded from
#: the denominator) | trending up"*), the route, dashboard, live-metrics
#: store and meta-overfit gap store's peer under the same member-first
#: prefix.  The member's suite asserts this seat and the member's own
#: :data:`~ops.OPS_DISCOVERY_RATE_COMPONENT_NAME` cannot drift apart.
OPS_DISCOVERY_RATE_COMPONENT_NAME = "ops-discovery-rate"

#: The component name the ops member registers its Type-B depth store
#: under (feature 345: persists Type-B depth past the flip for Type-D
#: worlds — docs §16's research metric *"Type-B depth past the flip in
#: Type-D worlds"* and prd §11's secondary scorecard row *"Type-B error
#: rate: depth past the flip in Type-D worlds | falling across
#: campaigns"*), the route, dashboard, live-metrics store, meta-overfit
#: gap store and discovery-rate store's peer under the same member-first
#: prefix.  The member's suite asserts this seat and the member's own
#: :data:`~ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME` cannot drift apart.
OPS_TYPE_B_DEPTH_COMPONENT_NAME = "ops-type-b-depth"


def fdr_deploy_component(app: Application | None = None) -> "FdrDeployEndpoint | Any":
    """Return the composed fdr-deploy route (GET /metrics/fdr-deploy).

    With ``app`` given, the component is read from that application;
    without it, the application is composed first via
    :func:`app.module_loader.create_app` (scanning the declared
    workspace).  Returns ``None`` when no ``ops-fdr-deploy`` component
    is registered — an absent component is a discoverable state, not an
    exception, exactly as an empty workspace is for the factory and an
    unset ``DATABASE_URL`` is for the member's own builder.

    The operator surface that reads the top-line figure reaches the
    route through this accessor, so it never has to import the member —
    and never has to reach for the scoring member's store directly,
    which would put a second reader of the per-campaign rows where the
    one the spec's observability surface serves is supposed to be.
    """
    application = app if app is not None else create_app()
    return application.get(COMPONENT_NAME)


def dashboard_component(app: Application | None = None) -> "OperatorDashboard | Any":
    """Return the composed dashboard (feature 351's operator surface).

    The same composition accessor as :func:`fdr_deploy_component`, for
    the member's second component: reads from ``app`` when handed one,
    composes the declared workspace otherwise, and answers ``None``
    when no ``ops-dashboard`` component is registered — the same
    discoverable state, for the same reasons.  A caller that resolves
    ``None`` here and needs to render is pointed at
    :meth:`ops.dashboard.OperatorDashboard.composed`, which refuses by
    name rather than letting an operator surface render on without the
    figure.
    """
    application = app if app is not None else create_app()
    return application.get(DASHBOARD_COMPONENT_NAME)


def live_metric_component(app: Application | None = None) -> "LiveMetricsStore | Any":
    """Return the composed live-metrics store (feature 350's store).

    The same composition accessor as :func:`fdr_deploy_component`, for
    the member's third component: reads from ``app`` when handed one,
    composes the declared workspace otherwise, and answers ``None``
    when no ``ops-live-metric`` component is registered — the same
    discoverable state, for the same reasons (the member was not
    scanned, or nothing named a database).  A caller that resolves
    ``None`` here and needs to persist a live reading is pointed at the
    member's own store, which refuses to proceed rather than silently
    persisting nowhere — a metrics table with a hole in it where a live
    reading should be is exactly the quietly-defaulted number feature
    350 exists to rule out.
    """
    application = app if app is not None else create_app()
    return application.get(OPS_LIVE_METRIC_COMPONENT_NAME)


def meta_overfit_component(app: Application | None = None) -> "MetaOverfitGaps | Any":
    """Return the composed meta-overfit gap store (feature 347's store).

    The same composition accessor as :func:`fdr_deploy_component`, for
    the member's fourth component: reads from ``app`` when handed one,
    composes the declared workspace otherwise, and answers ``None`` when
    no ``ops-meta-overfit`` component is registered — the same
    discoverable state, for the same reasons (the member was not
    scanned, or nothing named a database).  A caller that resolves
    ``None`` here and needs to persist a cycle's gap is pointed at the
    member's own store, which refuses to proceed rather than silently
    persisting nowhere — a divergence that measured but never landed is
    exactly the state feature 347 exists to rule out, because docs §15
    reads its remedy for *"dreaming overfits the pool"* (*cap ``M`` per
    §10.3.1*) off this store's rows, and a missing row reads as a quiet
    cycle.
    """
    application = app if app is not None else create_app()
    return application.get(OPS_META_OVERFIT_COMPONENT_NAME)


def discovery_rate_component(app: Application | None = None) -> "DiscoveryRates | Any":
    """Return the composed discovery-rate store (feature 346's store).

    The same composition accessor as :func:`fdr_deploy_component`, for the
    member's fifth component: reads from ``app`` when handed one, composes
    the declared workspace otherwise, and answers ``None`` when no
    ``ops-discovery-rate`` component is registered — the same discoverable
    state, for the same reasons (the member was not scanned, or nothing
    named a database).  A caller that resolves ``None`` here and needs to
    persist a campaign's figure is pointed at the member's own store, which
    refuses to proceed rather than silently persisting nowhere — a rate that
    measured but never landed is exactly the state feature 346 exists to
    rule out, because prd §11 grades this metric by the direction its trend
    reads across these rows, and a missing row reads as a quiet campaign.
    """
    application = app if app is not None else create_app()
    return application.get(OPS_DISCOVERY_RATE_COMPONENT_NAME)


def type_b_depth_component(app: Application | None = None) -> "TypeBDepths | Any":
    """Return the composed Type-B depth store (feature 345's store).

    The same composition accessor as :func:`fdr_deploy_component`, for the
    member's sixth component: reads from ``app`` when handed one, composes
    the declared workspace otherwise, and answers ``None`` when no
    ``ops-type-b-depth`` component is registered — the same discoverable
    state, for the same reasons (the member was not scanned, or nothing
    named a database).  A caller that resolves ``None`` here and needs to
    persist a campaign's count is pointed at the member's own store, which
    refuses to proceed rather than silently persisting nowhere — a count
    that measured but never landed is exactly the state feature 345 exists
    to rule out, because prd §11's *"falling across campaigns"* is read
    off these rows, and a missing row reads as a campaign that crossed
    nothing — the quietest possible flattery.
    """
    application = app if app is not None else create_app()
    return application.get(OPS_TYPE_B_DEPTH_COMPONENT_NAME)
