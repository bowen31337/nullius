"""Feature 351's surface: the Streamlit dashboard, primary panel first.

app_spec.xml, "Observability & Dashboards", feature 351: *System renders
a Streamlit dashboard whose primary panel displays FDR_deploy rather
than an equity curve.*  The category's root (feature 341, the GET
/metrics/fdr-deploy route) established the seam every later feature
hangs from; this module is the one that hangs a *screen* from it — the
operator surface the spec's ``ui_layout`` draws: *"Operator surface is
a Streamlit dashboard reading the Postgres metrics table, which is the
simpler option the architecture explicitly permits at this scale.  The
primary panel is FDR_deploy with its provenance triple"* (docs §16's
stack line: *"a single Postgres metrics table with a Streamlit
dashboard if you would rather not run infrastructure"*).

**§16's one bolded sentence is the whole design brief.**  *"**The
top-line dashboard number is ``FDR_deploy``, not Sharpe.**  If the
primary chart is an equity curve, the system's actual purpose has been
quietly abandoned."*  The app spec's design system carries the rule
over as the one binding presentation rule in scope (*"the top-line
number is FDR_deploy and never an equity curve; any panel that would
promote profit above epistemic state is rejected at review"*) and its
success criteria state the acceptance test (*"The operator reads
FDR_deploy as the primary figure with its provenance triple visible …
No screen presents an equity curve above the fold"*).  This module
holds that law three ways, each concrete:

* **structurally** — the page model (:class:`DashboardPage`) has
  exactly one primary seat, and the only type that fills it
  (:class:`FdrDeployPanel`) is derived wholly from feature 341's
  :class:`~ops.fdr_route.FdrDeployResponse`; there is no field
  anywhere on the model a returns series, a NAV curve or a Sharpe
  could occupy, so the substitution cannot be *represented*, let
  alone rendered;
* **at review** — constructing a page whose primary panel does not
  answer the FDR panel's display contract is refused by name
  (:class:`~ops.errors.DashboardRenderError`), the model-level
  spelling of the spec's "rejected at review": the failure §16 names
  is a *quiet* abandonment, and a quiet acceptance of a foreign
  primary panel is the same failure one layer up;
* **in order** — :meth:`OperatorDashboard.render` emits the primary
  panel's numeral before any chart and draws the only chart it ever
  draws from the panel's own FDR_deploy trend, so nothing renders
  above the fold but epistemic state.

**The page is a reader of the route, the route a reader of the store.**
The dashboard owns no figure of its own — the member's law, stated in
its package docstring, is delegation — so :class:`FdrDeployPanel` is
built from feature 341's response and derives every display read from
it: the numeral is the response's newest campaign figure, the
provenance visible beside it is the response's own triple (the
campaign that measured it and the instant it was computed), and the
trend drawn below the fold is the same history the numeral was drawn
from — one answer, not two that could disagree.  prd §4.1.3's barred
figure (the raw in-campaign rate) is unreachable here by the same
delegation: the response cannot carry it, so no panel built from a
response can display it.

**The qualifier beside the figure is read from the one spelling.**
§16 lists the research metric as *"``FDR_deploy`` at π₀ = 0.9"*, and
the scoring member's own law is that *"the base rate travels in the
row beside the number"* — so the panel's headline carries the
qualifier, read at display time through
:func:`~ops.fdr_route.require_scoring` from
:data:`scoring.DEPLOYMENT_BASE_RATE` (π₀, spelled once in
:mod:`scoring._fdr`), never re-stated as a literal here: a dashboard
that hard-coded ``0.9`` would be a second place the deployment
projection's constant could drift from the one feature 267 reweights
under and the M3 gate judges.

**An empty trend renders an honest absence, never a flawless numeral.**
Feature 341's route answers a deployment that has closed no campaign
with ``None`` figures and a falsy value, and its own docstring hands
this surface its law: *"The dashboard this route feeds renders no
numeral for it; what it must never render is a flawless one."*  The
render emits a dash where the numeral would be and words that say why
— no ``0.0``, which is a *measurement* (a campaign that projected to
no false discoveries), and no chart of an empty series either.

**An absent route is refused, never answered around.**  The seat's
docstring (:mod:`app.modules.ops`) names this module as the caller
that must take exactly this stance: *"a caller that needs the
top-line figure and resolves ``None`` must refuse to proceed rather
than rendering a numeral nobody measured.  The dashboard this route
feeds (feature 351's) is that caller."*  :meth:`OperatorDashboard.
composed` honours it — a composed application that carries no
``ops-fdr-deploy`` route (no ``DATABASE_URL``, member not scanned) is
refused with :class:`~ops.errors.DashboardRenderError` naming the
repair — and a *failed* read propagates as feature 341's own
:class:`~ops.errors.FdrDeployMetricError`, already this member's
vocabulary: re-wrapping it would only bury the route that refused.

**Streamlit is the deployment's ambient dependency, not a workspace
one.**  §16's stack line names Streamlit the way it names Postgres —
an environment the operator runs, not a library the research loop
links against — so this member's pyproject gains no third-party edge
and the lockfile none either, and the render seam is duck-typed: the
carrier is handed in (:meth:`OperatorDashboard.render`'s ``st``) or
resolved through :func:`require_streamlit`, deferred past module scope
for the same scan-order reason :func:`~ops.fdr_route.require_scoring`
defers the scoring member — a module-scope ``import streamlit`` would
make this package's *import* depend on an environment the factory's
scan never promised to have it.  The contract is the calls the render
makes (``set_page_config``, ``title``, ``header``, ``metric``,
``caption``, ``line_chart``), duck-checked rather than
``isinstance``-guarded, because the factory's scan imports members
under synthetic names and the contract — not the class — is what
crosses every seam in this workspace.  The numeral is rendered
without a ``delta``: Streamlit colours a delta green-up, and the
figure has no "up is good" direction — a lower false discovery rate
is better — so the colour would state the opposite of the measurement
(green-up / red-down is also the first row of docs/design.md's
explicitly rejected table, though that document's console is out of
scope for this spec).

**The entrypoint is the module itself.**  ``streamlit run
packages/ops/src/ops/dashboard.py`` executes this file as a script,
outside the package import machinery, so the guard at the top of the
module puts the member's ``src/`` on ``sys.path`` and resolves
``__package__`` before the relative imports run — the same
reach-the-package-root discipline the member's test suites bootstrap
with — and the ``__main__`` block at the bottom calls :func:`main`,
which composes the application through the seat and renders.  A rerun
(Streamlit re-executes the page on every interaction) re-runs the
whole path: the route holds no cache, so the numeral is the store's
state at the moment of the rerun, not a fact about when the page was
first opened.

Stdlib-only, like the rest of the member: :mod:`dataclasses` for the
page model, :mod:`typing` for ``Any``/``Optional`` — streamlit and the
scoring member are both deferred past module scope and past builder
time, so importing this module (and composing the component it
registers) performs no I/O and no sibling import.
"""

