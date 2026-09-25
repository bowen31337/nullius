"""The ops member: the observability surface — metrics, lamps, dashboards.

app_spec.xml, "Observability & Dashboards", lands on this workspace
member (``packages/ops``, import name ``ops``).
docs/nullius-tech-architecture.md §16 fixes its subject in one bolded
sentence — *"**The top-line dashboard number is ``FDR_deploy``, not
Sharpe.**  If the primary chart is an equity curve, the system's actual
purpose has been quietly abandoned"* — and the category's features
split that sentence into layers.  Feature 341 is the foundation they
all stand on (every later feature in the category declares
``depends_on="341"``): *System exposes GET /metrics/fdr-deploy which
returns the base-rate reweighted false discovery rate as the top-line
figure.*  The route :mod:`ops.fdr_route` is that seam — the one place
an operator surface asks for the system's primary figure, answering
prd §11's primary metric (the base-rate-reweighted false discovery
rate, target *"< 25% at π₀ = 0.9"*) and never the raw in-campaign rate
prd §4.1.3 bars from the dashboard.

**The member owns no figure of its own.**  Every number it serves was
measured somewhere else: ``FDR_deploy`` is the scoring member's
(feature 267's per-campaign rows, reweighted once at the one constant),
342's lamps read the canary member's drift record and the null
oracle's KS guard, 343's counts read the regime member's coverage
ledger.  What this member owns is the *surface* — the routes, the
stores §16's later features persist into, the dashboard — and its law
is therefore delegation: the fdr-deploy route reads feature 267's
store through the scoring member itself (:func:`ops.fdr_route.
require_scoring`, the deferred-import door the router member opened
for the ingest parser) rather than growing a second spelling of the
reweighting, the pair-truth read law or the table; and it translates
the store's refusals into this member's vocabulary
(:class:`~ops.errors.FdrDeployMetricError`) at the seam, so a caller
that catches the route's error is never taken down by an error from a
module it never imported.

Importing this package registers one component with the application
factory.  :data:`OPS_COMPONENT_NAME` (``ops-fdr-deploy``) is feature
341's GET route — :class:`~ops.fdr_route.FdrDeployEndpoint` over the
FDR_deploy store ``DATABASE_URL`` names, or nothing when it names
nothing (an unconfigured store is a discoverable state, and the
composed application simply carries no ops route).  The registration is
a deliberate import side effect: this is how a member announces itself
to the factory without the factory knowing its name in advance, and no
edit to any central registry, router table or app factory is needed or
wanted to wire this package in.

**The ``@register`` decorator lives here, in this ``__init__``, and in
no submodule.**  The factory's scan re-executes a package's
``__init__`` on every :func:`~app.module_loader.create_app` call, but a
submodule already cached in ``sys.modules`` is not re-executed; a
``@register`` in a submodule would therefore fire on the first
composition of a process and silently drop out of every later one.
Registration lives on the import path the scan always runs — the same
invariant every other member's registration states.

**What the later features of this category will add, and the shapes
they will take.**  342's lamps and 343's coverage arrive as their own
route modules over the members that hold those facts; 344-347's and
350's persisted metrics arrive as this member's own tables in the same
relational store (§16's *"single Postgres metrics table"* allowance) —
the metrics store feature 267's own docstring already reserves
(*"the research-metrics row is the ops member's (feature 344 ...)"*);
348-349's structured log records arrive as emission seams; 351-352's
dashboard reads the routes and the store.  Each is its own module with
its own refusal vocabulary under :class:`~ops.errors.OpsError`, and
each composes only if its sentence demands state a deployment holds —
the registration-grows-per-feature shape the ledger, nulloracle and
canary members already take, spelled here once so the category's
growth stays on one pattern.

The public API is small on purpose, and each piece is the seam a later
feature composes rather than a second spelling of something another
member already says:

* :class:`~ops.fdr_route.FdrDeployEndpoint` with
  :class:`~ops.fdr_route.FdrDeployResponse` — feature 341's route:
  GET /metrics/fdr-deploy, answering the base-rate-reweighted false
  discovery rate as the top-line figure (the newest campaign's, from
  feature 267's own trend read) with the campaign and instant that
  attribute it.
* :data:`~ops.fdr_route.FDR_DEPLOY_ROUTE` — the route's one spelling,
  shared by the endpoint's ``route`` attribute and the spec's API
  summary row.
* :class:`~ops.errors.OpsError` with
  :class:`~ops.errors.FdrDeployMetricError` — the member's refusal
  vocabulary: one base so a caller catches the member as a whole, one
  subclass per route so a refusal names where it happened.
"""

from __future__ import annotations

from app.module_loader import register

from .errors import FdrDeployMetricError, OpsError
from .fdr_route import (
    FDR_DEPLOY_ROUTE,
    FdrDeployEndpoint,
    FdrDeployResponse,
    require_scoring,
)

__all__ = [
    "FDR_DEPLOY_ROUTE",
    "FdrDeployEndpoint",
    "FdrDeployMetricError",
    "FdrDeployResponse",
    "OPS_COMPONENT_NAME",
    "OpsError",
    "require_scoring",
]

#: The component name the member's fdr-deploy route registers under —
#: member-first and route-second, the spelling every route-shaped
#: component in this workspace takes (the ledger member's
#: ``ledger-k-effective`` for feature 94's GET among them), so a
#: composed application's ``order`` sorts this member's routes *beside*
#: — never inside — another member's components, and the sibling routes
#: this category's later features add (342's lamps, 343's coverage)
#: land as its peers under the same prefix.  Spelled here, in the app
#: package seat (:mod:`app.modules.ops`) and nowhere else; the member's
#: suite asserts the spellings agree.
OPS_COMPONENT_NAME = "ops-fdr-deploy"


@register(OPS_COMPONENT_NAME)
def build_fdr_deploy_route() -> FdrDeployEndpoint | None:
    """Component builder: the GET /metrics/fdr-deploy route, bound to
    the store ``DATABASE_URL`` names.

    Takes no arguments — the factory's registration protocol — and
    decides at build time only whether a store is configured: it reads
    ``DATABASE_URL`` itself (absent, empty and whitespace-only all
    unset) and holds the URL in a deferred carrier that constructs the
    scoring member's store on the first read.  The deferral is the
    scan-order law :func:`~ops.fdr_route.require_scoring` exists for,
    applied one step further: builders fire after the factory's scan
    has taken each member's ``src/`` back off ``sys.path``, so
    importing the scoring member here would make this component's
    presence — and every whole-workspace composition that fires it —
    depend on an import that is not promised to work at that moment.
    The URL, once resolved, is the composition fact: the composed
    route, the composed ``scoring-fdr-deploy`` store component and
    every other reader of the per-campaign rows always point at the
    one database (the member's suite pins the agreement both ways).

    Returns ``None`` when no ``DATABASE_URL`` is configured — an
    unconfigured store is a discoverable deployment state, not an
    exception, the same stance the ledger member's builders and the
    scoring member's own store builder take.  And building performs no
    I/O of any kind: no store is constructed, no database opened, no
    schema created — the first ``get()`` is where the store is both
    constructed and asked.
    """
    return FdrDeployEndpoint.from_env()
