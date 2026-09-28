"""The route table: the pairing of HTTP route to composed component.

These tests hold :mod:`nullius_api.routes` to its own law — the
pairing of route to component is spelled *once*, here, and agrees with
app_spec.xml's ``<api_endpoints_summary>`` on the one side and the
members' own route constants on the other, so the transport, the spec
and the members cannot drift apart on who serves what.  The
store-wrapping is pinned too: the promotion and forward components
arrive as stores and are served through the members' own endpoint
classes, never by calling a store directly.
"""

from __future__ import annotations

# The members' own spellings, imported directly for the agreement
# assertions — the same discipline the members' suites apply to their
# cross-member constants.
import forward
import ledger
import nulloracle
import ops
import promotion
import pytest
import risk
from nullius_api import (
    API_ROUTES,
    PRE_REGISTER_WRAP,
    PROMOTE_WRAP,
    ApiRoute,
    resolve_routes,
    routes_by_path,
)
from nullius_api.routes import _resolve_one

from app.module_loader import Application, create_app


class _FakePreRegistrationStore:
    """A store shaped like feature 291's — the ``pre_register`` seam."""

    def pre_register(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("the wrap test never serves a request")


class _FakeForwardStore:
    """A store shaped like feature 332's — the ``open_record`` seam."""

    def open_record(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("the wrap test never serves a request")


class _FakeEndpoint:
    """Something that already speaks a route's verb method."""

    route = "/nowhere"

    def post(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("the wrap test never serves a request")


def test_the_table_is_the_spec_summary_restated() -> None:
    """Ten routes, the paths and verbs app_spec.xml's summary states."""
    assert [(row.path, row.verb) for row in API_ROUTES] == [
        ("/forward/decay", "GET"),
        ("/forward/promote", "POST"),
        ("/ledger/debit", "POST"),
        ("/ledger/k-effective", "GET"),
        ("/metrics/fdr-deploy", "GET"),
        ("/metrics/instrument-status", "GET"),
        ("/metrics/regime-coverage", "GET"),
        ("/promotion/pre-register", "POST"),
        ("/target", "POST"),
        ("/risk/halt", "POST"),
    ]


def test_the_table_agrees_with_the_members_route_constants() -> None:
    """Every route this transport serves is spelled by the member that
    owns it — the pairing cannot drift from the members' own constants."""
    members_spellings = {
        "/metrics/fdr-deploy": ops.FDR_DEPLOY_ROUTE,
        "/metrics/instrument-status": ops.INSTRUMENT_STATUS_ROUTE,
        "/metrics/regime-coverage": ops.REGIME_COVERAGE_ROUTE,
        "/ledger/debit": ledger.DEBIT_ROUTE,
        "/ledger/k-effective": ledger.KEFFECTIVE_ROUTE,
        "/promotion/pre-register": promotion.PRE_REGISTER_ROUTE,
        "/forward/promote": forward.FORWARD_PROMOTE_ROUTE,
        "/forward/decay": forward.FORWARD_DECAY_ROUTE,
        "/target": nulloracle.TARGET_ROUTE,
        "/risk/halt": risk.RISK_HALT_ROUTE,
    }
    for row in API_ROUTES:
        assert members_spellings[row.path] == row.path


def test_the_table_names_the_composed_components() -> None:
    """The lookup names are the members' registered component names —
    the spellings the factory's registry and the app package seats
    already pin."""
    assert {row.component for row in API_ROUTES} == {
        "ops-fdr-deploy",
        "ops-instrument-status",
        "ops-regime-coverage",
        "ledger-debit",
        "ledger-k-effective",
        "nulloracle-target-route",
        "risk-halt",
        "forward-decay",
        "promotion",
        "forward",
    }


def test_only_the_two_store_components_carry_a_wrap() -> None:
    """Promotion and forward arrive as stores; the rest as endpoints."""
    wrapped = {row.component: row.wrap for row in API_ROUTES if row.wrap}
    assert wrapped == {
        "promotion": PRE_REGISTER_WRAP,
        "forward": PROMOTE_WRAP,
    }


def test_the_table_groups_by_path_verb_aware() -> None:
    """The grouping a wrong-verb refusal states its Allow set from —
    one group per path, every verb that path serves, nothing invented."""
    grouped = routes_by_path()
    assert set(grouped) == {row.path for row in API_ROUTES}
    assert grouped["/forward/decay"] == (
        ApiRoute("/forward/decay", "GET", "forward-decay", "research"),
    )
    assert [row.verb for row in grouped["/ledger/debit"]] == ["POST"]
    for path, rows in grouped.items():
        assert {row.path for row in rows} == {path}


def test_a_composed_store_is_wrapped_as_the_members_own_endpoint() -> None:
    """The promotion store is served through PreRegisterEndpoint, the
    forward store through PromoteEndpoint — the members' endpoint
    classes, not a store called directly and not a re-implementation.

    Asserted duck-typed (type name and route constant, never class
    identity with a direct import): the factory's scan may hand the
    same member back under a synthetic module name, and identity
    assertions across that seam are exactly what breaks.
    """
    application = Application(
        components={
            "promotion": _FakePreRegistrationStore(),
            "forward": _FakeForwardStore(),
        },
        order=("promotion", "forward"),
    )
    resolved = {row.route.path: row.endpoint for row in resolve_routes(application)}
    assert type(resolved["/promotion/pre-register"]).__name__ == "PreRegisterEndpoint"
    assert resolved["/promotion/pre-register"].route == promotion.PRE_REGISTER_ROUTE
    assert callable(resolved["/forward/promote"].post)
    assert type(resolved["/forward/promote"]).__name__ == "PromoteEndpoint"
    assert resolved["/forward/promote"].route == forward.FORWARD_PROMOTE_ROUTE


def test_a_component_that_already_speaks_the_route_passes_through() -> None:
    """A member that ever registers its endpoint directly is served as
    composed — the wrap never double-wraps an endpoint into a refusal."""

    class _PromoteShaped(_FakeEndpoint):
        route = "/forward/promote"

    application = Application(
        components={"forward": _PromoteShaped()}, order=("forward",)
    )
    (resolved,) = [
        row for row in resolve_routes(application) if row.route.path == "/forward/promote"
    ]
    assert type(resolved.endpoint) is _PromoteShaped


def test_an_absent_component_resolves_to_none_not_an_omission() -> None:
    """An unconfigured store is a discovered endpoint-less route — the
    distinction between nowhere-configured and configured-and-empty."""
    application = Application(components={}, order=())
    resolved = resolve_routes(application)
    assert len(resolved) == len(API_ROUTES)
    assert all(row.endpoint is None for row in resolved)


def test_an_unknown_wrap_marker_is_refused_by_name() -> None:
    """The table's own guard: a wrap it cannot spell is a refusal, not
    a silently-unwrapped store."""
    with pytest.raises(TypeError) as raised:
        _resolve_one(
            Application(components={"x": _FakePreRegistrationStore()}, order=("x",)),
            ApiRoute("/x", "POST", "x", "research", wrap="nowhere"),
        )
    assert "nowhere" in str(raised.value)


def test_the_composed_application_resolves_real_components(
    test_database_url: str,
) -> None:
    """Against the factory's own composition, the table resolves the
    members' real endpoints — looked up with the application's own
    ``get``, exactly the door the factory hands out.

    The store-bound routes resolve over a fresh per-test database; the
    target route stays honestly unconfigured (nothing names a sidecar
    in a test environment), which is itself the resolution the table
    records rather than an omission.
    """
    application = create_app()
    resolved = {row.route.path: row.endpoint for row in resolve_routes(application)}
    assert type(resolved["/metrics/fdr-deploy"]).__name__ == "FdrDeployEndpoint"
    assert type(resolved["/ledger/debit"]).__name__ == "DebitEndpoint"
    assert type(resolved["/risk/halt"]).__name__ == "HaltEndpoint"
    assert type(resolved["/forward/decay"]).__name__ == "DecayCurveEndpoint"
    # The two store wraps, over the really-composed stores.
    assert type(resolved["/promotion/pre-register"]).__name__ == "PreRegisterEndpoint"
    assert type(resolved["/forward/promote"]).__name__ == "PromoteEndpoint"
    # No sidecar names a null oracle in this environment.
    assert resolved["/target"] is None