from __future__ import annotations

if __package__ in (None, ""):  # pragma: no cover - the streamlit-run script path
    # `streamlit run packages/ops/src/ops/dashboard.py` executes this
    # file as a script: no package context, so the relative imports
    # below would fail before the dashboard ever rendered.  Put the
    # member's src/ on sys.path and resolve __package__ — the same
    # reach-the-package-root bootstrap the member's test suites use —
    # and only when the module is NOT being imported as ops.dashboard.
    import sys as _sys
    from pathlib import Path as _Path

    _member_src = str(_Path(__file__).resolve().parents[1])
    if _member_src not in _sys.path:
        _sys.path.insert(0, _member_src)
    __package__ = "ops"

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

from app.modules.ops import fdr_deploy_component

from .errors import DashboardRenderError
from .fdr_route import (
    FDR_DEPLOY_ROUTE,
    FdrDeployEndpoint,
    FdrDeployResponse,
    require_scoring,
)

__all__ = [
    "DASHBOARD_PAGE_TITLE",
    "DASHBOARD_TITLE",
    "FDR_DEPLOY_LABEL",
    "DashboardPage",
    "FdrDeployPanel",
    "OperatorDashboard",
    "main",
    "require_streamlit",
]

#: The primary metric's label — §16's own spelling of the top-line
#: number's name ("The top-line dashboard number is ``FDR_deploy``, not
#: Sharpe"), carried once so the numeral's label, the panel's headline
#: and the spec's figure cannot drift apart on the name.
FDR_DEPLOY_LABEL = "FDR_deploy"

