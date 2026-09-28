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
unconfigured component, a member's refusal, the server's own unexpected
faults, an oversized body and a request that stalls all answer the same
shape — the structured error envelope of :func:`error_payload` — and
the envelope never carries a traceback or a filesystem path: an
unexpected fault answers a generic internal error (the detail goes to
the server's log, class name only), because a body an operator reads is
not a place to leak a stack.  The reader also caps what it will spend
on one request — a body over :data:`MAX_BODY_BYTES` is refused unread
and a read that outlives :data:`READ_TIMEOUT_SECONDS` is abandoned
(feature 19) — and both refusals pass the same door, so no caller,
however large or slow, can hold a worker the halt route needs.

**Every refusal carries its class.**  The envelope :func:`error_payload`
returns is ``{"error": {"code", "class", "message"}}`` — the code word
to tell one refusal from another, the class to route on the refusal's
own name without parsing the message, and the message for the repair.
Each door passes the class it knows: the transport's own refusals pass
a stable class name they own (a constant in this module), and the
member-refusal door passes ``type(exc).__name__`` — the very class the
served member's traceback would name.  A class name is a word the
refusal's owner would state, never a stack, a module path or a
filesystem path, so carrying it keeps the envelope's own law intact
rather than opening a second place a path could leak; the class field
is a plain string, never the live object, so the codec and every caller
read it the same way they read the code and the message.

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

import html
import importlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .json_encoding import dumps
from .routes import ResolvedRoute, resolve_routes

__all__ = [
    "BODY_TOO_LARGE_CLASS",
    "COMPONENT_UNCONFIGURED_CLASS",
    "DEFAULT_ERROR_CLASS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "EXECUTION_ENGINE_ENV",
    "EXECUTION_ENGINE_UNBOUND_CLASS",
    "HOST_ENV",
    "INTERNAL_ERROR_CLASS",
    "MALFORMED_REQUEST_CLASS",
    "MAX_BODY_BYTES",
    "METHOD_NOT_ALLOWED_CLASS",
    "PROMOTION_CONFLICT_CODE",
    "PROMOTION_PARENT_ABSENT_CODE",
    "READ_TIMEOUT_SECONDS",
    "REQUEST_STALLED_CLASS",
    "ROUTE_NOT_IMPLEMENTED_CLASS",
    "TARGET_UNKNOWN_NODE_CLASS",
    "UNKNOWN_ROUTE_CLASS",
    "ApiConfig",
    "ApiRequest",
    "ApiRequestHandler",
    "ApiServer",
    "ExecutionEngineResolutionError",
    "build_server",
    "error_payload",
    "resolve_execution_engine",
]

#: The class a refusal carries when no more specific one is named — the bare
#: base of the envelope, so every refusal answers a class even the transport's
#: own generic faults, and a caller never reads an absent field.
DEFAULT_ERROR_CLASS = "Error"

#: The stable class names the transport's own refusals carry — the greppable
#: class a caller routes on, parallel to the code word. They are names the
#: transport owns, never a traceback or a filesystem path (a class name is
#: neither), so carrying them keeps the envelope law intact.
UNKNOWN_ROUTE_CLASS = "UnknownRouteError"
METHOD_NOT_ALLOWED_CLASS = "MethodNotAllowedError"
COMPONENT_UNCONFIGURED_CLASS = "ComponentUnconfiguredError"
ROUTE_NOT_IMPLEMENTED_CLASS = "RouteNotImplementedError"
MALFORMED_REQUEST_CLASS = "MalformedRequestError"
INTERNAL_ERROR_CLASS = "InternalServerError"
EXECUTION_ENGINE_UNBOUND_CLASS = "ExecutionEngineUnboundError"

#: The class names the reader's cap refusals carry (feature 19) — the
#: same greppable, route-without-message-parsing stance the classes
#: above take, for the two facts about a *request's* size and pace the
#: reader owns: a body too large for the transport to read (413) and a
#: body that did not finish arriving inside the read deadline (408).
BODY_TOO_LARGE_CLASS = "BodyTooLargeError"
REQUEST_STALLED_CLASS = "RequestStalledError"

#: The most request-body bytes the reader will read: 1 MiB, the number
#: feature 19's sentence states.  A ``Content-Length`` over this cap is
#: refused *unread* — the size is a fact the header already states, and
#: reading bytes the reader has already refused would spend the very
#: socket time the cap exists to bound.
MAX_BODY_BYTES = 1024 * 1024

#: How long the reader will wait for one request's body to finish
#: arriving: 10 seconds, the other number feature 19's sentence states.
#: One deadline covers the whole read (see
#: :meth:`ApiRequestHandler._read_capped_body` for why it is not one
#: timeout per receive), because the cap exists so a slow caller cannot
#: hold a worker the halt route needs — a deadline a caller could extend
#: by dripping bytes would not be that cap.
READ_TIMEOUT_SECONDS = 10.0

#: How many body bytes one loop iteration of the capped read asks the
#: buffered reader for — small enough that the deadline between
#: iterations is re-checked as a body arrives, large enough that a fast
#: body is a handful of underlying receives rather than one per byte.
_READ_CHUNK_BYTES = 64 * 1024

#: The status the null oracle's ``POST /target`` answers for a node the
#: sidecar does not hold: §7.2's route reports *unknown node* as a fact
#: about the world, and the feature's own clause is *which returns 404
#: for a node the sidecar does not know*.  Named here rather than left as
#: a bare literal because the adapter below is the one door that reads
#: the member's status off a response, and the pair is the member's own
#: closed vocabulary (:data:`nulloracle.target.STATUS_CODES`).
TARGET_NOT_FOUND = 404

#: The class a ``POST /target`` 404 carries.  The transport's own name
#: for the one *answer* it relays — the member calls this state a fact
#: rather than a failure (:class:`nulloracle.errors.TargetRouteError`'s
#: docstring states the distinction), so the class says what the body is:
#: an unknown node, not a refusal this server made.
TARGET_UNKNOWN_NODE_CLASS = "TargetUnknownNodeError"

#: The body field the null oracle's answer carries its payload under —
#: §7.2's ``target_series``, and ``charges_budget`` beside it.  Spelled
#: here as the wire names the member's own record already answers with
#: (:class:`nulloracle.target.TargetResponse`'s field names), so the
#: adapter recognises a payload by the names the contract uses.
_TARGET_SERIES_FIELD = "target_series"
_TARGET_BUDGET_FIELD = "charges_budget"

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


def error_payload(
    code: str, message: str, *, error_class: str = DEFAULT_ERROR_CLASS
) -> dict[str, Any]:
    """The structured error envelope: a code word, a class and the message.

    The one shape every refusal answers — feature 4's *"a JSON body for
    every response"* made decidable: a caller reads ``error.code`` to
    tell one refusal from another, ``error.class`` to route on the
    refusal's own class without parsing the message, and ``error.message``
    for the repair, and never a traceback or a filesystem path, because
    the messages and classes passed here are composed from names the
    operator can act on (the path asked for, the component not
    configured, the member's own operator-facing refusal text and the
    class the member's own traceback would name).  A class name is a
    word the refusal's owner would state — never a stack, a module path
    or a filesystem path — so carrying it keeps the envelope's own law
    intact rather than opening a second place a path could leak.

    ``error_class`` is keyword-only with a default, so every call site
    and every existing test that named only the code and the message
    keeps working unchanged: the envelope *gains* a field, it is not
    reshaped.  A call site that names no class still answers one — the
    bare base — so a caller never reads an absent field.
    """
    return {"error": {"code": code, "class": error_class, "message": message}}


# -- The discoverability surface ---------------------------------------------------
#
# Two routes sit outside the ten-route table app_spec.xml's summary
# promises and :data:`API_ROUTES` spells: ``GET /`` and ``GET /healthz``
# (additions_spec_journeys.xml feature 12).  They are *meta* routes —
# the transport describing its own surface, and a liveness probe — not
# a composed component's answer, so they are not rows in the table and
# not entries in HTTP_ADAPTERS: a row in the table would break the
# "ten routes, ten adapters" law the route and server suites pin, and
# an adapter would imply a composed endpoint behind it.  They are
# served by the dispatch directly, from the resolved route table the
# server already holds.

#: The path of the HTML index of every served route.
INDEX_PATH = "/"

#: The path of the liveness probe, which answers 200 with no token.
HEALTHZ_PATH = "/healthz"

#: The status the liveness probe answers — a bare 200, the honest
#: "the process is up and answering", never a figure.
HEALTHZ_STATUS = "ok"


def _index_html(routes: Collection[ResolvedRoute]) -> str:
    """The HTML index of every route, its verb and its configured state.

    The transport describing its own surface: one row per resolved
    route, in the table's own deterministic order, each naming the path,
    the verb and whether the composed component is configured — the
    ``endpoint is not None`` fact the dispatch already computes for the
    served routes.  The component is looked up from the route, never
    re-derived, so the index says exactly what a request to the route
    would find.

    Every value is HTML-escaped before it reaches the page, so a path or
    a component name can never inject markup; the page carries no
    external resource, no stylesheet link and no script, so it opens
    from any origin with nothing to fetch, and it answers both light and
    dark themes through ``prefers-color-scheme`` — the same self-
    contained, theme-aware stance the workspace's own docs pages take.
    """
    def _row(route: ResolvedRoute) -> str:
        configured = route.endpoint is not None
        state = "configured" if configured else "unconfigured"
        spec = route.route
        return (
            "      <tr>"
            f"<td><code>{html.escape(spec.verb)}</code></td>"
            f"<td><code>{html.escape(spec.path)}</code></td>"
            f"<td><code>{html.escape(spec.component)}</code></td>"
            f"<td class='{state}'>{html.escape(state)}</td></tr>"
        )

    rows = "\n".join(_row(route) for route in routes)
    configured = sum(1 for route in routes if route.endpoint is not None)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>nullius-api — routes</title>\n"
        "<style>\n"
        "body{font:15px/1.5 system-ui,sans-serif;margin:2rem;max-width:60rem}\n"
        "h1{font-size:1.3rem}\n"
        "table{border-collapse:collapse;width:100%;margin-top:1rem}\n"
        "th,td{border:1px solid #8885;padding:0.4rem 0.6rem;text-align:left;"
        "vertical-align:top}\n"
        "th{background:#f2f2ef}\n"
        "code{font-family:ui-monospace,monospace}\n"
        ".configured{color:#0a6d0a}\n"
        ".unconfigured{color:#9a7a00}\n"
        "summary{cursor:pointer;color:#4a4a46}\n"
        ".count{color:#4a4a46}\n"
        "@media (prefers-color-scheme: dark){body{background:#1b1b19;color:#e7e7e2}"
        "th{background:#2a2a27}code{color:#e7e7e2}.configured{color:#6fce6f}"
        ".unconfigured{color:#d8c26a}summary{color:#b9b9b2}}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>nullius-api</h1>\n"
        f"<p class='count'>{len(routes)} routes declared, "
        f"{configured} configured.</p>\n"
        "<table>\n"
        "  <thead>\n"
        "    <tr><th>Verb</th><th>Path</th><th>Component</th>"
        "<th>Configured</th></tr>\n"
        "  </thead>\n"
        "  <tbody>\n"
        f"{rows}\n"
        "  </tbody>\n"
        "</table>\n"
        "</body>\n"
        "</html>\n"
    )


