"""The token gate at the wire: what answers, what is refused, and how.

Feature 18's second half — *returns 401 for a missing or unknown token,
403 for a token outside the route's scope* — stated over a booted
server rather than over :mod:`nullius_api.auth`'s loader, which
:mod:`test_auth` already holds to the file's own contract.  Both halves
are the same sentence, but they fail differently: a wrong loader is a
deployment that cannot start, and a wrong dispatch is a deployment that
*did* start and answered the wrong thing.

Three laws are pinned here beyond the status codes, because each is a
constraint in its own right rather than a detail of the refusal:

*Every route but* ``GET /healthz`` *is gated* — including the index and
including paths no route serves, so an unauthenticated caller cannot
enumerate the surface by probing it.

*Authorization comes strictly after authentication and strictly before
the deployment* — so a wrong-scoped credential cannot learn from the
status whether a store is configured.

*The token is never echoed and never logged* — the access log the base
class writes carries the request line, which has no header in it, and
no body this module produces carries a credential.

The endpoints here are fakes, the same discipline :mod:`test_server`
states: this module is about the gate's own behaviour, so a fake
component makes every case reachable without a store, a database, or a
member's cooperation.  Where a case needs the *real* surface — that the
gate stands in front of all ten rows — the table is read directly
rather than booting ten composed servers.
"""

from __future__ import annotations

import http.client
import json
import threading
from dataclasses import dataclass

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import (
    API_ROUTES,
    API_SCOPES,
    EVALUATOR,
    FORBIDDEN_CLASS,
    INDEX_SCOPE,
    METRICS_READ,
    RESEARCH,
    RISK,
    UNAUTHENTICATED_CLASS,
    ApiServer,
    ApiTokens,
)
from nullius_api.server import INDEX_PATH

from app.module_loader import Application

# -- A booted server and one request -----------------------------------------------


@dataclass(frozen=True)
class _Answer:
    """A response-shaped answer, the honest-absence fields included."""

    history: tuple = ()
    figure: float | None = None


class _Endpoint:
    """One fake endpoint speaking whichever verb its route declares."""

    def __init__(self, route: str, verb: str) -> None:
        self.route = route
        self._verb = verb.lower()
        self.asked = 0

    def __getattr__(self, name: str):
        if name != self._verb:  # pragma: no cover - the dispatch never asks
            raise AttributeError(name)

        def answer(*args, **kwargs):
            self.asked += 1
            return _Answer()

        return answer


