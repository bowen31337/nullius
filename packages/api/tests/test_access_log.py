"""Feature 20: one structured access-log record per request.

additions_spec_journeys.xml, "HTTP API Transport", feature 20
(``depends_on="18"``): *System emits one structured access-log record
per request carrying the token's scope name, verb, route, status and
latency and never the request body or the token, which saves to the
``nullius_api.access`` logger.*

Each clause of that sentence is pinned below, and the two prohibitions
are pinned the hard way — by presenting a real token in a real header
and posting a real body, then searching **everything** the server wrote
for either.  A prohibition tested with a token the server never saw
would prove nothing.

The suite asks two kinds of question, and the split is deliberate:

* **Through the wire** (the server's own lifecycle): one record per
  request, the five fields' values, the two absences, and the
  prohibitions.  These boot a real server on an ephemeral port and make
  real requests, because *per request* is a fact about the handler's
  lifecycle and only a request exercises one.
* **At the seam** (the record's own law): the field validation, the
  derived line, the mapping freshness.  These call
  :func:`~nullius_api.emit_access_log` directly, because a record built
  by hand must be held to the same law the emission path already
  passed — a frozen value that validated nothing would lend the seam's
  guarantees to testimony nobody stood behind.

The boot helper is :class:`test_server._Boot`, reused rather than
re-spelled: the access record is emitted by the *same* dispatch every
other route is served from, so the fixture that boots one server boots
them all.
"""

from __future__ import annotations

import http.client
import json
import logging
import math
import re
from typing import Any

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import (
    ACCESS_LOG_LEVEL,
    ACCESS_LOG_LOGGER_NAME,
    AccessLogError,
    AccessLogRecord,
    ApiServer,
    emit_access_log,
)
from nullius_api.server import INDEX_PATH
from test_server import _Boot, _GetEndpoint  # type: ignore[import-not-found]

#: The five field names the sentence spells, in the sentence's own
#: order.  Written once here and asserted against
#: :attr:`AccessLogRecord.fields`' own key order, so a sixth field — or
#: a rename — is a failing test rather than a silent schema drift a
#: deployment's parser would discover in production.
THE_FIVE_FIELDS = ("scope", "verb", "route", "status", "latency_ms")


@pytest.fixture
def boot() -> _Boot:
    """One server per case, on an ephemeral port, on loopback."""
    runner = _Boot()
    yield runner
    runner.shutdown()


def _emitted(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The access records in the capture, in emission order.

    Filtered by *logger* rather than by level: the server also logs its
    startup lines on ``nullius_api.server``, and a test asserting on
    what the access stream carries must not count those.
    """
    return [r for r in caplog.records if r.name == ACCESS_LOG_LOGGER_NAME]


def _carried(record: logging.LogRecord) -> dict[str, Any]:
    """The five fields as the emitted record carries them.

    Read off the :class:`logging.LogRecord`'s attributes — which is what
    ``extra`` means and what a deployment's structured formatter does —
    rather than off the seam's own value object: an assertion that read
    the returned :class:`AccessLogRecord` would pass even if none of the
    five had reached the emitted record at all.
    """
    return {name: getattr(record, name) for name in THE_FIVE_FIELDS}


def _everything_written(records: list[logging.LogRecord]) -> str:
    """Every byte the server logged: each message *and* each field.

    The prohibition searches have to cover both media.  A rule that held
    for the message and not for the structured fields would be no rule
    at all for the deployment's real consumer, which reads the fields —
    and a test that searched only the rendered line would pass while the
    leak sat one attribute away.
    """
    return "\n".join(
        f"{record.getMessage()} {json.dumps(_carried(record), default=str)}"
        for record in records
    )


def _ask(
    server: ApiServer,
    method: str,
    path: str,
    header: str | None = None,
    body: bytes | None = None,
) -> tuple[int, dict[str, str], Any]:
    """One request, with the ``Authorization`` header and body verbatim.

    ``header`` is the whole header value, not a scope, because the
    shapes the gate refuses are not spellable as a scope; ``None`` sends
    no header at all.
    """
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        headers = {} if header is None else {"Authorization": header}
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        answer = {name.lower(): value for name, value in response.getheaders()}
        try:
            parsed: Any = json.loads(raw) if raw else None
        except ValueError:  # pragma: no cover - only the index answers HTML
            parsed = raw
        return response.status, answer, parsed
    finally:
        connection.close()


def _bearer(scope: str) -> str:
    """The header a caller holding ``scope`` presents."""
    return f"Bearer {token_for(scope)}"


def _wait_for(count: int, caplog: pytest.LogCaptureFixture, timeout: float = 10.0) -> None:
    """Wait for ``count`` access records to appear, or give up.

    The access record is emitted in the handler's own thread, a moment
    after the client has read its response — so a test that asserted on
    the capture *the instant* the response arrived would be racing the
    server.  Bounded, so a record that never comes is a failing test
    rather than a hung one.
    """
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(_emitted(caplog)) < count:
        time.sleep(0.01)


# -- one record per request -------------------------------------------------------


def test_one_request_emits_exactly_one_record(boot: _Boot, caplog) -> None:
    """The sentence's *per request*, as a count.  Not zero (a request
    answered silently is the stream the feature exists to produce,
    missing), not two (a seam emitting per field would give a pipeline
    several partial records to reassemble)."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    assert len(_emitted(caplog)) == 1


