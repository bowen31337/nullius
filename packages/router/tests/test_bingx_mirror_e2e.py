"""End-to-end: the mirror command against a BingX stand-in on 127.0.0.1.

Feature 4 of ``additions_spec_bingx_vst_mirror.xml``, driven the way an
operator drives it — ``python -m router.bingx_mirror --book BOOK --place``
— against a stand-in that *verifies every signature* it receives and holds a
flat account.  For the recorded fixtures and the synthetic book:

* a first ``--place`` sends exactly five ``POST /trade/order`` requests;
* a second ``--place`` sends none and prints ``prior`` for all five;
* a run whose client targets ``open-api.bingx.com`` answers
  ``live_host_refused`` with no socket opened;
* the API key and the secret never appear in stdout, stderr or the placement
  store.

**How a loopback stand-in stands in for the venue without changing the
host.**  The constraints are explicit — *the only host the client can reach
is open-api-vst.bingx.com; there is no --live flag, no host setting, and no
environment variable that changes it* — so this suite does not point the
client anywhere else.  It starts an :class:`http.server` stand-in on
``127.0.0.1`` and, in the *child* process, installs a ``sitecustomize`` that
rewrites only the ``urllib`` call: a request whose URL is
``https://open-api-vst.bingx.com/...`` is sent over plain HTTP to the
stand-in's ``127.0.0.1:port``.  The client still assembles and host-guards
its URL as ``open-api-vst.bingx.com`` — the guard runs before the transport,
on the name the client was built with — and the child's own
``sitecustomize`` refuses any socket that is not loopback, so a stray network
attempt fails loudly rather than reaching BingX.

**Every signature is checked, not assumed.**  Each signed request carries
``timestamp``, ``recvWindow``, ``signature`` and the ``X-BX-APIKEY`` header;
the stand-in recomputes the HMAC-SHA256 hex over the sorted, encoded
parameters with the fake secret and refuses — with the venue's own refusal
envelope — any request whose signature or key does not match.  The tests
assert the stand-in recorded no signature failure, so the five placements
are five *verified* placements.

No test reads a real credential or opens a connection to BingX.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from router.bingx_client import (
    BALANCE_PATH,
    CONTRACTS_PATH,
    LEVERAGE_PATH,
    LIVE_HOST,
    MARGIN_TYPE_PATH,
    OPEN_ORDERS_PATH,
    ORDER_NOT_FOUND_CODE,
    ORDER_PATH,
    POSITIONS_PATH,
    PREMIUM_INDEX_PATH,
    SERVER_TIME_PATH,
    VST_HOST,
    BingXClient,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst"

#: Fake credentials, invented here and used nowhere else.  The tests assert
#: that neither value crosses into the command's output or its store.
API_KEY = "e2e-fake-vst-key"
API_SECRET = "e2e-fake-vst-secret"

#: The public, unsigned reads: the venue's quote documents and its clock.
#: Every other endpoint this client touches is signed and is verified.
PUBLIC_PATHS = frozenset({CONTRACTS_PATH, PREMIUM_INDEX_PATH, SERVER_TIME_PATH})

#: The five symbols the synthetic book orders with a flat account.
ORDERED_SYMBOLS = ("1000PEPE-USDT", "BTC-USDT", "DOGE-USDT", "ETH-USDT", "SOL-USDT")

#: A ``sitecustomize`` the child process imports before anything else.  It
#: rewrites the client's own HTTPS URL to the loopback stand-in — leaving
#: the client's host guard untouched, because the guard has already run —
#: and refuses every socket that is not loopback, so nothing in a run can
#: reach the network beyond this machine.
_SITE_CUSTOMIZE = '''
import os
import socket
import urllib.request

_BASE = os.environ["E2E_STAND_IN_URL"]
_VST = "https://open-api-vst.bingx.com"

_real_urlopen = urllib.request.urlopen


def _urlopen(request, *args, **kwargs):
    url = getattr(request, "full_url", request)
    if isinstance(url, str) and url.startswith(_VST):
        request.full_url = _BASE + url[len(_VST):]
        request.headers.pop("Host", None)
    return _real_urlopen(request, *args, **kwargs)


urllib.request.urlopen = _urlopen

_real_connect = socket.socket.connect


def _connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("e2e guard: refused a socket to %r" % (host,))
    return _real_connect(self, address)


socket.socket.connect = _connect
'''


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _signature_ok(params: dict, signature: str | None, key: str | None) -> bool:
    """Recompute the venue's signature over the presented parameters."""
    if key != API_KEY or not signature:
        return False
    if "timestamp" not in params or "recvWindow" not in params:
        return False
    signed = {k: v for k, v in params.items() if k != "signature"}
    query = urlencode(sorted(signed.items()))
    expected = hmac.new(
        API_SECRET.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


class _StandIn:
    """A BingX stand-in: verifies signatures, holds a flat account.

    Records every request it receives — method, path, decoded parameters,
    headers — so the tests can count the ``POST /trade/order`` requests and
    inspect the parameters the venue would have read.  A request whose
    signature does not recompute is refused with the venue's own envelope
    and recorded as a failure, so a run that "succeeded" over a broken
    signature cannot pass silently.
    """

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.signature_failures: list[dict] = []
        self.orders: dict[str, dict] = {}
        self.open_orders: list[dict] = []
        self._lock = threading.Lock()

    # -- introspection used by the tests -----------------------------------
    def order_posts(self) -> list[dict]:
        return [
            r for r in self.requests
            if r["method"] == "POST" and r["path"] == ORDER_PATH
        ]

    # -- the venue ----------------------------------------------------------
    def handle(
        self, method: str, path: str, query: str, body: bytes, headers: dict
    ) -> tuple[int, dict]:
        raw = query if method == "GET" else body.decode("ascii") if body else ""
        params = dict(parse_qsl(raw))
        entry = {"method": method, "path": path, "params": params, "headers": headers}
        with self._lock:
            self.requests.append(entry)

        if path not in PUBLIC_PATHS and not _signature_ok(
            params, params.get("signature"), headers.get("x-bx-apikey")
        ):
            with self._lock:
                self.signature_failures.append(entry)
            return 401, {"code": 109400, "msg": "signature check failed"}

        if path == CONTRACTS_PATH:
            # The client answers the envelope's `data`, and the documents
            # feature 1's translator reads are its rows; the recorded
            # fixture's own envelope is returned as the stand-in's body.
            return 200, _fixture("contracts.json")
        if path == PREMIUM_INDEX_PATH:
            return 200, _fixture("premium_index.json")
        if path == SERVER_TIME_PATH:
            return 200, {
                "code": 0,
                "msg": "",
                "data": {"serverTime": int(time.time() * 1000)},
            }
        if path == BALANCE_PATH:
            return 200, {
                "code": 0,
                "msg": "",
                "data": {"balance": {"asset": "USDT", "availableMargin": "100000"}},
            }
        if path == POSITIONS_PATH:
            return 200, {"code": 0, "msg": "", "data": []}
        if path == MARGIN_TYPE_PATH:
            return 200, {"code": 0, "msg": "", "data": {}}
        if path == LEVERAGE_PATH:
            return 200, {"code": 0, "msg": "", "data": {}}
        if path == ORDER_PATH and method == "POST":
            client_order_id = params.get("clientOrderID")
            with self._lock:
                if client_order_id in self.orders:
                    # BingX's duplicate-clientOrderID refusal, verbatim in
                    # spirit: a blind re-post of an order that landed is
                    # exactly what the mirror must never earn.
                    return 200, {
                        "code": 109404,
                        "msg": "duplicate clientOrderID",
                    }
                self.orders[client_order_id] = params
                self.open_orders.append(
                    {
                        "clientOrderID": client_order_id,
                        "symbol": params.get("symbol"),
                        "status": "NEW",
                    }
                )
            return 200, {
                "code": 0,
                "msg": "",
                "data": {"orderId": "1", "clientOrderID": client_order_id},
            }
        if path == ORDER_PATH and method == "GET":
            client_order_id = params.get("clientOrderID")
            with self._lock:
                order = self.orders.get(client_order_id)
            if order is None:
                return 200, {
                    "code": ORDER_NOT_FOUND_CODE,
                    "msg": "order does not exist",
                }
            return 200, {
                "code": 0,
                "msg": "",
                "data": {
                    "symbol": order.get("symbol"),
                    "clientOrderID": client_order_id,
                    "status": "NEW",
                    "executedQty": "0",
                    "avgPrice": "0",
                },
            }
        if path == ORDER_PATH and method == "DELETE":
            client_order_id = params.get("clientOrderID")
            with self._lock:
                self.orders.pop(client_order_id, None)
                self.open_orders = [
                    o for o in self.open_orders
                    if o["clientOrderID"] != client_order_id
                ]
            return 200, {"code": 0, "msg": "", "data": {}}
        if path == OPEN_ORDERS_PATH:
            with self._lock:
                listed = list(self.open_orders)
            # A foreign order rides the listing: it belongs to no rebalance
            # this command knows, and the cancel must leave it untouched.
            listed.append(
                {"clientOrderID": "f" * 40, "symbol": "OTHER-USDT", "status": "NEW"}
            )
            return 200, {"code": 0, "msg": "", "data": listed}

        return 404, {"code": 109400, "msg": f"no such path {path}"}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args) -> None:  # pragma: no cover - silence
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        # HTTP header names are case-insensitive and urllib normalises their
        # case on the way out, so the reader lower-cases them once here
        # rather than guessing a spelling at every lookup.
        headers = {name.lower(): value for name, value in self.headers.items()}
        status, payload = self.server.stand_in.handle(
            method, parsed.path, parsed.query, self._body(), headers
        )
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@pytest.fixture
def stand_in():
    """A loopback BingX stand-in, with its URL and a stopping handle."""
    server = _Server(("127.0.0.1", 0), _Handler)
    server.stand_in = _StandIn()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield server, server.stand_in, f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def book_path(tmp_path: Path) -> Path:
    path = tmp_path / "book.json"
    path.write_text(json.dumps(_fixture("synthetic_book.json")), encoding="utf-8")
    return path


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'mirror-e2e.db'}"