class _Boot:
    """Boot one server per case on an ephemeral port, on loopback.

    Every server here boots with the suite's own token set and a fake
    endpoint for each route the case asks about, so a test states the
    *credentials* it means and nothing else.  The component names come
    off :data:`API_ROUTES` rather than being spelled here — a second
    spelling of the table is exactly what :mod:`nullius_api.routes`
    exists to prevent.
    """

    def __init__(self) -> None:
        self._servers: list[tuple[ApiServer, threading.Thread]] = []

    def __call__(self, tokens: ApiTokens | None = None, *, configured: bool = True):
        components = {}
        if configured:
            components = {
                row.component: _Endpoint(row.path, row.verb) for row in API_ROUTES
            }
        application = Application(components=components, order=tuple(components))
        server = ApiServer(
            ("127.0.0.1", 0),
            application,
            TEST_TOKENS if tokens is None else tokens,
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


def _ask(
    server: ApiServer, method: str, path: str, header: str | None = None
) -> tuple[int, dict[str, str], object]:
    """One request with the ``Authorization`` header verbatim.

    ``header`` is the whole header value rather than a scope, because
    the shapes this module refuses — a different scheme, a bare token,
    a ``Bearer`` with nothing after it — are not spellable as a scope,
    and those are half of what a 401 is for.  ``None`` sends no header
    at all.
    """
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        headers = {} if header is None else {"Authorization": header}
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        answer = {name.lower(): value for name, value in response.getheaders()}
        try:
            parsed: object = json.loads(body) if body else None
        except ValueError:  # pragma: no cover - only the index answers HTML
            parsed = body
        return response.status, answer, parsed
    finally:
        connection.close()


def _bearer(scope: str) -> str:
    """The header a caller holding ``scope`` presents."""
    return f"Bearer {token_for(scope)}"


def _refused_by_the_gate(status: int) -> bool:
    """Whether ``status`` is one of the gate's own two refusals.

    Used by the acceptance sweeps below, which are about whether a
    credential is *admitted* rather than about what the route then
    answers: the adapters are the real ones, and a bodyless ``POST``
    reaches the route as a malformed ask (400) whatever its scope.  That
    400 is the adapter's answer to a question this module did not
    finish asking, so it is neither a pass nor a failure of the gate —
    but a 401 or a 403 is unambiguously the gate saying no.
    """
    return status in (401, 403)


# -- GET /healthz is the one route that answers without a token --------------------


def test_healthz_answers_with_no_token_at_all(boot) -> None:
    """*Every route except GET /healthz* — the carve-out, stated first
    because it is the boundary the rest of this module is measured
    against.  The probe asks nothing of a store, so it has nothing to
    protect and nothing to leak."""
    server = boot()
    status, _, body = _ask(server, "GET", "/healthz")
    assert status == 200
    assert body == {"status": "ok"}


def test_healthz_answers_the_same_with_a_token(boot) -> None:
    """A credential is not *required* and not *refused*: the probe
    answers the same body either way, so a deployment's monitoring does
    not break when it starts presenting one."""
    server = boot()
    status, _, body = _ask(server, "GET", "/healthz", _bearer(METRICS_READ))
    assert status == 200
    assert body == {"status": "ok"}


def test_healthz_still_refuses_a_wrong_verb_without_a_token(boot) -> None:
    """The carve-out is for ``GET /healthz``, not for the path: a wrong
    verb is refused *before* the gate, because that refusal is about the
    request line rather than about the caller — a caller who cannot be
    told their verb is wrong has no way to learn the right one."""
    server = boot()
    status, headers, body = _ask(server, "POST", "/healthz")
    assert status == 405
    assert headers["allow"] == "GET"
    assert body["error"]["code"] == "method_not_allowed"


# -- 401: no usable credential ------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/metrics/fdr-deploy", "/ledger/k-effective", "/risk/halt", "/", "/nope"],
)
def test_every_other_path_answers_401_without_a_token(boot, path: str) -> None:
    """No header, and every route but the probe refuses.  ``/nope`` is
    deliberately in this list: an unauthenticated caller must not be
    able to tell a route from a non-route, or the 404s would map the
    surface for them."""
    server = boot()
    status, _, body = _ask(server, "GET" if path != "/risk/halt" else "POST", path)
    assert status == 401
    assert body["error"]["code"] == "missing_token"
    assert body["error"]["class"] == UNAUTHENTICATED_CLASS


@pytest.mark.parametrize(
    "header",
    [
        "Basic dXNlcjpwYXNz",
        "Bearer",
        "Bearer   ",
        "token-with-no-scheme",
        f"Token {token_for(RISK)}",  # the right secret, the wrong scheme
        "",
    ],
)
def test_a_header_with_no_bearer_token_answers_401(boot, header: str) -> None:
    """The right secret under the wrong scheme is still *you have not
    identified yourself* — the caller's repair is the scheme, not the
    credential."""
    server = boot()
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy", header)
    assert status == 401
    assert body["error"]["code"] == "missing_token"


def test_an_unknown_token_answers_401_with_its_own_code(boot) -> None:
    """*401 for a missing or unknown token* — one status, two operator
    facts: *add a header* and *this header is not one of ours* send an
    operator to different places, so they carry different code words."""
    server = boot()
    status, _, body = _ask(
        server, "GET", "/metrics/fdr-deploy", "Bearer not-a-configured-token"
    )
    assert status == 401
    assert body["error"]["code"] == "unknown_token"
    assert body["error"]["class"] == UNAUTHENTICATED_CLASS


def test_the_401_body_never_repeats_the_presented_token(boot) -> None:
    """The credential is not echoed, not hashed, not truncated — a body
    is read by an operator and kept by whatever logs it."""
    secret = "a-guess-that-is-not-configured"
    server = boot()
    status, _, body = _ask(server, "GET", "/metrics/fdr-deploy", f"Bearer {secret}")
    assert status == 401
    assert secret not in json.dumps(body)


