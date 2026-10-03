"""Tests for :mod:`router.bingx_client` — signed, VST-only, nothing sent elsewhere.

Feature 1 of additions_spec_bingx_vst_mirror.xml, held clause by clause:
*System delivers BingX swap requests only to open-api-vst.bingx.com, each
signed: a request carries timestamp and recvWindow, its parameters sorted by
key and URL-encoded, signature equal to the HMAC-SHA256 hex of that query
string keyed by the secret, and the key in the X-BX-APIKEY header.  A request
addressed to any other host, open-api.bingx.com included, returns a
live_host_refused refusal before anything is sent.  A response whose code is
not 0 returns a bingx_refused error carrying that code and msg.  HTTP 429
raises router.errors.RouterRateLimitedError.  Credentials are read from
BINGX_VST_API_KEY and BINGX_VST_SECRET_KEY; a missing one returns a
vst_credentials_missing refusal naming the variable, and neither value appears
in any repr, message or log line.*

Every test injects a transport that records what it was handed — the suite
never opens a socket.  The pinned signature is recomputed in the test with
:mod:`hmac` rather than read back off the client, so the test is an
independent check of the arithmetic and not a second copy of it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from pathlib import Path

import pytest
from router.bingx_client import (
    API_KEY_ENV,
    BALANCE_PATH,
    BINGX_REFUSED_CODE,
    DEPTH_PATH,
    LIVE_HOST,
    LIVE_HOST_REFUSED_CODE,
    OPEN_ORDERS_PATH,
    ORDER_NOT_FOUND_CODE,
    ORDER_PATH,
    POSITION_MODE_PATH,
    POSITIONS_PATH,
    SECRET_KEY_ENV,
    VST_BASE_URL,
    VST_CREDENTIALS_MISSING_CODE,
    VST_HOST,
    BingXClient,
    RouterBingXClientError,
    RouterBingXRefusedError,
    RouterBingXResponseError,
    RouterBingXTransportError,
    RouterLiveHostError,
    RouterVSTCredentialsMissingError,
)
from router.errors import RouterError, RouterRateLimitedError

API_KEY = "vst-key-0123456789"
SECRET_KEY = "vst-secret-abcdef"
FIXED_MILLIS = 1_700_000_000_123

#: The recorded live VST captures — inputs only, never edited.  The
#: position-mode fixtures are the two answers the live smoke test took on
#: one sub-account before and after switching it to one-way, and they pin
#: the spelling ``position_mode`` reads (bug_spec_bingx_vst_smoke.xml,
#: bug 2).
LIVE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bingx_vst" / "live"


def _live(name: str) -> object:
    """One recorded live answer, as the venue sent it."""
    return json.loads((LIVE_FIXTURES / name).read_text(encoding="utf-8"))


def _envelope(data: object, *, code: int = 0, msg: str = "") -> bytes:
    """A venue response body, as JSON bytes."""
    import json

    return json.dumps({"code": code, "msg": msg, "data": data}).encode("utf-8")


class _Recorder:
    """A transport that records every request and answers scripted responses.

    The suite's whole network stance: nothing here opens a socket, and the
    recorder keeps what it was handed so a test can assert the URL, the
    headers and the body *before* judging the answer.
    """

    def __init__(self, *answers: tuple[int, bytes] | Exception) -> None:
        self._answers = list(answers)
        self.requests: list[tuple[str, str, dict, bytes]] = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, dict(headers), bytes(body)))
        if not self._answers:
            return 200, _envelope(None)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    @property
    def sent(self) -> int:
        return len(self.requests)

    @property
    def last_url(self) -> str:
        return self.requests[-1][1]

    @property
    def last_headers(self) -> dict:
        return self.requests[-1][2]


def _client(recorder: _Recorder, **kwargs) -> BingXClient:
    """A client over the recorder with fake credentials and a pinned clock."""
    return BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=recorder,
        clock=lambda: FIXED_MILLIS,
        **kwargs,
    )


# -- Signing ------------------------------------------------------------------


def test_the_signature_is_the_hmac_sha256_hex_of_the_sorted_encoded_query() -> None:
    """The sentence's signing clause, recomputed independently in the test."""
    recorder = _Recorder((200, _envelope({"ok": True})))
    client = _client(recorder)
    parameters = {"symbol": "BTC-USDT", "side": "BUY", "quantity": "0.0100"}

    url, headers, _body = client._signed_target("GET", ORDER_PATH, parameters)

    # The query the client built, split back into its parts.
    query = urllib.parse.urlsplit(url).query
    pairs = urllib.parse.parse_qsl(query)
    fields = dict(pairs)
    assert fields["timestamp"] == str(FIXED_MILLIS)
    assert fields["recvWindow"] == "5000"
    assert fields["symbol"] == "BTC-USDT"
    assert fields["side"] == "BUY"
    assert fields["quantity"] == "0.0100"

    # Sorted by key and URL-encoded: the signed string is exactly this.
    signed = urllib.parse.urlencode(
        sorted({**parameters, "timestamp": str(FIXED_MILLIS), "recvWindow": "5000"}.items())
    )
    signature = fields.pop("signature")
    assert query == f"{signed}&signature={signature}"

    expected = hmac.new(
        SECRET_KEY.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert signature == expected
    assert headers["X-BX-APIKEY"] == API_KEY


def test_the_key_travels_in_the_x_bx_apikey_header_and_never_in_the_url() -> None:
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder)

    client.balance()

    _method, url, headers, _body = recorder.requests[-1]
    assert headers["X-BX-APIKEY"] == API_KEY
    assert API_KEY not in url
    assert SECRET_KEY not in url


