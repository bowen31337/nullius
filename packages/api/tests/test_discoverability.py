"""The discoverability surface: feature 12's ``GET /`` and ``GET /healthz``.

*System serves GET / as an HTML index listing every route with its verb
and whether its component is configured, and GET /healthz, which returns
200.*  These tests pin each clause of that sentence: the index is HTML,
lists every declared route with its verb and its configured state, and
names nothing that leaks a traceback or a path; the liveness probe
answers a bare 200; and both are GET-only, answering the same 405
envelope as a table route when asked with the wrong verb.

The two routes are *meta* routes — the transport describing its own
surface, and a liveness probe — not a composed component's answer, so
they are not rows in the ten-route table and not entries in the
adapter map; the tests assert that separation holds, so a route added
to the table never silently becomes a meta-route or vice versa.

The endpoints here are fakes for the transport's own behaviour, the
same discipline :mod:`test_server` states: the index's configured
state is the ``endpoint is not None`` fact the dispatch computes, so a
fake endpoint present and an absent one are all the index needs to
prove.
"""

from __future__ import annotations

import pytest
from conftest import token_for
from nullius_api import API_ROUTES, INDEX_SCOPE, ApiServer, ResolvedRoute
from nullius_api.routes import ApiRoute
from nullius_api.server import (
    HEALTHZ_PATH,
    HEALTHZ_STATUS,
    INDEX_PATH,
    METHOD_NOT_ALLOWED_CLASS,
    _index_html,
)
from test_server import _ask, _Boot, _GetEndpoint  # type: ignore[import-not-found]


def _ask_raw(
    server: ApiServer, method: str, path: str, scope: str | None = None
) -> tuple[int, dict, str]:
    """One request returning the *raw* body — the index is HTML, not
    JSON, so it cannot pass through the JSON-parsing ``_ask``.

    ``scope`` is the credential to present; the default of ``None``
    means *no header*, because the meta-routes are where the suite
    exercises the gate and the caller must be able to say so explicitly.
    Tests asking for the index's HTML pass the scope ``/`` wants
    (``INDEX_SCOPE``); ``/healthz`` needs none.
    """
    import http.client

    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        headers = (
            {"Authorization": f"Bearer {token_for(scope)}"} if scope else {}
        )
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, body
    finally:
        connection.close()


@pytest.fixture
def boot() -> _Boot:
    """Boot one server per case on an ephemeral port, on loopback.

    The transport's own boot helper (:class:`test_server._Boot`), reused
    rather than re-spelled: the discoverability routes are served by the
    same dispatch and answered through the same request as every other
    route, so the fixture that boots one is the fixture that boots all.
    """
    runner = _Boot()
    yield runner
    runner.shutdown()


# -- The index is HTML and lists every route ---------------------------------------


def test_the_index_answers_html_with_a_route_per_declared_row(boot: _Boot) -> None:
    """``GET /`` is a complete HTML document, one row per declared
    route, each naming the route's own verb, path and component."""
    server = boot({})
    status, headers, body = _ask_raw(server, "GET", INDEX_PATH, INDEX_SCOPE)
    assert status == 200
    assert headers["content-type"] == "text/html; charset=utf-8"
    assert body.startswith("<!doctype html>")
    for row in API_ROUTES:
        assert row.verb in body
        assert row.path in body
        assert row.component in body


def test_the_index_names_whether_each_component_is_configured(
    boot: _Boot,
) -> None:
    """The index says *configured* for a route whose component resolved
    and *unconfigured* for one that did not — the same fact a request
    to the route would find, named rather than omitted.

    One component present, the rest absent: the present route's row
    reads *configured* and the absent ones read *unconfigured*, so the
    page reflects the resolved table rather than asserting every route
    is up.
    """
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    _, _, body = _ask_raw(server, "GET", INDEX_PATH, INDEX_SCOPE)
    # The present component is configured; the nine absent ones are not,
    # so both words appear and neither is the whole table.
    assert "configured" in body
    assert "unconfigured" in body
    # The configured row names the component that resolved.
    assert "ops-fdr-deploy" in body
    # A route with no component is named unconfigured, not omitted.
    assert "risk-halt" in body