def test_a_401_carries_the_bearer_challenge(boot) -> None:
    """A 401 owes the caller a ``WWW-Authenticate`` challenge saying
    which scheme to use; without it the client cannot know what the
    refusal is asking for."""
    server = boot()
    for header in (None, "Bearer wrong"):
        status, headers, _ = _ask(server, "GET", "/metrics/fdr-deploy", header)
        assert status == 401
        assert headers["www-authenticate"] == "Bearer"


def test_a_token_from_another_deployment_is_401_not_403(boot) -> None:
    """An unknown token is never a 403, even on a route it *would* have
    had the scope for — the two refusals answer different questions and
    are never merged."""
    other = ApiTokens.from_scope_tokens({"risk": "another-deployments-token"})
    server = boot(other)
    status, _, _ = _ask(server, "POST", "/risk/halt", "Bearer another-deployments-token")
    assert not _refused_by_the_gate(status)  # its own token, its own scope
    status, _, body = _ask(server, "POST", "/risk/halt", f"Bearer {token_for(RISK)}")
    assert status == 401
    assert body["error"]["code"] == "unknown_token"


# -- 403: a known token outside the route's scope ----------------------------------


@pytest.mark.parametrize(
    "scope,path,verb",
    [
        (RISK, "/metrics/fdr-deploy", "GET"),
        (METRICS_READ, "/risk/halt", "POST"),
        (RESEARCH, "/ledger/k-effective", "GET"),
        (EVALUATOR, "/forward/decay", "GET"),
        (METRICS_READ, "/forward/promote", "POST"),
        (EVALUATOR, "/promotion/pre-register", "POST"),
        (RESEARCH, "/metrics/instrument-status", "GET"),
        (RISK, "/ledger/debit", "POST"),
    ],
)
def test_a_token_outside_the_route_s_scope_answers_403(
    boot, scope: str, path: str, verb: str
) -> None:
    """*403 for a token outside the route's scope* — a real credential
    of this deployment, held to a surface it does not reach.  Each pair
    is a token that exists and a route it must not touch, so the case
    cannot pass by accident of an unknown token."""
    server = boot()
    status, _, body = _ask(server, verb, path, _bearer(scope))
    assert status == 403
    assert body["error"]["code"] == "forbidden_scope"
    assert body["error"]["class"] == FORBIDDEN_CLASS


def test_the_403_names_the_route_both_scopes_and_neither_token(boot) -> None:
    """The refusal says what the caller must act on — the route, the
    scope it wants, the scope they hold — and nothing else.  The list
    of configured scopes is deliberately absent: which surfaces this
    deployment provisions is not a fact a wrong-scoped caller needs."""
    server = boot()
    _, _, body = _ask(server, "POST", "/risk/halt", _bearer(METRICS_READ))
    message = body["error"]["message"]
    assert "POST /risk/halt" in message
    assert RISK in message
    assert METRICS_READ in message
    assert token_for(RISK) not in message
    assert token_for(METRICS_READ) not in message


def test_every_shipped_route_admits_its_own_scope(boot) -> None:
    """The gate is not a wall: for each of the ten rows, the credential
    that row declares gets *past* the gate.  Without this, a typo in one
    row's scope would pass every 403 test below and fail in production.

    The assertion is *not refused by the gate*, not *200*: these are the
    real adapters over fake endpoints, and a bodyless ``POST`` is a
    malformed ask (400) however good the credential.  What this pins is
    the gate's own decision — the credential is admitted — which is why
    the status is read against :func:`_refused_by_the_gate` rather than
    against a number the adapter would have to cooperate with.
    """
    server = boot()
    for row in API_ROUTES:
        status, _, body = _ask(server, row.verb, row.path, _bearer(row.scope))
        assert not _refused_by_the_gate(status), (
            f"{row.verb} {row.path} refused its own scope {row.scope}: {body}"
        )


def test_every_shipped_route_refuses_every_other_scope(boot) -> None:
    """And the exhaustive complement: for each row, each of the *other*
    three scope words is a 403.  Stated as a sweep rather than as four
    hand-picked pairs, because the failure this catches — one row
    accepting a scope it should not — is invisible to any list of pairs
    somebody wrote while thinking about the rows they had in mind."""
    server = boot()
    for row in API_ROUTES:
        for scope in API_SCOPES:
            if scope == row.scope:
                continue
            status, _, body = _ask(server, row.verb, row.path, _bearer(scope))
            assert status == 403, f"{row.verb} {row.path} accepted {scope}"
            assert body["error"]["code"] == "forbidden_scope"