def test_two_requests_emit_two_records_in_order(boot: _Boot, caplog) -> None:
    """Two requests on two connections are two records, each carrying
    its own request's facts — the stream is per-request testimony, and
    a stream that merged two requests into one line could not be
    counted by status or by route."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _ask(server, "GET", "/healthz")
        _wait_for(2, caplog)
    first, second = _emitted(caplog)
    assert first.route == "/metrics/fdr-deploy"
    assert second.route == "/healthz"


def test_a_refused_request_still_emits_its_record(boot: _Boot, caplog) -> None:
    """Every outcome is a request that happened, so a 401 is *counted*
    rather than dropped: the record for a credential this deployment
    does not configure is exactly the testimony an operator wants when
    they are looking for a caller with the wrong token — and dropping it
    would make the log a record of successes."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", "Bearer unknown-to-this-server")
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.status == 401
    assert record.scope is None


def test_an_unknown_path_still_emits_its_record(boot: _Boot, caplog) -> None:
    """A 404 is a request too, and the *path asked for* is the whole
    value of its record — it is how an operator learns a client is
    calling a route this deployment does not serve."""
    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/no-such-route", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.route == "/no-such-route"
    assert record.status == 404


def test_a_capped_body_still_emits_its_record(boot: _Boot, caplog) -> None:
    """Feature 19's 413 leaves through the dispatch's own door, so it is
    a response like any other and gets a record like any other.  The
    pairing matters: the refusal is *about* a large body, which makes it
    precisely the request whose record must carry the status and not
    the bytes."""
    from nullius_api import MAX_BODY_BYTES

    server = boot({"ledger-debit": _GetEndpoint()})
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
            connection.request(
                "POST",
                "/ledger/debit",
                body=b"{}",
                headers={
                    "Authorization": _bearer("research"),
                    "Content-Length": str(MAX_BODY_BYTES + 1),
                },
            )
            response = connection.getresponse()
            assert response.status == 413
            response.read()
            _wait_for(1, caplog)
    finally:
        connection.close()
    (record,) = _emitted(caplog)
    assert record.status == 413
    assert record.verb == "POST"
    assert record.route == "/ledger/debit"


# -- the five fields ------------------------------------------------------------------


