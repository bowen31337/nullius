"""Feature 351's surface: the Streamlit dashboard, primary panel first.

These tests hold the dashboard to its own sentence — *renders a
Streamlit dashboard whose primary panel displays FDR_deploy rather
than an equity curve* — from the side the member owns.  The figure is
the route's (feature 341, over feature 267's rows); what is pinned
here is the screen: the page model that has nowhere for an equity
curve to land, the review that refuses a foreign primary panel by
name, the render order that puts the numeral above every chart, the
honest absence for a deployment that has closed no campaign, and the
refusal — never a fallback numeral — when the route cannot be had.

Streamlit is absent from this environment by design (the workspace
lockfile carries no third-party edge for it), so the render is tested
through a recording carrier duck-shaped like the module — which is
the whole contract, the same way the route's store is tested through
duck-typed carriers — and the real module is reached only through the
deferred door, whose repair words the absent case pins.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import runpy
import sys
import types
import uuid
from pathlib import Path

import pytest
import scoring
from ops import (
    DASHBOARD_PAGE_TITLE,
    DASHBOARD_TITLE,
    FDR_DEPLOY_LABEL,
    OPS_DASHBOARD_COMPONENT_NAME,
    DashboardPage,
    DashboardRenderError,
    FdrDeployEndpoint,
    FdrDeployPanel,
    FdrDeployResponse,
    OperatorDashboard,
    OpsError,
    main,
    require_streamlit,
)

from app.module_loader import Application, Registration, create_app, scan_components
from app.modules import ops as ops_seat

MEMBER_SRC = Path(__import__("ops").__file__).resolve().parent.parent

#: The Streamlit calls the render makes, in the order the render makes
#: them — the feature's ordering law, asserted as the exact transcript.
RENDER_SEQUENCE = (
    "set_page_config",
    "title",
    "header",
    "metric",
    "caption",
    "line_chart",
)

STREAMLIT_INSTALLED = importlib.util.find_spec("streamlit") is not None


class _Pair:
    """A stand-in for feature 266's calibration figures — exactly the
    two attributes the reweighting reads, and nothing else."""

    __slots__ = ("sensitivity", "specificity")

    def __init__(self, sensitivity: float, specificity: float) -> None:
        self.sensitivity = sensitivity
        self.specificity = specificity


class _RecordingStreamlit:
    """A duck-typed stand-in for the ``streamlit`` module — one entry
    per call, in order, which is what makes the render's *order* (the
    feature's law) assertable without the UI library."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _call(*args, **kwargs) -> None:
            self.calls.append((name, args, kwargs))

        return _call

    @property
    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]

    def one(self, name: str) -> tuple[tuple, dict]:
        """The single call emitted under ``name`` (there is at most one
        of each in a page render)."""
        matching = [call for call in self.calls if call[0] == name]
        assert len(matching) == 1, f"expected one {name}, got {matching}"
        return matching[0][1], matching[0][2]


def _persisted_store(test_database_url: str) -> scoring.FdrDeployStore:
    """The real store with two campaigns' figures landed through its
    own write, so the page under test reads real rows.  The pairs are
    chosen for their projections: a symmetric pair reweights to π₀
    (0.9), and the newest campaign's pair (sensitivity 0.45,
    specificity 0.95) reweights to exactly 0.5 — a clean numeral the
    render assertions can read."""
    store = scoring.FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.5, 0.5),
        computed_at="2026-01-01T00:00:00",
    )
    store.persist(
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
        _Pair(0.45, 0.95),
        computed_at="2026-02-01T00:00:00",
    )
    return store


def _dashboard(test_database_url: str) -> OperatorDashboard:
    return OperatorDashboard(FdrDeployEndpoint(_persisted_store(test_database_url)))


# -- the component and its spellings -------------------------------------------


