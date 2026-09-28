"""The reader's caps: feature 19's sentence, held to at the wire.

*System caps a request body at 1 MiB and a socket read at 10 seconds,
which returns 413 for an oversized body and 408 for a request that
stalls, so one slow caller cannot hold a worker the halt route needs.*

Both caps belong to the body reader — the one door every request passes
through before any route is consulted — so both refusals are facts
about the *request*, never about any route: a body too large for the
reader answers 413 wherever it was posted, and a body that stalls
answers 408 whatever path it named.  The suite pins each clause of the
sentence: the two numbers themselves; the 413 refused on the
``Content-Length`` declaration alone, unread; the boundary — a body of
exactly 1 MiB is read whole and leaves the connection positioned for a
next request; the 408 for a body that never arrives and for one that
only drips; the connection closing after both; and the purpose clause
— a stalled caller's hold on its worker ends at the cap while the halt
route answers on a connection of its own.

The deadline behaviours are pinned through the constant the reader
reads at call time (:data:`nullius_api.server.READ_TIMEOUT_SECONDS`),
shortened for the stall tests: the sentence's own number is pinned
directly, and no test waits out a real ten seconds.  The endpoints are
fakes — the transport's own behaviour is the whole subject here, the
same discipline ``test_server.py`` states — and the raw-socket requests
are the one way to say precisely what a caller sent and when it
stopped.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
from typing import Any

import pytest
from conftest import TEST_TOKENS, token_for
from nullius_api import ApiServer
from nullius_api.server import (
    BODY_TOO_LARGE_CLASS,
    MAX_BODY_BYTES,
    READ_TIMEOUT_SECONDS,
    REQUEST_STALLED_CLASS,
    ApiRequestHandler,
    _RequestStalled,
)

from app.module_loader import Application

# -- Fakes and helpers ---------------------------------------------------------------


class _DebitEndpoint:
    """An endpoint shaped like the debit route: ``post(request)``,
    recording every ask so a cap's refusal can prove the store was
    never reached."""

    route = "/ledger/debit"

    def __init__(self) -> None:
        self.asked: list[Any] = []

    def post(self, request):
        self.asked.append(request)
        return {"accepted": True}


class _HaltEndpoint:
    """An endpoint shaped like the halt route, recording the engine each
    request carried — the route the purpose clause names, served here
    over a fake so the stall tests need no book to flatten."""

    route = "/risk/halt"

    def __init__(self) -> None:
        self.asked: list[Any] = []

    def post(self, request):
        self.asked.append(request.execution_engine)
        return {"instruction": {"instruction": "kill"}, "result": {}}


class _Boot:
    """Boot one server per case on an ephemeral port, on loopback."""

    def __init__(self) -> None:
        self._servers: list[tuple[ApiServer, threading.Thread]] = []

    def __call__(self, components, execution_engine=None) -> ApiServer:
        application = Application(components=dict(components), order=tuple(components))
        server = ApiServer(
            ("127.0.0.1", 0),
            application,
            TEST_TOKENS,
            execution_engine=execution_engine,
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


def _request_bytes(
    verb: str,
    path: str,
    *,
    content_length: int,
    body: bytes = b"",
    scope: str | None = None,
) -> bytes:
    """One HTTP/1.1 request head, exactly as spelled, plus any body bytes
    the caller wants to have already sent when the request stalls.

    ``scope`` adds the ``Authorization`` header for that scope; the
    default of ``None`` sends *no* header, which is what the cap cases
    want — the reader's refusals precede the token gate (see
    :meth:`~nullius_api.server.ApiRequestHandler._dispatch_by_table`),
    so a body over the cap or a stalled read answers 413 or 408 to a
    caller who never authenticated.  Only the cases that expect to
    *reach* a route present a token.
    """
    authorization = (
        f"Authorization: Bearer {token_for(scope)}\r\n" if scope else ""
    )
    head = (
        f"{verb} {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        f"{authorization}"
        f"Content-Length: {content_length}\r\n"
        "\r\n"
    )
    return head.encode("utf-8") + body


def _connect(server: ApiServer, timeout: float = 10.0) -> socket.socket:
    return socket.create_connection(
        ("127.0.0.1", server.server_address[1]), timeout=timeout
    )


def _read_response(sock: socket.socket) -> tuple[int, dict[str, str], bytes]:
    """One HTTP/1.1 response off the raw socket: status, headers, body."""
    buffer = b""
    while b"\r\n\r\n" not in buffer:
        part = sock.recv(65536)
        if not part:
            raise AssertionError(f"the socket closed before a response: {buffer!r}")
        buffer += part
    head, _, rest = buffer.partition(b"\r\n\r\n")
    lines = head.decode("utf-8").split("\r\n")
    status = int(lines[0].split()[1])
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    body = rest
    while len(body) < int(headers.get("content-length", "0")):
        part = sock.recv(65536)
        if not part:
            break
        body += part
    return status, headers, body


def _server_closed(sock: socket.socket) -> bool:
    """Whether the server hung up after its response.

    A close with unread bytes waiting in the kernel's receive queue
    arrives as a reset rather than an end of stream — a reset close is a
    close, so both spellings count.
    """
    try:
        return sock.recv(1024) == b""
    except OSError:
        return True


def _post(
    server: ApiServer, path: str, scope: str = "risk"
) -> tuple[int, Any]:
    """One ordinary body-less POST, as a well-behaved caller sends it."""
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=10
    )
    try:
        connection.request(
            "POST", path, headers={"Authorization": f"Bearer {token_for(scope)}"}
        )
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        return response.status, (json.loads(raw) if raw else None)
    finally:
        connection.close()


# -- The sentence's own numbers -------------------------------------------------------


def test_the_caps_are_the_sentence_s_own_numbers() -> None:
    """1 MiB and 10 seconds — the two numbers the feature states, pinned
    as the constants the reader reads them from, so the wire below and
    the sentence above cannot drift apart."""
    assert MAX_BODY_BYTES == 1024 * 1024
    assert READ_TIMEOUT_SECONDS == 10.0


# -- 413: a body over the cap ---------------------------------------------------------


def test_a_body_declared_over_the_cap_answers_413(boot) -> None:
    """The header's own declaration is the refusal: a ``Content-Length``
    over 1 MiB answers 413 with the transport's code word and class,
    before any byte of the body is read and before any route — or any
    store — is consulted."""
    endpoint = _DebitEndpoint()
    server = boot({"ledger-debit": endpoint})
    with _connect(server) as sock:
        # Declared over the cap with real bytes behind it: the refusal is
        # made on the declaration alone, so the bytes — sentinel and all —
        # are never read, never echoed, never logged.
        request = _request_bytes(
            "POST",
            "/ledger/debit",
            content_length=MAX_BODY_BYTES + 1,
            body=b'{"sentinel": "Zm9vYmFy"}',
        )
        started = time.monotonic()
        sock.sendall(request)
        status, headers, raw = _read_response(sock)
        elapsed = time.monotonic() - started
        closed = _server_closed(sock)
    assert status == 413
    assert headers["content-type"] == "application/json"
    assert headers["connection"] == "close"
    answer = json.loads(raw)
    assert answer["error"]["code"] == "body_too_large"
    assert answer["error"]["class"] == BODY_TOO_LARGE_CLASS
    assert "1 MiB" in answer["error"]["message"]
    assert b"Zm9vYmFy" not in raw  # never echoed
    # Refused on the declaration alone, unread: the answer comes back
    # immediately rather than at any read deadline.
    assert elapsed < 2.0
    assert endpoint.asked == []
    assert closed


def test_one_byte_over_the_cap_is_still_over(boot) -> None:
    """The boundary is ``>`` and nothing softer: 1 MiB plus one byte is
    refused, so the cap cannot be nudged by a caller counting on
    rounding."""
    server = boot({"ledger-debit": _DebitEndpoint()})
    with _connect(server) as sock:
        sock.sendall(
            _request_bytes("POST", "/ledger/debit", content_length=MAX_BODY_BYTES + 1)
        )
        status, _, raw = _read_response(sock)
    assert status == 413
    assert json.loads(raw)["error"]["code"] == "body_too_large"


@pytest.mark.parametrize(
    ("verb", "path"),
    [
        ("POST", "/ledger/debit"),
        ("GET", "/ledger/debit"),  # the wrong verb for the path
        ("GET", "/healthz"),  # the token-free probe
        ("POST", "/nowhere"),  # no route at all
    ],
)
def test_the_oversized_refusal_precedes_every_route_decision(
    boot, verb: str, path: str
) -> None:
    """The reader runs before the table, before the meta-routes, before
    the verb check — so an oversized body answers 413 wherever it was
    sent, and no route's own contract has to state the cap."""
    server = boot({"ledger-debit": _DebitEndpoint()})
    with _connect(server) as sock:
        sock.sendall(_request_bytes(verb, path, content_length=MAX_BODY_BYTES + 1))
        status, _, raw = _read_response(sock)
    assert status == 413
    assert json.loads(raw)["error"]["code"] == "body_too_large"