#: The dashboard's visible title — one word, the deployment's name.
#: Chrome, not content: it states whose metrics these are and nothing
#: else (no return figure in the navigation — there is no screen where
#: that is the question being asked).
DASHBOARD_TITLE = "Nullius"

#: The browser tab's title for the dashboard page — the Streamlit page
#: configuration's ``page_title``, emitted before anything renders
#: because Streamlit only honours it as the first command on the page.
DASHBOARD_PAGE_TITLE = "Nullius — deployment metrics"

#: The primary panel's display contract — the reads the render makes of
#: whatever occupies the page's primary seat.  A carrier that does not
#: answer them all is not an FDR_deploy panel, and the page refuses it
#: (see :class:`DashboardPage`): the named, actionable spelling of the
#: spec's "rejected at review".
_PRIMARY_PANEL_CONTRACT = (
    "figure",
    "trend",
    "qualifier",
    "headline",
    "numeral",
    "plate",
    "series",
)

#: The Streamlit calls the render makes — the whole contract a render
#: carrier must answer, spelled once so the duck-check, the render and
#: the tests cannot drift apart on what "a streamlit" is here.
_RENDER_CARRIER_CONTRACT = (
    "set_page_config",
    "title",
    "header",
    "metric",
    "caption",
    "line_chart",
)


def require_streamlit() -> Any:
    """Import and return the :mod:`streamlit` module, or raise loudly.

    The mirror of :func:`~ops.fdr_route.require_scoring`, for the one
    ambient dependency this member's surface renders through.  Deferred
    past module scope and past builder time for the same scan-order
    reason: the factory's workspace scan imports this package to fire
    its ``@register``, and nothing promises the scanning environment
    carries a UI library the research loop never links against — §16's
    stack line names Streamlit the way it names Postgres, an
    environment the operator runs.  A deployment that genuinely renders
    the dashboard is told which wheel is missing rather than shown a
    bare :class:`ImportError`.
    """
    try:
        import streamlit
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "the ops member's dashboard renders through Streamlit (docs "
            "§16's stack line: a single metrics table with a Streamlit "
            "dashboard), and Streamlit is not importable in this "
            "environment; install it where the dashboard runs (uv pip "
            "install streamlit in the deployment environment) — the "
            "workspace lockfile deliberately carries no third-party edge "
            "for it, so the render seam stays duck-typed and this member "
            "imports without it (feature 351, docs §16)"
        ) from exc
    return streamlit


