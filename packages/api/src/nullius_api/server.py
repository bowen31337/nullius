"""The HTTP transport: a threading server that answers only in JSON.

The whole of additions_spec_journeys.xml feature 4 at its seam — *System
serves the composed application over HTTP from the api workspace member
built on the standard library's ThreadingHTTPServer with ``python -m
nullius_api``, which returns a JSON body for every response and binds
127.0.0.1 by default* — built on :class:`http.server.
ThreadingHTTPServer` and nothing else from the network stack, so the
lockfile gains no third-party edge for the transport (the constraint the
member's whole scaffold exists under).

Three laws shape the design:

**Every response carries a JSON body.**  One door writes every body —
:meth:`ApiRequestHandler._write_json`, through :func:`~nullius_api.
json_encoding.dumps` — and the inherited HTML error path
(:meth:`BaseHTTPRequestHandler.send_error`, which the base class uses
for protocol-level refusals like an unreadable request line) is
overridden to the same JSON envelope, so there is no code path left
that can answer in anything else.  An unknown path, a wrong verb, an
unconfigured component, a member's refusal and the server's own
unexpected faults all answer the same shape — the structured error
envelope of :func:`error_payload` — and the envelope never carries a
traceback or a filesystem path: an unexpected fault answers a generic
internal error (the detail goes to the server's log, class name only),
because a body an operator reads is not a place to leak a stack.

**The server binds 127.0.0.1 unless told otherwise.**  A deployment
that names no host serves on the loopback interface only — the same
local-only stance the dashboard's launch configuration takes — with
``--host``/``--port`` flags overriding the ``NULLIUS_API_HOST`` /
``NULLIUS_API_PORT`` environment, and flags overriding both.

**The endpoints are the members', never re-implemented.**  The server
holds the composed :class:`~app.module_loader.Application` and serves
each route through the component the factory handed out
(:mod:`nullius_api.routes` spells the pairing); the adapters below are
the thinnest possible calls — no figure is computed, defaulted or
fabricated here, so an empty store reaches the wire as the honest
``null``/empty the members answer, never as ``0.0``.
"""

from __future__ import annotations

import importlib
import logging
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .json_encoding import dumps
from .routes import ResolvedRoute, resolve_routes

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "EXECUTION_ENGINE_ENV",
    "HOST_ENV",
    "PORT_ENV",
    "ApiConfig",
    "ApiRequest",
    "ApiRequestHandler",
    "ApiServer",
    "ExecutionEngineResolutionError",
    "build_server",
    "error_payload",
    "resolve_execution_engine",
]

#: The interface bound when no host is named — loopback only, so a
#: server started casually on a workstation serves its operator and
#: nothing else (the local-only stance the spec's J7 journey states for
#: the dashboard, held here for the API until a deployment names a host
#: explicitly).
DEFAULT_HOST = "127.0.0.1"

#: The port bound when neither the flag nor the environment names one.
#: No spec line pins an API port — the deployment fact the flags and
#: environment exist to state — so this is a collision-free default,
#: deliberately clear of Streamlit's 8501.
DEFAULT_PORT = 8710

#: The environment the host is read from when the flag is absent.
HOST_ENV = "NULLIUS_API_HOST"

#: The environment the port is read from when the flag is absent.
PORT_ENV = "NULLIUS_API_PORT"

#: The environment naming the execution engine bound to POST /risk/halt
#: at server start, as a ``module:attribute`` path (additions_spec_
#: journeys.xml's integration points).  Unset means unbound — the halt
#: route's refusal to answer, never a refusal to start.
EXECUTION_ENGINE_ENV = "NULLIUS_EXECUTION_ENGINE"

log = logging.getLogger("nullius_api.server")


# -- Configuration ---------------------------------------------------------------