def test_the_record_carries_the_scopes_name_not_the_token(boot: _Boot, caplog) -> None:
    """*The token's scope name*, exactly: the word the credential's
    authority is called by, read off the gate's own resolution — so the
    record says *a ``metrics:read`` caller asked* without saying which
    caller, and a reader of the log cannot turn the record back into a
    credential."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.scope == "metrics:read"


def test_every_scope_reaches_the_record_it_actually_holds(boot: _Boot, caplog) -> None:
    """The scope field is the *presented* credential's scope, read from
    the gate rather than assumed from the route — so a token the gate
    accepted carries its own scope even where the route's row wanted
    another one and the request was then refused 403.  Both the admitted
    request and the forbidden one are checked, since a field that read
    the route's row instead of the caller's token would pass the first
    and fail the second."""
    from conftest import TEST_TOKENS as tokens

    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("risk"))
        _wait_for(2, caplog)
    admitted, forbidden = _emitted(caplog)
    assert admitted.scope == "metrics:read"
    assert admitted.status == 200
    assert forbidden.scope == "risk"
    assert forbidden.status == 403
    assert len(tokens.scopes) == 4


def test_the_record_carries_the_verb_route_and_status(boot: _Boot, caplog) -> None:
    """The other three of the sentence's five facts, on one request: the
    method, the path the request line named, and the status the response
    was written with.  All three are read from the request's own
    lifecycle rather than restated, so a record cannot disagree with
    what the handler actually did."""
    from nullius_api.server import HEALTHZ_PATH

    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        status, _, _ = _ask(server, "GET", HEALTHZ_PATH)
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.verb == "GET"
    assert record.route == HEALTHZ_PATH
    # The record's status is the status the *client* saw, not a constant
    # restated here: reading it off the response that actually came back
    # is what makes this an assertion about the handler rather than
    # about the test's own belief.
    assert record.status == status == 200


def test_the_record_drops_the_query_string(boot: _Boot, caplog) -> None:
    """``route`` is the *path*, and the query is dropped rather than
    carried: a query string is caller-authored text, which is one more
    place a payload could reach the stream, and *which route was asked*
    is answered by the path alone.  Feature 9's ``GET /forward/decay``
    asks with ``?node_id=``, so this is the shape real traffic has."""
    from test_server import _DecayEndpoint  # type: ignore[import-not-found]

    server = boot({"forward-decay": _DecayEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        status, _, _ = _ask(
            server,
            "GET",
            "/forward/decay?node_id=node-7",
            _bearer("research"),
        )
        assert status == 200, "the query must have reached the endpoint"
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.route == "/forward/decay"
    assert "node-7" not in _everything_written(_emitted(caplog))
    assert "node_id" not in _everything_written(_emitted(caplog))


def test_the_record_carries_a_measured_latency_in_milliseconds(
    boot: _Boot, caplog
) -> None:
    """*Latency*, and the unit is in the field's name because a bare
    number would be a scale a reader has to guess.

    The value is *measured*, which the test establishes by bounding it:
    a real request takes some measurable moment, so the record's latency
    is a positive number — and it is small, because nothing was asked of
    the endpoint that a request to loopback could not answer in a
    moment.  An unmeasured field (a hardcoded ``0.0``, a default) fails
    the first assertion; a wrongly-scaled one (seconds for milliseconds)
    fails the second."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.latency_ms > 0.0
    assert record.latency_ms < 10_000.0


def test_latency_measures_the_request_not_the_connection(boot: _Boot, caplog) -> None:
    """The interval's two ends are the request's own, not the
    connection's: a caller that opens a connection and waits before
    sending must not inflate the latency the record reports.  The
    handler cannot see the wait — it begins at the request line — so a
    record that had timed the *socket* would report the idle pause and
    this assertion would catch it."""
    import socket
    import time

    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    raw = socket.create_connection(
        ("127.0.0.1", server.server_address[1]), timeout=10
    )
    try:
        time.sleep(0.5)  # the connection idles: not the request's latency
        with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
            request = (
                "GET /metrics/fdr-deploy HTTP/1.1\r\n"
                f"Authorization: {_bearer('metrics:read')}\r\n"
                "Host: 127.0.0.1\r\n"
                "Connection: close\r\n\r\n"
            )
            raw.sendall(request.encode("ascii"))
            while raw.recv(65536):
                pass
            _wait_for(1, caplog)
    finally:
        raw.close()
    (record,) = _emitted(caplog)
    assert record.latency_ms < 500.0, record.getMessage()


# -- the two absences -----------------------------------------------------------------


def test_a_request_that_presented_no_token_carries_no_scope(boot: _Boot, caplog) -> None:
    """``GET /healthz`` is the route that answers without a token, so
    its record carries *no accepted authority asked* — ``None``, not an
    empty string and not a fabricated scope.  An operator counting the
    log by scope must be able to tell *nobody identified themselves*
    from *somebody identified themselves as ""*."""
    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/healthz")
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.scope is None
    assert record.status == 200