def test_a_body_exactly_at_the_cap_is_read_whole(boot) -> None:
    """The cap refuses *over*, not *at*: a body of exactly 1 MiB — one
    JSON object, the most the transport will read — passes the cap door,
    is read to its last byte, and leaves the connection positioned for
    the next request on it."""
    endpoint = _HaltEndpoint()
    engine = object()
    server = boot({"risk-halt": endpoint}, execution_engine=engine)
    # {"pad": "…"} is 11 bytes of framing around the padding, so the
    # body is exactly the cap.
    body = b'{"pad": "' + b"x" * (MAX_BODY_BYTES - 11) + b'"}'
    assert len(body) == MAX_BODY_BYTES
    with _connect(server) as sock:
        request = _request_bytes(
            "POST", "/risk/halt", content_length=len(body), body=body, scope="risk"
        )
        sock.sendall(request)
        status, _, _raw = _read_response(sock)
        assert status == 200
        assert endpoint.asked == [engine]
        # The same connection answers a next request: exactly the
        # declared bytes were consumed — none more, none fewer.
        sock.sendall(_request_bytes("GET", "/healthz", content_length=0))
        status, _, follow_up = _read_response(sock)
    assert status == 200
    assert json.loads(follow_up) == {"status": "ok"}


# -- 408: a request that stalls -------------------------------------------------------