def _child_env(
    tmp_path: Path,
    stand_in_url: str,
    database_url: str | None,
    *,
    credentials: bool = True,
) -> dict:
    """The child's environment: paths, fake credentials, loopback URL.

    ``PYTHONPATH`` leads with a directory holding this test's
    ``sitecustomize`` (the URL rewrite and the socket guard), then every
    workspace member's scan root, so the child imports the same code the
    test does.
    """
    guard = tmp_path / "child-guard"
    guard.mkdir(exist_ok=True)
    (guard / "sitecustomize.py").write_text(_SITE_CUSTOMIZE, encoding="utf-8")

    from app.module_loader import workspace_scan_roots

    roots = [str(guard), str(REPO_ROOT / "src")]
    roots += [str(root) for root in workspace_scan_roots()]

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(roots)
    env["E2E_STAND_IN_URL"] = stand_in_url
    if database_url is not None:
        env["DATABASE_URL"] = database_url
    else:
        env.pop("DATABASE_URL", None)
    if credentials:
        env["BINGX_VST_API_KEY"] = API_KEY
        env["BINGX_VST_SECRET_KEY"] = API_SECRET
    else:
        env.pop("BINGX_VST_API_KEY", None)
        env.pop("BINGX_VST_SECRET_KEY", None)
    return env