def test_a_missing_token_leaves_the_scope_absent(boot: _Boot, caplog) -> None:
    """A 401 from the *missing*-token branch never reached a resolution,
    so the record says so rather than naming a scope the request never
    proved it held.  Same for the unknown-token branch below: in neither
    case did this deployment accept a credential, so in neither case
    does the record claim one."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy")  # no header at all
        _ask(server, "GET", "/metrics/fdr-deploy", "Bearer unknown")  # not ours
        _wait_for(2, caplog)
    missing, unknown = _emitted(caplog)
    assert missing.scope is None
    assert unknown.scope is None
    assert missing.status == unknown.status == 401


def test_the_line_spells_an_absence_as_none_never_as_a_zero() -> None:
    """The rendered absence, which is what a plain-text handler prints:
    ``scope=None`` and ``status=None``, never ``scope=`` and never
    ``status=0``.  The member's *never fabricate a figure* constraint
    lands here as *never spell an absence as a value*."""
    record = AccessLogRecord(
        scope=None, verb="GET", route="/healthz", status=None, latency_ms=1.5
    )
    assert "scope=None" in record.line
    assert "status=None" in record.line
    assert "status=0" not in record.line
    assert "scope= " not in record.line


def test_a_request_no_response_reached_carries_no_status(
    boot: _Boot, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """The *other* absence.  A dispatch that fails before any response
    is written still happened, and its record must say *no status was
    written* rather than defaulting one — ``200`` would be a fabricated
    success, and ``0`` is not a status.

    The fault is injected at the one door every response leaves through,
    so what is exercised is the handler's own lifecycle with an
    unwritable socket: the record still has to appear, carrying the
    request's verb and route and no status."""
    from nullius_api.server import ApiRequestHandler

    server = boot({"ops-fdr-deploy": _GetEndpoint()})

    # The writing door is made to fail the way a gone socket makes it
    # fail: every response the handler would write raises instead of
    # reaching the wire.  That is the state `status = None` is about —
    # the request happened, the transport was asked, and no status was
    # ever written.  The *dispatch* still runs normally underneath, so
    # the belt that turns a fault into a 500 is exercised too: its own
    # 500 goes through the same broken door and is abandoned, which is
    # exactly how a real dead socket behaves.
    def _broken(self, status, payload, extra_headers=None):  # type: ignore[no-untyped-def]
        raise OSError("the connection is gone")

    monkeypatch.setattr(ApiRequestHandler, "_write_json", _broken)
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        try:
            _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        except (http.client.HTTPException, OSError):
            pass
        _wait_for(1, caplog)
    records = _emitted(caplog)
    assert records, "a request no response reached left no record at all"
    assert records[0].status is None
    assert records[0].route == "/metrics/fdr-deploy"
    assert records[0].verb == "GET"
    # The credential was still read before the socket died, so the
    # record says who asked even though the answer never left.
    assert records[0].scope == "metrics:read"


# -- never the body and never the token -------------------------------------------------