# -- The index is gated too ---------------------------------------------------------


def test_the_index_is_not_exempt_from_the_gate(boot) -> None:
    """Only ``/healthz`` is.  The index describes the transport's *own*
    surface, which is exactly the map an unauthenticated caller must not
    get: it names every route and whether each store is configured."""
    server = boot()
    status, _, body = _ask(server, "GET", INDEX_PATH)
    assert status == 401
    assert body["error"]["code"] == "missing_token"


def test_the_index_refuses_a_scope_it_does_not_carry(boot) -> None:
    """``/`` wants :data:`~nullius_api.routes.INDEX_SCOPE`; the other
    three words are 403 rather than a rendered map."""
    server = boot()
    status, _, body = _ask(server, "GET", INDEX_PATH, _bearer(RISK))
    assert status == 403
    assert body["error"]["code"] == "forbidden_scope"

    status, _, body = _ask(server, "GET", INDEX_PATH, _bearer(INDEX_SCOPE))
    assert status == 200
    assert isinstance(body, str) and body.startswith("<!doctype html>")


# -- Ordering: authorization before the deployment's own state ----------------------


def test_a_wrong_scope_learns_nothing_about_what_is_configured(boot) -> None:
    """The 403 precedes the unconfigured-component check, so the same
    wrong credential answers the same 403 whether or not the deployment
    configured the store.  Otherwise the status alone would report which
    stores exist."""
    configured = boot(configured=True)
    bare = boot(configured=False)
    for server in (configured, bare):
        status, _, body = _ask(server, "POST", "/risk/halt", _bearer(METRICS_READ))
        assert status == 403
        assert body["error"]["code"] == "forbidden_scope"


def test_a_right_scope_reaches_the_unconfigured_refusal(boot) -> None:
    """And the other side of that ordering: a *correct* credential on an
    unconfigured deployment gets the 503, which is the deployment's own
    fact and one this caller is entitled to."""
    server = boot(configured=False)
    status, _, body = _ask(server, "POST", "/risk/halt", _bearer(RISK))
    assert status == 503
    assert body["error"]["code"] == "component_unconfigured"


def test_an_unknown_path_answers_401_before_404(boot) -> None:
    """*Which routes exist* is not a fact an unauthenticated caller can
    probe: the gate precedes the table lookup, so an unknown path is
    indistinguishable from a known one until a token is presented."""
    server = boot()
    status, _, body = _ask(server, "GET", "/a-path-that-is-not-a-route")
    assert status == 401
    assert body["error"]["code"] == "missing_token"

    status, _, body = _ask(
        server, "GET", "/a-path-that-is-not-a-route", _bearer(METRICS_READ)
    )
    assert status == 404
    assert body["error"]["code"] == "unknown_route"


def test_a_wrong_verb_answers_401_before_405(boot) -> None:
    """The same ordering for the verb: an unauthenticated caller who
    posts to a GET route is told to identify themselves, not that the
    route answers GET — the ``Allow`` set is itself part of the map."""
    server = boot()
    status, _, body = _ask(server, "POST", "/metrics/fdr-deploy")
    assert status == 401
    assert body["error"]["code"] == "missing_token"


def test_a_wrong_verb_with_the_right_scope_answers_405(boot) -> None:
    """Past the gate, the 405 arrives with its ``Allow`` set as before —
    the gate is a door in front of the dispatch, not a change to it."""
    server = boot()
    status, headers, _ = _ask(
        server, "POST", "/metrics/fdr-deploy", _bearer(METRICS_READ)
    )
    assert status == 405
    assert headers["allow"] == "GET"