# -- The request the adapters see ------------------------------------------------


@dataclass(frozen=True)
class ApiRequest:
    """What an adapter is handed: the verb, the path, the query.

    Deliberately this small for the transport core: the GET routes the
    core serves need nothing but the query, and the POST routes the
    spec's later features add extend this value with the body rather
    than reshaping the adapters' door.  ``query`` carries each
    parameter's first value (a repeated parameter is a client's
    restatement of one ask).  ``execution_engine`` is the one exception
    to "nothing but the request states": it is the entrypoint's own
    bind (:data:`EXECUTION_ENGINE_ENV`, read once at server start), not
    anything this particular request carries, so it rides in on every
    ``ApiRequest`` rather than reopening the adapter signature for the
    one route that needs it.  ``body`` is the parsed JSON object a POST
    carried, or ``None`` for every request that carried none — read by
    the dispatch through :meth:`ApiRequestHandler._read_json_body`
    *before* the route is looked up, so the socket is left positioned at
    the next request on this keep-alive connection and a body that
    cannot be read is refused by the reader's own 400 rather than by
    whichever adapter happened to be asked.  The size and time caps on
    that read are the body-limit feature's half and land in the reader.
    """

    verb: str
    path: str
    query: Mapping[str, str]
    execution_engine: Any = None
    body: Any = None


# -- The adapters ----------------------------------------------------------------
#
# One callable per (verb, path) the transport core serves.  Each is the
# thinnest call through the composed endpoint — the members own every
# figure and every refusal; an adapter that computed, defaulted or
# retried anything would be a second spelling of a member's law.