def test_a_body_that_never_arrives_answers_408(
    boot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Headers that promise a body the caller never finishes sending: the
    read is abandoned at the deadline and answered 408 — the transport's
    own code word and class, no byte of what did arrive echoed, and the
    connection closed behind the refusal."""
    monkeypatch.setattr("nullius_api.server.READ_TIMEOUT_SECONDS", 0.5)
    endpoint = _DebitEndpoint()
    server = boot({"ledger-debit": endpoint})
    with _connect(server) as sock:
        request = _request_bytes(
            "POST",
            "/ledger/debit",
            content_length=64,
            body=b'{"sentinel": "Zm9vYmFy"}',
        )
        sock.sendall(request)
        started = time.monotonic()
        status, headers, raw = _read_response(sock)
        elapsed = time.monotonic() - started
        closed = _server_closed(sock)
    assert status == 408
    assert headers["content-type"] == "application/json"
    assert headers["connection"] == "close"
    answer = json.loads(raw)
    assert answer["error"]["code"] == "request_stalled"
    assert answer["error"]["class"] == REQUEST_STALLED_CLASS
    assert b"Zm9vYmFy" not in raw  # what arrived is never echoed
    # Answered at the (shortened) deadline, not at the caller's pleasure
    # — and never by reaching the route the request named.
    assert elapsed >= 0.4
    assert endpoint.asked == []
    assert closed


def test_a_body_that_only_drips_answers_408_at_the_deadline(
    boot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deadline is the read's, not each byte's: a caller that drips
    one byte at a time — no single receive ever slow enough to time out
    alone — still loses the worker when the read's own window closes,
    which is the whole of the sentence's purpose clause.  A cap spelled
    one-time-out-per-receive would let exactly this caller hold the
    worker forever."""
    monkeypatch.setattr("nullius_api.server.READ_TIMEOUT_SECONDS", 1.0)
    server = boot({"ledger-debit": _DebitEndpoint()})
    with _connect(server) as sock:
        sock.sendall(_request_bytes("POST", "/ledger/debit", content_length=64))
        started = time.monotonic()
        for _ in range(8):
            try:
                sock.sendall(b"a")
            except OSError:  # the refusal closes the socket under us
                break
            time.sleep(0.1)
        status, _, raw = _read_response(sock)
        elapsed = time.monotonic() - started
    assert status == 408
    assert json.loads(raw)["error"]["code"] == "request_stalled"
    # The read ended at the deadline, not when the drips ran out: eight
    # tenths of a second of drips inside a one-second window.
    assert elapsed >= 0.9
    assert elapsed < 5.0


def test_a_stalled_caller_does_not_hold_the_worker_the_halt_route_needs(
    boot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The purpose clause, held to at the wire: while one caller stalls
    mid-body, the halt route answers on a connection of its own — and
    the stalled caller's hold on its worker ends at the cap, in a 408,
    rather than when its own clock says."""
    monkeypatch.setattr("nullius_api.server.READ_TIMEOUT_SECONDS", 2.0)
    engine = object()
    endpoint = _HaltEndpoint()
    server = boot({"risk-halt": endpoint}, execution_engine=engine)
    stalled = _connect(server)
    try:
        stalled.sendall(_request_bytes("POST", "/risk/halt", content_length=64))
        # Mid-stall, on another connection: the halt answers now.
        started = time.monotonic()
        status, _ = _post(server, "/risk/halt")
        answered = time.monotonic() - started
        assert status == 200
        assert answered < 1.0  # well inside the stalled read's window
        assert endpoint.asked == [engine]
        # And the stalled read itself ends at the cap.
        stall_status, headers, raw = _read_response(stalled)
    finally:
        stalled.close()
    assert stall_status == 408
    assert headers["connection"] == "close"
    assert json.loads(raw)["error"]["code"] == "request_stalled"


# -- The timed read, unit-pinned at its own seam --------------------------------------


class _FakeConnection:
    """A socket's timeout surface, recording every ``settimeout``."""

    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def gettimeout(self) -> float | None:
        return None  # the blocking socket the handler is handed today

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)


class _FakeRFile:
    """A buffered reader's single-receive surface over a scripted wave
    list: each wave is the bytes one ``read1`` returns, or the exception
    it raises."""

    def __init__(self, waves: list) -> None:
        self._waves = list(waves)
        self.sizes: list[int] = []

    def read1(self, size: int) -> bytes:
        self.sizes.append(size)
        wave = self._waves.pop(0)
        if isinstance(wave, BaseException):
            raise wave
        return wave


def _handler_with(connection: _FakeConnection, rfile: _FakeRFile) -> ApiRequestHandler:
    """A handler carrying only what the timed read touches — the socket
    and its buffered reader — built without a connection of its own."""
    handler = ApiRequestHandler.__new__(ApiRequestHandler)
    handler.connection = connection
    handler.rfile = rfile
    return handler


def test_the_timed_read_returns_short_reads_and_restores_the_socket() -> None:
    """An end of stream before the declared size is a short read — the
    same bytes ``read(size)`` would return, refused downstream as the
    truncation it is — and the socket's blocking state is restored after
    the read, so a completed read leaves the connection as it found it
    rather than carrying the deadline's stale remainder."""
    handler = _handler_with(_FakeConnection(), _FakeRFile([b"ab", b""]))
    assert handler._read_capped_body(4) == b"ab"
    timeouts = handler.connection.timeouts
    # The deadline's remainder before each read, then the restore.
    assert len(timeouts) == 3
    assert 0 < timeouts[1] <= timeouts[0] <= READ_TIMEOUT_SECONDS
    assert timeouts[-1] is None


def test_a_timing_out_read_is_the_stall_refusal_and_still_restores() -> None:
    """A receive that outlives its remaining window is the transport's
    own 408 refusal — and the socket is restored even on the way out, so
    an abandoned read leaves no stale deadline behind either."""
    handler = _handler_with(
        _FakeConnection(), _FakeRFile([TimeoutError("the window closed")])
    )
    with pytest.raises(_RequestStalled) as raised:
        handler._read_capped_body(4)
    assert raised.value.code == "request_stalled"
    assert handler.connection.timeouts[-1] is None


def test_an_exhausted_deadline_refuses_without_reading_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deadline already spent refuses before asking the socket for
    another byte — the check between reads is what a drip-feed caller
    cannot outlive, so it is pinned on its own."""
    monkeypatch.setattr("nullius_api.server.READ_TIMEOUT_SECONDS", 0.0)
    rfile = _FakeRFile([])
    handler = _handler_with(_FakeConnection(), rfile)
    with pytest.raises(_RequestStalled):
        handler._read_capped_body(4)
    assert rfile.sizes == []