def test_the_dashboard_component_name_is_spelled_once_everywhere() -> None:
    # The member's constant, the app-seat's constant and the composed
    # application's order are one string — three spellings of one name
    # is exactly the kind of drift a test is cheaper than.
    assert OPS_DASHBOARD_COMPONENT_NAME == "ops-dashboard"
    assert ops_seat.DASHBOARD_COMPONENT_NAME == OPS_DASHBOARD_COMPONENT_NAME


def test_the_scan_registers_both_surfaces_exactly_once() -> None:
    # The registration-lives-in-__init__ invariant, held for the second
    # component: a rescan replaces by name, so one dashboard survives
    # any number of compositions rather than silently dropping out of
    # every one after the first.
    import ops

    registry = Registration()
    names = [c.name for c in scan_components(MEMBER_SRC, registry=registry)]
    assert names.count(OPS_DASHBOARD_COMPONENT_NAME) == 1
    assert OPS_DASHBOARD_COMPONENT_NAME in names
    assert ops.OPS_COMPONENT_NAME in names
    again = [c.name for c in scan_components(MEMBER_SRC, registry=registry)]
    assert again.count(OPS_DASHBOARD_COMPONENT_NAME) == 1


# -- the page is the route's answer ---------------------------------------------


def test_the_page_derives_every_read_from_the_routes_response(
    test_database_url: str,
) -> None:
    # The member's law is delegation: the panel adds display-shaped
    # reads over feature 341's response and re-spells nothing — the
    # numeral is the response's top line, the trend the response's
    # history, one answer rather than two that could disagree.
    dashboard = _dashboard(test_database_url)
    response = FdrDeployEndpoint(_persisted_store(test_database_url)).get()
    panel = dashboard.page().primary

    assert panel.figure == response.fdr_deploy
    assert panel.campaign_id == response.campaign_id == "22222222-2222-2222-2222-222222222222"
    assert panel.computed_at == response.computed_at == "2026-02-01T00:00:00"
    assert panel.trend == response.history
    assert panel.series == tuple(figure for _c, figure, _i in response.history)


def test_the_provenance_triple_is_visible_beside_the_figure(
    test_database_url: str,
) -> None:
    # The spec's ui_layout: "The primary panel is FDR_deploy with its
    # provenance triple", and its success criteria: "The operator reads
    # FDR_deploy as the primary figure with its provenance triple
    # visible".  The numeral (the figure), the plate (the campaign and
    # instant that attribute it) and the headline (the qualifier §16
    # carries beside the number) are all on the panel a render reads.
    panel = _dashboard(test_database_url).page().primary
    assert panel.numeral == "50.0%"
    assert "22222222-2222-2222-2222-222222222222" in panel.plate
    assert "2026-02-01T00:00:00" in panel.plate
    assert panel.headline.startswith(FDR_DEPLOY_LABEL)


def test_the_qualifier_is_read_from_the_one_spelling(
    test_database_url: str,
) -> None:
    # §16 lists the metric as "FDR_deploy at π₀ = 0.9" and the scoring
    # member's law is that the base rate travels beside the number.
    # The panel reads it through the member's deferred door from
    # DEPLOYMENT_BASE_RATE — never a literal here, which would be a
    # second place the deployment projection's constant could drift.
    panel = _dashboard(test_database_url).page().primary
    assert panel.qualifier == scoring.DEPLOYMENT_BASE_RATE
    assert panel.headline == f"FDR_deploy at π₀ = {scoring.DEPLOYMENT_BASE_RATE:g}"