@dataclass(frozen=True, slots=True)
class FdrDeployPanel:
    """The dashboard's primary panel: §16's top-line figure, with its
    provenance visible beside it.

    Thin by design — the member's law is delegation, and every
    guarantee this panel's reads enjoy was earned by the value it
    holds: feature 341's :class:`~ops.fdr_route.FdrDeployResponse`,
    whose construction already rebuilt and narrowed the whole trend
    (each triple validated, the order held, the newest row the top
    line).  The panel adds exactly the display-shaped reads a render
    needs and re-spells nothing: no second validation of the figures,
    no second derivation of the top line, no base-rate literal (the
    qualifier is read through the scoring member's one spelling,
    :data:`scoring.DEPLOYMENT_BASE_RATE`, at display time).

    The provenance the spec's ``ui_layout`` demands visible — *"The
    primary panel is FDR_deploy with its provenance triple"* — is the
    response's own: :attr:`figure` (the numeral), :attr:`campaign_id`
    and :attr:`computed_at` (the plate that attributes it), with
    :attr:`qualifier` beside them as §16's line carries it
    (*"``FDR_deploy`` at π₀ = 0.9"*).  A top-line number an operator
    cannot attribute to the campaign that measured it is a number
    nobody can audit — the reasoning the route's own docstring gives
    for identifying the figure it answers.

    There is deliberately no field an equity curve could occupy.  The
    panel's whole surface is the FDR_deploy trend; a returns series,
    a NAV curve or a Sharpe has nowhere to land on this type, which is
    the structural half of the feature's *"rather than an equity
    curve"* clause — the refusal half lives at
    :class:`DashboardPage`, the ordering half in
    :meth:`OperatorDashboard.render`.

    An empty trend is the honest absence: falsy, every derived read
    ``None`` or empty — never ``0.0``, which would be a measurement no
    campaign made.
    """

    #: Feature 341's testimony — the validated per-campaign history the
    #: panel's every read derives from.
    response: FdrDeployResponse

    @property
    def figure(self) -> Optional[float]:
        """§16's number: the newest campaign's ``FDR_deploy``, the
        deployment projection at π₀.  ``None`` when no campaign has
        closed — an absence, never a zero."""
        return self.response.fdr_deploy

    @property
    def campaign_id(self) -> Optional[str]:
        """The campaign the figure belongs to — its plate."""
        return self.response.campaign_id

    @property
    def computed_at(self) -> Optional[str]:
        """When the figure's campaign was computed (ISO 8601 UTC)."""
        return self.response.computed_at

    @property
    def trend(self) -> tuple[tuple[str, float, str], ...]:
        """The per-campaign figures, oldest first — the same history
        the numeral was drawn from, read as one answer."""
        return self.response.history

    @property
    def qualifier(self) -> float:
        """The deployment base rate the figure is pinned to — π₀, read
        from :data:`scoring.DEPLOYMENT_BASE_RATE` through the member's
        one deferred door, never re-spelled as a literal here."""
        return require_scoring().DEPLOYMENT_BASE_RATE

    @property
    def headline(self) -> str:
        """The panel's heading — §16's own line for the metric:
        ``"FDR_deploy at π₀ = 0.9"``, the qualifier carried beside the
        figure the way the scoring member's rows carry it beside the
        number."""
        return f"{FDR_DEPLOY_LABEL} at π₀ = {self.qualifier:g}"

    @property
    def numeral(self) -> Optional[str]:
        """The figure as the render displays it — a percentage, the
        form prd §11's target is stated in (*"< 25% at π₀ = 0.9"*).
        ``None`` when no campaign has closed: the render shows a dash,
        never a zero that would answer "a flawless system" for a
        deployment that never ran."""
        figure = self.figure
        return None if figure is None else f"{figure:.1%}"

    @property
    def plate(self) -> Optional[str]:
        """The provenance rendered beneath the numeral — the campaign
        that measured it and the instant it was computed.  ``None``
        when there is no figure to attribute."""
        if self.campaign_id is None:
            return None
        return f"campaign {self.campaign_id}, computed {self.computed_at}"

    @property
    def series(self) -> tuple[float, ...]:
        """The trend's figures, oldest first — the only series this
        panel can offer a chart, and the only one the dashboard ever
        draws."""
        return tuple(figure for _campaign, figure, _instant in self.trend)

    def __bool__(self) -> bool:
        """Whether the deployment has closed a campaign at all — the
        same split the response pins: an absence (``False``, render no
        numeral) is not a measured ``0.0`` (``True``, render it)."""
        return bool(self.response)