def test_a_write_carries_the_same_signed_string_in_its_body() -> None:
    recorder = _Recorder((200, _envelope({"orderId": 1})))
    client = _client(recorder)

    client.place_order({"symbol": "BTC-USDT", "side": "BUY", "quantity": "0.0100"})

    method, _url, _headers, body = recorder.requests[-1]
    assert method == "POST"
    fields = dict(urllib.parse.parse_qsl(body.decode("ascii")))
    assert fields["symbol"] == "BTC-USDT"
    assert fields["timestamp"] == str(FIXED_MILLIS)
    assert fields["recvWindow"] == "5000"
    assert "signature" in fields
    # The signature signs the body's own query string, exactly.
    unsigned = {key: value for key, value in fields.items() if key != "signature"}
    signed = urllib.parse.urlencode(sorted(unsigned.items()))
    expected = hmac.new(
        SECRET_KEY.encode("utf-8"), signed.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert fields["signature"] == expected


def test_sign_is_a_pure_recomputation_a_caller_can_check() -> None:
    client = _client(_Recorder())
    query, signature = client.sign({"symbol": "ETH-USDT"}, timestamp=42)
    assert query == "recvWindow=5000&symbol=ETH-USDT&timestamp=42"
    assert signature == hmac.new(
        SECRET_KEY.encode("utf-8"), query.encode("utf-8"), hashlib.sha256
    ).hexdigest()


# -- The host guard -----------------------------------------------------------


@pytest.mark.parametrize("host", [LIVE_HOST, "example.com", "open-api-vst.bingx.com.evil.test"])
def test_any_host_other_than_vst_is_refused_before_anything_is_sent(host: str) -> None:
    """*"before anything is sent"*: the recorder sees zero requests."""
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder, base_url=f"https://{host}")

    with pytest.raises(RouterLiveHostError) as raised:
        client.balance()

    assert raised.value.host == host
    assert str(raised.value).startswith(LIVE_HOST_REFUSED_CODE)
    assert recorder.sent == 0


def test_the_live_host_refusal_names_the_live_host_and_states_no_flag_changes_it() -> None:
    client = _client(_Recorder(), base_url=f"https://{LIVE_HOST}")
    with pytest.raises(RouterLiveHostError) as raised:
        client.server_time()
    message = str(raised.value)
    assert LIVE_HOST in message
    assert VST_HOST in message


def test_the_default_base_url_is_the_vst_host() -> None:
    assert VST_BASE_URL == f"https://{VST_HOST}"