@dataclass(frozen=True)
class ApiConfig:
    """Where the server binds: flags over environment over defaults.

    The precedence is the sentence's own order — *binds 127.0.0.1 by
    default*, the environment naming the deployment's answer, the flag
    the operator's explicit ask on top — so a host is served non-
    loopback only when somebody said so, out loud, on the command line
    or in the environment.  Frozen, because the address a server bound
    is a fact about the process, not a knob to adjust mid-flight.
    """

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT

    @classmethod
    def resolve(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> ApiConfig:
        """Resolve the bind address: ``host``/``port`` win, then the
        environment, then the defaults.

        ``env`` defaults to the process environment; ``host`` and
        ``port`` are the command-line flags (``None`` = not given).
        An unset, empty or whitespace-only environment value counts as
        absent — the same unset semantics every member's environment
        resolution takes — and a port that does not name a TCP port is
        refused by name rather than guessed around.
        """
        source = os.environ if env is None else env
        resolved_host = host if host else (source.get(HOST_ENV, "").strip() or DEFAULT_HOST)
        raw_port = port if port is not None else source.get(PORT_ENV, "").strip()
        if str(raw_port).strip() == "":
            resolved_port: int = DEFAULT_PORT
        else:
            try:
                resolved_port = int(str(raw_port))
            except ValueError as exc:
                raise ValueError(
                    f"{PORT_ENV} and --port must name a TCP port; got "
                    f"{raw_port!r}. The repair is a decimal port number "
                    "(1-65535), and unset means the default "
                    f"{DEFAULT_PORT}"
                ) from exc
            if not 0 <= resolved_port <= 65535:
                raise ValueError(
                    f"a TCP port is between 0 and 65535 (0 binds an "
                    f"ephemeral port); got "
                    f"{resolved_port}. The repair is a port in range, "
                    f"and unset means the default {DEFAULT_PORT}"
                )
        return cls(host=resolved_host, port=resolved_port)


# -- The error envelope ----------------------------------------------------------


def error_payload(code: str, message: str) -> dict[str, Any]:
    """The structured error envelope: a code word and the message.

    The one shape every refusal answers — feature 4's *"a JSON body for
    every response"* made decidable: a caller reads ``error.code`` to
    tell one refusal from another and ``error.message`` for the repair,
    and never a traceback or a filesystem path, because the messages
    passed here are composed from names the operator can act on (the
    path asked for, the component not configured, the member's own
    operator-facing refusal text).  The spec's later features extend
    the payload with the error class; the shape they extend is this
    one.
    """
    return {"error": {"code": code, "message": message}}


# -- The request the adapters see ------------------------------------------------


@dataclass(frozen=True)
class ApiRequest:
    """What an adapter is handed: the verb, the path, the query.

    Deliberately this small for the transport core: the GET routes the
    core serves need nothing but the query, and the POST routes the
    spec's later features add extend this value with the body rather
    than reshaping the adapters' door.  ``query`` carries each
    parameter's first value (a repeated parameter is a client's
    restatement of one ask).
    """

    verb: str
    path: str
    query: Mapping[str, str]


# -- The adapters ----------------------------------------------------------------
#
# One callable per (verb, path) the transport core serves.  Each is the
# thinnest call through the composed endpoint — the members own every
# figure and every refusal; an adapter that computed, defaulted or
# retried anything would be a second spelling of a member's law.


def _no_argument_get(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve a GET whose endpoint answers ``get()`` with no arguments.

    The four no-argument reads — the three metrics routes and
    ``/ledger/k-effective`` — where the whole of serving is asking the
    composed endpoint and answering what it said, 200.
    """
    return 200, endpoint.get()


def _forward_decay_get(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``GET /forward/decay?node_id=…``: the signal's curve.

    The identity a GET *for a signal* must state comes from the query
    string, passed to the endpoint exactly as asked — the store owns
    validation, and a malformed identity is refused by the member
    rather than re-validated here (a second validation could disagree
    with the one that owns the rows).  A missing identity is the one
    ask this adapter refuses itself: 400, because the request — not
    the store — failed to state who it is asking about.
    """
    node_id = request.query.get("node_id")
    if node_id is None or not node_id.strip():
        raise _MalformedRequest(
            "missing_node_id",
            "GET /forward/decay must state the signal it is asking about "
            "as ?node_id=<identity>. The repair is the query parameter "
            "the route's sentence names; a request without it never "
            "reaches the store it would read",
        )
    return 200, endpoint.get(node_id)


class _MalformedRequest(Exception):
    """An ask the adapter refuses before any member is reached.

    Carries the code word and the operator-facing message itself — the
    one refusal class the transport owns, for requests that failed to
    state what they are asking.  Members' refusals (a store that cannot
    answer, an absent row) are their own classes, caught by the
    dispatch below and answered with the member's message.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


#: The adapters the transport core wires: ``(verb, path)`` → call.  The
#: POST routes are declared in the table (so their paths answer the
#: wrong-verb refusal and the index the later features serve) but carry
#: no adapter here — their request construction is the spec's per-route
#: features', layered onto this dispatch without reshaping it.
HTTP_ADAPTERS: dict[tuple[str, str], Callable[[Any, ApiRequest], tuple[int, Any]]] = {
    ("GET", "/metrics/fdr-deploy"): _no_argument_get,
    ("GET", "/metrics/instrument-status"): _no_argument_get,
    ("GET", "/metrics/regime-coverage"): _no_argument_get,
    ("GET", "/ledger/k-effective"): _no_argument_get,
    ("GET", "/forward/decay"): _forward_decay_get,
}


# -- Member refusal recognition --------------------------------------------------
#
# A refusal raised by a served member's code is operator-facing by the
# workspace's law — a typed error whose message names the repair — so
# the dispatch answers it (503, the member's message).  Anything else
# is an unexpected fault: the same 503 catch would echo messages nobody
# designed for an operator, so it answers the generic internal error
# instead, and the log carries the class name only.  Recognition is by
# module path segment: a member's classes live under the member's
# package name, whether imported directly (``ledger.errors``) or under
# the factory's scan alias (``_nullius_scanned_ledger.ledger.errors``).
# A miss only downgrades a refusal to the generic 500 — the safe
# direction.

_MEMBER_SEGMENTS = frozenset(
    {"ops", "ledger", "promotion", "forward", "nulloracle", "risk"}
)


def _is_member_refusal(exc: BaseException) -> bool:
    module = type(exc).__module__ or ""
    return any(
        segment in _MEMBER_SEGMENTS or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


# -- The server and its handler --------------------------------------------------


class ApiServer(ThreadingHTTPServer):
    """A threading HTTP server over one composed application.

    Threading — the spec's own choice, and the load-bearing one: an
    operator's metrics read must not queue behind a caller's slow POST,
    and a worker a halt route needs cannot be held by one stalled
    request.  Each request is answered on its own thread; the members'
    stores open their connections per operation, so threads never
    share a database connection through this server.

    Holds the composed :class:`~app.module_loader.Application`, the
    resolved route bindings (:func:`~nullius_api.routes.resolve_routes`
    over the whole table, so an unconfigured component is a discovered
    fact the server can name, not a route that vanished), and the
    execution engine the entrypoint bound — the supervisor's hold the
    halt route drives, or ``None`` when the deployment named none.
    """

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        application: Any,
        execution_engine: Any = None,
    ) -> None:
        super().__init__(address, ApiRequestHandler)
        self.application = application
        self.execution_engine = execution_engine
        self.routes: tuple[ResolvedRoute, ...] = resolve_routes(application)
        # The resolved table grouped by path — the handler's lookup
        # surface, so a wrong-verb refusal states its Allow set from
        # the rows the server actually serves rather than a second
        # spelling of the table.
        grouped: dict[str, tuple[ResolvedRoute, ...]] = {}
        for resolved in self.routes:
            grouped.setdefault(resolved.route.path, ())
            grouped[resolved.route.path] = (*grouped[resolved.route.path], resolved)
        self.routes_by_path = grouped
        configured = sum(1 for resolved in self.routes if resolved.endpoint is not None)
        log.info(
            "composed %d routes over %d components: %d configured, %d "
            "unconfigured",
            len(self.routes),
            _component_count(application),
            configured,
            len(self.routes) - configured,
        )


def _component_count(application: Any) -> int:
    """How many components the composed application holds, for the log."""
    try:
        return len(getattr(application, "components", ()))
    except TypeError:  # pragma: no cover - defensive over a non-sized value
        return 0


def build_server(
    config: ApiConfig | None = None,
    *,
    application: Any = None,
    execution_engine: Any = None,
    env: Mapping[str, str] | None = None,
) -> ApiServer:
    """Build the serving transport: compose, resolve, bind.

    The one construction path the entrypoint and the tests share.  With
    no ``application`` the factory composes it
    (:func:`~app.module_loader.create_app` — the member registers no
    component of its own; it serves the ones the other members
    registered), and with no ``config`` the address resolves from the
    environment (:class:`ApiConfig.resolve` — 127.0.0.1 by default).
    Binding to port 0 lets a caller take the ephemeral port the kernel
    chose off ``server.server_address`` — how the tests boot one server
    per case without a port race.
    """
    if config is None:
        config = ApiConfig.resolve(env=env)
    if application is None:
        from app.module_loader import create_app  # deferred past module scope

        application = create_app()
    return ApiServer(
        (config.host, config.port), application, execution_engine=execution_engine
    )


class ApiRequestHandler(BaseHTTPRequestHandler):
    """Answers every request with a JSON body through one writing door.

    The dispatch is a table lookup, nothing cleverer: find the row for
    the path (404 when none), check the verb (405 with ``Allow`` when
    wrong), serve through the adapter (503 naming the component when
    the composed application resolved nothing for it).  What makes the
    handler the transport's core is that *every* outcome — those
    refusals, the adapters' successes, a member's refusal, the
    server's own unexpected faults, and the protocol-level errors the
    base class used to answer in HTML — funnels into
    :meth:`_write_json`, so *"a JSON body for every response"* is a
    property of the one door, not a habit each route has to keep.
    """

    # The composed transport this handler answers for.
    server: ApiServer

    #: Advertise the member, not the base class's Python version.
    server_version = "nullius-api/0.1.0"
    sys_version = ""

    #: Keep-alive with accurate Content-Length on every body (the one
    #: writing door always sets it), so a caller may hold a connection.
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # the base class's own spelling
        self._dispatch()

    def do_POST(self) -> None:  # the base class's own spelling
        self._dispatch()

    # -- The one writing door ---------------------------------------------------

    def _write_json(
        self,
        status: int,
        payload: Any,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        """Write one response: status, JSON body, and nothing else.

        Every response the server can answer passes through here — the
        single place the content type, the encoding and the length are
        spelled, so no path through the handler can answer a body the
        envelope laws do not cover.  The body is encoded by the
        member's one codec; an encoding refusal (a payload outside the
        JSON vocabulary) answers the generic internal error rather than
        a half-written response.
        """
        try:
            body = dumps(payload).encode("utf-8")
        except Exception:
            log.exception(
                "a response payload could not be spelled as JSON; "
                "answering the internal error instead"
            )
            status = 500
            body = dumps(
                error_payload(
                    "internal_error",
                    "the response could not be encoded; the server log "
                    "names the cause",
                )
            ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        """Answer the base class's protocol errors in JSON, not HTML.

        The inherited door answers an unreadable request line, an
        unsupported method, a too-long URI — with an HTML page.  This
        override keeps the statuses and swaps the body for the same
        envelope every other refusal answers, which is what closes the
        last non-JSON path a response could take.  The connection
        closes after a protocol-level refusal (the request may be
        mid-breakage), exactly as the base class arranges.
        """
        try:
            self.send_response(code, message)
            self.send_header("Connection", "close")
            self.send_header("Content-Type", "application/json")
            payload = error_payload(
                _snake_case(
                    self.responses[code][0] if code in self.responses else "Error"
                ),
                message
                or (self.responses[code][0] if code in self.responses else "refused"),
            )
            body = dumps(payload).encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except Exception:  # noqa: BLE001, S110 - a broken socket cannot be told
            pass
        self.close_connection = True

    # -- The dispatch -----------------------------------------------------------

    def _dispatch(self) -> None:
        """Answer one request by the table: look up, check, serve.

        The body below is the dispatch; the ``try`` around it is the
        belt that makes the every-response-is-JSON law unconditional —
        a fault in the dispatch's *own* code (not the adapter's, whose
        faults are handled inside) still answers the generic internal
        error rather than dropping the connection with no response at
        all, because a socket that closes unanswered is the one shape
        a JSON-everywhere transport cannot allow itself.
        """
        try:
            self._dispatch_by_table()
        except Exception as exc:  # noqa: BLE001 - the belt is the point here
            log.error(
                "unexpected fault dispatching %s: %s",
                getattr(self, "requestline", "<unread>") and self.requestline,
                type(exc).__name__,
            )
            try:
                self._write_json(
                    500,
                    error_payload(
                        "internal_error",
                        "the request could not be answered; the server "
                        "log names the cause",
                    ),
                )
            except Exception:  # noqa: BLE001 - a broken socket cannot be told
                self.close_connection = True

    def _dispatch_by_table(self) -> None:
        """The dispatch itself: find the row, check the verb, serve."""
        verb = self.command or ""
        parts = urlsplit(self.path or "/")
        path = parts.path or "/"
        query = {
            name: values[0]
            for name, values in parse_qs(parts.query, keep_blank_values=True).items()
        }

        grouped = self.server.routes_by_path.get(path)
        if not grouped:
            self._write_json(
                404,
                error_payload(
                    "unknown_route",
                    f"no route is served at {path}. The transport serves "
                    "the routes app_spec.xml's api_endpoints_summary "
                    "states; the repair is a spelled route, not a "
                    "shorter or longer variant of one",
                ),
            )
            return

        allowed = sorted({row.route.verb for row in grouped})
        if verb not in allowed:
            self._write_json(
                405,
                error_payload(
                    "method_not_allowed",
                    f"{verb} {path} is not served; the route answers "
                    f"{', '.join(allowed)}. The repair is the route's "
                    "own verb",
                ),
                extra_headers={"Allow": ", ".join(allowed)},
            )
            return

        resolved = next(row for row in grouped if row.route.verb == verb)
        if resolved.endpoint is None:
            self._write_json(
                503,
                error_payload(
                    "component_unconfigured",
                    f"the component {resolved.route.component} that "
                    f"serves {verb} {path} resolved to nothing: no "
                    f"{resolved.route.configuration} names its store in "
                    "this deployment. The repair is the configuration "
                    "that member resolves; an empty store is then "
                    "answered as the honest absence, never as a "
                    "fabricated figure",
                ),
            )
            return

        adapter = HTTP_ADAPTERS.get((verb, path))
        if adapter is None:
            self._write_json(
                501,
                error_payload(
                    "route_not_implemented",
                    f"{verb} {path} is declared in the route table but no "
                    "adapter serves it in this build. The route's "
                    "serving behaviour lands with the spec's per-route "
                    "features; the composed component is configured and "
                    "was resolved for this request",
                ),
            )
            return

        try:
            status, payload = adapter(resolved.endpoint, ApiRequest(verb, path, query))
        except _MalformedRequest as exc:
            self._write_json(400, error_payload(exc.code, exc.message))
            return
        except Exception as exc:  # noqa: BLE001 - the member/500 split is the point
            if _is_member_refusal(exc):
                # A served member's own typed refusal — operator-facing
                # by the workspace's law, answered with the member's
                # message verbatim (it names the code word and the one
                # repair), never retried and never answered around.
                log.debug(
                    "member refusal serving %s %s: %s",
                    verb,
                    path,
                    type(exc).__name__,
                )
                self._write_json(503, error_payload("member_refusal", str(exc)))
                return
            # An unexpected fault: the body stays generic (no traceback,
            # no filesystem path, no echoed detail), and the log carries
            # the class name — the message an exception echoes could
            # quote request-derived text, which no log of this server
            # is promised to hold.
            log.error(
                "unexpected fault serving %s %s: %s", verb, path, type(exc).__name__
            )
            self._write_json(
                500,
                error_payload(
                    "internal_error",
                    "the request could not be answered; the server log "
                    "names the cause",
                ),
            )
            return
        self._write_json(status, payload)

    # -- Logging ------------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # the base class's own spelling
        """Route the base class's request log to the access logger.

        What the base class logs is the request line and the status —
        never a header, never a body — so no bearer token and no
        request payload can reach a log through this door.  The
        structured per-request access record the spec's later features
        add builds on the same logger name.
        """
        logging.getLogger("nullius_api.access").info(format, *args)


def _snake_case(text: str) -> str:
    """Spell an HTTP reason phrase as a greppable code word."""
    return "_".join(
        word.lower() for word in _WORD.findall(text)
    )


#: Word boundaries for the reason-phrase → code-word spelling above.
_WORD = re.compile(r"[A-Za-z0-9]+")


# -- The execution engine binding -------------------------------------------------


class ExecutionEngineResolutionError(Exception):
    """``NULLIUS_EXECUTION_ENGINE`` names an engine that cannot be bound.

    Refused at startup — the entrypoint reports it and exits, the same
    stance a missing token file takes later in the spec — because a
    server that started with a silently-unbound engine would answer the
    halt route as though the deployment had configured one.  The
    message names the path given and the one repair; it never carries
    the import's own traceback.
    """


def resolve_execution_engine(spec: str | None) -> Any:
    """Bind the engine ``module:attribute`` names, or ``None``.

    The halt route's engine is bound at server start, from the one
    environment the integration points state — the supervisor's hold
    on the engine, imported by path so nothing in this member imports
    the deployment's engine module by name.  Unset (or whitespace) is
    the honest unbound state: the route's later refusal, not a startup
    error.  A malformed path or an import that fails is refused by
    name, with the cause spelled as a sentence — never a traceback.
    """
    if spec is None or not spec.strip():
        return None
    text = spec.strip()
    module_name, separator, attribute_path = text.partition(":")
    if not separator or not module_name.strip() or not attribute_path.strip():
        raise ExecutionEngineResolutionError(
            f"{EXECUTION_ENGINE_ENV} must spell a module:attribute path "
            f"(for example my_package.execution:ENGINE); got {spec!r}. "
            "The repair is both halves of the path, colon-separated"
        )
    try:
        module = importlib.import_module(module_name.strip())
    except Exception as exc:
        raise ExecutionEngineResolutionError(
            f"{EXECUTION_ENGINE_ENV} names the module "
            f"{module_name.strip()!r}, which could not be imported "
            f"({type(exc).__name__}). The repair is a module importable "
            "by the server process; the cause is in the server's log"
        ) from exc
    engine: Any = module
    for attribute in attribute_path.strip().split("."):
        try:
            engine = getattr(engine, attribute)
        except AttributeError as exc:
            raise ExecutionEngineResolutionError(
                f"{EXECUTION_ENGINE_ENV} names the attribute "
                f"{attribute_path.strip()!r} on module "
                f"{module_name.strip()!r}, which is absent. The repair "
                "is the dotted path to the engine the deployment holds"
            ) from exc
    return engine