@dataclass(frozen=True, slots=True)
class DashboardPage:
    """The dashboard's whole page: one primary panel, first.

    The page model exists to hold the feature's ordering law where a
    test can reach it: the primary seat is the page's first and
    defining content, and the panel that fills it is the FDR one.
    Construction is the spec's review — *"any panel that would promote
    profit above epistemic state is rejected at review"* — made
    executable: a primary carrier that does not answer the FDR panel's
    display contract (:data:`_PRIMARY_PANEL_CONTRACT`) is refused by
    name, with §16's abandonment sentence in the refusal, because the
    failure that law describes is a quiet one — an equity curve that
    drifts into the primary seat renders nothing here, and the page
    says so instead.

    The check is duck-typed, not ``isinstance``-guarded, for the
    reason every seam in this workspace gives: the factory's scan
    imports members under synthetic names, so a composed panel is
    structurally this member's without being the same class object a
    direct import yields.  The contract is the panel's public reads —
    and a carrier that answers all of them *is* an FDR_deploy panel
    for every purpose the render has.

    Later features of this category hang their own content off the
    page (352's permanent chrome beside the primary panel) without
    touching the primary seat, which is the point of modelling the seat
    explicitly: chrome grows, the top line does not move.
    """

    primary: FdrDeployPanel

    def __post_init__(self) -> None:
        missing = [
            name
            for name in _PRIMARY_PANEL_CONTRACT
            if not hasattr(self.primary, name)
        ]
        if missing:
            raise DashboardRenderError(
                f"a DashboardPage's primary panel is the FDR_deploy one "
                f"(an {FdrDeployPanel.__name__} or any carrier answering "
                f"its display contract: "
                f"{', '.join(_PRIMARY_PANEL_CONTRACT)}), and this carrier "
                f"does not answer: {', '.join(missing)}. Docs §16: 'If "
                f"the primary chart is an equity curve, the system's "
                f"actual purpose has been quietly abandoned' — the page "
                f"is the review that spec names, and the primary seat is "
                f"refused rather than rendered with a panel that promotes "
                f"anything above epistemic state (feature 351, docs §16)"
            )