@pytest.mark.parametrize("verb", ["PUT", "DELETE", "PATCH", "OPTIONS"])
def test_a_verb_no_route_uses_is_refused_identically_everywhere(
    boot, verb: str
) -> None:
    """A verb the transport does not implement never reaches the dispatch
    at all: only ``GET`` and ``POST`` have handlers, so the base class's
    protocol door answers 501 before ``_dispatch`` — and therefore before
    the gate.

    That is safe, and this test is what says why: the refusal is
    *byte-identical* for a route and for a path no route serves, so it
    cannot be used to map the surface, which is the whole of what the
    gate's ordering protects.  It is also pre-existing feature-4/5
    behaviour (*"the base class's own unsupported-method door answers the
    envelope too"*), so feature 18 changes nothing here and this pins
    that it did not.
    """
    known = boot()
    bare = boot(configured=False)
    refusals = {
        _ask(server, verb, path)[2]["error"]["message"]
        for server in (known, bare)
        for path in ("/risk/halt", "/no-such-route")
    }
    assert len(refusals) == 1, refusals
    status, headers, body = _ask(known, verb, "/risk/halt")
    assert status == 501
    assert headers["content-type"] == "application/json"
    assert "error" in body


# -- The credential does not travel -------------------------------------------------


def test_no_successful_body_carries_the_token(boot) -> None:
    """Every route's own answer is a fact about the store, never about
    the credential that asked — the gate reads the token and then the
    token is gone, for the whole of the request's life.  Both the
    admitted answer and the adapter's own refusal are checked, since
    either is a body a caller receives."""
    server = boot()
    for row in API_ROUTES:
        for header in (_bearer(row.scope), None, _bearer(INDEX_SCOPE)):
            _, _, body = _ask(server, row.verb, row.path, header)
            written = json.dumps(body)
            assert token_for(row.scope) not in written
            assert token_for(INDEX_SCOPE) not in written


def test_the_access_log_carries_the_request_line_not_the_header(
    boot, caplog: pytest.LogCaptureFixture
) -> None:
    """*Tokens and request bodies are never written to a log.*

    One line per request, carrying the request line and the status and
    nothing else; this pins that the transport adds nothing to it.  No
    handler here logs the header, the parsed token or the body, so the
    one line the server writes is one that cannot carry a credential.
    The token is presented in the header and asserted absent from
    everything written.

    Feature 20 replaced the base class's unstructured line with the
    structured record — which is still one line per request, and still
    the verb, the route and the status — so this assertion is unchanged
    by that feature and is exactly the property the structured record
    had to preserve: the credential travels nowhere near the stream.
    """
    import logging
    import time

    server = boot()
    with caplog.at_level(logging.DEBUG):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer(METRICS_READ))
        _ask(server, "GET", "/metrics/fdr-deploy", "Bearer unknown-to-this-server")
        _ask(server, "GET", "/metrics/fdr-deploy")
        # The record is emitted in the handler's own thread once the
        # request's lifecycle ends, a moment after the client has read
        # its response, so the capture is waited for rather than read on
        # the instant the last request returned.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not any(
            "/metrics/fdr-deploy" in record.getMessage() for record in caplog.records
        ):
            time.sleep(0.01)
    written = "\n".join(record.getMessage() for record in caplog.records)
    assert token_for(METRICS_READ) not in written
    assert "unknown-to-this-server" not in written
    # And the access line itself is present, so the assertion above is
    # about what that line contains rather than about logging being off.
    assert "/metrics/fdr-deploy" in written


def test_no_refusal_body_carries_a_traceback_or_a_path(boot) -> None:
    """The envelope's own law, held for this feature's refusals: an
    operator reads these, and a stack or a filesystem path is neither a
    repair nor something to publish."""
    server = boot()
    asks = [
        ("GET", "/metrics/fdr-deploy", None),
        ("GET", "/metrics/fdr-deploy", "Bearer unknown"),
        ("POST", "/risk/halt", _bearer(METRICS_READ)),
        ("GET", "/", None),
        ("GET", "/nowhere", _bearer(METRICS_READ)),
    ]
    for method, path, header in asks:
        _, _, body = _ask(server, method, path, header)
        written = json.dumps(body)
        assert "Traceback" not in written
        assert "/home/" not in written
        assert ".py" not in written


# -- A server cannot be constructed without credentials ----------------------------


def test_an_empty_token_set_is_refused_at_construction() -> None:
    """*Refuses to start when no token is configured*, at the type: a
    hand-built :class:`ApiTokens` with no entries cannot exist, so
    *the server holds a set* is not a property a later caller can
    accidentally drop.  :class:`ApiServer` requires the argument too —
    it has no default — which is the same law at the next layer out."""
    from nullius_api import ApiTokenConfigError

    with pytest.raises(ApiTokenConfigError):
        ApiTokens(entries=())
    assert len(TEST_TOKENS) == 4