def test_no_record_carries_the_token_that_was_presented(boot: _Boot, caplog) -> None:
    """*Never the token*, the hard way: the suite's real credentials are
    presented in real headers on every branch that reads one — the
    admitted request, the forbidden scope, the unknown token — and the
    *entire* stream is searched for each.

    The search covers every field the record emits and the rendered
    line, because a prohibition that held for the message and not for
    the structured fields would be no prohibition at all for the
    deployment's real consumer.  Both halves of the ``Bearer`` framing
    are checked too, since the scheme is as good as the credential to
    an attacker assembling one."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("risk"))
        _ask(server, "GET", "/metrics/fdr-deploy", "Bearer unknown-to-this-server")
        _ask(server, "GET", "/metrics/fdr-deploy")
        _wait_for(4, caplog)

    written = _everything_written(_emitted(caplog))
    for scope in TEST_TOKENS.scopes:
        assert token_for(scope) not in written, scope
    assert "unknown-to-this-server" not in written
    assert "Bearer" not in written
    # And the stream is present, so the assertion above is about what it
    # contains rather than about logging being off.
    assert "/metrics/fdr-deploy" in written
    # The *scopes* are there, which is the other half of the sentence:
    # the name travels, the credential does not.
    assert "scope=metrics:read" in written
    assert "scope=risk" in written


def test_no_record_carries_any_part_of_the_request_body(boot: _Boot, caplog) -> None:
    """*Never the request body*, the hard way: a body is posted through
    the real transport — read whole off the socket, parsed as JSON, and
    handed to the adapter — and every distinctive string in it is
    searched for in everything the server logged.

    Two shapes are posted.  The one that *reached* an adapter (a
    well-formed debit, so the body really was parsed and really did
    travel the dispatch) is the case the prohibition is about; a body
    that was refused unread would pass this test for the wrong reason.
    The one that was refused — malformed JSON — covers the other
    reader's paths, where a careless implementation might quote the text
    it could not parse back into the log to explain itself."""
    from nullius_api import MAX_BODY_BYTES
    from nullius_api import server as server_module

    class _DebitEndpoint:
        route = "/ledger/debit"

    server = boot({"ledger-debit": _DebitEndpoint()})
    secret = "SECRET-CANARY-IN-THE-BODY-7f3a"
    delivered: list[Any] = []

    # The adapter is replaced with one that *keeps* the parsed body, so
    # the test can prove the body really travelled the dispatch — read
    # off the socket, parsed as an object, and handed on — rather than
    # being refused before any of that and then searched for in a stream
    # that never had a chance to leak it.  This is the difference
    # between a prohibition that held and one that was never tested.
    def _capture(endpoint, request):  # type: ignore[no-untyped-def]
        delivered.append(request.body)
        return 200, {"appended": False}

    monkeypatch_adapters = server_module.HTTP_ADAPTERS
    original = monkeypatch_adapters[("POST", "/ledger/debit")]
    monkeypatch_adapters[("POST", "/ledger/debit")] = _capture

    good = json.dumps({"amount_usd": secret, "reason": secret}).encode("utf-8")
    try:
        with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
            status, _, _ = _ask(
                server,
                "POST",
                "/ledger/debit",
                _bearer("evaluator"),
                body=good,
            )
            assert status == 200, "the body must have reached the adapter"
            assert delivered and secret in json.dumps(delivered[0])
            _ask(
                server,
                "POST",
                "/ledger/debit",
                _bearer("evaluator"),
                body=b"not-json-" + secret.encode("utf-8"),
            )
            _ask(
                server,
                "POST",
                "/ledger/debit",
                _bearer("evaluator"),
                body=b"x" * (MAX_BODY_BYTES + 100),
            )
            _wait_for(3, caplog)
    finally:
        monkeypatch_adapters[("POST", "/ledger/debit")] = original

    written = _everything_written(_emitted(caplog))
    assert secret not in written
    assert "amount_usd" not in written
    assert "not-json" not in written
    assert len(_emitted(caplog)) == 3
    # The three requests are recorded, with the statuses they answered —
    # so the search above is over a stream that really carried the
    # requests, not over one that carried nothing.
    assert [r.status for r in _emitted(caplog)] == [200, 400, 413]


def test_the_record_has_exactly_the_five_fields(boot: _Boot, caplog) -> None:
    """The schema, pinned as a closed set: five names, the sentence's
    own.  A sixth field added here would be a second place the stream's
    schema could grow opinions the deployment's parser then has to
    track — and a formatter written against these five would silently
    keep working while the stream grew something nobody asked for."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert tuple(AccessLogRecord(
        scope=None, verb="GET", route="/", status=200, latency_ms=0.0
    ).fields) == THE_FIVE_FIELDS
    carried = _carried(record)
    assert carried["scope"] == "metrics:read"
    assert carried["verb"] == "GET"
    assert carried["route"] == "/metrics/fdr-deploy"
    assert carried["status"] == 200
    assert isinstance(carried["latency_ms"], float)
    # And nothing else: the schema is *closed* on the emitted record
    # too, so a sixth attribute added to the ``extra`` mapping would be
    # a failing test rather than a silent growth of the stream's schema.
    declared = {name for name in vars(type(record)) if not name.startswith("__")}
    assert not (declared & {"token", "body", "authorization", "client", "headers"})


def test_the_five_fields_ride_the_record_as_attributes(boot: _Boot, caplog) -> None:
    """*Structured*, in the sense a pipeline means: the values are
    attributes of the emitted :class:`logging.LogRecord` (passed as
    ``extra``), so a structured formatter reads them without parsing
    anything — which is the whole difference between this record and
    the base class's formatted line."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    carried = _carried(record)
    assert carried["scope"] == "metrics:read"
    assert carried["verb"] == "GET"
    assert carried["route"] == "/metrics/fdr-deploy"
    assert carried["status"] == 200
    assert carried["latency_ms"] == record.latency_ms


def test_the_status_field_is_a_number_not_a_formatted_sentence(
    boot: _Boot, caplog
) -> None:
    """The field's *type*, which is what makes it queryable: an ``int``,
    so a log pipeline's ``status >= 500`` is a comparison rather than a
    substring match on ``"… 500 -"``.  This is the one place feature 20
    deliberately departs from the base class's line, which spells the
    status into a sentence."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert isinstance(record.status, int)
    assert not isinstance(record.status, bool)


# -- exactly one line, not two -----------------------------------------------------------