def test_refusing_a_live_host_opens_no_socket_even_with_the_real_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*"before anything is sent"*: with ``socket.socket`` patched to raise.

    The client here uses its **default** urllib transport; if the guard ran
    after the transport, or did not run at all, the patched socket would
    raise a transport error instead of :class:`RouterLiveHostError`.
    """
    import socket

    def _no_socket(*args, **kwargs):
        raise AssertionError("a socket was opened for a refused host")

    monkeypatch.setattr(socket, "socket", _no_socket)
    client = BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        base_url=f"https://{LIVE_HOST}",
        clock=lambda: FIXED_MILLIS,
    )
    with pytest.raises(RouterLiveHostError):
        client.balance()


def test_no_credential_is_ever_logged(caplog: pytest.LogCaptureFixture) -> None:
    """*"neither value appears in any repr, message or log line"*."""
    import logging

    def refusing(method, url, headers, body):
        return 200, _envelope(None, code=1, msg="boom")

    client = BingXClient(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        transport=refusing,
        clock=lambda: FIXED_MILLIS,
    )
    with caplog.at_level(logging.DEBUG):
        for action in (
            client.balance,
            lambda: client.place_order({"symbol": "BTC-USDT"}),
        ):
            with pytest.raises(RouterBingXClientError):
                action()
    rendered = "\n".join(
        record.getMessage() + repr(record.args) for record in caplog.records
    )
    assert API_KEY not in rendered
    assert SECRET_KEY not in rendered


def test_a_live_host_client_still_refuses_even_a_public_read() -> None:
    """The guard is on the URL, not on whether the endpoint is signed."""
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder, base_url=f"https://{LIVE_HOST}")
    with pytest.raises(RouterLiveHostError):
        client.contracts()
    assert recorder.sent == 0


# -- Responses ----------------------------------------------------------------


def test_a_non_zero_code_is_a_bingx_refused_carrying_the_code_and_msg() -> None:
    recorder = _Recorder((200, _envelope(None, code=80001, msg="invalid signature")))
    client = _client(recorder)

    with pytest.raises(RouterBingXRefusedError) as raised:
        client.balance()

    assert raised.value.code == 80001
    assert raised.value.msg == "invalid signature"
    assert str(raised.value).startswith(BINGX_REFUSED_CODE)


def test_a_zero_code_returns_the_data_field() -> None:
    recorder = _Recorder((200, _envelope({"asset": "USDT", "balance": "100"})))
    client = _client(recorder)
    assert client.balance() == {"asset": "USDT", "balance": "100"}


def test_a_string_zero_code_is_also_success() -> None:
    """Some venue versions spell the success code ``"0"``."""
    recorder = _Recorder((200, _envelope({"ok": True}, code="0")))
    client = _client(recorder)
    assert client.balance() == {"ok": True}


@pytest.mark.parametrize("code", [1, True, None, 0.0, "abc", "1"])
def test_anything_other_than_zero_is_refused_with_its_code(code) -> None:
    """*"A response whose code is not 0"* — exact, so garbled codes are not success."""
    recorder = _Recorder((200, _envelope(None, code=code, msg="nope")))
    client = _client(recorder)
    with pytest.raises(RouterBingXRefusedError) as raised:
        client.balance()
    assert raised.value.code == code


def test_a_response_with_no_code_field_is_a_response_error() -> None:
    import json

    recorder = _Recorder((200, json.dumps({"msg": "", "data": None}).encode("utf-8")))
    client = _client(recorder)
    with pytest.raises(RouterBingXResponseError):
        client.balance()


def test_http_429_raises_the_router_rate_limited_error_with_a_reading() -> None:
    recorder = _Recorder((429, b""))
    client = _client(recorder)

    with pytest.raises(RouterRateLimitedError) as raised:
        client.place_order({"symbol": "BTC-USDT"})

    refusal = raised.value
    assert isinstance(refusal, RouterError)
    # The refusal carries a well-formed headroom so feature 319 can pace it.
    assert refusal.headroom.allowed is False
    assert refusal.headroom.deficit == 1
    assert refusal.retry_after is not None


def test_a_429_on_a_get_is_also_the_rate_limit_refusal() -> None:
    client = _client(_Recorder((429, b"")))
    with pytest.raises(RouterRateLimitedError):
        client.balance()


def test_a_body_that_is_not_the_envelope_is_a_response_error() -> None:
    client = _client(_Recorder((502, b"<html>bad gateway</html>")))
    with pytest.raises(RouterBingXResponseError):
        client.balance()


def test_a_non_zero_code_on_a_query_order_is_judgeable_by_its_code() -> None:
    """Feature 3 reads ``not_found`` off the carried code, never the message."""
    client = _client(
        _Recorder((200, _envelope(None, code=ORDER_NOT_FOUND_CODE, msg="order not exist")))
    )
    with pytest.raises(RouterBingXRefusedError) as raised:
        client.query_order("a" * 40)
    assert raised.value.code == ORDER_NOT_FOUND_CODE


def test_a_transport_failure_on_a_write_reports_the_outcome_unknown() -> None:
    client = _client(_Recorder(TimeoutError("timed out")))
    with pytest.raises(RouterBingXTransportError) as raised:
        client.place_order({"symbol": "BTC-USDT"})
    assert raised.value.outcome_unknown is True


def test_a_transport_failure_on_a_read_reports_a_safe_retry() -> None:
    client = _client(_Recorder(ConnectionResetError("dropped")))
    with pytest.raises(RouterBingXTransportError) as raised:
        client.balance()
    assert raised.value.outcome_unknown is False


# -- Credentials and redaction ------------------------------------------------


@pytest.mark.parametrize("missing", [API_KEY_ENV, SECRET_KEY_ENV])
def test_a_missing_credential_refuses_naming_the_variable(missing: str) -> None:
    env = {API_KEY_ENV: "k", SECRET_KEY_ENV: "s"}
    env.pop(missing)
    env[missing] = ""  # present but empty counts as missing

    with pytest.raises(RouterVSTCredentialsMissingError) as raised:
        BingXClient.from_env(env=env)

    assert raised.value.variable == missing
    assert str(raised.value).startswith(VST_CREDENTIALS_MISSING_CODE)
    assert missing in str(raised.value)


def test_an_absent_environment_variable_is_named_not_guessed() -> None:
    with pytest.raises(RouterVSTCredentialsMissingError) as raised:
        BingXClient.from_env(env={})
    assert raised.value.variable == API_KEY_ENV


def test_from_env_builds_a_client_from_the_two_named_variables() -> None:
    client = BingXClient.from_env(
        env={API_KEY_ENV: "k", SECRET_KEY_ENV: "s"},
        transport=_Recorder((200, _envelope(None))),
        clock=lambda: 1,
    )
    assert client.api_key == "k"
    assert client.secret_key == "s"


def test_neither_credential_appears_in_the_repr() -> None:
    client = _client(_Recorder())
    rendered = repr(client)
    assert API_KEY not in rendered
    assert SECRET_KEY not in rendered
    assert "redacted" in rendered


def test_neither_credential_appears_in_any_refusal_message() -> None:
    # A live-host refusal, a missing-credential refusal, a venue refusal and a
    # transport failure: the four messages a caller might log.
    cases: list[RouterBingXClientError] = [
        RouterLiveHostError(LIVE_HOST),
        RouterVSTCredentialsMissingError(API_KEY_ENV),
        RouterBingXRefusedError(1, "bad"),
        RouterBingXTransportError("POST", VST_BASE_URL, "timeout", outcome_unknown=True),
    ]
    for error in cases:
        assert API_KEY not in str(error)
        assert SECRET_KEY not in str(error)


def test_neither_credential_appears_in_a_signed_url_or_headers() -> None:
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder)
    client.positions()
    _method, url, headers, body = recorder.requests[-1]
    assert SECRET_KEY not in url and SECRET_KEY not in body.decode("ascii")
    assert API_KEY not in url
    assert API_KEY in headers["X-BX-APIKEY"]  # the key *is* the header's whole point


# -- The nine exposed operations ----------------------------------------------


def test_open_orders_hits_its_own_endpoint() -> None:
    recorder = _Recorder((200, _envelope([])))
    client = _client(recorder)
    assert client.open_orders() == []
    assert recorder.last_url.startswith(f"{VST_BASE_URL}{OPEN_ORDERS_PATH}")


def test_positions_can_be_narrowed_to_one_symbol() -> None:
    recorder = _Recorder((200, _envelope([])))
    client = _client(recorder)
    client.positions("BTC-USDT")
    assert "symbol=BTC-USDT" in recorder.last_url


def test_depth_reads_one_symbols_book_from_its_own_public_endpoint() -> None:
    """GET quote/depth for the symbol — public, so it signs nothing.

    The read the mirror's passive repricing stands on: a PostOnly order
    rests on its own side of the *book*, and the mark can sit on the far
    side of it (the live capture's ETH-USDT book — the best bid 2665.89,
    the best ask 2673.27 — against a mark of 2685.87).  Market data is
    public like contracts and premiumIndex: no signature, no key.
    """
    recorder = _Recorder(
        (200, _envelope({"bids": [["2665.89", "45.451"]], "asks": [["2673.27", "39.807"]]}))
    )
    client = _client(recorder)

    data = client.depth("ETH-USDT")

    assert data["bids"][0][0] == "2665.89"
    assert data["asks"][0][0] == "2673.27"
    method, url, headers, body = recorder.requests[-1]
    assert method == "GET"
    assert url.startswith(f"{VST_BASE_URL}{DEPTH_PATH}")
    assert "symbol=ETH-USDT" in url
    assert "X-BX-APIKEY" not in headers
    assert body == b""


def test_position_mode_hits_its_own_endpoint_signed_like_every_account_read() -> None:
    """The hedge question's one read: GET positionSide/dual, signed and keyed.

    An account read like ``balance`` — signed parameters, the key in the
    header, the host guard already run on the assembled URL — because the
    answer names this account's own arrangement, not market data.
    """
    recorder = _Recorder((200, _envelope({"dualSidePosition": "false"})))
    client = _client(recorder)

    assert client.position_mode() is False

    method, url, headers, body = recorder.requests[-1]
    assert method == "GET"
    assert url.startswith(f"{VST_BASE_URL}{POSITION_MODE_PATH}")
    query = urllib.parse.urlsplit(url).query
    assert "timestamp" in query and "recvWindow" in query
    assert "signature" in query
    assert headers["X-BX-APIKEY"] == API_KEY
    assert body == b""


def test_position_mode_answers_both_live_captures_and_the_boolean_spelling() -> None:
    """The venue's own two answers — pinned on the live captures — read exactly.

    The smoke test took both answers on one sub-account: ``"true"`` as a
    fresh hedge-mode account, ``"false"`` after the switch to one-way.  A
    JSON boolean is the same fact's other spelling, so both read; the
    preflight's hedge refusal stands on this boolean, never on a
    position's ``positionSide``.
    """
    for spelling, expected in (
        (_live("position_mode_hedge.json")["data"], True),
        (_live("position_mode_one_way.json")["data"], False),
        ({"dualSidePosition": True}, True),
        ({"dualSidePosition": False}, False),
    ):
        recorder = _Recorder((200, _envelope(spelling)))
        client = _client(recorder)
        assert client.position_mode() is expected, spelling


def test_a_position_mode_answer_that_is_not_the_two_spellings_is_refused() -> None:
    """A ``dualSidePosition`` this cannot judge is a response fault, not a guess.

    The hedge-mode refusal must stand on the venue's own words: a value
    that is neither of the spellings the document answers — nor a
    missing field, nor ``null`` — is refused rather than read through
    its truthiness, because a garbled answer must not pass for one-way.
    """
    for data in (
        {"dualSidePosition": "maybe"},
        {"dualSidePosition": None},
        {"dualSidePosition": 1},
        {},
        {"dualSidePosition2": "true"},
    ):
        recorder = _Recorder((200, _envelope(data)))
        client = _client(recorder)
        with pytest.raises(RouterBingXResponseError):
            client.position_mode()


def test_set_margin_type_sends_isolated_by_default() -> None:
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder)
    client.set_margin_type("BTC-USDT")
    fields = dict(urllib.parse.parse_qsl(recorder.requests[-1][3].decode("ascii")))
    assert fields["marginType"] == "ISOLATED"
    assert fields["symbol"] == "BTC-USDT"


def test_set_leverage_sends_one_on_both_sides() -> None:
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder)
    client.set_leverage("ETH-USDT")
    fields = dict(urllib.parse.parse_qsl(recorder.requests[-1][3].decode("ascii")))
    assert fields["leverage"] == "1"
    assert fields["side"] == "BOTH"


def test_cancel_order_sends_a_delete_carrying_the_client_order_id() -> None:
    recorder = _Recorder((200, _envelope(None)))
    client = _client(recorder)
    client.cancel_order("b" * 40)
    method, _url, _headers, body = recorder.requests[-1]
    assert method == "DELETE"
    fields = dict(urllib.parse.parse_qsl(body.decode("ascii")))
    assert fields["clientOrderID"] == "b" * 40


def test_every_path_the_feature_lists_has_an_exposed_call() -> None:
    recorder = _Recorder(*[(200, _envelope(None))] * 9)
    client = _client(recorder)
    assert callable(client.server_time)
    client.balance()
    client.positions()
    client.set_margin_type("BTC-USDT")
    client.set_leverage("BTC-USDT")
    client.place_order({"symbol": "BTC-USDT"})
    client.query_order("c" * 40)
    client.cancel_order("d" * 40)
    client.open_orders()
    assert recorder.sent == 8  # server_time was referenced, not called
    paths = {urllib.parse.urlsplit(request[1]).path for request in recorder.requests}
    assert ORDER_PATH in paths
    assert BALANCE_PATH in paths
    assert POSITIONS_PATH in paths
    assert OPEN_ORDERS_PATH in paths


def test_the_public_reads_carry_no_key_header() -> None:
    """Market data is public: server time, contracts and premiumIndex sign nothing."""
    recorder = _Recorder(
        (200, _envelope({"serverTime": 5})),
        (200, _envelope([])),
        (200, _envelope([])),
    )
    client = _client(recorder)
    client.server_time()
    client.contracts()
    client.premium_index()
    for method, url, headers, body in recorder.requests:
        assert "X-BX-APIKEY" not in headers
        assert body == b""
