"""The ops member's registration, composition, and seat in the app
namespace.

The implementation lives in the ``ops`` workspace member
(``packages/ops``), which self-registers with the application factory
under ``"ops-fdr-deploy"`` and ``"ops-dashboard"`` (feature 351's
operator surface, pinned in its own suite).  ``src/app/modules/ops/``
is the member's seat in the app package namespace: it names the
components and asks the factory for them without the ``app`` package
depending on any member at import time.  These tests pin that chain —
workspace declaration,
scan, registration, composition, seat — so the member cannot silently
fall out of the composed application, and so a composition without a
configured ``DATABASE_URL`` degrades to "no ops route" rather than
breaking.

The member's third component is feature 350's live-metrics store
(``ops-live-metric``), its fourth is feature 347's meta-overfit gap
store (``ops-meta-overfit``, the train-versus-holdout world score gap —
docs §16's *"train-vs-holdout world score gap (meta-overfit)"*) and its
fifth is feature 346's discovery-rate store (``ops-discovery-rate``,
discoveries per 1000 budget-charging trials — docs §16's *"discoveries
per 1000 budget-charging trials"*, prd §11's *"Discoveries per 1,000
trials charged (nulls excluded from the denominator)"*); all are pinned
here at the composition seam and in their own suites.

They also pin the member's two composition-time promises: building the
route touches no disk (the store it holds resolves its path lazily, so
composing an application never opens a database), and the route and
the scoring member's own ``scoring-fdr-deploy`` store component — the
rows this route reads — resolve the *same* database when both are
scanned together.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import ops
import pytest
import scoring

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_scan_roots,
)
from app.modules import ops as ops_seat

MEMBER_SRC = Path(ops.__file__).resolve().parent.parent
SCORING_SRC = Path(scoring.__file__).resolve().parent.parent

#: The seat's whole public surface.  Asserted as an exact set rather
#: than as a membership check, because the failure this guards against
#: is the seat *growing* a re-export, and a membership check cannot
#: see that.
EXPECTED_EXPORTS = {
    "COMPONENT_NAME",
    "DASHBOARD_COMPONENT_NAME",
    "OPS_DISCOVERY_RATE_COMPONENT_NAME",
    "OPS_LIVE_METRIC_COMPONENT_NAME",
    "OPS_META_OVERFIT_COMPONENT_NAME",
    "dashboard_component",
    "discovery_rate_component",
    "fdr_deploy_component",
    "live_metric_component",
    "meta_overfit_component",
}


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace
    # member and therefore scannable — the registration chain starts
    # here, and no edit to any central file was needed to make it
    # true.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_scan_registers_the_fdr_deploy_route() -> None:
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_COMPONENT_NAME in names
    assert ops.OPS_COMPONENT_NAME == "ops-fdr-deploy"
    # The scan re-imports the package under its alias; the registry
    # replaces by name, so one ops route survives any number of
    # rescans — the registration-lives-in-__init__ invariant, which is
    # what keeps the component from silently dropping out of every
    # composition after the first.
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count(ops.OPS_COMPONENT_NAME) == 1


def test_composed_app_builds_the_route(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_COMPONENT_NAME)
    assert component is not None
    # Duck-checked rather than isinstance against the canonical import:
    # the scan imports the member under an alias module, so the
    # composed component is structurally an endpoint but never the
    # same module object a direct import yields.
    assert component.route == "/metrics/fdr-deploy"
    assert callable(component.get)
    # Bound to the database the process is pointed at — resolved at
    # composition time from DATABASE_URL, set per test by the fixtures.
    assert component.store.database_url == test_database_url
    assert ops.OPS_COMPONENT_NAME in app.order


def test_composing_the_route_touches_no_disk(test_database_url: str) -> None:
    # Composition-time work must not touch the disk: the store the
    # endpoint holds resolves its path lazily, so building the
    # application creates no database and no schema.  The first get()
    # is where the store is asked — the store's own "constructing one
    # performs no I/O" law, pinned here at the route that holds it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no ops route, the
    # same degradation the factory applies to an absent workspace and
    # the scoring member's own store builder takes.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_COMPONENT_NAME) is None


def test_the_route_and_the_store_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, pinned at
    # composition: scanning this member and the scoring member
    # together composes the rows' owner (``scoring-fdr-deploy``, the
    # store feature 267 registers) and the surface that reads them
    # (``ops-fdr-deploy``, this route) over the one database
    # ``DATABASE_URL`` names — never two databases the route and its
    # rows could drift apart on.
    app = create_app(MEMBER_SRC, SCORING_SRC, registry=Registration())
    store = app.get("scoring-fdr-deploy")
    route = app.get(ops.OPS_COMPONENT_NAME)
    assert store is not None and route is not None
    assert store.database_url == route.store.database_url == test_database_url


def test_the_seat_names_line_up() -> None:
    # The seat's constant, the member's constant and the spec's route
    # row are one string.  Three spellings of one name is exactly the
    # kind of drift a test is cheaper than.
    assert ops_seat.COMPONENT_NAME == ops.OPS_COMPONENT_NAME == "ops-fdr-deploy"


def test_scan_registers_the_live_metric_store() -> None:
    # The member's third component registers under its own name, beside
    # the route and the dashboard — the registration-grows-per-feature
    # shape, and the growth the member's own registration reserved when
    # feature 341 landed.
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME in names
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME == "ops-live-metric"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count(ops.OPS_LIVE_METRIC_COMPONENT_NAME) == 1


def test_composed_app_builds_the_live_metric_store(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_LIVE_METRIC_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME in app.order


def test_composing_the_live_metric_store_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk: the store resolves
    # its path lazily, so building the application creates no database
    # and no schema.  The first record() is where the store is asked —
    # the store's own "constructing one performs no I/O" law, pinned
    # here at the component that holds it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_live_metric_store_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no live-metric
    # component, the same degradation the factory applies to an absent
    # workspace and the member's own route and dashboard builders take.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_LIVE_METRIC_COMPONENT_NAME) is None


def test_the_seat_names_line_up_live_metric() -> None:
    # The seat's constant, the member's constant and the spec's store
    # name are one string.  Three spellings of one name is exactly the
    # kind of drift a test is cheaper than.
    assert (
        ops_seat.OPS_LIVE_METRIC_COMPONENT_NAME
        == ops.OPS_LIVE_METRIC_COMPONENT_NAME
        == "ops-live-metric"
    )


def test_the_seat_exposes_the_composed_live_metric_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.live_metric_component(app)
    assert component is app.get(ops.OPS_LIVE_METRIC_COMPONENT_NAME)
    assert component.database_url == test_database_url


def test_scan_registers_the_meta_overfit_store() -> None:
    # The member's fourth component registers under its own name, beside the
    # route, the dashboard and the live-metrics store — the
    # registration-grows-per-feature shape, and the growth the member's own
    # registration reserved when feature 341 landed.
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_META_OVERFIT_COMPONENT_NAME in names
    assert ops.OPS_META_OVERFIT_COMPONENT_NAME == "ops-meta-overfit"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count(ops.OPS_META_OVERFIT_COMPONENT_NAME) == 1


def test_composed_app_builds_the_meta_overfit_store(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url
    assert ops.OPS_META_OVERFIT_COMPONENT_NAME in app.order


def test_composing_the_meta_overfit_store_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk: the store resolves its
    # path lazily, so building the application creates no database and no
    # schema.  The first record() is where the store is asked — the store's
    # own "constructing one performs no I/O" law, pinned here at the
    # component that holds it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_meta_overfit_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no meta-overfit
    # component, the same degradation the factory applies to an absent
    # workspace and the member's other store-bound builders take.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME) is None


def test_the_seat_names_line_up_meta_overfit() -> None:
    # The seat's constant, the member's constant and the spec's feature
    # sentence are one name.  Three spellings of one name is exactly the kind
    # of drift a test is cheaper than.
    assert (
        ops_seat.OPS_META_OVERFIT_COMPONENT_NAME
        == ops.OPS_META_OVERFIT_COMPONENT_NAME
        == "ops-meta-overfit"
    )


def test_the_meta_overfit_store_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held for the member's
    # own tables too: the route, the live-metrics store and the meta-overfit
    # gap store resolve the one database DATABASE_URL names — never two
    # databases a metric and the surface that renders it could drift apart
    # on.
    app = create_app(MEMBER_SRC, registry=Registration())
    gaps = app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    live = app.get(ops.OPS_LIVE_METRIC_COMPONENT_NAME)
    assert gaps is not None and route is not None and live is not None
    assert gaps.database_url == route.store.database_url == test_database_url
    assert live.database_url == gaps.database_url


def test_the_seat_exposes_the_composed_meta_overfit_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.meta_overfit_component(app)
    assert component is app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME)
    assert component.database_url == test_database_url


def test_scan_registers_the_discovery_rate_store() -> None:
    # The member's fifth component registers under its own name, beside the
    # route, the dashboard and the member's three other stores — the
    # registration-grows-per-feature shape, and the growth the member's own
    # registration reserved when feature 341 landed (*"344-346's arrive as
    # their own tables under the same allowance"*).
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_DISCOVERY_RATE_COMPONENT_NAME in names
    assert ops.OPS_DISCOVERY_RATE_COMPONENT_NAME == "ops-discovery-rate"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME) == 1


def test_composed_app_builds_the_discovery_rate_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url
    assert ops.OPS_DISCOVERY_RATE_COMPONENT_NAME in app.order


def test_composing_the_discovery_rate_store_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk: the store resolves its
    # path lazily, so building the application creates no database and no
    # schema.  The first record() is where the store is asked — the store's
    # own "constructing one performs no I/O" law, pinned here at the
    # component that holds it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_discovery_rate_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no discovery-rate
    # component, the same degradation the factory applies to an absent
    # workspace and the member's other store-bound builders take.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME) is None


def test_the_seat_names_line_up_discovery_rate() -> None:
    # The seat's constant, the member's constant and the spec's feature
    # sentence are one name.  Three spellings of one name is exactly the
    # kind of drift a test is cheaper than.
    assert (
        ops_seat.OPS_DISCOVERY_RATE_COMPONENT_NAME
        == ops.OPS_DISCOVERY_RATE_COMPONENT_NAME
        == "ops-discovery-rate"
    )


def test_the_discovery_rate_store_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held for the member's
    # own tables too: the route, the live-metrics store, the meta-overfit gap
    # store and the discovery-rate store resolve the one database
    # DATABASE_URL names — never two databases a metric and the surface that
    # renders it could drift apart on.
    app = create_app(MEMBER_SRC, registry=Registration())
    rates = app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    gaps = app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME)
    assert rates is not None and route is not None and gaps is not None
    assert rates.database_url == route.store.database_url == test_database_url
    assert gaps.database_url == rates.database_url


def test_the_seat_exposes_the_composed_discovery_rate_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.discovery_rate_component(app)
    assert component is app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME)
    assert component.database_url == test_database_url


def test_the_seat_exposes_nothing_but_the_composition_accessor(
    test_database_url: str,
) -> None:
    # See the seat's docstring: its job is to answer one question, and
    # every extra name is a second thing to keep in sync with the
    # member — as well as a way for a later feature to accidentally
    # depend on the seat for a value type it should reach through the
    # member.
    assert set(ops_seat.__all__) == EXPECTED_EXPORTS
    for name in EXPECTED_EXPORTS:
        assert hasattr(ops_seat, name), name
    # And the member's own API is *not* among the exports — the
    # specific names a well-meaning re-export would add first.
    for leaked in (
        "FdrDeployEndpoint",
        "FdrDeployResponse",
        "FDR_DEPLOY_ROUTE",
        "OpsError",
        "FdrDeployMetricError",
        "OperatorDashboard",
        "DashboardPage",
        "FdrDeployPanel",
        "DashboardRenderError",
        "EpochCountChrome",
        "EpochCountGauge",
        "EPOCH_COUNT_LABEL",
        "require_promotion",
        "LiveMetricsStore",
        "LiveMetric",
        "LiveMetricError",
        "LIVE_METRICS",
        "LIVE_METRIC_TABLE",
        "MetaOverfitGaps",
        "MetaOverfitGap",
        "MetaOverfitGapError",
        "META_OVERFIT_TABLE",
        "DiscoveryRates",
        "DiscoveryRate",
        "DiscoveryRateError",
        "DISCOVERY_RATE_TABLE",
    ):
        assert leaked not in ops_seat.__all__


def test_the_seat_exposes_the_composed_route(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = ops_seat.fdr_deploy_component(app)
    assert component is app.get(ops.OPS_COMPONENT_NAME)
    assert component.route == "/metrics/fdr-deploy"


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    application = Application(
        components={ops_seat.COMPONENT_NAME: {"sentinel": True}},
        order=(ops_seat.COMPONENT_NAME,),
    )
    assert ops_seat.fdr_deploy_component(application) == {"sentinel": True}


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    # A module that cannot reach the component returns None rather
    # than failing — mirroring the factory's stance toward absent
    # components.
    assert ops_seat.fdr_deploy_component(Application()) is None