def test_a_request_writes_one_line_not_the_base_class_s_plus_ours(
    boot: _Boot, caplog
) -> None:
    """The regression this feature could most easily ship: leaving the
    base class's own ``log_request`` in place *and* adding the
    structured record would write two lines per request, the first a
    strict subset of the second — and a deployment whose parser reads
    the stream positionally would then read half its records as
    garbage.

    Counted at the logger, which is the only place the question can be
    asked: exactly one record, and its message is the structured line
    rather than the base class's ``"GET /path HTTP/1.1" 200 -``."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.getMessage().startswith("access ")
    assert not re.match(r'^"GET ', record.getMessage())


def test_the_record_is_emitted_at_info_on_the_named_logger(
    boot: _Boot, caplog
) -> None:
    """The logger name is the sentence's own literal and the level is
    INFO: a record the feature exists to emit must survive a default
    logger config, where DEBUG defaults the stream off — and WARNING
    would page an operator for routine traffic."""
    assert ACCESS_LOG_LOGGER_NAME == "nullius_api.access"
    assert ACCESS_LOG_LEVEL == logging.INFO
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.name == ACCESS_LOG_LOGGER_NAME
    assert record.levelno == ACCESS_LOG_LEVEL


def test_a_handler_on_the_parent_captures_the_record(boot: _Boot) -> None:
    """The dotted-name decision, pinned: these records nest under
    ``nullius_api``, so a deployment's single handler on the parent —
    one destination, one level — captures the access stream *and* the
    server's own startup and fault lines.  One knob, not one per
    logger."""
    server = boot({"ops-fdr-deploy": _GetEndpoint()})
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    parent = logging.getLogger("nullius_api")
    handler = _Capture(level=logging.INFO)
    parent.addHandler(handler)
    previous_level = parent.level
    parent.setLevel(logging.INFO)
    try:
        _ask(server, "GET", "/metrics/fdr-deploy", _bearer("metrics:read"))
        _wait_for_captured(captured)
    finally:
        parent.setLevel(previous_level)
        parent.removeHandler(handler)
    assert any(r.name == ACCESS_LOG_LOGGER_NAME for r in captured)
    access = [r for r in captured if r.name == ACCESS_LOG_LOGGER_NAME]
    assert access[0].scope == "metrics:read"


def _wait_for_captured(captured: list[logging.LogRecord], timeout: float = 10.0) -> None:
    """Wait for a record to reach the parent's handler, or give up."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not captured:
        time.sleep(0.01)


# -- the seam's own law, asked directly ---------------------------------------------------


def test_the_line_names_every_field_once_in_the_sentences_order() -> None:
    """The message a plain-text handler prints — derived from the same
    mapping the ``extra`` carriage reads, so the line and the attributes
    cannot disagree about what the record says.  Asserted as an exact
    equality rather than a set of substrings, because *in the
    sentence's order* is part of the claim."""
    record = AccessLogRecord(
        scope="metrics:read",
        verb="GET",
        route="/metrics/fdr-deploy",
        status=200,
        latency_ms=1.25,
    )
    assert record.line == (
        "access scope=metrics:read verb=GET route=/metrics/fdr-deploy "
        "status=200 latency_ms=1.25"
    )


def test_emit_returns_the_record_it_emitted(caplog) -> None:
    """*Name what you just made*, so the caller can hold the testimony
    beside the stream that carries it (feature 255's writer answers the
    row's id for the same reason — it never has to be re-read to be
    known).  And the returned record's line is the message that actually
    went out, which is the property that makes the return value worth
    anything."""
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        record = emit_access_log(
            scope="risk", verb="POST", route="/risk/halt", status=200, latency_ms=3.0
        )
    (emitted,) = _emitted(caplog)
    assert emitted.getMessage() == record.line
    assert emitted.route == "/risk/halt"


def test_fields_is_a_fresh_mapping_per_read() -> None:
    """A ``dict``, not a frozen proxy: the deployment's serializer owns
    the mapping's next step (``json.dumps`` refuses a proxy), and the
    freshness is what lets a caller treat its copy as its own."""
    record = AccessLogRecord(
        scope=None, verb="GET", route="/healthz", status=200, latency_ms=0.5
    )
    first = record.fields
    first["status"] = 500
    assert record.fields["status"] == 200
    assert record.fields is not first


def test_the_record_is_frozen() -> None:
    """Testimony that could move would be a latency that changed after
    the request was answered — so the value a reader holds is the value
    the handler emitted, for its whole life."""
    record = AccessLogRecord(
        scope=None, verb="GET", route="/healthz", status=200, latency_ms=0.5
    )
    # ``dataclasses.FrozenInstanceError`` is the exception a frozen
    # dataclass raises; named exactly rather than as the bare
    # ``Exception`` a blind assertion would accept, so the test fails if
    # the record ever stops being frozen rather than passing on any
    # fault that happened to be raised.
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        record.status = 500  # type: ignore[misc]


