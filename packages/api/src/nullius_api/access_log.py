"""Feature 20's seam: one structured access-log record per request.

additions_spec_journeys.xml, "HTTP API Transport", feature 20
(``depends_on="18"``): *System emits one structured access-log record
per request carrying the token's scope name, verb, route, status and
latency and never the request body or the token, which saves to the
``nullius_api.access`` logger.*

The sentence is an **emission**, not a store: it names no table and no
figure, so what this module owes is one stdlib
:class:`logging.LogRecord` per request and nothing a deployment has to
keep.  The sink is the deployment's — the logger name is the routing
handle it points a handler at — which is the same stance feature 349's
seam takes in the ``ops`` member (*"the log stream ships exactly where
a deployment points a handler"*), and the same reason nothing here
reads ``DATABASE_URL`` or opens a socket: a transport that spent I/O
on its own testimony would be spending it inside the halt route's
window.

**The word this feature is built on is "structured", and the five
fields are its schema.**  The record is one
:class:`logging.LogRecord` whose ``extra`` carries ``scope``,
``verb``, ``route``, ``status`` and ``latency_ms`` as named, typed
values — a deployment pointing a structured formatter (any handler
that reads ``record.<name>``) at the stream gets the five without
parsing anything — and whose message is the stable ``key=value`` line
:attr:`AccessLogRecord.line` derives from that same mapping, so a
plain-text handler still gets them and the line cannot drift from the
attributes.  The line is deliberately **not** a serialization: the
five values ride typed and their spelling is the formatter's decision,
exactly as feature 349's record leaves its own.

**The two prohibitions are the record's shape, not a filter over it.**
*Never the token* is why the credential's field is the **scope name**
— the word the token's authority is called by, resolved by
:meth:`~nullius_api.auth.ApiTokens.scope_for` and never the credential
that resolved it — and why nothing else about the ``Authorization``
header is carried, no scheme, no length, no prefix, nothing a reader
of the log could use to ask again.  *Never the request body* is why no
field holds request content at all: ``route`` is the path the request
line named, which is what the transport's own request log has always
carried (the base class logs the whole request line), and the body —
the only caller-authored payload this transport reads — reaches no
field, because a body is not a log.  Feature 19's reader states the
same law from its own side (*"the body is not echoed back and is not
written to a log"*); this module is the door that law was holding
closed.

**Exactly one record per request, and the count is a property of where
the emission sits.**  :class:`~nullius_api.server.ApiRequestHandler`
emits from the per-request lifecycle it already runs — one call to
``handle_one_request`` is one request on the connection, whatever the
outcome — rather than from each of the dispatch's doors, so no path
through the handler (the adapters' successes, the refusals, the
protocol-level answers, the belt's own 500) can be answered without a
record and none can be answered twice.  The status is captured where
every response is written (:meth:`~nullius_api.server.ApiRequestHandler.
log_request`, which the base class calls from ``send_response``) and
the latency is measured around the request itself, never around the
connection's idle time.

**An absence is carried as an absence.**  A request that presented no
usable credential — ``GET /healthz``, which needs none, or a 401 that
was refused one — carries ``scope = None`` rather than an empty string
or a fabricated scope: *no authority asked* is a different fact from
*the authority named "" asked*, and an operator counting the log by
scope must be able to tell them apart.  A request that produced no
response at all (a socket that broke mid-write) carries
``status = None`` for the same reason — the honest absence the whole
workspace answers where a figure was never measured.

Stdlib only — :mod:`dataclasses` for the record, :mod:`logging` for
the one emission, :mod:`math` for the finite check — so the member's
lockfile gains no edge for its own log, and the import stays cheap on
every factory scan.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "ACCESS_LOG_LEVEL",
    "ACCESS_LOG_LOGGER_NAME",
    "AccessLogError",
    "AccessLogRecord",
    "emit_access_log",
]

#: The logger this seam emits on — a literal, not ``__name__``, and the
#: sentence's own spelling.  Dotted under ``"nullius_api"`` so the
#: deployment's one handler on the parent captures the transport's
#: whole log surface: these records and the server's own startup and
#: fault lines, one knob and one destination.  It is the same name
#: feature 4 routed the base class's request log to, so a deployment
#: that already pointed a handler at ``nullius_api.access`` keeps
#: receiving one line per request — now the structured one.
ACCESS_LOG_LOGGER_NAME = "nullius_api.access"

#: The level the record is emitted at — INFO, the level of routine
#: testimony.  This is the transport's per-request volume, not a
#: dreaming cycle's, but the argument is feature 349's: WARNING would
#: page an operator for requests the sentence says the system *emits*,
#: and DEBUG would default the stream off in every deployment that had
#: not opted in — and a record the feature exists to emit must survive
#: a default logger config.  INFO is the opt-in level: the stream ships
#: exactly where a deployment points a handler at the logger.
ACCESS_LOG_LEVEL = logging.INFO

#: The statuses an HTTP response can carry (RFC 9110's three-digit
#: code), stated once here so a record built by hand is held to the
#: same range the transport's own answers fall in.
_MIN_STATUS = 100
_MAX_STATUS = 599


class AccessLogError(Exception):
    """Feature 20's refusal: an ask that cannot be honest testimony.

    Raised by the record's own construction, in exactly one place per
    field, and its law is the *ordering* one feature 349's sibling seam
    states for its stream: **the ask is refused before anything is
    emitted**, so a record that could not honestly be carried puts
    nothing on the log at all.  A quietly defaulted field here would be
    the fabricated figure the member's whole constraint forbids, in its
    log-shaped form — and the log is the one medium where the mistake
    cannot be corrected by a re-read, because the record an operator
    counted is the record that was wrong.

    The message opens with what the field *is* and names what arrived,
    then the repair — never the request body and never a token, since
    neither can reach a caller of this seam in the first place: the
    scope is the credential's *name*, and the other four fields are
    facts about the transport's own answer.
    """


@dataclass(frozen=True, slots=True)
class AccessLogRecord:
    """The structured record one request emits — the sentence's five
    fields.

    Frozen, because testimony that could move would be a latency that
    changed after the request was answered: the record is what the
    handler emitted at the instant it finished, and a mutable one would
    let a later reader see a fact no request produced.

    Construction holds the record to what a log stream can honestly
    carry, and every refusal is :class:`AccessLogError`:

    * **scope** — the scope name of the credential the request
      presented, or ``None`` for a request that presented none this
      deployment accepted.  *Never the token.*  An empty or non-string
      scope is refused: a scope name is a word, and ``""`` would read
      as an authority that named nothing.
    * **verb** — the request's method, a non-empty string.  ``"-"`` is
      what the handler carries for a request line the parser refused
      before it named a verb — the base class's own spelling for an
      absent field, kept rather than replaced by an empty string.
    * **route** — the path the request line named, a non-empty string.
      The *path*, not the route table's row: a 404's record carries the
      path that was asked for, which is the fact an operator greps for,
      and the verb beside it says which row that path would have wanted.
    * **status** — the response's three-digit code, or ``None`` for a
      request no response reached.  ``bool`` is refused as everywhere in
      this workspace.
    * **latency_ms** — the measured interval from the request line
      arriving to the response being written, in **milliseconds**, a
      finite non-negative real.  The unit is in the name because a bare
      ``0.0042`` would be a number a reader has to guess the scale of;
      a NaN is refused (it compares false against everything and would
      read as "not measured") and a negative is refused (the clock is
      monotonic; a negative interval is not a measurement).

    The five fields are the whole record.  No token, no header, no
    body, no size, no client address, no user agent — every one of
    those is either forbidden by the sentence or a second fact the
    deployment's own reverse proxy already logs, and a field here that
    the sentence did not name would be a second place the stream's
    schema could grow opinions the deployment's parser then has to
    track.
    """

    #: The scope name the presented token carried, or ``None`` when the
    #: request presented none this deployment accepted.  Never the
    #: token.
    scope: str | None

    #: The request's method (``GET``, ``POST``), or ``"-"`` for a
    #: request line the parser refused before it named one.
    verb: str

    #: The path the request line named.
    route: str

    #: The response's status code, or ``None`` for a request no
    #: response reached.
    status: int | None

    #: The measured response latency, in milliseconds.
    latency_ms: float

    def __post_init__(self) -> None:
        # The ask, validated field by field — every refusal fires here,
        # at construction, which is *before* the emitter asks the
        # logger for anything: a refused ask puts no record on the
        # stream at all.
        _require_scope(self.scope)
        _require_text(self.verb, "verb")
        _require_text(self.route, "route")
        _require_status(self.status)
        _require_latency(self.latency_ms)

    @property
    def fields(self) -> dict[str, Any]:
        """The five fields as a mapping — the record's one schema.

        The sentence's five facts spelled as a mapping, in the order it
        spells them, so the emission (``extra``), the derived
        :attr:`line` and any formatter or test reading the record all
        share **one** spelling of the five names — a second list of
        them anywhere in this module would be a second thing to keep in
        sync with the sentence.  A fresh ``dict`` per call, deliberately
        not a frozen proxy: the deployment's serializer owns this
        mapping's next step, and a proxy is a type ``json.dumps``
        refuses.  Treat it as read-only testimony; the record it came
        from does not move.
        """
        return {
            "scope": self.scope,
            "verb": self.verb,
            "route": self.route,
            "status": self.status,
            "latency_ms": self.latency_ms,
        }

    @property
    def line(self) -> str:
        """The record's message — every field, once, in the sentence's
        order.

        ``"access scope=… verb=… route=… status=… latency_ms=…"``,
        derived from :attr:`fields` so the line and the mapping cannot
        disagree.  The two absences render as the honest spellings —
        ``scope=None`` for a request that presented no accepted
        credential, ``status=None`` for one no response reached — never
        as ``""`` or ``0`` standing in for either.  This is the line a
        plain-text handler prints and the string a raw stream greps; it
        is not the serialization, and the structured consumers read
        :attr:`fields` off the emitted record instead.
        """
        return "access " + " ".join(
            f"{name}={value}" for name, value in self.fields.items()
        )


def emit_access_log(
    *,
    scope: Any,
    verb: Any,
    route: Any,
    status: Any,
    latency_ms: Any,
) -> AccessLogRecord:
    """Emit one structured access-log record for one request.

    Feature 20's sentence as one call: emit exactly one stdlib log
    record on :data:`ACCESS_LOG_LOGGER_NAME` at :data:`ACCESS_LOG_LEVEL`
    carrying the scope name of the credential the request presented,
    the verb, the route, the status and the measured latency — the five
    fields as ``extra`` on the record and as the derived ``key=value``
    line in its message — and carrying nothing else, in particular no
    part of the request body and no part of any token.

    **One call, one record.**  The call is the seam's whole
    transaction: the record is constructed first (which validates every
    field it holds), and only a record that passed reaches the logger —
    one :class:`logging.LogRecord` per call, so a caller invoking this
    once per request emits one structured record per request, and a
    refused ask emits nothing at all.

    The five parameters are keyword-only and there are **exactly five**:
    the seam's signature is the sentence's schema, so a later edit
    cannot quietly add a sixth field to the stream by appending an
    argument here.  Each value is passed through as the caller read it,
    never re-spelled — the record's own construction refuses one it
    could not honestly carry.

    Args:
        scope: The scope name the presented token carried, or ``None``.
        verb: The request's method, or ``"-"`` when the request line
            named none.
        route: The path the request line named.
        status: The response's status code, or ``None`` when no
            response reached the caller.
        latency_ms: The measured latency in milliseconds.

    Returns:
        The :class:`AccessLogRecord` emitted — frozen testimony the
        caller can hold, and the same value the stream now carries.

    Raises:
        AccessLogError: The ask, refused — a scope that is not a
            non-empty string and not ``None``, an empty verb or route, a
            status that is not a three-digit code and not ``None``, a
            latency that is not a finite non-negative real.  Every
            refusal fires before the logger is asked, so a refused ask
            puts nothing on the stream.
    """
    # The ask first, the stream second: the record is constructed (which
    # validates every field it holds) before the logger is asked for
    # anything, so a refused ask leaves no testimony behind — and the
    # stream never carries a record whose fields were defaulted rather
    # than measured.
    record = AccessLogRecord(
        scope=scope,
        verb=verb,
        route=route,
        status=status,
        latency_ms=latency_ms,
    )
    logging.getLogger(ACCESS_LOG_LOGGER_NAME).log(
        ACCESS_LOG_LEVEL, record.line, extra=record.fields
    )
    return record


# -- the record's own law ---------------------------------------------------------


def _require_scope(value: Any) -> None:
    """The scope name, or the honest absence of one.

    ``None`` is allowed and is *not* a stand-in for an unknown scope:
    it is the record of a request that presented no credential this
    deployment accepted — ``GET /healthz``, which needs none, and every
    401 — and the polarity is the workspace's own (the decision that
    was never made stays distinguishable from one that was).  Anything
    else must be a non-empty string; ``bool`` needs no separate refusal
    because it is not a ``str``.
    """
    if value is None:
        return
    if not isinstance(value, str) or not value.strip():
        raise AccessLogError(
            f"an access record's scope is the scope name of the "
            f"credential the request presented (a non-empty string), or "
            f"None for a request that presented none — got {value!r} "
            f"({type(value).__name__}). The field is the credential's "
            "*name*, never the token, so an empty or non-string value "
            "here would read as an authority that named nothing "
            "(feature 20)"
        )


def _require_text(value: Any, what: str) -> None:
    """A non-empty string — a verb or a route.

    ``"-"`` passes, deliberately: it is the base class's own spelling
    for a field a request line did not carry, and a parser-refused line
    is a request with no verb and no route to name rather than one this
    seam may drop.
    """
    if not isinstance(value, str) or not value.strip():
        raise AccessLogError(
            f"an access record's {what} is a non-empty string — got "
            f"{value!r} ({type(value).__name__}). The record names the "
            f"{what} the request line carried, and the transport's own "
            "spelling for one a refused line did not carry is '-' "
            "(feature 20)"
        )


def _require_status(value: Any) -> None:
    """The response's code, or the honest absence of one.

    ``None`` is allowed for a request no response reached at all — a
    socket that broke before the first byte of one — because *no status
    was written* is not one of the statuses, and a record that defaulted
    it to ``200`` or ``0`` would be the fabricated figure the member's
    constraint forbids.  A value that is present must be a real
    three-digit code; ``bool`` is refused, as everywhere in this
    workspace.
    """
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not _MIN_STATUS <= value <= _MAX_STATUS
    ):
        raise AccessLogError(
            f"an access record's status is the response's three-digit "
            f"code ({_MIN_STATUS}-{_MAX_STATUS}), or None when no "
            f"response reached the caller — got {value!r} "
            f"({type(value).__name__}). The repair is the status the "
            "response was written with, read where the response is "
            "written (feature 20)"
        )


def _require_latency(value: Any) -> None:
    """The measured interval — a finite, non-negative real.

    The clock is :func:`time.monotonic`, so a negative interval is not
    a measurement of anything; a NaN is refused for the reason feature
    349 refuses one (it compares false against everything and would
    read as "not measured"), and an infinity is refused as a value no
    request produced.
    """
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise AccessLogError(
            f"an access record's latency_ms is a finite non-negative "
            f"number of milliseconds — got {value!r} "
            f"({type(value).__name__}). The repair is the interval "
            "measured across the request with the monotonic clock; a "
            "NaN, an infinity and a negative interval are each a "
            "duration no request produced (feature 20)"
        )