def _run(args: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "router.bingx_mirror", *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=120,
        check=False,
    )


def _lines(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


# -- The first and second --place ---------------------------------------------


def test_a_first_place_sends_exactly_five_verified_order_posts(
    tmp_path, stand_in, book_path, database_url
):
    _, venue, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    assert venue.signature_failures == []
    assert len(venue.order_posts()) == 5
    assert {p["params"]["symbol"] for p in venue.order_posts()} == set(ORDERED_SYMBOLS)


def test_a_second_place_sends_none_and_prints_prior_for_all_five(
    tmp_path, stand_in, book_path, database_url
):
    _, venue, url = stand_in
    env = _child_env(tmp_path, url, database_url)
    first = _run(["--book", str(book_path), "--place"], env)
    assert first.returncode == 0, first.stderr
    assert len(venue.order_posts()) == 5

    second = _run(["--book", str(book_path), "--place"], env)
    assert second.returncode == 0, second.stderr
    # Not one further order POST: the store answered every leg.
    assert len(venue.order_posts()) == 5
    priors = [line for line in _lines(second.stdout) if line.get("placement") == "prior"]
    assert len(priors) == 5


def test_the_orders_reach_the_venue_as_stage_zeros_parameters(
    tmp_path, stand_in, book_path, database_url
):
    _, venue, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    for post in venue.order_posts():
        params = post["params"]
        assert params["positionSide"] == "BOTH"
        assert params["type"] in ("LIMIT", "MARKET")
        # BingX receives the 40-character projection, never the 64-hex key.
        assert len(params["clientOrderID"]) == 40
        assert "signature" in params
        assert post["headers"].get("x-bx-apikey") == API_KEY


def test_placing_prints_one_line_per_leg_with_the_placement_word(
    tmp_path, stand_in, book_path, database_url
):
    _, _, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    lines = _lines(result.stdout)
    # Seven legs: five orders placed, two refused by the gates.
    assert len(lines) == 7
    assert sum(line.get("placement") == "placed" for line in lines) == 5
    assert sum("refusal" in line for line in lines) == 2


def test_the_idempotency_key_in_the_store_is_the_full_sixty_four_hex(
    tmp_path, stand_in, book_path, database_url
):
    import sqlite3

    _, _, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    path = Path(database_url.removeprefix("sqlite:///"))
    with sqlite3.connect(path) as connection:
        keys = [
            row[0]
            for row in connection.execute(
                "SELECT client_order_id FROM router_order_placement"
            )
        ]
    assert len(keys) == 5
    assert all(len(key) == 64 and key == key.lower() for key in keys)


# -- Credentials ---------------------------------------------------------------


def test_the_api_key_and_secret_never_appear_in_stdout_or_stderr(
    tmp_path, stand_in, book_path, database_url
):
    _, _, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert API_KEY not in combined
    assert API_SECRET not in combined


def test_neither_credential_reaches_the_placement_store(
    tmp_path, stand_in, book_path, database_url
):
    _, _, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    raw = Path(database_url.removeprefix("sqlite:///")).read_bytes()
    assert API_KEY.encode() not in raw
    assert API_SECRET.encode() not in raw


# -- The host guard ------------------------------------------------------------


def test_a_run_against_the_live_host_is_refused_with_no_socket_opened(
    book_path, database_url, test_database_url
):
    """A client aimed at open-api.bingx.com refuses before any transport call."""
    calls: list[tuple] = []

    def spy(method, url, headers, body):
        calls.append((method, url))
        raise AssertionError("the guard should have refused before this ran")

    client = BingXClient.from_env(
        env={"BINGX_VST_API_KEY": API_KEY, "BINGX_VST_SECRET_KEY": API_SECRET},
        transport=spy,
        base_url=f"https://{LIVE_HOST}",
    )

    from router.bingx_mirror import main as mirror_main

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mirror_main(["--book", str(book_path)], client=client)

    assert code == 1
    assert err.getvalue().startswith("bingx_mirror: ")
    assert "live_host_refused" in err.getvalue()
    assert LIVE_HOST in err.getvalue()
    assert VST_HOST not in client.base_url
    assert calls == []


def test_the_child_never_opens_a_socket_beyond_loopback(
    tmp_path, stand_in, book_path, database_url
):
    """The child's own guard proves a run touches nothing but 127.0.0.1."""
    _, _venue, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, database_url),
    )
    assert result.returncode == 0, result.stderr
    # The guard would have raised and failed the run had anything reached
    # further; the run's own success is the proof.
    assert "e2e guard: refused a socket" not in result.stderr


