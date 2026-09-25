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
ledger, 352's chrome count is the promotion member's (feature 297's
gauge over feature 294's epoch ledger — §13 item 4's depleting
resource, read through that member's own derivation rather than
re-spelled here).  What this member owns is the *surface* — the routes, the
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

Importing this package registers its components with the application
factory.  :data:`OPS_COMPONENT_NAME` (``ops-fdr-deploy``) is feature
341's GET route — :class:`~ops.fdr_route.FdrDeployEndpoint` over the
FDR_deploy store ``DATABASE_URL`` names, or nothing when it names
nothing (an unconfigured store is a discoverable state, and the
composed application simply carries no ops route).  Its peer under the
same member-first prefix is :data:`OPS_DASHBOARD_COMPONENT_NAME`
(``ops-dashboard``), feature 351's operator surface — the
:class:`~ops.dashboard.OperatorDashboard` rendered over that same
route, composing on the same ``DATABASE_URL`` decision and refusing at
render time when the figure cannot be had honestly.  The registration
is a deliberate import side effect: this is how a member announces
itself to the factory without the factory knowing its name in advance,
and no edit to any central registry, router table or app factory is
needed or wanted to wire this package in.

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
route modules over the members that hold those facts; the persisted
metrics arrive as this member's own tables in the same relational
store (§16's *"single Postgres metrics table"* allowance) — the
metrics store feature 267's own docstring already reserves
(*"the research-metrics row is the ops member's (feature 344 ...)"*):
347's train-versus-holdout world score gap (the whole row
*"train-vs-holdout world score gap (meta-overfit)"* of §16, landed as
:mod:`ops.meta_overfit`) and 350's four live metrics (landed as
:mod:`ops.live_metrics`) are the two that have; 344-346's arrive as
their own tables under the same allowance, each with its own refusal
vocabulary and its own ``@register`` here beside the route, the
dashboard and the two stores' — 348's evaluation record and 349's
replay record landed as
:mod:`ops.evaluation_log` and :mod:`ops.replay_log` — the emission
seams the reserved clause named: one structured stdlib log record per
evaluation, carrying §16's provenance triple plus ``node_id`` and
``campaign_id``, and one per replay, carrying §16's tuple
``(policy_version, world_id, beta, score, committed_pick)`` — each
with no store and no component because the sentences say *emits*,
not *persists* (feature 87's stamp on the trial row is the
evaluation's persistence half, feature 255's row the replay's);
351's dashboard (:mod:`ops.dashboard`,
landed) reads the route; 352's chrome (:mod:`ops.chrome`, landed)
hangs off its page model — the remaining clean epoch count, read
through the promotion member's own gauge (feature 297's) over the same
``DATABASE_URL`` the route resolved, and rendered as one caption
beneath the title on every page the dashboard draws.  Each is its own
module with its own refusal
vocabulary under :class:`~ops.errors.OpsError`, and each composes only
if its sentence demands state a deployment holds — the
registration-grows-per-feature shape the ledger, nulloracle and canary
members already take, spelled here once so the category's growth stays
on one pattern.

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
* :class:`~ops.dashboard.OperatorDashboard` with
  :class:`~ops.dashboard.DashboardPage` and
  :class:`~ops.dashboard.FdrDeployPanel` — feature 351's surface: the
  Streamlit dashboard whose primary panel displays ``FDR_deploy``
  (with its provenance visible beside it) rather than an equity
  curve, rendered over the composed route and refused, by name, when
  the route is absent or the primary seat is occupied by anything
  else.
* :class:`~ops.chrome.EpochCountChrome` with
  :class:`~ops.chrome.EpochCountGauge` and
  :func:`~ops.chrome.require_promotion` — feature 352's chrome: the
  remaining clean epoch count, read through the promotion member's
  own gauge (feature 297's, deferred past builder time) and rendered
  in permanent chrome on every page, so depletion stays visible —
  refused, by name, when the carrier cannot answer the count, the
  count is not one, or the ledger read fails.
* :class:`~ops.replay_log.ReplayLogRecord` with
  :func:`~ops.replay_log.emit_replay_log` — feature 349's emission
  seam: one structured log record per replay, carrying §16's tuple
  (policy version, world id, beta, score, committed pick) as named
  fields on one stdlib log record over the logger
  :data:`~ops.replay_log.REPLAY_LOG_LOGGER_NAME` names — refused by
  name when the ask names no replay, with the miss (``-inf``, no pick)
  emitted, never refused, because the stream is where the miss rate is
  counted.
* :class:`~ops.evaluation_log.EvaluationLogRecord` with
  :func:`~ops.evaluation_log.emit_evaluation_log` — feature 348's
  emission seam, the replay half's sibling over §16's other record:
  one structured log record per evaluation, carrying the full
  provenance triple (evaluator, snapshot, cost model — feature 87's
  stamp) plus ``node_id`` and ``campaign_id``, read duck-typed off the
  charge the evaluation was booked as, over the logger
  :data:`~ops.evaluation_log.EVALUATION_LOG_LOGGER_NAME` names beside
  the replay records — refused by name when the ask names no
  evaluation the ledger could join.
* :class:`~ops.meta_overfit.MetaOverfitGaps` with
  :class:`~ops.meta_overfit.MetaOverfitGap` — feature 347's store: the
  train-versus-holdout world score gap per dreaming cycle, §16's
  research metric (*"train-vs-holdout world score gap (meta-overfit)"*)
  and the observable half of §15's *"dreaming overfits the pool"* row,
  persisted into the member's own table in the store
  ``DATABASE_URL`` names.  The gap itself is the store's own
  arithmetic — ``train_mean − holdout_mean``, with no parameter for it
  at any spelling — because feature 340's law holds here too: a
  caller-stated difference would let the system persist two levels and
  a third number that disagrees with both, and §15's remedy (*cap ``M``
  per §10.3.1*) is read off these rows.