def test_the_numeral_is_the_percentage_the_target_is_stated_in(
    test_database_url: str,
) -> None:
    # prd §11's target is "< 25% at π₀ = 0.9" — the form the operator
    # judges the figure in is a percentage, so that is the form the
    # render displays.  Both ends of [0, 1] are measurements and both
    # display.
    store = scoring.FdrDeployStore(test_database_url)
    store.persist(
        uuid.UUID("11111111-1111-1111-1111-111111111111"),
        _Pair(0.5, 1.0),
        computed_at="2026-01-01T00:00:00",
    )
    panel = OperatorDashboard(FdrDeployEndpoint(store)).page().primary
    assert panel.figure == 0.0
    assert panel.numeral == "0.0%"

    store.persist(
        uuid.UUID("22222222-2222-2222-2222-222222222222"),
        _Pair(0.0, 0.5),
        computed_at="2026-02-01T00:00:00",
    )
    assert panel.figure == 0.0  # the panel is frozen testimony
    fresh = OperatorDashboard(FdrDeployEndpoint(store)).page().primary
    assert fresh.figure == 1.0
    assert fresh.numeral == "100.0%"


def test_a_campaign_closed_between_two_renders_moves_the_numeral(
    test_database_url: str,
) -> None:
    # No cache anywhere in the dashboard: the route holds none, the
    # page is built fresh per render, and a campaign closed between two
    # renders moves the second numeral — a cached figure would make
    # the top line a fact about when the page was first opened.
    store = _persisted_store(test_database_url)
    dashboard = OperatorDashboard(FdrDeployEndpoint(store))
    assert dashboard.render(_RecordingStreamlit()).primary.figure == pytest.approx(0.5)

    newest = store.persist(
        uuid.UUID("33333333-3333-3333-3333-333333333333"),
        _Pair(0.75, 0.75),
        computed_at="2026-03-01T00:00:00",
    )
    page = dashboard.render(_RecordingStreamlit())
    assert page.primary.figure == newest == pytest.approx(0.75)
    assert newest != pytest.approx(0.5)
    assert page.primary.campaign_id == "33333333-3333-3333-3333-333333333333"


def test_the_page_is_frozen_testimony(test_database_url: str) -> None:
    # The page is the route's testimony at the moment it was read;
    # nothing on it is a knob to adjust.
    page = _dashboard(test_database_url).page()
    with pytest.raises(dataclasses.FrozenInstanceError):
        page.primary = page.primary  # type: ignore[misc]


# -- the honest absence ----------------------------------------------------------


def test_an_empty_trend_renders_no_numeral_ever_a_flawless_one(
    test_database_url: str,
) -> None:
    # Feature 341's docstring hands this surface its law: "The
    # dashboard this route feeds renders no numeral for it; what it
    # must never render is a flawless one."  A dash where the numeral
    # would be, words that say why, and no chart of an empty series.
    dashboard = OperatorDashboard(FdrDeployEndpoint(scoring.FdrDeployStore(test_database_url)))
    panel = dashboard.page().primary
    assert not panel
    assert panel.figure is None
    assert panel.numeral is None
    assert panel.plate is None
    assert panel.series == ()

    st = _RecordingStreamlit()
    page = dashboard.render(st)
    assert not page.primary
    value = st.one("metric")[1]["value"]
    assert value == "—"
    assert value != "0.0%"
    caption = st.one("caption")[0][0]
    assert "no campaign has closed" in caption
    # No chart of an empty series: the trend chart is the panel's own,
    # and an absent trend has none to draw.
    assert "line_chart" not in st.names


# -- the render order is the law --------------------------------------------------


def test_the_render_emits_the_primary_panel_first(test_database_url: str) -> None:
    # The feature's clause made literal: page configuration, the
    # title, the primary panel — headline, numeral, plate — and only
    # then the one chart the dashboard draws, over the panel's own
    # FDR_deploy trend.  Nothing renders above the numeral but chrome,
    # and the only series ever charted is the trend's figures.
    st = _RecordingStreamlit()
    page = _dashboard(test_database_url).render(st)

    assert st.names == list(RENDER_SEQUENCE)
    assert st.names.index("metric") < st.names.index("line_chart")
    # The numeral is the primary panel's, labelled with the metric's
    # one spelling.
    metric_args, metric_kwargs = st.one("metric")
    assert not metric_args
    assert metric_kwargs["label"] == FDR_DEPLOY_LABEL
    assert metric_kwargs["value"] == page.primary.numeral
    # The header is the panel's headline — the qualifier beside the
    # figure's name, §16's own line.
    assert st.one("header")[0][0] == page.primary.headline
    # The plate renders the provenance beneath the numeral.
    assert st.one("caption")[0][0] == page.primary.plate
    # The one chart is the trend, and nothing else is charted.
    chart_args, _kwargs = st.one("line_chart")
    assert chart_args[0] == list(page.primary.series)
    assert st.one("set_page_config")[1]["page_title"] == DASHBOARD_PAGE_TITLE
    assert st.one("title")[0][0] == DASHBOARD_TITLE