def _no_argument_get(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve a GET whose endpoint answers ``get()`` with no arguments.

    The four no-argument reads — the three metrics routes and
    ``/ledger/k-effective`` (feature 94's per-epoch ``K_effective``,
    the deflation input §10.3's term consumes) — where the whole of
    serving is asking the composed endpoint and answering what it said,
    200.  The route carries no argument because a GET over the
    append-only log has no body and no filter to state; an empty ledger
    answers the derivation's honest empty counts rather than a
    fabricated ``0.0``, which is the members' own law passed through.
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

    Everything else — an absent record, an unobserved one, a store
    that could not be read — is the store's own refusal
    (:class:`~forward.errors.ForwardAbsentError` or its parent
    :class:`~forward.errors.ForwardStoreError`), left to propagate
    untouched; the dispatch's own doors turn the first into 404 and
    the second into 503 (see :func:`_is_forward_absent_refusal`).
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


def _forward_promote_post(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``POST /forward/promote``: open the signal's forward record.

    Feature 332's whole act, relayed rather than re-decided: the body's
    two terms (``node_id``, ``forward_days``) are built into the
    member's own :class:`~forward.record.ForwardRecordRequest` by
    :func:`_forward_record_request` — which is also the one door that
    translates a malformed term into the transport's 400 — and the
    endpoint's answer is passed straight to the wire, 200, whether this
    call opened the row or found the standing one from an earlier
    retry (:attr:`~forward.record.ForwardRecordResponse.created`
    tells the two apart; there is no second status for a retry,
    because the row it answers with is the same row either way).

    Every other refusal the endpoint raises — no promotion instant to
    open at (:class:`~forward.errors.ForwardPromotionError`), a node
    the tree does not hold or a standing record that disagrees with
    this ask (:class:`~forward.errors.ForwardAbsentError`,
    :class:`~forward.errors.ForwardIdentityError`) — propagates
    untouched to the dispatch, which answers the absent-node face 404
    and everything else 503 (see :func:`_is_forward_absent_refusal`
    and :func:`_is_member_refusal`).  Nothing here computes, defaults
    or retries anything the member did not already decide.
    """
    return 200, endpoint.post(_forward_record_request(request))


def _forward_record_request(request: ApiRequest) -> Any:
    """Feature 332's body as the member's own request record.

    Imported deferred, for the reason :func:`_risk_halt_post` names: a
    module-scope cross-member import would make importing this package
    depend on the sibling being importable first, which the workspace's
    scan order never promises.

    Built by the *member's* constructor, so both terms — the identity
    as a UUID and the horizon as a positive count of days — are
    validated by the module that owns the contract.  A term that fails
    validation raises the member's
    :class:`~forward.errors.ForwardRecordError`, translated here to the
    transport's own :class:`_MalformedRequest` (400) for the same
    reason :func:`_target_request` translates ``TargetRouteError``: a
    body that cannot say what it is asking for is the caller's to
    repair, and left to the generic member-refusal door it would
    answer 503 — the wrong escalation for a fixable ask.  Every other
    refusal the constructor cannot raise (there are only the two
    terms), so nothing else is translated here.
    """
    from forward import ForwardRecordRequest  # deferred past module scope

    body = request.body or {}
    try:
        return ForwardRecordRequest(
            node_id=body.get("node_id"),
            forward_days=body.get("forward_days"),
        )
    except Exception as exc:  # re-raised unless it is the ask class
        if not _is_forward_record_refusal(exc):
            raise
        raise _MalformedRequest("malformed_body", str(exc)) from exc


#: The member's request-contract class, by the one name that survives the
#: factory's scan — the same discipline :data:`_TARGET_ROUTE_REFUSAL_NAME`
#: states: the endpoint is imported under a synthetic module alias, so a
#: composed refusal is never an instance of the class a direct import
#: yields, and the name is what is checked.
_FORWARD_RECORD_REFUSAL_NAME = "ForwardRecordError"


def _is_forward_record_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the forward member's malformed-ask refusal.

    Both halves are checked — the class name and the member segment in
    the module path — so an unrelated exception sharing the name is not
    silently re-spelled as a 400; a miss leaves it to the dispatch's
    general handling, the safe direction.
    """
    if type(exc).__name__ != _FORWARD_RECORD_REFUSAL_NAME:
        return False
    module = type(exc).__module__ or ""
    return any(
        segment == "forward" or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


#: The forward member's *absence* refusal — a state of the world rather
#: than a fault: no forward record for the node, or a record nobody has
#: observed yet (:class:`~forward.errors.ForwardAbsentError`'s own
#: docstring names both faces, across ``GET /forward/decay`` and ``POST
#: /forward/promote`` alike).  Checked by name for the reason
#: :data:`_FORWARD_RECORD_REFUSAL_NAME` states: the factory's scan
#: imports the member under a synthetic module alias, so a composed
#: refusal is never an instance of the class a direct import yields.
_FORWARD_ABSENT_REFUSAL_NAME = "ForwardAbsentError"


def _is_forward_absent_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the forward member's *absence* refusal.

    ``ForwardAbsentError`` subclasses ``ForwardStoreError`` precisely so
    every existing ``except ForwardStoreError`` keeps catching it — this
    is the one door that must tell the two apart, so a signal simply not
    yet promoted or not yet observed answers 404 rather than falling
    into the generic member-refusal 503 (:func:`_is_member_refusal`).
    Both halves are checked — the class name and the member segment in
    the module path — for the same reason every duck check in this
    module gives: a miss leaves the exception to the safer, more
    conservative 503.
    """
    if type(exc).__name__ != _FORWARD_ABSENT_REFUSAL_NAME:
        return False
    module = type(exc).__module__ or ""
    return any(
        segment == "forward" or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


class _MalformedRequest(Exception):
    """A request the transport refuses before any member is reached.

    Carries the code word and the operator-facing message itself — the
    one refusal class the transport owns, for requests that failed to
    state what they are asking.  Members' refusals (a store that cannot
    answer, an absent row, §7.2's ask failing its own record's
    validation) are their own classes, caught by the dispatch below and
    answered with the member's message.

    Two doors raise it, and feature 5 names both as 400: the *body
    reader* (:meth:`ApiRequestHandler._read_json_body`), for a request
    whose bytes are not the JSON object the route reads — a malformed
    spelling, a truncation, a ``Content-Length`` that is not a byte
    count — raised at the top of the dispatch so an unread body never
    survives onto a kept-alive connection; and an *adapter*
    (``_forward_decay_get``, ``_target_request``), for a request whose
    bytes are fine and whose ask omits or misstates a term the route
    cannot do without.  Both are the caller's to repair, which is what
    makes them one class and one status rather than two.

    The reader's caps (feature 19) raise their own classes —
    :class:`_BodyTooLarge` and :class:`_RequestStalled` — because 413 and
    408 are facts about a request's *size* and *pace* rather than its
    shape: a caller told *your body was too large* or *your send stalled*
    has a different repair from one told *your body was not JSON*, which
    is what keeps them three doors rather than one.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _BodyCapRefusal(Exception):
    """A request the reader refuses on its caps — too large, or too slow.

    Carries the code word and the operator-facing message exactly as
    :class:`_MalformedRequest` does, but is deliberately not that class,
    for the reason that class's docstring states: a cap's refusal is a
    fact about the request's size or pace, not about its shape, and it
    answers 413 or 408 rather than 400 — so a caller never reads
    *malformed* about a body that was merely big, or merely slow.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _BodyTooLarge(_BodyCapRefusal):
    """A declared body over :data:`MAX_BODY_BYTES` — answered 413, unread.

    The refusal is made on the ``Content-Length`` declaration alone: the
    size is a fact the header already states, so the reader spends no
    socket time on bytes it has already refused — reading them, only to
    refuse them a moment later, would hold exactly the worker the cap
    exists to free.
    """


class _RequestStalled(_BodyCapRefusal):
    """A body that did not finish arriving within the read deadline — 408.

    The read is abandoned mid-body, so the socket is left somewhere no
    next request begins; the dispatch answers the 408 and closes the
    connection rather than leaving the leftovers to be parsed as a
    request line.
    """


class _ExecutionEngineUnbound(Exception):
    """``POST /risk/halt`` reached with no execution engine bound.

    A sibling of :class:`_MalformedRequest` in shape (code word plus an
    operator-facing message, caught by the dispatch below), but a
    different fact: the request itself is well-formed, and the
    deployment is the thing with nothing to state — the entrypoint
    started with no :data:`EXECUTION_ENGINE_ENV` naming an engine to
    drive.  That is a 503, not a 400: no ask of the caller's would fix
    it, only a deployment that binds an engine at server start.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _risk_halt_post(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``POST /risk/halt``: send the kill, then flatten the book.

    The engine the flatten drives is never one this request's body
    could carry — it is the supervisor's own hold, bound once at server
    start from :data:`EXECUTION_ENGINE_ENV` and read here off
    :attr:`ApiRequest.execution_engine` (:attr:`ApiServer.
    execution_engine`, threaded in by the dispatch).  Unbound is
    answered by name, 503, *before* the composed :class:`~risk.halt.
    HaltEndpoint` is ever asked — a halt request with no engine has no
    book to flatten, and the endpoint's own :class:`~risk.errors.
    RiskFlattenError` would say so a moment later in a less direct
    place.  Bound, the endpoint does the whole of the halt — the kill
    sent first, the book flattened second — and this adapter computes
    nothing: the response is the endpoint's own testimony, passed
    straight to the wire.
    """
    if request.execution_engine is None:
        raise _ExecutionEngineUnbound(
            "execution_engine_unbound",
            f"POST /risk/halt has no execution engine bound: the server "
            f"started with no {EXECUTION_ENGINE_ENV} naming one. The "
            "repair is a module:attribute path to the engine the "
            "deployment holds (for example my_package.execution:ENGINE), "
            "bound at server start; a halt with no engine has no book to "
            "flatten",
        )
    from risk import HaltRequest  # deferred: a cross-member import at call time

    return 200, endpoint.post(HaltRequest(execution_engine=request.execution_engine))


def _target_post(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``POST /target``: §7.2's ask, whose status the member decides.

    The route answers in two shapes — an *answer* and a *refusal* — and
    this adapter relays each without deciding anything itself.

    **The 404 is an answer, and it is relayed rather than refused.**  A
    node the sidecar does not hold comes back from the endpoint as a
    :class:`~nulloracle.target.TargetResponse` whose status is
    :data:`TARGET_NOT_FOUND`; the adapter passes that status and the
    record's own detail through, so the unknown-node body carries *who*
    was asked for (:attr:`TargetResponse.node_id`) beside the reason.  It
    is deliberately not routed through the envelope the transport's own
    refusals use: §7.2's route reports an unknown node as a fact about
    the world, and dressing it as a server refusal would tell a caller to
    escalate a deployment that is answering correctly.  The 404 body's
    class names that state (:data:`TARGET_UNKNOWN_NODE_CLASS`), so a
    caller can still tell it from every other 404 the transport answers
    (an unknown path) by class alone.

    **A known node's refusal is the member's, and it is byte-identical
    whichever branch asked.**  When no target series supply is wired the
    endpoint raises :class:`~nulloracle.target.TargetPayloadError` —
    *before* the branch is chosen, so a null node and a real node raise
    the same class with a message naming the missing supply and the node,
    never the branch (§7.2's information barrier, feature 114's
    same-shape promise).  The adapter does nothing to that exception: it
    neither catches, reshapes, retries nor augments it, and the dispatch
    below answers it through the same member-refusal door as any other
    member's typed error.  That is the whole of the byte-identity
    guarantee — both branches take one path, and the path has no branch
    in it.  The *class* the caller reads is the member's own
    (``TargetPayloadError``), which is a word §7.2 already allows across
    the barrier: it names a missing supply, which is a deployment fact,
    and not which node the supply was missing for.

    **The ask is built by the member's own record, never by a second
    spelling of §7.2's terms here.**  The parsed body reaches this
    adapter on :attr:`ApiRequest.body` — the dispatch reads it, out of
    the transport's reader, before the route table is even consulted —
    and :func:`_target_request` hands all six terms to
    :class:`~nulloracle.target.TargetRequest`'s constructor, so the
    identity, depth, horizon, cross-section and date range are validated
    by the module that owns them.  That function also carries the one
    translation this route makes (the member's malformed-ask refusal to
    the transport's own 400) and states why it is narrow; the caps on
    the reader itself — the 1 MiB/10 s body feature — are that reader's
    half and land there without reshaping this adapter.

    **Nothing is fabricated.**  The payload is the endpoint's own
    ``target_series`` and ``charges_budget``, passed straight to the
    wire; an empty store answers its honest absence, and this adapter
    could not invent a figure if it wanted to — it never inspects the
    values at all.  The one field it reads is the status, which is the
    member's testimony about the world.
    """
    response = endpoint.post(_target_request(request))
    status = _target_status(response)
    if status == TARGET_NOT_FOUND:
        return status, _target_unknown_node_payload(response)
    return status, response


def _target_request(request: ApiRequest) -> Any:
    """§7.2's ask as the endpoint's own request record.

    Imported deferred, for the reason :func:`_risk_halt_post` names:
    a module-scope cross-member import would make importing this package
    depend on the sibling being importable first, which the workspace's
    scan order never promises.

    The record is built by the *member's* constructor, so every term
    §7.2 names is validated by the code that owns the contract — the
    identity as a UUID, the depth as a non-negative integer, the horizon
    against the five the spec aligns, the symbols as a non-empty
    cross-section and the date range as a first-to-last pair.  The
    transport does not re-validate any of them: a second spelling of
    §7.2's terms could disagree with the one that owns them.

    **The member's malformed-ask refusal is translated to the transport's
    own 400 at this seam.**  A term that fails validation raises the
    member's :class:`~nulloracle.errors.TargetRouteError`, whose own
    docstring defines it as *a body that cannot say what it is asking
    for* — which is, word for word, what :class:`_MalformedRequest` is
    the transport's door for, and what feature 5 promises a caller as
    ``400``.  So the refusal is re-raised as that class, carrying the
    member's message unchanged (it names the offending term and the one
    repair, which is the half a caller acts on) and the transport's own
    class for the status.  Left to the generic member-refusal door it
    would answer 503 — *the deployment cannot serve you* — for a request
    the *caller* can fix, which is the wrong escalation and the wrong
    status.

    The translation is deliberately narrow: it fires for the null
    oracle's request-contract class on this route alone, and it happens
    **before the sidecar is opened**, so whether the ask was malformed is
    a fact about the body and never about the node the body named.  A
    node that does not exist and a node that does are refused this way
    identically, which is what keeps this door from becoming a second
    channel the branch could leak through.

    Every other refusal the endpoint raises — the payload/supply class in
    particular, which is *not* the caller's to repair — propagates
    untouched to the dispatch's member-refusal door.
    """
    from nulloracle import TargetRequest  # deferred past module scope

    body = request.body or {}
    try:
        return TargetRequest(
            node_id=body.get("node_id"),
            campaign_id=body.get("campaign_id"),
            depth=body.get("depth"),
            horizon=body.get("horizon"),
            symbols=body.get("symbols"),
            date_range=body.get("date_range"),
        )
    except Exception as exc:  # re-raised unless it is the ask class
        if not _is_target_route_refusal(exc):
            raise
        raise _MalformedRequest("malformed_body", str(exc)) from exc


#: The member's request-contract class, by the one name that survives the
#: factory's scan: the endpoint is imported under a synthetic module alias
#: (``_nullius_scanned_nulloracle.errors``, probed rather than assumed), so
#: a composed refusal is never an instance of the class a direct import
#: yields and an ``isinstance`` here would never fire.  The contract is the
#: name, and the name is what is read — the same discipline the query
#: route's duck checks and the codec's dataclass check follow.
_TARGET_ROUTE_REFUSAL_NAME = "TargetRouteError"


def _is_target_route_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the null oracle's malformed-ask refusal.

    Both halves are checked: the class *name* (see
    :data:`_TARGET_ROUTE_REFUSAL_NAME`) and the member segment in the
    module path, so an unrelated exception that happens to share the name
    is not silently re-spelled as a 400.  A miss leaves the exception to
    the dispatch's general handling, which is the safe direction — the
    refusal keeps its own class and its 503, rather than a caller being
    told their body was malformed when it was not.
    """
    if type(exc).__name__ != _TARGET_ROUTE_REFUSAL_NAME:
        return False
    module = type(exc).__module__ or ""
    return any(
        segment == "nulloracle" or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


def _target_status(response: Any) -> int:
    """The status the member's answer carries, as this transport's own int.

    The endpoint's record is duck-read by field name rather than by
    ``isinstance``, for the reason every seam in this workspace gives: the
    factory's scan imports the member under a synthetic module name, so
    the *composed* answer is structurally a ``TargetResponse`` but never
    an instance of any class this module could name (probed, not assumed:
    ``type(exc).__module__`` of a composed endpoint's refusal is
    ``_nullius_scanned_nulloracle.errors``).  The contract is the fields.

    A response that carries no integer status is refused rather than
    guessed at: the transport has no way to answer a caller about a
    record whose own testimony it cannot read, and inventing a 200 would
    be the fabricated answer this member exists not to serve.  The
    refusal is the transport's *internal* fault — the composed endpoint
    is not what the route table promised — so it is a
    :class:`TypeError`, answered by the dispatch as the generic internal
    error with the class name in the log and nothing on the wire.
    """
    status = getattr(response, "status", None)
    if isinstance(status, bool) or not isinstance(status, int):
        raise TypeError(
            f"the composed endpoint serving POST /target answered a "
            f"response whose status is {status!r} "
            f"({type(status).__name__}); the route's answer carries the "
            "status it reports the world with, and a record the transport "
            "cannot read is a composition fault, not a status to invent"
        )
    return status


def _target_unknown_node_payload(response: Any) -> dict[str, Any]:
    """The body for a known route's *unknown node* answer — a 404 carrying
    who was asked for and why the sidecar answered nothing.

    §7.2's route answers 404 with *everything it knows*, which is that the
    sidecar holds no entry for the node named — so the body carries the
    canonical ``node_id`` and the member's own ``detail`` sentence, both
    of them the member's words rather than the transport's.  It is a
    :func:`error_payload` without being one of the transport's own
    refusals: the same envelope every other body uses (so a caller parses
    one shape) and the class naming the state
    (:data:`TARGET_UNKNOWN_NODE_CLASS`), so an unknown node and an unknown
    path are told apart by class rather than by message.

    The payload fields are not among the body's, and a ``detail`` that is
    absent is left out rather than spelled as ``null``: an unknown node
    answers with no series and no directive — the member's record refuses
    to carry either, and this body must not put a ``None`` where the
    contract says the field does not exist.  A series on this answer would
    be the fabricated figure the whole member refuses to serve.
    """
    node_id = getattr(response, "node_id", None)
    detail = getattr(response, "detail", None)
    return error_payload(
        "unknown_node",
        detail
        or (
            f"the sidecar holds no entry for node {node_id}; §7.2's route "
            "answers for the nodes a campaign assigned, and a node no "
            "sidecar holds is unknown — a fact about the world, not a "
            "failure of the oracle"
        ),
        error_class=TARGET_UNKNOWN_NODE_CLASS,
    ) | {"node_id": node_id}


def _pre_register_post(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``POST /promotion/pre-register``: fix the criteria, or answer
    the standing row.

    Feature 291's whole act, relayed rather than re-decided.  The body's
    three terms (``node_id``, ``epoch_id``, the six-term ``criteria``
    document) are built into the member's own
    :class:`~promotion.pre_register.PreRegistrationRequest` by
    :func:`_pre_registration_request` — which is also the one door that
    translates a malformed term into the transport's 400 — and the
    endpoint's answer is passed straight to the wire with the status
    :func:`_pre_registration_status` derives from the member's own
    ``created`` flag.

    **The status is the feature's, and every clause of it is the
    member's own testimony.**  A registration *this* call appended is a
    new registration — ``201 Created``, the status the spec's J9 journey
    names for the first call.  A registration the store answered with a
    standing row is an identical retry — ``200 OK``, because the row
    that comes back is the row that already existed and the response
    says so with ``created`` false; nothing was created, so nothing may
    claim to have been.  The two are one branch reading one field, so
    the retry can never be answered as a creation: the flag *is* the
    store's finding, not a guess the transport made about the body it
    sent.

    **The two refusals this route makes decidable are the members' own
    subclasses, and this adapter translates neither.**  A node
    re-registered with different criteria raises
    :class:`~promotion.errors.PromotionConflictError` — ``409``,
    because the body is well-formed and the conflict is with a row — and
    a registration naming a ``node`` or ``epoch_ledger`` row the
    database does not hold raises
    :class:`~promotion.errors.PromotionParentAbsentError` — ``422``,
    because the ask is syntactically fine and semantically unfulfillable.
    Both propagate untouched to the dispatch, which recognises them by
    class name (see :func:`_is_promotion_conflict_refusal` and
    :func:`_is_promotion_parent_absent_refusal`) and answers with the
    member's own message verbatim.  Every *other* refusal the endpoint
    raises — the ask face's malformed document (already translated to
    400 by the request builder), a ``DATABASE_URL`` this member cannot
    speak or a row that did not land
    (:class:`~promotion.errors.PromotionStoreError`) — falls to the
    generic member-refusal door's 503, which is the right escalation for
    a deployment that cannot serve.

    **Nothing here computes, defaults or retries anything the member did
    not already decide.**  In particular the adapter never re-derives the
    criteria hash: the hash on the wire is the one the response's record
    carries, which is the one the table holds.
    """
    response = endpoint.post(_pre_registration_request(request))
    return _pre_registration_status(response), response


def _debit_post(endpoint: Any, request: ApiRequest) -> tuple[int, Any]:
    """Serve ``POST /ledger/debit``: append the charge, or answer the prior row.

    Feature 95's whole act, relayed rather than re-decided.  The body's
    terms — the two identities, the outcome, the budget directive, the
    charge unit, the epoch and the provenance triple — are built into the
    member's own :class:`~ledger.debit.DebitRequest` by
    :func:`_debit_request`, which is also the one door that translates a
    malformed term into the transport's 400, and the endpoint's answer is
    passed straight to the wire with the status
    :func:`_debit_status` derives from the member's own ``appended`` flag.

    **The status is the feature's, and every clause of it is the
    member's own testimony.**  A charge *this* call appended is an
    appended charge — ``201 Created``.  A POST the store answered by
    finding the node's standing row is an idempotent retry — ``200 OK``,
    and the body carries the *same* sequence number the original POST
    returned, because :attr:`~ledger.debit.DebitResponse.seq` is read off
    the prior row rather than minted here; nothing was appended, so
    nothing may claim to have been.  The two are one branch reading one
    field, so a retry can never be answered as a creation: the flag *is*
    the store's finding, not a guess the transport made about the body it
    sent, and the sequence the caller accounted with cannot move between
    the two calls.

    **The refusals this route makes decidable are the member's own, and
    this adapter translates none of them.**  An ask that cannot say what
    it is charging — an unknown outcome, a malformed provenance term, a
    naive stamp, an absent epoch or directive — is the member's
    :class:`~ledger.errors.TrialRecordError`, already re-raised as the
    transport's 400 by :func:`_debit_request` *before the store is
    touched*, because that repair belongs to the caller.  A configured
    store whose write failed, or a ``DATABASE_URL`` this member cannot
    speak, is :class:`~ledger.errors.TrialStoreError`, which propagates
    untouched to the generic member-refusal door's 503 — the right
    escalation for a deployment that cannot serve.  Nothing here
    computes, defaults, retries or re-derives anything the member did not
    already decide; in particular the sequence on the wire is the
    record's own ``seq``, never a second count kept here.
    """
    response = endpoint.post(_debit_request(request))
    return _debit_status(response), response


def _debit_request(request: ApiRequest) -> Any:
    """Feature 95's body as the member's own request record.

    Imported deferred, for the reason :func:`_risk_halt_post` names: a
    module-scope cross-member import would make importing this package
    depend on the sibling being importable first, which the workspace's
    scan order never promises.

    Built by the *member's* constructor, so every term is validated by
    the module that owns the contract: the identities as UUIDs, the
    outcome against feature 91's closed vocabulary, the directive as a
    genuine bool (feature 90 — supplied by the caller, never derived
    here), the unit as a positive finite real (feature 89), the epoch as
    a name that names one (feature 88) and each provenance term as 64
    hex characters (feature 87).  The document is passed through exactly
    as the body spelled it: the member's own constructor is where that
    law belongs, and a second spelling of the terms here could disagree
    with the one that owns the row.

    The one term the member defaults keeps *the member's* default: an
    absent ``charge_units`` is filled from
    :data:`~ledger.units.DEFAULT_CHARGE_UNITS` — the same ``1.0`` §8's
    column declares — so the transport spells no presumption of its own.
    A body that states the term as ``null`` is refused rather than
    defaulted, because *absent* and *stated as nothing* are different
    facts and a null unit is not a unit the caller stated.

    A term that fails validation raises the member's
    :class:`~ledger.errors.TrialRecordError` — the ask face, a body that
    cannot say what it is charging — translated here to the transport's
    own :class:`_MalformedRequest` (400) for the same reason
    :func:`_target_request` translates ``TargetRouteError``: a body that
    cannot say what it is asking for is the caller's to repair, and left
    to the generic member-refusal door it would answer 503 — the wrong
    escalation for a fixable ask.  The translation is deliberately the
    *exact* class, never a refinement of it, so a refusal the store owns
    can never be re-spelled as a malformed body.

    Everything else the endpoint can raise — the store's own
    :class:`~ledger.errors.TrialStoreError` — propagates untouched.
    """
    from ledger import DebitRequest  # deferred past module scope

    body = request.body or {}
    try:
        return DebitRequest(
            node_id=body.get("node_id"),
            campaign_id=body.get("campaign_id"),
            outcome=body.get("outcome"),
            charges_budget=body.get("charges_budget"),
            charge_units=body.get("charge_units", 1.0),
            epoch_id=body.get("epoch_id"),
            evaluator_hash=body.get("evaluator_hash"),
            snapshot_hash=body.get("snapshot_hash"),
            cost_model_hash=body.get("cost_model_hash"),
            ts=body.get("ts"),
        )
    except Exception as exc:  # re-raised unless it is the ask class
        if not _is_trial_record_refusal(exc):
            raise
        raise _MalformedRequest("malformed_body", str(exc)) from exc


def _debit_status(response: Any) -> int:
    """The status one debit answer carries: 201, or 200 on an idempotent retry.

    Read off the member's own ``appended`` flag — duck-read by field name
    for the reason every seam in this workspace gives: the factory's scan
    imports the member under a synthetic module name, so the *composed*
    answer is structurally a :class:`~ledger.debit.DebitResponse` but
    never an instance of any class this module could name.  The contract
    is the field.

    A response that carries no boolean ``appended`` is refused rather
    than guessed at: the transport has no way to tell an append from a
    retry on a record whose own testimony it cannot read, and inventing a
    201 would claim a charge was written that may not have been — the
    fabricated answer this member exists not to serve.  The refusal is
    the transport's *internal* fault — the composed endpoint is not what
    the route table promised — so it is a :class:`TypeError`, answered by
    the dispatch as the generic internal error with the class name in the
    log and nothing on the wire.
    """
    appended = getattr(response, "appended", None)
    if not isinstance(appended, bool):
        raise TypeError(
            f"the composed endpoint serving POST /ledger/debit answered a "
            f"response whose appended flag is {appended!r} "
            f"({type(appended).__name__}); the route's status is 201 for the "
            "charge this call appended and 200 for the idempotent retry the "
            "store answered with the node's standing row, and a record the "
            "transport cannot read is a composition fault, not a status to "
            "invent"
        )
    return 201 if appended else 200


#: The ledger member's *malformed-ask* refusal — the body cannot say what
#: it is charging (:class:`~ledger.errors.TrialRecordError`'s own
#: docstring: a row contract violated at the write).  Checked by name for
#: the reason :data:`_FORWARD_RECORD_REFUSAL_NAME` states: the factory's
#: scan imports the member under a synthetic module alias, so a composed
#: refusal is never an instance of the class a direct import yields.
_TRIAL_RECORD_REFUSAL_NAME = "TrialRecordError"


def _is_trial_record_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the ledger member's malformed-ask refusal.

    The *exact* class, never a refinement of it: the store's own
    :class:`~ledger.errors.TrialStoreError` and the immutability
    refusal's :class:`~ledger.errors.TrialImmutableError` both subclass
    the same base, so the check is ``==`` on the name rather than
    ``issubclass`` — a store that cannot write must never be reported to
    the caller as a malformed body.

    Both halves are checked — the class name and the member segment in
    the module path — so an unrelated exception sharing the name is not
    silently re-spelled as a 400 either; a miss leaves it to the
    dispatch's general handling, the safe direction.
    """
    if type(exc).__name__ != _TRIAL_RECORD_REFUSAL_NAME:
        return False
    module = type(exc).__module__ or ""
    return any(
        segment == "ledger" or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


def _pre_registration_request(request: ApiRequest) -> Any:
    """Feature 291's body as the member's own request record.

    Imported deferred, for the reason :func:`_risk_halt_post` names: a
    module-scope cross-member import would make importing this package
    depend on the sibling being importable first, which the workspace's
    scan order never promises.

    Built by the *member's* constructor, so both identities — the node
    as a UUID and the epoch as non-empty text — and the criteria
    document are validated by the module that owns the contract.  The
    six-term document is passed through exactly as the body spelled it:
    the member's own :func:`~promotion.pre_register.
    _criteria_from_document` refuses a document missing a term or
    carrying one that is not one of the six, which is where that law
    belongs — a second spelling of the six terms here could disagree
    with the one that owns the hash.

    A term that fails validation raises the member's
    :class:`~promotion.errors.PromotionError` (the ask face), translated
    here to the transport's own :class:`_MalformedRequest` (400) for the
    same reason :func:`_target_request` translates ``TargetRouteError``:
    a body that cannot say what it is asking for is the caller's to
    repair, and left to the generic member-refusal door it would answer
    503 — the wrong escalation for a fixable ask.
    """
    from promotion import PreRegistrationRequest  # deferred past module scope

    body = request.body or {}
    try:
        return PreRegistrationRequest(
            node_id=body.get("node_id"),
            epoch_id=body.get("epoch_id"),
            criteria=body.get("criteria"),
        )
    except Exception as exc:  # re-raised unless it is the ask class
        if not _is_promotion_ask_refusal(exc):
            raise
        raise _MalformedRequest("malformed_body", str(exc)) from exc


def _pre_registration_status(response: Any) -> int:
    """The status one pre-registration answer carries: 201, or 200 on a retry.

    Read off the member's own ``created`` flag — duck-read by field name
    for the reason every seam in this workspace gives: the factory's scan
    imports the member under a synthetic module name, so the *composed*
    answer is structurally a :class:`~promotion.pre_register.
    PreRegistrationResponse` but never an instance of any class this
    module could name.  The contract is the field.

    A response that carries no boolean ``created`` is refused rather than
    guessed at: the transport has no way to tell a creation from a retry
    on a record whose own testimony it cannot read, and inventing a 201
    would claim a row was written that may not have been.  The refusal is
    the transport's *internal* fault — the composed endpoint is not what
    the route table promised — so it is a :class:`TypeError`, answered by
    the dispatch as the generic internal error with the class name in the
    log and nothing on the wire.
    """
    created = getattr(response, "created", None)
    if not isinstance(created, bool):
        raise TypeError(
            f"the composed endpoint serving POST /promotion/pre-register "
            f"answered a response whose created flag is {created!r} "
            f"({type(created).__name__}); the route's status is 201 for the "
            "registration this call wrote and 200 for the retry the store "
            "answered with a standing row, and a record the transport cannot "
            "read is a composition fault, not a status to invent"
        )
    return 201 if created else 200


#: The code word a 409 carries: the promotion member's own greppable word
#: for *a node was re-registered with different criteria*
#: (``promotion.errors.PROMOTION_CONFLICT_ERROR_CODE``).  Restated here
#: rather than imported, for the reason the workspace states everywhere a
#: member restates another's literal — no member imports another at module
#: scope, and the transport's own door must be able to spell the word
#: before any member is importable.  It is *the member's* word, not a
#: second transport coinage: an operator greps one word and lands on both
#: the refusal and the store that composed it, exactly as
#: ``forward_record_absent`` does for the absence door above.
PROMOTION_CONFLICT_CODE = "promotion_criteria_conflict"

#: The code word a 422 carries: the promotion member's own greppable word
#: for *the node or epoch row this registration names does not exist*
#: (``promotion.errors.PROMOTION_PARENT_ABSENT_ERROR_CODE``), restated for
#: the same reason and read the same way.
PROMOTION_PARENT_ABSENT_CODE = "promotion_parent_absent"

#: The promotion member's request-contract refusal, by the one name that
#: survives the factory's scan — the same discipline
#: :data:`_TARGET_ROUTE_REFUSAL_NAME` states: the endpoint is imported
#: under a synthetic module alias, so a composed refusal is never an
#: instance of the class a direct import yields, and the name is what is
#: checked.  ``PromotionError`` is the ask face itself, and it is
#: deliberately also the name of the base every refinement subclasses —
#: but the *two* refinements this route must route on are checked first
#: (see :func:`_is_promotion_conflict_refusal` and
#: :func:`_is_promotion_parent_absent_refusal`), so a conflict raised
#: from inside the request constructor can never be re-spelled as a 400.
_PROMOTION_ASK_REFUSAL_NAME = "PromotionError"


def _promotion_module_is_readable(exc: BaseException) -> bool:
    """Whether ``exc``'s module path names the promotion member.

    Both halves of every promotion duck check below: the class *name* and
    the member segment in the module path, so an unrelated exception that
    happens to share a name is never silently re-spelled.  ``promotion``
    is the directly-imported spelling; ``_nullius_scanned_promotion`` is
    the one the factory's scan produces (probed rather than assumed).
    """
    module = type(exc).__module__ or ""
    return any(
        segment == "promotion" or segment.startswith("_nullius_scanned_")
        for segment in module.split(".")
    )


def _is_promotion_ask_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the promotion member's malformed-ask refusal.

    The *exact* class, never a refinement of it: the conflict (409) and
    the absent parent (422) are subclasses of the classes this route
    translates to 400, so the check is ``==`` on the name rather than
    ``issubclass`` — a caller posting criteria a node has already fixed
    must never be told their body was malformed.
    """
    return (
        type(exc).__name__ == _PROMOTION_ASK_REFUSAL_NAME
        and _promotion_module_is_readable(exc)
    )


#: The promotion member's *conflict* refusal — a re-registration stating
#: different criteria, and the class that makes it a 409.
_PROMOTION_CONFLICT_REFUSAL_NAME = "PromotionConflictError"


def _is_promotion_conflict_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the promotion member's criteria-conflict refusal.

    Checked by name for the reason every duck check in this module gives:
    the factory's scan imports the member under a synthetic module alias,
    so a composed refusal is never an instance of the class a direct
    import yields.  A miss leaves the refusal to the safer, more
    conservative 503.
    """
    return (
        type(exc).__name__ == _PROMOTION_CONFLICT_REFUSAL_NAME
        and _promotion_module_is_readable(exc)
    )


#: The promotion member's *absent parent* refusal — the node or the
#: epoch row the registration named does not exist, and the class that
#: makes it a 422.
_PROMOTION_PARENT_ABSENT_REFUSAL_NAME = "PromotionParentAbsentError"


def _is_promotion_parent_absent_refusal(exc: BaseException) -> bool:
    """Whether ``exc`` is the promotion member's absent-parent refusal.

    The third of the promotion route's typed doors, and the one that
    answers 422 — the ask is well-formed, the store is reachable, and
    the row it references does not exist.  Checked by name, both halves,
    for the same reason the two above are.
    """
    return (
        type(exc).__name__ == _PROMOTION_PARENT_ABSENT_REFUSAL_NAME
        and _promotion_module_is_readable(exc)
    )


#: The adapters the transport core wires: ``(verb, path)`` → call.  Every
#: row of the table that has landed an adapter is listed here; a row
#: declared but not yet wired (none today) answers the route-not-
#: implemented refusal, because the table is what makes its path answer
#: the wrong-verb refusal and the index, and the serving behaviour is
#: said by the adapter rather than by the row.
HTTP_ADAPTERS: dict[tuple[str, str], Callable[[Any, ApiRequest], tuple[int, Any]]] = {
    ("GET", "/metrics/fdr-deploy"): _no_argument_get,
    ("GET", "/metrics/instrument-status"): _no_argument_get,
    ("GET", "/metrics/regime-coverage"): _no_argument_get,
    ("GET", "/ledger/k-effective"): _no_argument_get,
    ("POST", "/ledger/debit"): _debit_post,
    ("GET", "/forward/decay"): _forward_decay_get,
    ("POST", "/forward/promote"): _forward_promote_post,
    ("POST", "/promotion/pre-register"): _pre_register_post,
    ("POST", "/risk/halt"): _risk_halt_post,
    ("POST", "/target"): _target_post,
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


# -- The envelope's last law: nothing on the wire names the filesystem ------------
#
# "No response body contains a traceback or a filesystem path" is a law
# about the *body*, not about the class that composed it, so it is
# enforced at the door every body leaves through rather than trusted to
# each member's message.  A member's typed refusal is operator-facing on
# purpose — its message names the code word and the one repair, which is
# what makes 503 actionable — and most of those messages are about
# figures, rows and identities, so publishing them verbatim is the
# behaviour the workspace wants.
#
# But not all of them are.  A store that cannot open names Where it
# looked: ``nulloracle``'s :class:`~nulloracle.errors.SidecarStoreError`
# says *"no sidecar exists at /srv/nullius/z0/null/sidecar.enc"*, and
# ``SidecarAccessError`` names the file whose mode bits are too wide.
# Those refusals are correct — an operator reading a log needs the path —
# so the members keep composing them; the transport simply must not
# publish them.  The repair a *caller* acts on is the configuration that
# named the missing store, never the deployment's own directory layout,
# and a body is not a log.
#
# So the substitution is by shape, not by member: any absolute path in a
# message is replaced with the configuration it came from, and the rest
# of the sentence — the code word and the one repair — is published
# unchanged.  A message carrying no path is untouched, which is every
# refusal this route has answered until a store went missing.
#
# The pattern is deliberately conservative: it matches a run of
# path-shaped text starting at a root (``/``, or a Windows drive), and it
# stops at whitespace, a quote, or a clause boundary.  Those boundaries
# are excluded from the match so the *matched text* is the path alone —
# without that, ``"could not answer GET /metrics/fdr-deploy: the store
# refused"`` would match ``/metrics/fdr-deploy:`` and the trailing colon
# would make a served route unrecognisable.  Erring towards a *shorter*
# match is also the safe direction for the redaction itself: a missed
# separator means a fragment of path survives in the body.
#
# **A route path is not a filesystem path, and the difference is not in
# the shape.**  Member refusals very often name the route they were
# answering — ``"could not answer GET /metrics/fdr-deploy: the store
# refused"`` — and that path is the *caller's own ask* coming back, the
# same way the unknown-route refusal names it.  Redacting it would break
# the verbatim-message law for every one of those, and no amount of
# pattern-tuning separates ``/metrics/fdr-deploy`` from ``/srv/null`` by
# looking at the text: both are rooted, unspaced runs.  So the separator
# is the transport's own knowledge — the paths it actually serves, which
# it already holds in its route table — rather than a guess about what a
# filesystem path looks like.

_PATH_IN_MESSAGE = re.compile(r"(?:[A-Za-z]:)?/[^\s'\";:,)\]]+")


def _publish(message: str, *, served_paths: Collection[str] = ()) -> str:
    """``message`` as a response body may carry it: no filesystem path.

    See the note above: the transport redacts paths rather than asking
    every member to stop composing the operator-facing messages that
    legitimately contain them.  ``served_paths`` is the route table's own
    set (see :data:`_PATH_IN_MESSAGE` for why the caller's paths are
    exempt), and a match naming one of them is left exactly as the member
    wrote it.

    A message with no path at all is returned unchanged and unexamined, so
    the common refusal — a figure, a row, an identity, a missing supply, a
    route — reaches the caller word for word.
    """
    def _spell(match: re.Match[str]) -> str:
        found = match.group(0)
        # A match may carry a query string (`/forward/decay?node_id=…`);
        # the route is the part before it.
        route = found.split("?", 1)[0].split("#", 1)[0]
        return found if route in served_paths else "<path>"

    return _PATH_IN_MESSAGE.sub(_spell, message)


# -- The server and its handler --------------------------------------------------


class ApiServer(ThreadingHTTPServer):
    """A threading HTTP server over one composed application.

    Threading — the spec's own choice, and the load-bearing one: an
    operator's metrics read must not queue behind a caller's slow POST,
    and a worker a halt route needs cannot be held by one stalled
    request — a hold the reader's caps bound (feature 19): a body over
    :data:`MAX_BODY_BYTES` is refused unread and a read that outlives
    :data:`READ_TIMEOUT_SECONDS` is answered 408 and closed, so a
    stalled caller's thread ends at the cap rather than when the
    caller's own clock says.  Each request is answered on its own
    thread; the members' stores open their connections per operation, so
    threads never share a database connection through this server.

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

    # -- The request body -------------------------------------------------------

    def _read_json_body(self) -> Any:
        """The parsed JSON object this request carried, or ``None``.

        A POST's body is one JSON object (§7.2's ask is the only body this
        build reads), read whole off the socket and parsed through the
        standard library's decoder.  A request that declares no
        ``Content-Length``, declares ``0``, or carries no body at all
        answers ``None`` — *no body was sent*, which is a different fact
        from *a body arrived that could not be read*, and the two are kept
        apart here for the reason every seam in this workspace keeps them
        apart: a caller told "you sent no body" and a caller told "your
        body was not JSON" have different repairs.

        A body that is not a JSON object — malformed text, a bare array, a
        bare number — is refused as the transport's own malformed request,
        the 400 feature 5 promises for a malformed body.  The reader never
        coerces and never guesses: a body it cannot read is refused by
        name, and the exception carries no part of the body itself, so
        nothing a caller sent can reach the log or the body through this
        door (feature 20's law, held here before the access log exists).

        **The size and time caps are feature 19's, and they are this
        reader's own law.**  A declared ``Content-Length`` over
        :data:`MAX_BODY_BYTES` (1 MiB) is refused *unread* — 413 —
        because the size is a fact the header already states and reading
        the bytes would spend the very window the cap exists to bound;
        and the read itself runs under one
        :data:`READ_TIMEOUT_SECONDS` (10 s) deadline through
        :meth:`_read_capped_body`, so a request that stalls mid-body
        answers 408 rather than holding its worker until the caller's own
        clock says.  Both refusals name the caller's repair — a smaller
        body, an unstalled send — and both close the connection (the
        dispatch's doors for them sit beside this method's own), because
        a body the reader refused or abandoned leaves the socket
        somewhere no next request begins.
        """
        length = self.headers.get("Content-Length")
        if length is None:
            return None
        try:
            size = int(length)
        except (TypeError, ValueError) as exc:
            raise _MalformedRequest(
                "malformed_content_length",
                f"the request's Content-Length {length!r} is not a number of "
                "bytes. The repair is a decimal byte count, or no header at "
                "all for a request that carries no body",
            ) from exc
        if size <= 0:
            return None
        if size > MAX_BODY_BYTES:
            raise _BodyTooLarge(
                "body_too_large",
                f"the request declares a body of {size} bytes, over the "
                f"{MAX_BODY_BYTES // 1024 // 1024} MiB ({MAX_BODY_BYTES}-byte) "
                "cap this transport reads. The repair is a body under the "
                "cap; the declared bytes are never read, the connection is "
                "closed, and the body is not echoed back and is not written "
                "to a log",
            )
        raw = self._read_capped_body(size)
        if not raw.strip():
            return None
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, ValueError) as exc:
            raise _MalformedRequest(
                "malformed_body",
                "the request body is not JSON. The repair is one JSON object "
                "carrying the route's own terms; the body is not echoed back "
                "and is not written to a log",
            ) from exc
        if not isinstance(parsed, dict):
            raise _MalformedRequest(
                "malformed_body",
                f"the request body is a JSON {type(parsed).__name__}, not an "
                "object. The repair is one JSON object carrying the route's "
                "own terms, and the body is not echoed back",
            )
        return parsed

    def _read_capped_body(self, size: int) -> bytes:
        """Read ``size`` body bytes under one :data:`READ_TIMEOUT_SECONDS`
        deadline, or refuse the request as stalled.

        The socket's own timeout is the instrument, set to the deadline's
        *remaining* time before every read, and the reads are
        single-receive reads (``read1``) so the deadline is re-checked
        between them.  Both halves are load-bearing: one ``read(size)``
        under one timeout would let a caller that drips a byte every nine
        seconds hold the worker forever — every individual receive
        succeeds, and the one read never finishes — and the purpose
        clause is exactly that caller (*so one slow caller cannot hold a
        worker the halt route needs*).  The cap the sentence states is
        *a socket read at 10 seconds*: the read as one act, not the byte.

        A timeout is this reader's own 408 refusal
        (:class:`_RequestStalled`); every other fault a socket can raise
        — a reset, a half-close — propagates exactly as the uncapped read
        would have raised it, so the dispatch's belt answers those the
        way it always has.  An end of stream before the declared size
        breaks the loop and returns what did arrive — the same short read
        ``self.rfile.read(size)`` gives — a truncation the JSON decoder
        (or the no-body branch above) refuses as its own 400, never as
        this reader's.

        The socket's prior timeout — ``None`` today; whatever a later
        feature sets — is restored in a ``finally``, so a completed read
        leaves the connection as it found it.  Without the restore, the
        deadline's stale remainder would sit on the socket and silently
        close a kept-alive connection that idled past it.
        """

        def _stalled() -> _RequestStalled:
            return _RequestStalled(
                "request_stalled",
                f"the request body did not finish arriving within "
                f"{READ_TIMEOUT_SECONDS:g} seconds, so the read was "
                "abandoned. The repair is a caller that sends its whole "
                "body without stalling; the bytes that did arrive are not "
                "echoed back and are not written to a log, and the "
                "connection is closed",
            )

        deadline = time.monotonic() + READ_TIMEOUT_SECONDS
        previous_timeout = self.connection.gettimeout()
        chunks: list[bytes] = []
        remaining = size
        try:
            while remaining > 0:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise _stalled()
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(remaining, _READ_CHUNK_BYTES))
                if not chunk:  # end of stream before the declared size
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except TimeoutError as exc:
            # socket.timeout is TimeoutError's own name, so one except
            # clause covers both spellings; anything else a socket can
            # raise is not a stall and keeps propagating.
            raise _stalled() from exc
        finally:
            self.connection.settimeout(previous_timeout)
        return b"".join(chunks)

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
                    error_class=INTERNAL_ERROR_CLASS,
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

    def _write_html(self, status: int, html_body: str) -> None:
        """Write one HTML response: status and body, with a length.

        The one door the meta-routes' HTML leaves through, parallel to
        :meth:`_write_json`. The body is already a complete HTML
        document (:func:`_index_html`), so there is nothing here to
        encode — a string is written as UTF-8 with the exact
        Content-Length, the same length discipline the JSON door keeps.
        """
        body = html_body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _method_not_allowed(self, path: str, allowed: Collection[str]) -> None:
        """Answer a known meta-route path asked with the wrong verb.

        The meta-routes own one verb each (GET); a POST to ``/`` or
        ``/healthz`` is the same wrong-verb refusal a POST to a GET
        route is, answered 405 with the same envelope and an ``Allow``
        header naming the verb the path answers — the same shape the
        table routes answer, so the transport's own surface is
        consistent whether the route is a composed component's or the
        transport's.
        """
        allowed_sorted = sorted(allowed)
        self._write_json(
            405,
            error_payload(
                "method_not_allowed",
                f"{self.command or 'GET'} {path} is not served; the route "
                f"answers {', '.join(allowed_sorted)}. The repair is the "
                "route's own verb",
                error_class=METHOD_NOT_ALLOWED_CLASS,
            ),
            extra_headers={"Allow": ", ".join(allowed_sorted)},
        )

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
            reason = self.responses[code][0] if code in self.responses else "Error"
            payload = error_payload(
                _snake_case(reason),
                message or reason,
                error_class=_snake_case(reason),
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
                        error_class=INTERNAL_ERROR_CLASS,
                    ),
                )
            except Exception:  # noqa: BLE001 - a broken socket cannot be told
                self.close_connection = True

    def _dispatch_by_table(self) -> None:
        """The dispatch itself: read the body, find the row, serve.

        The body is read **first**, before the table is consulted, and
        that ordering is load-bearing rather than tidy.  The handler
        keeps connections alive (``protocol_version`` is HTTP/1.1 and
        every body sets an accurate ``Content-Length``), so a body left
        unread on the socket is not discarded — it is *re-parsed as the
        next request line*, and a caller who posted to an unknown path and
        then reused the connection would have its second request answered
        as garbage or not at all.  Reading here means every path out of
        this method — the 404, the wrong-verb 405, the unconfigured 503,
        the not-implemented 501 — leaves the socket positioned at the next
        request.

        A body the transport cannot read is refused before any of those
        checks: feature 5 makes it a 400, the caller's own repair, and it
        is the same refusal whether or not a route lives at the path the
        body was posted to.  The reader's caps (feature 19) are refused
        here too, ahead of every one of those decisions for the same
        reason — a body over the cap answers 413 and a stalled read
        answers 408, whatever path the request named — and both close the
        connection, because a body the reader refused or abandoned leaves
        the socket somewhere no next request begins.
        """
        try:
            body = self._read_json_body()
        except _BodyTooLarge as exc:
            # Refused on the declaration, so the declared bytes are still
            # on the socket: the connection closes (and the response says
            # so), because a kept-alive connection would parse the refused
            # body as its own next request line.
            self.close_connection = True
            self._write_json(
                413,
                error_payload(exc.code, exc.message, error_class=BODY_TOO_LARGE_CLASS),
                extra_headers={"Connection": "close"},
            )
            return
        except _RequestStalled as exc:
            # A read abandoned mid-body leaves the socket just as
            # unreadable for a next request, and the caller may be gone
            # entirely; answer the 408 and close.
            self.close_connection = True
            self._write_json(
                408,
                error_payload(exc.code, exc.message, error_class=REQUEST_STALLED_CLASS),
                extra_headers={"Connection": "close"},
            )
            return
        except _MalformedRequest as exc:
            self._write_json(
                400,
                error_payload(exc.code, exc.message, error_class=MALFORMED_REQUEST_CLASS),
            )
            return

        verb = self.command or ""
        parts = urlsplit(self.path or "/")
        path = parts.path or "/"
        query = {
            name: values[0]
            for name, values in parse_qs(parts.query, keep_blank_values=True).items()
        }

        # The two meta-routes the transport serves directly, not through
        # the composed component table: the liveness probe answers a
        # bare 200, and the index describes the transport's own surface.
        # Both are served only for the verb they own.  They are answered
        # from the resolved table the server already holds, ahead of the
        # table lookup — the probe's openness (it needs no token, unlike
        # every other route) is exactly the property a later token gate
        # keys off this same ``path == HEALTHZ_PATH`` test.
        if path == HEALTHZ_PATH:
            if verb != "GET":
                self._method_not_allowed(path, ("GET",))
                return
            self._write_json(
                200,
                {"status": HEALTHZ_STATUS},
            )
            return
        if path == INDEX_PATH:
            if verb != "GET":
                self._method_not_allowed(path, ("GET",))
                return
            self._write_html(
                200,
                _index_html(self.server.routes),
            )
            return

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
                    error_class=UNKNOWN_ROUTE_CLASS,
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
                    error_class=METHOD_NOT_ALLOWED_CLASS,
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
                    error_class=COMPONENT_UNCONFIGURED_CLASS,
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
                    error_class=ROUTE_NOT_IMPLEMENTED_CLASS,
                ),
            )
            return

        request = ApiRequest(
            verb,
            path,
            query,
            execution_engine=self.server.execution_engine,
            body=body,
        )
        try:
            status, payload = adapter(resolved.endpoint, request)
        except _MalformedRequest as exc:
            # The one refusal the transport owns: it carries its own code
            # word and the operator-facing message; the class is the
            # transport's own malformed-request class.
            self._write_json(
                400,
                error_payload(exc.code, exc.message, error_class=MALFORMED_REQUEST_CLASS),
            )
            return
        except _ExecutionEngineUnbound as exc:
            # A deployment fact, not a malformed ask — the request is
            # fine, the server simply bound no engine at start.
            self._write_json(
                503,
                error_payload(
                    exc.code, exc.message, error_class=EXECUTION_ENGINE_UNBOUND_CLASS
                ),
            )
            return
        except Exception as exc:  # noqa: BLE001 - the member/500 split is the point
            if _is_promotion_conflict_refusal(exc):
                # A decidable refusal about a *row*, not about the body: the
                # node already holds a pre-registration and this request
                # states different criteria, which §13 item 7 refuses.
                # Answered 409 — the ask is well formed, the store is
                # reachable, and the conflict is with the state of the
                # registry — ahead of the generic member-refusal door below
                # so it is never reported as a deployment that cannot serve.
                log.debug(
                    "promotion-conflict answering %s %s: %s",
                    verb,
                    path,
                    type(exc).__name__,
                )
                self._write_json(
                    409,
                    error_payload(
                        PROMOTION_CONFLICT_CODE,
                        _publish(
                            str(exc),
                            served_paths=self.server.routes_by_path.keys(),
                        ),
                        error_class=type(exc).__name__,
                    ),
                )
                return
            if _is_promotion_parent_absent_refusal(exc):
                # The third promotion door: the node or the epoch the
                # registration named has no row, so the write has no parent
                # to reference.  Answered 422 — the ask is well-formed and
                # semantically unfulfillable against the state of the
                # database — rather than a 404 (the *route* is known) or the
                # generic 503 (nothing about the deployment is broken).
                log.debug(
                    "promotion-parent-absent answering %s %s: %s",
                    verb,
                    path,
                    type(exc).__name__,
                )
                self._write_json(
                    422,
                    error_payload(
                        PROMOTION_PARENT_ABSENT_CODE,
                        _publish(
                            str(exc),
                            served_paths=self.server.routes_by_path.keys(),
                        ),
                        error_class=type(exc).__name__,
                    ),
                )
                return
            if _is_forward_absent_refusal(exc):
                # A decidable state of the world, not a fault: no forward
                # record for this node, or a record nobody has observed
                # yet (forward.errors.ForwardAbsentError's own docstring
                # names both faces).  Answered 404 ahead of the generic
                # member-refusal door below, so this signal is told apart
                # from a store that could not be read at all — the class
                # is still the member's own, carried the same way a
                # member refusal's class is.
                log.debug(
                    "forward-absent answering %s %s: %s",
                    verb,
                    path,
                    type(exc).__name__,
                )
                self._write_json(
                    404,
                    error_payload(
                        "forward_record_absent",
                        _publish(
                            str(exc),
                            served_paths=self.server.routes_by_path.keys(),
                        ),
                        error_class=type(exc).__name__,
                    ),
                )
                return
            if _is_member_refusal(exc):
                # A served member's own typed refusal — operator-facing
                # by the workspace's law, answered with the member's
                # message verbatim (it names the code word and the one
                # repair), never retried and never answered around.  The
                # class is the refusal's own — ``type(exc).__name__``,
                # the very class the member's traceback would name — so
                # carrying it is not the leak the envelope law forbids: a
                # class name is a word the member owns, never a stack, a
                # module path or a filesystem path.
                log.debug(
                    "member refusal serving %s %s: %s",
                    verb,
                    path,
                    type(exc).__name__,
                )
                self._write_json(
                    503,
                    error_payload(
                        "member_refusal",
                        _publish(
                            str(exc),
                            served_paths=self.server.routes_by_path.keys(),
                        ),
                        error_class=type(exc).__name__,
                    ),
                )
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
                    error_class=INTERNAL_ERROR_CLASS,
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
