"""The transport itself: feature 4's server, held to its own sentence.

*System serves the composed application over HTTP from the api
workspace member built on the standard library's ThreadingHTTPServer
with ``python -m nullius_api``, which returns a JSON body for every
response and binds 127.0.0.1 by default.*  These tests pin each clause:
the server is a ``ThreadingHTTPServer`` subclass that serves concurrent
callers; every response it can answer — success, unknown path, wrong
verb, unconfigured component, the adapter's own malformed-ask refusal,
a member's refusal, the server's own faults, even the base class's
protocol errors — carries a JSON body through the one writing door; no
body carries a traceback or a filesystem path; and the address binds
loopback by default.

The endpoints here are fakes for the dispatch laws (deterministic,
focused on the transport's own behaviour) and the real composition for
the serving laws — the fakes appear only where the transport's own
refusals need them, the same discipline the ops member's route suite
states.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import typing
from dataclasses import dataclass

import pytest
from nullius_api import ApiServer, build_server, error_payload
from nullius_api.server import (
    COMPONENT_UNCONFIGURED_CLASS,
    DEFAULT_ERROR_CLASS,
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOST_ENV,
    INTERNAL_ERROR_CLASS,
    MALFORMED_REQUEST_CLASS,
    METHOD_NOT_ALLOWED_CLASS,
    PORT_ENV,
    ROUTE_NOT_IMPLEMENTED_CLASS,
    UNKNOWN_ROUTE_CLASS,
    ApiConfig,
)

from app.module_loader import Application, create_app

# -- Helpers ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Figure:
    """A response-shaped answer: the honest-absence fields included."""

    history: tuple = ()
    figure: float | None = None


class _GetEndpoint:
    """An endpoint shaped like the no-argument GET routes the core serves."""

    route = "/metrics/fdr-deploy"

    def __init__(self, answer=None, refusal=None) -> None:
        self._answer = answer if answer is not None else _Figure()
        self._refusal = refusal
        self.asked = 0

    def get(self):
        self.asked += 1
        if self._refusal is not None:
            raise self._refusal
        return self._answer


class _DecayEndpoint:
    """An endpoint shaped like the decay route: ``get(node_id)``."""

    route = "/forward/decay"

    def __init__(self) -> None:
        self.asked_for: list[str] = []

    def get(self, node_id):
        self.asked_for.append(node_id)
        return _Figure(history=((node_id, 0.5),))


# A member-flavoured refusal: the dispatch recognises a served member's
# typed error by its module path segment, so the fake carries one.  Only
# the 503-versus-500 routing reads it — never anything about the value.
_MemberRefusal = type(
    "FdrDeployMetricError", (Exception,), {"__module__": "ops.errors"}
)


class _Boot:
    """Boot one server per case on an ephemeral port, on loopback."""

    def __init__(self) -> None:
        self._servers: list[tuple[ApiServer, threading.Thread]] = []

    def __call__(self, components, execution_engine=None) -> ApiServer:
        application = (
            components
            if isinstance(components, Application)
            else Application(components=dict(components), order=tuple(components))
        )
        server = ApiServer(
            ("127.0.0.1", 0), application, execution_engine=execution_engine
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._servers.append((server, thread))
        return server

    def shutdown(self) -> None:
        for server, thread in self._servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.fixture
def boot():
    runner = _Boot()
    yield runner
    runner.shutdown()


def _ask(server: ApiServer, method: str, path: str) -> tuple[int, dict, typing.Any]:
    """One request: status, lower-cased headers, parsed JSON body."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, (json.loads(body) if body else None)
    finally:
        connection.close()


# -- The server is the spec's own server ------------------------------------------


def test_the_server_is_built_on_the_threading_http_server(boot) -> None:
    """The standard library's ThreadingHTTPServer — the sentence's own
    substrate, and the reason a slow caller cannot queue a fast one."""
    from http.server import ThreadingHTTPServer

    assert issubclass(ApiServer, ThreadingHTTPServer)
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    status, headers, _ = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 200
    assert headers["content-type"] == "application/json"