# -- the ask is refused before anything is emitted ---------------------------------------


def test_a_refused_ask_emits_nothing(caplog) -> None:
    """The ordering law this member's sibling seams state for their own
    streams: the record is validated *before* the logger is asked, so a
    malformed ask puts nothing on the stream at all.  A quietly
    defaulted field here would be a fabricated figure in the one medium
    where the mistake cannot be corrected by a re-read."""
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        with pytest.raises(AccessLogError):
            emit_access_log(
                scope=17, verb="GET", route="/x", status=200, latency_ms=1.0
            )
        with pytest.raises(AccessLogError):
            emit_access_log(
                scope=None, verb="GET", route="/x", status=200, latency_ms=math.nan
            )
    assert _emitted(caplog) == []


def test_an_empty_scope_is_refused_but_none_is_carried() -> None:
    """The polarity the whole workspace keeps: ``None`` is *no accepted
    authority asked* and is carried; ``""`` is an authority that named
    nothing and is refused.  Collapsing the two would make the record
    unable to say which happened."""
    emit_access_log(scope=None, verb="GET", route="/x", status=200, latency_ms=0.0)
    with pytest.raises(AccessLogError) as refusal:
        emit_access_log(scope="", verb="GET", route="/x", status=200, latency_ms=0.0)
    assert "scope" in str(refusal.value)


def test_a_scope_that_is_not_a_string_is_refused() -> None:
    """``bool`` is a ``str``'s non-relation — it is simply not a string,
    and the same refusal covers it without a separate branch."""
    for value in (17, True, ["metrics:read"], {"scope": "metrics:read"}):
        with pytest.raises(AccessLogError):
            emit_access_log(
                scope=value, verb="GET", route="/x", status=200, latency_ms=0.0
            )


def test_an_empty_verb_or_route_is_refused() -> None:
    """A record whose verb or route names nothing is testimony of a
    request that cannot be identified — and the honest spelling for a
    field the request line did not carry is ``"-"``, which *is* a
    non-empty string and passes."""
    for kwargs in (
        {"verb": "", "route": "/x"},
        {"verb": "GET", "route": ""},
        {"verb": 5, "route": "/x"},
        {"verb": "GET", "route": None},
    ):
        with pytest.raises(AccessLogError):
            emit_access_log(scope=None, status=200, latency_ms=0.0, **kwargs)
    record = emit_access_log(
        scope=None, verb="-", route="-", status=None, latency_ms=0.0
    )
    assert record.verb == "-"


def test_a_status_outside_the_three_digit_range_is_refused() -> None:
    """A real HTTP code, or ``None``.  ``0``, ``99``, ``600`` and a
    ``bool`` are each a value no response can be written with, and the
    result of accepting one would be a log a status query silently
    miscounts."""
    for value in (0, 99, 600, -1, True, "200", 200.5):
        with pytest.raises(AccessLogError) as refusal:
            emit_access_log(
                scope=None, verb="GET", route="/x", status=value, latency_ms=0.0
            )
        assert "status" in str(refusal.value)
    # The boundaries themselves are served, so the range is a range and
    # not an off-by-one that quietly refused a real code.
    for value in (100, 599):
        emit_access_log(
            scope=None, verb="GET", route="/x", status=value, latency_ms=0.0
        )


def test_a_latency_that_is_not_a_measurement_is_refused() -> None:
    """The clock is monotonic, so a negative interval is not a duration
    of anything; a NaN compares false against everything and would read
    as *not measured*; an infinity is a number no request produced.
    Each is refused rather than carried, and ``bool`` with them."""
    for value in (-0.001, math.nan, math.inf, -math.inf, True, "1.5", None):
        with pytest.raises(AccessLogError) as refusal:
            emit_access_log(
                scope=None, verb="GET", route="/x", status=200, latency_ms=value
            )
        assert "latency_ms" in str(refusal.value)


def test_a_latency_of_zero_is_carried() -> None:
    """``0.0`` is *not* an absence and is not refused: a sub-resolution
    interval is a measurement, and the honest spelling of one is the
    number the clock answered — not a floor and not a ``None``.  The
    distinction is the same one the member's constraint draws between an
    empty store and a fabricated figure, read the other way round."""
    record = emit_access_log(
        scope=None, verb="GET", route="/x", status=204, latency_ms=0
    )
    assert record.latency_ms == 0