def test_the_numeral_carries_no_delta(test_database_url: str) -> None:
    # Streamlit colours a metric delta green-up, and the figure has no
    # "up is good" direction — a lower false discovery rate is better —
    # so the colour would state the opposite of the measurement.  The
    # render passes exactly the label and the value.
    st = _RecordingStreamlit()
    _dashboard(test_database_url).render(st)
    _args, kwargs = st.one("metric")
    assert set(kwargs) == {"label", "value"}


def test_the_render_answers_the_page_it_rendered(test_database_url: str) -> None:
    # The caller (or the test) can read exactly what the operator saw:
    # the page answered is the page that rendered.
    dashboard = _dashboard(test_database_url)
    st = _RecordingStreamlit()
    assert dashboard.render(st) == dashboard.page()


# -- the review: rather than an equity curve --------------------------------------


def test_the_model_has_nowhere_for_an_equity_curve_to_land() -> None:
    # The structural half of the clause, pinned as a shape: the page
    # holds a primary seat, the panel holds the route's response, the
    # response holds the per-campaign FDR_deploy history — and that is
    # the whole surface, top to bottom.  A returns series, a NAV curve
    # or a Sharpe has no field anywhere on this path to occupy, so the
    # substitution cannot be represented, let alone rendered.
    assert [f.name for f in dataclasses.fields(DashboardPage)] == ["primary"]
    assert [f.name for f in dataclasses.fields(FdrDeployPanel)] == ["response"]
    assert [f.name for f in dataclasses.fields(FdrDeployResponse)] == ["history"]


def test_a_page_whose_primary_is_not_the_fdr_panel_is_refused() -> None:
    # The spec's design system: "any panel that would promote profit
    # above epistemic state is rejected at review".  The page model is
    # that review, made executable: an equity-curve panel — a carrier
    # of NAV points that answers none of the FDR panel's reads — is
    # refused by name, with §16's abandonment sentence in the refusal.
    class _EquityCurvePanel:
        """What the clause refuses: a P&L series posing as the primary
        panel — points of account equity, and not one epistemic read."""

        series = (100.0, 101.2, 99.8, 103.0)

    with pytest.raises(DashboardRenderError) as raised:
        DashboardPage(primary=_EquityCurvePanel())  # type: ignore[arg-type]
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "equity curve" in message
    assert "quietly abandoned" in message
    assert "series" in message


def test_the_primary_seat_judges_the_contract_not_the_class(
    test_database_url: str,
) -> None:
    # The factory's scan imports members under synthetic names, so a
    # composed panel is structurally this member's without being the
    # same class object a direct import yields — the seat duck-checks
    # the display contract, and a carrier that answers all of it *is*
    # an FDR_deploy panel for every purpose the render has.
    real = _dashboard(test_database_url).page().primary

    class _DuckPanel:
        figure = real.figure
        trend = real.trend
        qualifier = real.qualifier
        headline = real.headline
        numeral = real.numeral
        plate = real.plate
        series = real.series

    page = DashboardPage(primary=_DuckPanel())  # type: ignore[arg-type]
    assert page.primary.numeral == real.numeral


# -- the doors and their refusals -------------------------------------------------


