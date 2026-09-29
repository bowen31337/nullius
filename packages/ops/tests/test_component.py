"""The ops member's registration and composition.

The implementation lives in the ``ops`` workspace member
(``packages/ops``), which self-registers with the application factory
under ``"ops-fdr-deploy"`` and ``"ops-dashboard"`` (feature 351's
operator surface, pinned in its own suite), and callers reach each
component as ``create_app().get("<component-name>")``.  These tests pin
that chain — workspace declaration, scan, registration, composition — so
the member cannot silently fall out of the composed application, and so
a composition without a configured ``DATABASE_URL`` degrades to "no ops
route" rather than breaking.

The member's third component is feature 350's live-metrics store
(``ops-live-metric``), its fourth is feature 347's meta-overfit gap
store (``ops-meta-overfit``, the train-versus-holdout world score gap —
docs §16's *"train-vs-holdout world score gap (meta-overfit)"*), its
fifth is feature 346's discovery-rate store (``ops-discovery-rate``,
discoveries per 1000 budget-charging trials — docs §16's *"discoveries
per 1000 budget-charging trials"*, prd §11's *"Discoveries per 1,000
trials charged (nulls excluded from the denominator)"*) and its sixth
is feature 345's Type-B depth store (``ops-type-b-depth``, Type-B
depth past the flip per Type-D campaign — docs §16's *"Type-B depth
past the flip in Type-D worlds"*, prd §11's *"Type-B error rate: depth
past the flip in Type-D worlds | falling across campaigns"*) and its
seventh is feature 344's calibration store
(``ops-null-calibration``, the planted-null sensitivity/specificity
pair per campaign — docs §16's *"sensitivity/specificity on planted
nulls"*, prd §11's *"Sensitivity / specificity on planted nulls
(base-rate independent) | tracked, not targeted"*); all are pinned
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

MEMBER_SRC = Path(ops.__file__).resolve().parent.parent
SCORING_SRC = Path(scoring.__file__).resolve().parent.parent

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


def test_the_names_line_up() -> None:
    # The member's constant and the spec's route row are one string.  Two
    # spellings of one name is exactly the kind of drift a test is cheaper
    # than.
    assert ops.OPS_COMPONENT_NAME == "ops-fdr-deploy"


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


def test_the_names_line_up_live_metric() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_LIVE_METRIC_COMPONENT_NAME == "ops-live-metric"


def test_the_application_exposes_the_composed_live_metric_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_LIVE_METRIC_COMPONENT_NAME)
    assert component is not None
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


def test_the_names_line_up_meta_overfit() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_META_OVERFIT_COMPONENT_NAME == "ops-meta-overfit"


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


def test_the_application_exposes_the_composed_meta_overfit_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_META_OVERFIT_COMPONENT_NAME)
    assert component is not None
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


def test_the_names_line_up_discovery_rate() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_DISCOVERY_RATE_COMPONENT_NAME == "ops-discovery-rate"


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


def test_the_application_exposes_the_composed_discovery_rate_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url


def test_scan_registers_the_type_b_depth_store() -> None:
    # The member's sixth component registers under its own name, beside the
    # route, the dashboard and the member's four other stores — the
    # registration-grows-per-feature shape, and the growth the member's own
    # registration reserved when feature 341 landed (*"344's and 345's
    # arrive as their own tables under the same allowance"*).
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME in names
    assert ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME == "ops-type-b-depth"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert [c.name for c in again].count(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME) == 1


def test_composed_app_builds_the_type_b_depth_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url
    assert ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME in app.order


def test_composing_the_type_b_depth_store_touches_no_disk(
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


def test_the_type_b_depth_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no Type-B depth
    # component, the same degradation the factory applies to an absent
    # workspace and the member's other store-bound builders take.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME) is None


def test_the_names_line_up_type_b_depth() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME == "ops-type-b-depth"


def test_the_type_b_depth_store_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held for the
    # member's own tables too: the route and the member's four stores
    # resolve the one database DATABASE_URL names — never two databases a
    # metric and the surface that renders it could drift apart on.
    app = create_app(MEMBER_SRC, registry=Registration())
    depths = app.get(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    rates = app.get(ops.OPS_DISCOVERY_RATE_COMPONENT_NAME)
    assert depths is not None and route is not None and rates is not None
    assert depths.database_url == route.store.database_url == test_database_url
    assert rates.database_url == depths.database_url


def test_the_application_exposes_the_composed_type_b_depth_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url


def test_scan_registers_the_null_calibration_store() -> None:
    # The member's seventh component registers under its own name, beside the
    # route, the dashboard and the member's five other stores — the
    # registration-grows-per-feature shape, and the growth the member's own
    # registration reserved when feature 341 landed (*"344's and 345's arrive
    # as their own tables under the same allowance"*).
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_NULL_CALIBRATION_COMPONENT_NAME in names
    assert ops.OPS_NULL_CALIBRATION_COMPONENT_NAME == "ops-null-calibration"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert (
        [c.name for c in again].count(ops.OPS_NULL_CALIBRATION_COMPONENT_NAME) == 1
    )


def test_composed_app_builds_the_null_calibration_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_NULL_CALIBRATION_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url
    assert ops.OPS_NULL_CALIBRATION_COMPONENT_NAME in app.order


def test_composing_the_null_calibration_store_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk: the store resolves its
    # path lazily, so building the application creates no database and no
    # schema.  The first record() is where the store is asked — the store's own
    # "constructing one performs no I/O" law, pinned here at the component that
    # holds it.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_null_calibration_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an error:
    # the composed application simply carries no calibration component, the
    # same degradation the factory applies to an absent workspace and the
    # member's other store-bound builders take.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_NULL_CALIBRATION_COMPONENT_NAME) is None


def test_the_names_line_up_null_calibration() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_NULL_CALIBRATION_COMPONENT_NAME == "ops-null-calibration"


def test_the_null_calibration_store_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held for the member's
    # own tables too: the route and the member's five stores resolve the one
    # database DATABASE_URL names — never two databases a metric and the
    # surface that renders it could drift apart on.
    app = create_app(MEMBER_SRC, registry=Registration())
    calibration = app.get(ops.OPS_NULL_CALIBRATION_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    depths = app.get(ops.OPS_TYPE_B_DEPTH_COMPONENT_NAME)
    assert calibration is not None and route is not None and depths is not None
    assert (
        calibration.database_url == route.store.database_url == test_database_url
    )
    assert depths.database_url == calibration.database_url


def test_the_application_exposes_the_composed_null_calibration_store(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_NULL_CALIBRATION_COMPONENT_NAME)
    assert component is not None
    assert component.database_url == test_database_url


def test_scan_registers_the_regime_coverage_route() -> None:
    # The member's eighth component registers under its own name, beside the
    # route, the dashboard and the member's five stores — the
    # registration-grows-per-feature shape, and the peer the member's own
    # route registration reserved when feature 341 landed (*"the sibling
    # routes this category's later features add (342's lamps, 343's
    # coverage) land as its peers under the same prefix"*).
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_REGIME_COVERAGE_COMPONENT_NAME in names
    assert ops.OPS_REGIME_COVERAGE_COMPONENT_NAME == "ops-regime-coverage"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert (
        [c.name for c in again].count(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME) == 1
    )


def test_composed_app_builds_the_regime_coverage_route(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME)
    assert component is not None
    assert component.route == "/metrics/regime-coverage"
    assert component.store.database_url == test_database_url
    assert ops.OPS_REGIME_COVERAGE_COMPONENT_NAME in app.order


def test_composing_the_regime_coverage_route_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk, and for this route that
    # is doubly load-bearing: the store it reads belongs to another member,
    # reached through a deferred carrier, so a builder that imported the
    # regime member — or constructed its store — would both touch the disk
    # and make composition depend on an import that is not promised to work
    # where builders fire.  Building creates no database and no schema; the
    # first get() is where the store is both constructed and asked.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_regime_coverage_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an error:
    # the composed application simply carries no coverage route, the same
    # degradation the factory applies to an absent workspace and the member's
    # other store-bound builders take.  It is deliberately *not* the
    # empty-ledger answer — no route says there is nowhere a count could have
    # been persisted, which is a different fact from a configured database
    # where the census has not run.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME) is None


def test_the_names_line_up_regime_coverage() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_REGIME_COVERAGE_COMPONENT_NAME == "ops-regime-coverage"


def test_the_regime_coverage_route_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held across the
    # member's own surfaces: the coverage route and the fdr-deploy route
    # resolve the one database DATABASE_URL names — never two databases where
    # the distribution an operator reads and the ledger the promotion gate
    # blocks on could drift apart.
    app = create_app(MEMBER_SRC, registry=Registration())
    coverage = app.get(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    assert coverage is not None and route is not None
    assert coverage.store.database_url == route.store.database_url == test_database_url


def test_the_application_exposes_the_composed_regime_coverage_route(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME)
    assert component is not None
    assert component.route == "/metrics/regime-coverage"


def test_scan_registers_the_instrument_status_route() -> None:
    # The member's ninth component registers under its own name, beside the
    # three routes, the dashboard and the member's four stores — the
    # registration-grows-per-feature shape, and the peer the member's own
    # route registration reserved when feature 341 landed (*"342's lamps"*
    # named in the note beside 343's coverage).
    registry = Registration()
    components = scan_components(MEMBER_SRC, registry=registry)
    names = [component.name for component in components]
    assert ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME in names
    assert ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME == "ops-instrument-status"
    again = scan_components(MEMBER_SRC, registry=registry)
    assert (
        [c.name for c in again].count(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME) == 1
    )


def test_composed_app_builds_the_instrument_status_route(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME)
    assert component is not None
    assert component.route == "/metrics/instrument-status"
    assert component.readings.database_url == test_database_url
    assert ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME in app.order


def test_composing_the_instrument_status_route_touches_no_disk(
    test_database_url: str,
) -> None:
    # Composition-time work must not touch the disk, and for this route that
    # is the load-bearing contract twice over: two of its three lamps belong
    # to *other* members (the canary store and the nulloracle guard), reached
    # through deferred carriers, so a builder that imported either — or
    # constructed either store — would both touch the disk and make
    # composition depend on imports that are not promised to work where
    # builders fire.  Building creates no database and no schema; the first
    # get() is where each store is constructed and asked.
    database_path = Path(urlparse(test_database_url).path.removeprefix("/"))
    create_app(MEMBER_SRC, registry=Registration())
    assert not database_path.exists()


def test_the_instrument_status_builder_contributes_nothing_without_a_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unconfigured relational store is a discoverable state, not an
    # error: the composed application simply carries no instrument-status
    # route, the same degradation the member's other store-bound builders
    # take.  It is deliberately *not* the all-absent-lamp answer — no route
    # says there is nowhere a reading could have come from, which is a
    # different fact from a configured database whose instruments have not
    # been read yet.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME) is None


def test_the_names_line_up_instrument_status() -> None:
    # The member's constant and the spec's spelling of the name are one
    # string.  Two spellings of one name is exactly the kind of drift a
    # test is cheaper than.
    assert ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME == "ops-instrument-status"


def test_the_instrument_status_route_and_the_route_compose_over_one_database(
    test_database_url: str,
) -> None:
    # §16's "single Postgres metrics table" allowance, held across the
    # member's own surfaces: the lamp rail, the fdr-deploy route and the
    # coverage route resolve the one database DATABASE_URL names — never
    # three databases where the figure an operator reads and the lamps
    # beside it could drift apart.
    app = create_app(MEMBER_SRC, registry=Registration())
    lamps = app.get(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME)
    route = app.get(ops.OPS_COMPONENT_NAME)
    coverage = app.get(ops.OPS_REGIME_COVERAGE_COMPONENT_NAME)
    assert lamps is not None and route is not None and coverage is not None
    assert (
        lamps.readings.database_url
        == route.store.database_url
        == coverage.store.database_url
        == test_database_url
    )


def test_the_application_exposes_the_composed_instrument_status_route(
    test_database_url: str,
) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME)
    assert component is not None
    assert component.route == "/metrics/instrument-status"


def test_the_composed_instrument_status_route_reaches_the_sibling_members(
    test_database_url: str,
) -> None:
    # The deferred doors, through composition: the route's first lamp is the
    # *canary* member's own halt store read over the composed database, so
    # the rail an operator sees is the bit that member persists rather than
    # a second opinion computed here.  Deliberately built through
    # ``create_app`` — the requirement is that a *composed* route can reach
    # the sibling at ask time even though the builder must not at
    # build time.
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_INSTRUMENT_STATUS_COMPONENT_NAME)
    assert component is not None
    response = component.get()
    # Nothing has been recorded, so the halt table is empty and dreaming
    # runs; the other two lamps are absent rather than lit.
    assert response.canary is True
    assert response.absent == ("ks_guard", "ingest")


def test_the_application_exposes_the_composed_route(test_database_url: str) -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    component = app.get(ops.OPS_COMPONENT_NAME)
    assert component is not None
    assert component.route == "/metrics/fdr-deploy"


def test_an_absent_component_is_none_rather_than_an_error() -> None:
    # An application that does not carry the component answers None
    # rather than failing — the factory's stance toward absent
    # components.
    assert Application().get(ops.OPS_COMPONENT_NAME) is None