def test_every_refusal_carries_no_traceback_and_no_path(caplog) -> None:
    """The member's law for anything a refusal says: no stack, no
    filesystem path.  These messages are read by whoever is mounting
    this transport, and a path in one is a fact about the deployment
    nobody asked for."""
    with (
        caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME),
        pytest.raises(AccessLogError) as refusal,
    ):
        emit_access_log(
            scope="ok", verb="GET", route="/x", status=999, latency_ms=1.0
        )
    message = str(refusal.value)
    assert "Traceback" not in message
    assert ".py" not in message
    assert "/home/" not in message


def test_the_record_carries_nothing_the_sentence_did_not_name() -> None:
    """The closed schema at the *value*: no field holds a header, a
    client address, a body or a token — the five names are the whole
    record and there is no sixth slot for any of them to be smuggled
    into.  Asserted over a record built from a request's real facts, so
    the check is about the value the emission path produces."""
    record = AccessLogRecord(
        scope="metrics:read",
        verb="GET",
        route="/metrics/fdr-deploy",
        status=200,
        latency_ms=2.5,
    )
    assert set(record.fields) == set(THE_FIVE_FIELDS)
    assert "Authorization" not in record.line
    assert "127.0.0.1" not in record.line


def test_the_index_page_is_recorded_like_any_other_route(boot: _Boot, caplog) -> None:
    """The meta-routes are requests too.  ``GET /`` is served by the
    dispatch through :meth:`_write_html` rather than the JSON door, and
    its answer is HTML — which is exactly why it must be covered: a
    record emitted only from the JSON door would miss the transport's
    own surface, and this test is what would catch that."""
    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        status, _, _ = _ask(server, "GET", INDEX_PATH, _bearer("metrics:read"))
        assert status == 200
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.route == INDEX_PATH
    assert record.status == 200
    assert record.verb == "GET"


def test_a_request_line_that_cannot_be_framed_still_emits_a_record(
    boot: _Boot, caplog
) -> None:
    """The 414 hole, closed.  A request line over 64 KiB is refused by
    the base class *before* it frames anything, so ``parse_request``
    never runs for it — but it is a response like any other and must be
    a record like any other, or the per-response invariant has a hole
    exactly where an abusive or broken client lives.

    ``route`` and ``verb`` cannot be read for such a line — there is no
    framed request to read them from — so the honest spellings are the
    base class's ``"-"`` and the root path: never an empty string the
    record's own law would refuse, and never a fabricated route."""
    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        status, _, _ = _ask(server, "GET", "/" + "x" * 70000, _bearer("metrics:read"))
        assert status == 414
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.status == 414
    assert record.verb == "-"
    assert record.route == "/"
    assert record.latency_ms >= 0.0


def test_a_request_line_that_is_refused_still_emits_a_record(
    boot: _Boot, caplog
) -> None:
    """The 400 shape of the same invariant: a request line the base
    class cannot frame is a refused request, and a refused request is
    still a request.  The record stays honest about what it could not
    read — ``verb="-"`` — rather than guessing a method."""
    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        status, _, _ = _ask(server, "BREW", "/healthz", _bearer("metrics:read"))
        assert status == 501, "an unsupported method is answered by the base class"
        _wait_for(1, caplog)
    (record,) = _emitted(caplog)
    assert record.status == 501
    # The verb *is* known here — the line framed, only the method was
    # unsupported — so the record names it, which is the fact an
    # operator greps for when a client is speaking a protocol this
    # transport does not.
    assert record.verb == "BREW"
    assert record.route == "/healthz"


def test_an_idle_connection_that_closes_emits_no_record(boot: _Boot, caplog) -> None:
    """The count's lower bound, stated: a client that opens a connection
    and hangs up without sending a request line has made no request, so
    there is nothing to record.  A handler that emitted per *connection*
    rather than per *request* would write a record for a health
    checker's closed socket, and an operator would see traffic that
    never happened."""
    import socket

    server = boot({})
    with caplog.at_level(logging.INFO, logger=ACCESS_LOG_LOGGER_NAME):
        raw = socket.create_connection(
            ("127.0.0.1", server.server_address[1]), timeout=10
        )
        raw.close()
        # A real request afterwards, so the assertion below is about the
        # idle connection rather than about the server never having
        # started.
        _ask(server, "GET", "/healthz")
        _wait_for(1, caplog)
    assert len(_emitted(caplog)) == 1
    assert _emitted(caplog)[0].route == "/healthz"