class OperatorDashboard:
    """The operator surface: the primary panel, rendered over the
    composed route.

    Constructed over the route (:class:`~ops.fdr_route.FdrDeployEndpoint`
    or any carrier answering its ``get()``), and every render is a
    fresh read — the dashboard holds no cache of a previous page, for
    the reason the endpoint holds none: a campaign closed between two
    renders must move the second numeral, and a cached figure would
    make the dashboard's top line a fact about when the page was first
    opened rather than about what the system measured.

    Two construction doors, one law each:

    * :meth:`from_env` — the builder's door, over the store
      ``DATABASE_URL`` names; ``None`` when it names none (an
      unconfigured store is a discoverable deployment state, and the
      composed application simply carries no dashboard, exactly as it
      carries no route);
    * :meth:`composed` — the operator's door, through the seat in the
      app package namespace; a composed application that carries no
      route is *refused*, because a render asked for by name is a
      caller that needs the figure and must not be shown a numeral
      nobody measured.
    """

    def __init__(self, route: Any) -> None:
        if not callable(getattr(route, "get", None)):
            raise TypeError(
                "OperatorDashboard renders over the composed fdr-deploy "
                "route (something with a get() answering feature 341's "
                f"GET {FDR_DEPLOY_ROUTE} response); got "
                f"{type(route).__name__}. The primary panel is §16's "
                "top-line figure read through the route that owns it, "
                "and a carrier that cannot answer the route's response "
                "cannot name the figure a dashboard would render "
                "(feature 351, docs §16)"
            )
        self._route = route

    @property
    def route(self) -> Any:
        """The route this dashboard reads — feature 341's, held
        duck-typed across the seam."""
        return self._route

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["OperatorDashboard"]:
        """The dashboard over the route ``DATABASE_URL`` names, or
        ``None`` when it names none.

        The route's own :meth:`~ops.fdr_route.FdrDeployEndpoint.from_env`
        decides composition (absent, empty and whitespace-only all
        unset) and carries the deferred store — this door only wraps
        it, so the dashboard composes exactly when the route does and
        over the same database, with no second resolution to drift.
        """
        route = FdrDeployEndpoint.from_env(env)
        return None if route is None else cls(route)

    @classmethod
    def composed(cls, app: Any = None) -> "OperatorDashboard":
        """The dashboard over the application's composed route.

        Reached through the seat (:func:`app.modules.ops.
        fdr_deploy_component`) — the accessor whose docstring names
        this surface as its caller — so the operator surface never
        imports the member's store directly and never grows a second
        reader of the per-campaign rows.  With ``app`` given the
        component is read from it; without one the application is
        composed first (the full declared workspace, in the
        environment the dashboard runs in).

        A composition that carries no ``ops-fdr-deploy`` component is
        refused: :class:`~ops.errors.DashboardRenderError`, naming the
        route and the environment variable that would compose it.  The
        alternative — rendering on without the figure — is the
        quietly-defaulted number this category exists to rule out.
        """
        route = fdr_deploy_component(app)
        if route is None:
            raise DashboardRenderError(
                f"the dashboard cannot render: the composed application "
                f"carries no {FDR_DEPLOY_ROUTE} route (no ops-fdr-deploy "
                f"component — most often no DATABASE_URL configured, or "
                f"the ops member not scanned). The primary panel is docs "
                f"§16's top-line figure, and an operator surface that "
                f"needs it refuses to proceed rather than rendering a "
                f"numeral nobody measured; point DATABASE_URL at the "
                f"metrics store and compose again (feature 351, docs §16)"
            )
        return cls(route)

    # -- The page and its render ---------------------------------------------

    def page(self) -> DashboardPage:
        """One fresh page over the route's answer.

        The whole read is the route's ``get()`` — the store's own
        history, figures already rebuilt from the pair each row
        carries — and the page is built from the response alone.  A
        read that fails propagates as feature 341's
        :class:`~ops.errors.FdrDeployMetricError`: already this
        member's vocabulary, already translated at the route's seam,
        and re-wrapping it here would only bury which surface refused.
        """
        return DashboardPage(primary=FdrDeployPanel(response=self._route.get()))

    def render(self, st: Any = None) -> DashboardPage:
        """Render one page through Streamlit and answer it.

        ``st`` is the render carrier — the real :mod:`streamlit`
        module when handed ``None`` (resolved through
        :func:`require_streamlit`), or any duck-typed stand-in a test
        records calls on.  The carrier is checked against the render
        contract (:data:`_RENDER_CARRIER_CONTRACT`) before anything
        emits, the same duck-check discipline the endpoint applies its
        store.

        The order is the feature's law, made literal: page
        configuration, the title, then the primary panel — its
        headline (the qualifier beside the figure's name), its numeral
        (no delta: the figure has no green-up direction), its
        provenance plate — and only then the one chart the dashboard
        draws, the panel's own FDR_deploy trend.  Nothing renders
        above the numeral; nothing but the trend is ever charted.
        The page answered is the page that rendered, so a caller (or a
        test) can read exactly what the operator saw.
        """
        carrier = require_streamlit() if st is None else st
        missing = [
            name for name in _RENDER_CARRIER_CONTRACT
            if not callable(getattr(carrier, name, None))
        ]
        if missing:
            raise TypeError(
                "OperatorDashboard renders through a Streamlit carrier "
                f"(something callable for each of "
                f"{', '.join(_RENDER_CARRIER_CONTRACT)}); this carrier "
                f"does not answer: {', '.join(missing)}. The render is "
                f"duck-typed so the workspace never depends on the UI "
                f"library, and a carrier that cannot answer the calls "
                f"cannot render the primary panel (feature 351, docs §16)"
            )
        page = self.page()
        panel = page.primary
        carrier.set_page_config(page_title=DASHBOARD_PAGE_TITLE)
        carrier.title(DASHBOARD_TITLE)
        carrier.header(panel.headline)
        carrier.metric(label=FDR_DEPLOY_LABEL, value=panel.numeral or "—")
        if panel:
            carrier.caption(panel.plate or "")
            carrier.line_chart(list(panel.series))
        else:
            carrier.caption(
                "no campaign has closed, so no figure was measured"
            )
        return page


def main(app: Any = None, st: Any = None) -> DashboardPage:
    """The Streamlit entrypoint: compose, then render.

    What ``streamlit run packages/ops/src/ops/dashboard.py`` lands on
    (through the ``__main__`` guard below).  The application is
    composed through the seat — the dashboard reads the *composed*
    route, the one the deployment's process actually carries — and the
    page renders through the real :mod:`streamlit`.  Both doors are
    parameterised so the entrypoint is testable without a UI process:
    ``app`` hands in an already-composed application, ``st`` a
    recording carrier.

    Every rerun re-runs the whole path: compose, read, render.  There
    is no cache anywhere in it, by design — the numeral on the screen
    is the store's state at the moment of the rerun.
    """
    return OperatorDashboard.composed(app).render(st)


if __name__ == "__main__":  # pragma: no cover - the streamlit-run path
    main()