def test_composed_refuses_when_the_route_is_absent() -> None:
    # The seat's docstring names this surface as the caller that must
    # refuse: "a caller that needs the top-line figure and resolves
    # None must refuse to proceed rather than rendering a numeral
    # nobody measured."  A composition with no ops route is refused
    # naming the repair — never answered around with a fallback.
    with pytest.raises(DashboardRenderError) as raised:
        OperatorDashboard.composed(Application())
    assert isinstance(raised.value, OpsError)
    message = str(raised.value)
    assert "/metrics/fdr-deploy" in message
    assert "DATABASE_URL" in message


def test_main_refuses_when_the_route_is_absent() -> None:
    # The entrypoint inherits the same law: nothing renders when the
    # figure cannot be had honestly.
    with pytest.raises(DashboardRenderError):
        main(app=Application(), st=_RecordingStreamlit())


def test_the_route_carrier_is_duck_checked() -> None:
    # The contract is the route's get() — the store itself is not
    # enough (it answers the trend, not the route's response), and the
    # refusal says so.
    with pytest.raises(TypeError, match="OperatorDashboard"):
        OperatorDashboard("sqlite:///nowhere.db")


def test_the_render_carrier_is_duck_checked(test_database_url: str) -> None:
    # The render contract is the Streamlit calls it makes; a carrier
    # that cannot answer them cannot render the primary panel.
    with pytest.raises(TypeError, match="OperatorDashboard"):
        _dashboard(test_database_url).render(object())


def test_a_failing_read_propagates_as_the_routes_own_vocabulary(
    test_database_url: str,
) -> None:
    # The route already translated the store's refusal into the
    # member's vocabulary; the dashboard neither re-wraps it (which
    # would bury which surface refused) nor catches it into an answer
    # (every fallback is a number nobody measured).
    from ops.errors import FdrDeployMetricError

    class _RefusingRoute:
        def get(self):
            raise FdrDeployMetricError("the route's own words")

    dashboard = OperatorDashboard(_RefusingRoute())
    with pytest.raises(FdrDeployMetricError, match="the route's own words"):
        dashboard.page()
    with pytest.raises(FdrDeployMetricError, match="the route's own words"):
        dashboard.render(_RecordingStreamlit())


def test_streamlit_is_resolved_lazily_and_names_its_repair(
    test_database_url: str,
) -> None:
    # The deferred door: §16's stack line names Streamlit the way it
    # names Postgres — an environment the operator runs, not a
    # workspace dependency — so the module is absent here by design,
    # and the render told to resolve it says which wheel is missing
    # rather than failing with a bare ImportError.
    dashboard = _dashboard(test_database_url)
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    with pytest.raises(ModuleNotFoundError) as raised:
        dashboard.render()
    assert "streamlit" in str(raised.value)
    assert "uv pip install streamlit" in str(raised.value)


def test_require_streamlit_resolves_the_installed_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The deferred door, pinned from the side that has the module: a
    # deployment that carries Streamlit gets exactly the module it
    # installed — the door resolves and returns, nothing more.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    fake = types.ModuleType("streamlit")
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    assert require_streamlit() is fake


def test_the_deferred_door_uses_an_injected_streamlit(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The other half of the deferral: a deployment that does carry
    # Streamlit renders through exactly the module it installed — the
    # door resolves it and the render emits through it.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    recorder = _RecordingStreamlit()
    fake = types.ModuleType("streamlit")
    for name in RENDER_SEQUENCE:
        setattr(fake, name, getattr(recorder, name))
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    page = _dashboard(test_database_url).render()
    assert page.primary.numeral == "50.0%"
    assert recorder.names == list(RENDER_SEQUENCE)


def test_building_imports_neither_streamlit_nor_the_scoring_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The scan-order law, held for the second component: builders fire
    # after the factory's scan has taken each member's src/ back off
    # sys.path, and this workspace carries no streamlit edge at all —
    # so the builder (and the from_env door it wraps) imports neither
    # the sibling whose constant the qualifier reads nor the UI library
    # the render defers to.  The first page is where both are needed.
    import builtins

    real_import = builtins.__import__

    def _no_deferred(name, *args, **kwargs):
        if name in ("scoring", "streamlit"):
            raise AssertionError(
                f"the builder must not import {name} — it runs after the "
                "factory's scan has taken the sibling's src/ off "
                "sys.path, and the UI library is the deployment's "
                "ambient dependency (feature 351)"
            )
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_deferred)
    dashboard = OperatorDashboard.from_env(
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-deferred-test.db"}
    )
    assert dashboard is not None
    assert dashboard.route.route == "/metrics/fdr-deploy"


