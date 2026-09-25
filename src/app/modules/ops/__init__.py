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
composed fdr-deploy route?* and *what is the composed dashboard?* — so
the observability features that follow (342's lamps, 343's coverage,
352's chrome) can ask them without importing the member directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.module_loader import Application, create_app

if TYPE_CHECKING:  # pragma: no cover - typing only; the member is not a dependency
    from ops import FdrDeployEndpoint, OperatorDashboard

__all__ = [
    "COMPONENT_NAME",
    "DASHBOARD_COMPONENT_NAME",
    "dashboard_component",
    "fdr_deploy_component",
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