* :class:`~ops.errors.OpsError` with
  :class:`~ops.errors.FdrDeployMetricError`,
  :class:`~ops.errors.LiveMetricError`,
  :class:`~ops.errors.MetaOverfitGapError`,
  :class:`~ops.errors.ReplayLogError`,
  :class:`~ops.errors.EvaluationLogError` and
  :class:`~ops.errors.DashboardRenderError` — the member's refusal
  vocabulary: one base so a caller catches the member as a whole, one
  subclass per surface so a refusal names where it happened.
"""

from __future__ import annotations

from app.module_loader import register

from .chrome import (
    EPOCH_COUNT_LABEL,
    EpochCountChrome,
    EpochCountGauge,
    require_promotion,
)
from .dashboard import (
    DASHBOARD_PAGE_TITLE,
    DASHBOARD_TITLE,
    FDR_DEPLOY_LABEL,
    DashboardPage,
    FdrDeployPanel,
    OperatorDashboard,
    main,
    require_streamlit,
)
from .errors import (
    DashboardRenderError,
    EvaluationLogError,
    FdrDeployMetricError,
    LiveMetricError,
    MetaOverfitGapError,
    OpsError,
    ReplayLogError,
)
from .evaluation_log import (
    EVALUATION_LOG_LEVEL,
    EVALUATION_LOG_LOGGER_NAME,
    EvaluationLogRecord,
    emit_evaluation_log,
)
from .fdr_route import (
    FDR_DEPLOY_ROUTE,
    FdrDeployEndpoint,
    FdrDeployResponse,
    require_scoring,
)
from .live_metrics import (
    DATABASE_URL_ENV,
    LIVE_METRIC_TABLE,
    LIVE_METRICS,
    OPS_LIVE_METRIC_COMPONENT_NAME,
    LiveMetric,
    LiveMetricsStore,
)
from .meta_overfit import (
    META_OVERFIT_TABLE,
    OPS_META_OVERFIT_COMPONENT_NAME,
    MetaOverfitGap,
    MetaOverfitGaps,
)
from .replay_log import (
    REPLAY_LOG_LEVEL,
    REPLAY_LOG_LOGGER_NAME,
    ReplayLogRecord,
    emit_replay_log,
)

__all__ = [
    "DASHBOARD_PAGE_TITLE",
    "DASHBOARD_TITLE",
    "DATABASE_URL_ENV",
    "EPOCH_COUNT_LABEL",
    "EVALUATION_LOG_LEVEL",
    "EVALUATION_LOG_LOGGER_NAME",
    "FDR_DEPLOY_LABEL",
    "FDR_DEPLOY_ROUTE",
    "LIVE_METRICS",
    "LIVE_METRIC_TABLE",
    "META_OVERFIT_TABLE",
    "OPS_COMPONENT_NAME",
    "OPS_DASHBOARD_COMPONENT_NAME",
    "OPS_LIVE_METRIC_COMPONENT_NAME",
    "OPS_META_OVERFIT_COMPONENT_NAME",
    "REPLAY_LOG_LEVEL",
    "REPLAY_LOG_LOGGER_NAME",
    "DashboardPage",
    "DashboardRenderError",
    "EpochCountChrome",
    "EpochCountGauge",
    "EvaluationLogError",
    "EvaluationLogRecord",
    "FdrDeployEndpoint",
    "FdrDeployMetricError",
    "FdrDeployPanel",
    "FdrDeployResponse",
    "LiveMetric",
    "LiveMetricError",
    "LiveMetricsStore",
    "MetaOverfitGap",
    "MetaOverfitGapError",
    "MetaOverfitGaps",
    "OperatorDashboard",
    "OpsError",
    "ReplayLogError",
    "ReplayLogRecord",
    "emit_evaluation_log",
    "emit_replay_log",
    "main",
    "require_promotion",
    "require_scoring",
    "require_streamlit",
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


#: The component name the member registers its dashboard under — the
#: route component's peer under the same member-first prefix
#: (:data:`OPS_COMPONENT_NAME` above), so the category's surfaces sort
#: beside each other in a composed application's ``order``: the route
#: that answers the top-line figure, then the operator surface that
#: renders it.  Spelled in the app package seat
#: (:mod:`app.modules.ops`) as well, and the member's suite asserts the
#: two agree.
OPS_DASHBOARD_COMPONENT_NAME = "ops-dashboard"


@register(OPS_DASHBOARD_COMPONENT_NAME)
def build_operator_dashboard() -> OperatorDashboard | None:
    """Component builder: feature 351's dashboard, over the same store
    the route composes on.

    Takes no arguments — the factory's registration protocol — and
    decides at build time only what the route's own builder decides:
    whether ``DATABASE_URL`` names a store.  The dashboard is built
    over :meth:`~ops.dashboard.OperatorDashboard.from_env`, which wraps
    the route's own ``from_env`` door, so the two components compose on
    exactly the same decision and point at exactly the same database —
    the agreement the member's suite pins both ways, the composition
    fact §16's *"single Postgres metrics table"* allowance stands on.

    Returns ``None`` when no ``DATABASE_URL`` is configured — the
    composed application simply carries no dashboard, mirroring the
    route builder beside it.  Building performs no I/O and imports no
    sibling and no UI library: streamlit and the scoring member are
    both deferred past builder time (the render and the qualifier are
    where they are first needed), so whole-workspace composition never
    depends on their being importable at build time.

    What the composed dashboard is *for* is stated in
    :mod:`ops.dashboard`'s own docstring: the page factory and render
    seam the operator's ``streamlit run`` lands on, and the reflection
    a composed application carries for callers that ask for the
    surface by name.
    """
    return OperatorDashboard.from_env()


#: The component name the member registers its live-metrics store under —
#: the route and dashboard's peer under the same member-first prefix
#: (:data:`OPS_COMPONENT_NAME`, :data:`OPS_DASHBOARD_COMPONENT_NAME`), so a
#: composed application's ``order`` sorts this member's components *beside*
#: — never inside — another member's.  Spelled in the app package seat
#: (:mod:`app.modules.ops`) as well, and the member's suite asserts the two
#: agree.  The growth was reserved by the member's own registration when
#: feature 341 landed and the app-package seat reserved beside it (*"344-347's
#: and 350's persisted metrics arrive as this member's own tables"*).
@register(OPS_LIVE_METRIC_COMPONENT_NAME)
def build_live_metric_store() -> LiveMetricsStore | None:
    """Component builder: feature 350's live-metrics store, bound to the
    store ``DATABASE_URL`` names.

    Takes no arguments — the factory's registration protocol — and decides at
    build time only what the route's own builder decides: whether
    ``DATABASE_URL`` names a store.  It resolves the URL itself rather than
    importing any sibling, so whole-workspace composition never depends on a
    member that is not promised to be on ``sys.path`` at build time — the
    store is stdlib-only by design, and the URL is the one composition fact
    the route, the dashboard and this store all share.

    Returns ``None`` when no ``DATABASE_URL`` is configured — an unconfigured
    store is a discoverable deployment state, not an exception, the same
    stance the route and dashboard builders beside it take — so a deployment
    without a relational store still composes.  Building performs no I/O: no
    store is constructed, no database opened, no schema created — the first
    :meth:`~ops.live_metrics.LiveMetricsStore.record` is where the store is
    both constructed and asked.
    """
    return LiveMetricsStore.resolve()


@register(OPS_META_OVERFIT_COMPONENT_NAME)
def build_meta_overfit_store() -> MetaOverfitGaps | None:
    """Component builder: feature 347's meta-overfit gap store, bound to
    the store ``DATABASE_URL`` names.

    Takes no arguments — the factory's registration protocol — and decides
    at build time only what the live-metrics store's builder beside it
    decides: whether ``DATABASE_URL`` names a store.  It resolves the URL
    itself rather than importing any sibling, so whole-workspace
    composition never depends on a member that is not promised to be on
    ``sys.path`` at build time — the store is stdlib-only by design, and
    the URL is the one composition fact the route, the dashboard and the
    member's other two stores all share.

    Returns ``None`` when no ``DATABASE_URL`` is configured — an
    unconfigured store is a discoverable deployment state, not an
    exception, the same stance the route, dashboard and live-metrics
    builders take — so a deployment without a relational store still
    composes.  Building performs no I/O: no store is constructed, no
    database opened, no schema created — the first
    :meth:`~ops.meta_overfit.MetaOverfitGaps.record` is where the store is
    both constructed and asked.
    """
    return MetaOverfitGaps.resolve()