def test_the_index_is_the_resolved_table_rendered(boot: _Boot) -> None:
    """The HTML is built from the server's own resolved route table —
    the ``endpoint`` each row carries, not a re-derived guess — so the
    configured state the page shows is the state the server serves."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    _, _, body = _ask_raw(server, "GET", INDEX_PATH, INDEX_SCOPE)
    # All ten routes are declared; exactly one is configured (the one
    # component booted), the rest unconfigured — the page's count says
    # which, so the index reflects the resolved table, not a constant.
    assert "10 routes declared, 1 configured." in body


def test_the_index_builds_from_the_resolved_routes() -> None:
    """The page builder renders the resolved table's verb, path,
    component and configured state — a unit pin on the one function
    that turns the table into HTML."""
    route = ApiRoute("/metrics/fdr-deploy", "GET", "ops-fdr-deploy", "metrics:read")
    html = _index_html((ResolvedRoute(route=route, endpoint=object()),))
    assert "<!doctype html>" in html
    assert ">GET<" in html
    assert "/metrics/fdr-deploy" in html
    assert "ops-fdr-deploy" in html
    assert "configured" in html


def test_the_index_escapes_route_values() -> None:
    """A verb, path or component that carries HTML metacharacters is
    escaped, never injected — the page is text, not a script vector."""
    route = ApiRoute("/a<script>", "GE'T", "ops<>&", "metrics:read")
    html = _index_html((ResolvedRoute(route=route, endpoint=None),))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "ops&lt;&gt;&amp;" in html


# -- /healthz ----------------------------------------------------------------------


def test_healthz_answers_a_bare_200(boot: _Boot) -> None:
    """The liveness probe returns 200 — the honest "the process is up
    and answering", with no figure and no component behind it."""
    server = boot({})
    status, headers, body = _ask(server, "GET", HEALTHZ_PATH)
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body["status"] == HEALTHZ_STATUS


def test_healthz_answers_200_with_no_components_at_all(boot: _Boot) -> None:
    """A probe is not a route: it answers 200 even when every composed
    component is absent, because it asks nothing of a store."""
    server = boot({})
    status, _, _ = _ask(server, "GET", HEALTHZ_PATH)
    assert status == 200


# -- The meta-routes are GET-only --------------------------------------------------


def test_a_wrong_verb_on_the_index_answers_405_with_allow(boot: _Boot) -> None:
    """``POST /`` is the wrong verb for a GET-only meta-route — the same
    405 envelope and ``Allow`` header a table route answers."""
    server = boot({})
    status, headers, body = _ask(server, "POST", INDEX_PATH)
    assert status == 405
    assert headers["allow"] == "GET"
    assert body["error"]["code"] == "method_not_allowed"
    assert body["error"]["class"] == METHOD_NOT_ALLOWED_CLASS


def test_a_wrong_verb_on_healthz_answers_405(boot: _Boot) -> None:
    """``POST /healthz`` is refused the same way — the probe answers
    GET only."""
    server = boot({})
    status, headers, _body = _ask(server, "POST", HEALTHZ_PATH)
    assert status == 405
    assert headers["allow"] == "GET"


# -- The meta-routes stay out of the table -----------------------------------------


def test_the_meta_routes_are_not_rows_in_the_table() -> None:
    """The index and the probe are meta-routes, not composed routes:
    they are not rows in the ten-route table and not entries in the
    adapter map, so the table's "ten routes, ten adapters" law is
    untouched and a route added to either half never collides."""
    from nullius_api.server import HTTP_ADAPTERS

    paths = {row.path for row in API_ROUTES}
    assert INDEX_PATH not in paths
    assert HEALTHZ_PATH not in paths
    assert INDEX_PATH not in HTTP_ADAPTERS
    assert HEALTHZ_PATH not in HTTP_ADAPTERS


# -- No leak -----------------------------------------------------------------------


def test_no_body_on_the_index_carries_a_traceback_or_a_path(
    boot: _Boot, tmp_path
) -> None:
    """The index names only the routes it serves — never a traceback,
    never a filesystem path, including this test run's own temporary
    directory."""
    server = boot(
        {"ops-fdr-deploy": _GetEndpoint(refusal=RuntimeError(f"leaked {tmp_path}"))}
    )
    _, _, body = _ask_raw(server, "GET", INDEX_PATH, INDEX_SCOPE)
    assert "Traceback" not in body
    assert str(tmp_path) not in body
    assert ".py" not in body