# -- construction and composition -------------------------------------------------


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"DATABASE_URL": ""},
        {"DATABASE_URL": "   "},
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-env-1.db"},
        {"DATABASE_URL": "sqlite:///tmp/ops-dashboard-env-2.db"},
    ],
)
def test_from_env_composes_exactly_when_the_route_does(env) -> None:
    # The dashboard composes on the route's own decision — the same
    # unset spellings, the same resolved URL — with no second
    # resolution the two surfaces could drift apart on.
    route = FdrDeployEndpoint.from_env(env)
    dashboard = OperatorDashboard.from_env(env)
    if route is None:
        assert dashboard is None
    else:
        assert dashboard is not None
        assert dashboard.route.store.database_url == route.store.database_url


def test_the_dashboard_and_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, pinned at
    # composition for both surfaces: the route that answers the figure
    # and the dashboard that renders it resolve the one database
    # DATABASE_URL names — never two the numeral and its rows could
    # drift apart on.
    app = create_app(MEMBER_SRC, registry=Registration())
    route = app.get("ops-fdr-deploy")
    dashboard = app.get("ops-dashboard")
    assert dashboard is not None and route is not None
    assert dashboard.route.store.database_url == route.store.database_url
    assert dashboard.route.store.database_url == test_database_url
    assert "ops-dashboard" in app.order and "ops-fdr-deploy" in app.order


def test_the_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no dashboard,
    # mirroring the route builder beside it.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("ops-dashboard") is None


def test_composing_the_dashboard_touches_no_disk(
    test_database_url: str,
) -> None:
    from urllib.parse import urlparse

    # Building performs no I/O: no store constructed, no database
    # opened, no page read — the first render is where the route is
    # asked, and the route asks the store then.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_seat_exposes_the_composed_dashboard(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.dashboard_component(app)
    assert component is app.get("ops-dashboard")
    assert component is not None
    assert callable(component.page)


def test_main_renders_through_the_composed_route(test_database_url: str) -> None:
    # The entrypoint's whole path: compose, read, render — the page it
    # answers is the page the operator saw, through the application's
    # own composed route rather than a second resolution.
    _persisted_store(test_database_url)
    app = create_app(MEMBER_SRC, registry=Registration())
    st = _RecordingStreamlit()
    page = main(app=app, st=st)
    assert page.primary.figure == pytest.approx(0.5)
    assert st.names == list(RENDER_SEQUENCE)


# -- the script entrypoint --------------------------------------------------------


def test_the_streamlit_run_bootstrap_reaches_main(
    test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `streamlit run packages/ops/src/ops/dashboard.py` executes the
    # file as a script — no package context — so the module's guard
    # puts the member's src/ on sys.path and resolves __package__
    # before the relative imports run.  Pinned by running the file the
    # way runpy runs it: the imports resolve, main() is reached, and
    # (streamlit being absent here) the render names its repair rather
    # than failing on a relative import nobody fixed.
    if STREAMLIT_INSTALLED:
        pytest.skip("streamlit importable in this environment")
    with pytest.raises(ModuleNotFoundError) as raised:
        runpy.run_path(
            str(MEMBER_SRC / "ops" / "dashboard.py"),
            run_name="__main__",
        )
    assert "uv pip install streamlit" in str(raised.value)