def test_concurrent_requests_are_served_on_separate_threads(boot) -> None:
    """A worker a halt route needs cannot be held by one stalled read."""

    class _SlowEndpoint(_GetEndpoint):
        def get(self):
            time.sleep(0.75)
            return super().get()

    server = boot({"ops-fdr-deploy": _SlowEndpoint()})
    answers: list[int] = []

    def read() -> None:
        status, _, _ = _ask(server, "GET", "/metrics/fdr-deploy")
        answers.append(status)

    threads = [threading.Thread(target=read) for _ in range(2)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    elapsed = time.monotonic() - started
    assert answers == [200, 200]
    # Two full round trips inside one slow answer's span: the answers
    # overlapped instead of queueing (serially, two 0.75s answers take
    # at least 1.5s).
    assert elapsed < 1.4


# -- Every response carries a JSON body --------------------------------------------


def test_an_unknown_path_answers_a_json_404(boot) -> None:
    """No route is served there — and the refusal is still a body."""
    server = boot({})
    status, headers, body = _ask(server, "GET", "/nowhere")
    assert status == 404
    assert headers["content-type"] == "application/json"
    assert body["error"]["code"] == "unknown_route"
    assert "/nowhere" in body["error"]["message"]


def test_a_wrong_verb_answers_405_with_an_allow_header(boot) -> None:
    """The path is known, the verb is not — and Allow says which is."""
    server = boot({})
    status, headers, body = _ask(server, "GET", "/ledger/debit")
    assert status == 405
    assert headers["allow"] == "POST"
    assert headers["content-type"] == "application/json"
    assert body["error"]["code"] == "method_not_allowed"


def test_a_method_no_route_uses_answers_json_not_html(boot) -> None:
    """The base class's own unsupported-method door answers the
    envelope too — the last non-JSON path, closed."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    status, headers, body = _ask(server, "PUT", "/metrics/fdr-deploy")
    assert status == 501
    assert headers["content-type"] == "application/json"
    assert "error" in body


def test_an_unconfigured_component_is_named_in_the_refusal(boot) -> None:
    """A route whose store resolved to nothing answers 503 naming the
    component and the configuration it resolves from."""
    server = boot({})
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"
    assert "ops-fdr-deploy" in body["error"]["message"]
    assert "DATABASE_URL" in body["error"]["message"]


def test_a_post_route_without_an_adapter_answers_not_implemented(boot) -> None:
    """The table declares the route (so its verb answers 405 and its
    component resolves), and the serving lands with the per-route
    features — stated as a JSON refusal, never a dropped connection."""
    server = boot({"risk-halt": object()})
    status, _, body = _ask(server, "POST", "/risk/halt")
    assert status == 501
    assert body["error"]["code"] == "route_not_implemented"


def test_the_unbound_engine_is_carried_not_fabricated(boot) -> None:
    """The execution engine the entrypoint did not bind is None on the
    server — a fact the halt route's later refusal answers, not one the
    transport papers over."""
    marker = object()
    server = boot({}, execution_engine=marker)
    assert server.execution_engine is marker
    unbound = boot({})
    assert unbound.execution_engine is None


# -- Serving through the composed component ---------------------------------------


def test_a_get_route_answers_the_endpoint_response_as_json(boot) -> None:
    """Serving is asking the composed endpoint: 200, the member's own
    fields, nothing computed here."""
    endpoint = _GetEndpoint(answer=_Figure(history=(("c1", 0.5, "2026-09-28"),)))
    server = boot({"ops-fdr-deploy": endpoint})
    status, headers, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body == {"history": [["c1", 0.5, "2026-09-28"]], "figure": None}
    assert endpoint.asked == 1


def test_an_empty_store_answers_null_and_empty_never_zero(boot) -> None:
    """The honest absence passes straight through the transport — the
    figure is None and the history empty, never a fabricated 0.0."""
    server = boot({"ops-fdr-deploy": _GetEndpoint(answer=_Figure())})
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 200
    assert body == {"history": [], "figure": None}


def test_the_decay_route_passes_the_asked_identity_through(boot) -> None:
    """``?node_id=`` reaches the endpoint exactly as asked — the store
    owns validation, the transport does not re-state it."""
    endpoint = _DecayEndpoint()
    server = boot({"forward-decay": endpoint})
    status, _, body = _ask(
        server, "GET", "/forward/decay?node_id=00000000-0000-0000-0000-000000000001"
    )
    assert status == 200
    assert body["history"] == [["00000000-0000-0000-0000-000000000001", 0.5]]
    assert endpoint.asked_for == ["00000000-0000-0000-0000-000000000001"]


def test_the_decay_route_without_an_identity_is_refused_before_the_store(
    boot,
) -> None:
    """A GET that states no signal never reaches the store it would
    read — a malformed ask, answered 400 as the adapter's own refusal."""
    endpoint = _DecayEndpoint()
    server = boot({"forward-decay": endpoint})
    status, _, body = _ask(server, "GET", "/forward/decay")
    assert status == 400
    assert body["error"]["code"] == "missing_node_id"
    assert endpoint.asked_for == []


# -- Refusals: whose message, and what never leaks ----------------------------------


def test_a_members_refusal_answers_the_members_message(boot) -> None:
    """A served member's typed refusal is operator-facing by the
    workspace's law — answered verbatim, 503, never retried around."""
    refusal = _MemberRefusal(
        "fdr_deploy_metric: the store refused the trend read; the repair "
        "is the store's own"
    )
    server = boot({"ops-fdr-deploy": _GetEndpoint(refusal=refusal)})
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 503
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["message"].startswith("fdr_deploy_metric:")


def test_an_unexpected_fault_answers_a_generic_body(boot) -> None:
    """A fault that is nobody's typed refusal answers the internal
    error — the cause named in the log, never in the body."""
    server = boot({"ops-fdr-deploy": _GetEndpoint(refusal=RuntimeError("boom"))})
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 500
    assert body["error"]["code"] == "internal_error"
    assert "boom" not in json.dumps(body)


def test_an_unencodable_payload_answers_the_internal_error(boot) -> None:
    """Even a success the codec cannot spell never answers a half
    response or a repr — the one writing door refuses it."""

    @dataclass(frozen=True)
    class _Unspellable:
        path: object = object()

    server = boot({"ops-fdr-deploy": _GetEndpoint(answer=_Unspellable())})
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 500
    assert body["error"]["code"] == "internal_error"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/nowhere"),
        ("GET", "/ledger/debit"),
        ("PUT", "/metrics/fdr-deploy"),
        ("GET", "/metrics/fdr-deploy"),
        ("POST", "/risk/halt"),
        ("GET", "/forward/decay"),
        ("GET", "/target"),
    ],
)
def test_no_body_carries_a_traceback_or_a_filesystem_path(
    boot, tmp_path, method, path
) -> None:
    """The envelope law, over every refusal shape the transport answers:
    no traceback, no filesystem path — including this test run's own
    temporary directory, which a leaked store URL would name."""
    server = boot(
        {
            "ops-fdr-deploy": _GetEndpoint(
                refusal=RuntimeError(f"leaked {tmp_path / 'secret.db'}")
            )
        }
    )
    _, _, body = _ask(server, method, path)
    text = json.dumps(body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text


# -- Every refusal carries its class -------------------------------------------------


def test_every_refusal_shape_answers_a_class(boot) -> None:
    """The envelope is ``{"error": {"code", "class", "message"}}`` —
    every refusal answers a non-empty class alongside the code word and
    the message, so a caller routes on the refusal's own name without
    parsing the message."""
    refusal = _MemberRefusal("fdr_deploy_metric: the store refused; the repair")
    server = boot(
        {"ops-fdr-deploy": _GetEndpoint(refusal=refusal)}
    )
    shapes = [
        ("GET", "/nowhere"),
        ("GET", "/ledger/debit"),
        ("PUT", "/metrics/fdr-deploy"),
        ("POST", "/risk/halt"),
        ("GET", "/forward/decay"),
        ("GET", "/target"),
        ("GET", "/metrics/fdr-deploy"),  # the member refusal
    ]
    for method, path in shapes:
        _, _, body = _ask(server, method, path)
        assert body["error"]["class"], f"{method} {path} answered no class"
        assert "code" in body["error"] and "message" in body["error"]


def test_the_member_refusal_carries_the_raised_class(boot) -> None:
    """The member-refusal door carries ``type(exc).__name__`` — the very
    class the served member's own traceback would name, which is why
    carrying it is not the leak the envelope law forbids."""
    refusal = _MemberRefusal("fdr_deploy_metric: the store refused; the repair")
    server = boot({"ops-fdr-deploy": _GetEndpoint(refusal=refusal)})
    _, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert body["error"]["code"] == "member_refusal"
    assert body["error"]["class"] == "FdrDeployMetricError"
    # The class is the name only — never a module path or a filesystem
    # path smuggled in beside it.
    assert "." not in body["error"]["class"]
    assert "/" not in body["error"]["class"]


def test_the_transports_own_doors_answer_their_stable_classes(boot) -> None:
    """The transport's own refusals each answer the class they own, so a
    caller can tell an unknown route from a wrong verb from an
    unconfigured component without reading the message."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    _, _, unknown = _ask(server, "GET", "/nowhere")
    assert unknown["error"]["class"] == UNKNOWN_ROUTE_CLASS
    _, _, wrong = _ask(server, "GET", "/ledger/debit")
    assert wrong["error"]["class"] == METHOD_NOT_ALLOWED_CLASS
    # An unconfigured component is a route whose store resolved to
    # nothing — a server with no components, so /metrics/fdr-deploy has
    # no endpoint to serve.
    empty = boot({})
    _, _, unconfigured = _ask(empty, "GET", "/metrics/fdr-deploy")
    assert unconfigured["error"]["class"] == COMPONENT_UNCONFIGURED_CLASS
    configured = boot({"risk-halt": object()})
    _, _, not_impl = _ask(configured, "POST", "/risk/halt")
    assert not_impl["error"]["class"] == ROUTE_NOT_IMPLEMENTED_CLASS


def test_a_malformed_ask_answers_the_malformed_class(boot) -> None:
    """The one refusal the transport owns — a GET that states no signal
    — answers the malformed-request class."""
    endpoint = _DecayEndpoint()
    server = boot({"forward-decay": endpoint})
    _, _, body = _ask(server, "GET", "/forward/decay")
    assert body["error"]["code"] == "missing_node_id"
    assert body["error"]["class"] == MALFORMED_REQUEST_CLASS


def test_an_unexpected_fault_answers_the_internal_error_class(boot) -> None:
    """A fault that is nobody's typed refusal answers the generic
    internal error — a stable class, the cause named in the log, never
    in the body."""
    server = boot({"ops-fdr-deploy": _GetEndpoint(refusal=RuntimeError("boom"))})
    _, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["class"] == INTERNAL_ERROR_CLASS
    assert "boom" not in json.dumps(body)


def test_a_call_site_that_names_no_class_still_answers_a_class(boot) -> None:
    """The class argument is keyword-only with a default, so the envelope
    gains a field rather than reshaping — a caller that omits it still
    reads a class, never an absent field."""
    assert error_payload("c", "m")["error"]["class"] == DEFAULT_ERROR_CLASS
    assert error_payload("c", "m")["error"] == {
        "code": "c",
        "class": DEFAULT_ERROR_CLASS,
        "message": "m",
    }
    # The two original positional arguments are unchanged.
    assert error_payload("c", "m")["error"]["code"] == "c"
    assert error_payload("c", "m")["error"]["message"] == "m"


def test_the_class_is_a_plain_string_never_a_traceback_or_a_path(boot, tmp_path) -> None:
    """The class field does not become a second place a path could leak:
    a member refusal whose message quotes a leaked store URL answers a
    class that is a bare name, and no body carries a traceback, a
    filesystem path or a ``.py`` suffix."""
    server = boot(
        {
            "ops-fdr-deploy": _GetEndpoint(
                refusal=RuntimeError(f"leaked {tmp_path / 'secret.db'}")
            )
        }
    )
    _, _, body = _ask(server, "GET", "/metrics/fdr-deploy")
    text = json.dumps(body)
    assert "Traceback" not in text
    assert str(tmp_path) not in text
    assert ".py" not in text
    assert "/" not in body["error"]["class"]


# -- The address -------------------------------------------------------------------


def test_the_address_binds_loopback_by_default() -> None:
    """No host named: 127.0.0.1, the sentence's own default."""
    assert ApiConfig.resolve(env={}).host == DEFAULT_HOST == "127.0.0.1"
    assert ApiConfig.resolve(env={}).port == DEFAULT_PORT


def test_the_environment_answers_when_the_flag_is_absent() -> None:
    config = ApiConfig.resolve(env={HOST_ENV: "localhost", PORT_ENV: "9001"})
    assert config.host == "localhost"
    assert config.port == 9001


def test_the_flag_wins_over_the_environment() -> None:
    config = ApiConfig.resolve(
        env={HOST_ENV: "localhost", PORT_ENV: "9001"},
        host="127.0.0.1",
        port=9002,
    )
    assert config.host == "127.0.0.1"
    assert config.port == 9002


def test_an_unset_environment_value_counts_as_absent() -> None:
    """Empty and whitespace-only spellings are unset — the members' own
    unset semantics."""
    config = ApiConfig.resolve(env={HOST_ENV: "  ", PORT_ENV: ""})
    assert config.host == DEFAULT_HOST
    assert config.port == DEFAULT_PORT


def test_a_port_that_is_not_a_port_is_refused_by_name() -> None:
    with pytest.raises(ValueError) as raised:
        ApiConfig.resolve(env={PORT_ENV: "seven"})
    assert PORT_ENV in str(raised.value)


def test_a_port_out_of_range_is_refused_by_name() -> None:
    with pytest.raises(ValueError) as raised:
        ApiConfig.resolve(env={PORT_ENV: "70000"})
    assert "65535" in str(raised.value)


# -- The composed application, really composed --------------------------------------


def test_the_transport_serves_the_composed_application(
    boot, test_database_url: str
) -> None:
    """The flagship sentence: the factory's own composition — resolved
    through the application's own ``get`` — answers over HTTP, its
    empty store honestly empty."""
    application = create_app()
    server = boot(application)
    status, headers, body = _ask(server, "GET", "/metrics/fdr-deploy")
    assert status == 200
    assert headers["content-type"] == "application/json"
    assert body == {"history": []}

    status, _, body = _ask(server, "GET", "/metrics/instrument-status")
    assert status == 200
    assert body["canary"] is True
    assert body["ks_guard"] is None  # absent lamp: null, never lit

    status, _, body = _ask(server, "GET", "/metrics/regime-coverage")
    assert status == 200
    assert body == {"strata": []}


def test_build_server_composes_when_given_no_application(
    boot, test_database_url: str
) -> None:
    """The construction path the entrypoint takes: no application
    handed in means the factory composes one — and the routes resolve
    over what composition built."""
    server = build_server(ApiConfig.resolve(env={PORT_ENV: "0"}))
    try:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        status, _, body = _ask(server, "GET", "/ledger/k-effective")
        assert status == 200
        assert body == {"view": {"counts": []}}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