# -- Nothing placed without --place -------------------------------------------


def test_without_place_the_command_prints_the_plan_and_places_nothing(
    tmp_path, stand_in, book_path, database_url
):
    _, venue, url = stand_in
    result = _run(["--book", str(book_path)], _child_env(tmp_path, url, database_url))
    assert result.returncode == 0, result.stderr
    # The plan is read, but not one order leaves.
    assert venue.order_posts() == []
    assert venue.orders == {}
    lines = _lines(result.stdout)
    assert len(lines) == 7
    assert all("placement" not in line for line in lines)


def test_place_without_a_database_url_refuses_before_placing(
    tmp_path, stand_in, book_path
):
    _, venue, url = stand_in
    result = _run(
        ["--book", str(book_path), "--place"],
        _child_env(tmp_path, url, None),
    )
    assert result.returncode == 1
    assert "database_url_missing" in result.stderr
    assert venue.order_posts() == []


# -- --status and --cancel -----------------------------------------------------


def test_status_reads_back_the_five_orders_after_placing(
    tmp_path, stand_in, book_path, database_url
):
    _, _venue, url = stand_in
    env = _child_env(tmp_path, url, database_url)
    placed = _run(["--book", str(book_path), "--place"], env)
    assert placed.returncode == 0, placed.stderr

    status = _run(["--book", str(book_path), "--status"], env)
    assert status.returncode == 0, status.stderr
    lines = _lines(status.stdout)
    assert len(lines) == 5
    assert {line["status"] for line in lines} == {"NEW"}
    assert {line["symbol"] for line in lines} == set(ORDERED_SYMBOLS)


def test_cancel_leaves_the_listing_s_foreign_order_untouched(
    tmp_path, stand_in, book_path, database_url
):
    _, venue, url = stand_in
    env = _child_env(tmp_path, url, database_url)
    placed = _run(["--book", str(book_path), "--place"], env)
    assert placed.returncode == 0, placed.stderr

    cancel = _run(["--book", str(book_path), "--cancel"], env)
    assert cancel.returncode == 0, cancel.stderr
    cancelled = [line["clientOrderID"] for line in _lines(cancel.stdout)]
    assert len(cancelled) == 5
    assert all(len(identifier) == 40 for identifier in cancelled)
    # The foreign order in the listing was never handed to the venue's cancel.
    deletes = [
        r for r in venue.requests
        if r["method"] == "DELETE" and r["path"] == ORDER_PATH
    ]
    assert {r["params"]["clientOrderID"] for r in deletes} == set(cancelled)


# -- The stand-in itself is honest --------------------------------------------


def test_the_stand_in_refuses_a_broken_signature(stand_in):
    """A guard on the guard: a forged signature is refused, not accepted."""
    _, venue, url = stand_in
    request = urllib.request.Request(
        f"{url}{BALANCE_PATH}?timestamp=1&recvWindow=5000&signature=deadbeef",
        headers={"X-BX-APIKEY": API_KEY},
    )
    try:
        urllib.request.urlopen(request, timeout=5)
        status = 200
    except urllib.error.HTTPError as exc:
        status = exc.code
    assert status == 401
    assert len(venue.signature_failures) == 1
