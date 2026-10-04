"""Stage 1's signed BingX client — VST only, by construction.

``additions_spec_bingx_vst_mirror.xml``, "BingX VST Mirror", feature 1:
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
in any repr, message or log line.  The client exposes server time, balance,
positions, set margin type, set leverage, place order, query order, cancel
order and open orders.*

**Why the host guard is structural.**  The constraint is one sentence: *"The
only host the client can reach is open-api-vst.bingx.com.  There is no --live
flag, no host setting, and no environment variable that changes it."*  So the
live host is not a documented default that a flag can override — it is a
value this module *refuses to build a request for*, checked on the assembled
URL **before** the transport is called.  A test that wants a loopback
stand-in injects a transport and lets it rewrite the VST host to 127.0.0.1:
the URL the client hands the transport still names
:data:`VST_HOST`, so the guard has already run and the loopback is the
*test's* act, not a setting any deployment can reach.

**Signing is the standard library.**  ``hmac``, ``hashlib`` and
``urllib.parse``, exactly as the constraints require — the router adds no
third-party dependency.  The signed parameter set is ``timestamp`` (whole
milliseconds) and ``recvWindow`` merged into the caller's own, sorted by key,
URL-encoded with :func:`urllib.parse.urlencode`, and hashed with
HMAC-SHA256 keyed by the secret; ``signature=<hex>`` is appended and the key
travels in the ``X-BX-APIKEY`` header.  :meth:`BingXClient.sign` is the one
place that string is built, exposed so a caller — or a test — can recompute
it independently rather than trust it.

**The transport is injected.**  A transport is a callable
``(method, url, headers, body) -> (status, body)``; the default is a
:mod:`urllib.request` transport with a timeout.  The whole module is a pure
function of the transport it is handed, which is what makes *"no test opens a
network connection"* enforceable: the suite passes a recorder, and the
end-to-end test passes one that serves a loopback stand-in under the VST host
name.

**The API key and the secret are never rendered.**  They are the client's
private state: :meth:`BingXClient.__repr__` redacts both, every refusal names
the *environment variable* that should hold a value rather than the value, and
no message here interpolates either one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .bingx_order import BINGX_POSITION_SIDE_BOTH
from .errors import RouterError, RouterRateLimitedError
from .limiter import (
    DEFAULT_WEIGHT_SCOPE,
    OPERATION_ACCOUNT,
    OPERATION_CANCEL_ORDER,
    OPERATION_OPEN_ORDERS,
    OPERATION_PLACE_ORDER,
    OPERATION_QUERY_ORDER,
    RateLimitHeadroom,
    VenueWeightSchedule,
)

__all__ = [
    "API_KEY_ENV",
    "BALANCE_PATH",
    "BINGX_MARGIN_TYPE_CROSSED",
    "BINGX_MARGIN_TYPE_ISOLATED",
    "BINGX_REFUSED_CODE",
    "CONTRACTS_PATH",
    "DEFAULT_TIMEOUT_SECONDS",
    "DEPTH_PATH",
    "LEVERAGE_PATH",
    "LIVE_HOST",
    "LIVE_HOST_REFUSED_CODE",
    "MARGIN_TYPE_PATH",
    "OPEN_ORDERS_PATH",
    "ORDER_NOT_FOUND_CODE",
    "ORDER_PATH",
    "POSITION_MODE_PATH",
    "PREMIUM_INDEX_PATH",
    "RECV_WINDOW_MILLISECONDS",
    "SECRET_KEY_ENV",
    "SERVER_TIME_PATH",
    "TRANSPORT_CODE",
    "VST_BASE_URL",
    "VST_CREDENTIALS_MISSING_CODE",
    "VST_HOST",
    "VST_REQUEST_WEIGHT",
    "VST_WEIGHT_ALLOWANCE",
    "VST_WEIGHT_SCHEDULE",
    "VST_WEIGHT_WINDOW",
    "BingXClient",
    "RouterBingXClientError",
    "RouterBingXRefusedError",
    "RouterBingXResponseError",
    "RouterBingXTransportError",
    "RouterLiveHostError",
    "RouterVSTCredentialsMissingError",
    "make_urllib_transport",
]

#: The one host the client may reach.  Every request is built under this name
#: and the guard refuses any other, so a deployment cannot point the client at
#: the live venue even by accident.
VST_HOST = "open-api-vst.bingx.com"

#: The VST venue's root.  The guard reads :data:`VST_HOST` out of whatever base
#: URL the client was built with; this is only the value a caller with nothing
#: to state gets.
VST_BASE_URL = f"https://{VST_HOST}"

#: The live venue's host, named only so a refusal can say it was refused.  The
#: client will not build a request for it; the constant exists to make that
#: refusal legible, not to be reachable.
LIVE_HOST = "open-api.bingx.com"

#: The two environment variables credentials arrive through — injected by
#: ``op run`` through ``run.sh`` in a real deployment.  Referenced by name in
#: every refusal; their *values* are never interpolated anywhere.
API_KEY_ENV = "BINGX_VST_API_KEY"
SECRET_KEY_ENV = "BINGX_VST_SECRET_KEY"

#: Signed requests carry a receive window, in whole milliseconds, as BingX's
#: published sample code does.
RECV_WINDOW_MILLISECONDS = 5000

#: The default socket timeout for the urllib transport, in seconds.
DEFAULT_TIMEOUT_SECONDS = 10.0

#: The VST endpoints this client speaks, as the feature lists them.  Paths are
#: relative to :data:`VST_BASE_URL`.
SERVER_TIME_PATH = "/openApi/swap/v2/server/time"
CONTRACTS_PATH = "/openApi/swap/v2/quote/contracts"
PREMIUM_INDEX_PATH = "/openApi/swap/v2/quote/premiumIndex"
#: The symbol's order book — public market data, the read the mirror's
#: passive repricing stands on (``bug_spec_bingx_vst_mirror.xml``, bug on
#: mark-priced PostOnly orders).  Where the mark is only the venue's account
#: of value, the book is the collection of prices a PostOnly order can rest
#: against without crossing, so the mirror asks it just before placing.
DEPTH_PATH = "/openApi/swap/v2/quote/depth"
BALANCE_PATH = "/openApi/swap/v2/user/balance"
POSITIONS_PATH = "/openApi/swap/v2/user/positions"
MARGIN_TYPE_PATH = "/openApi/swap/v2/trade/marginType"
LEVERAGE_PATH = "/openApi/swap/v2/trade/leverage"
ORDER_PATH = "/openApi/swap/v2/trade/order"
OPEN_ORDERS_PATH = "/openApi/swap/v2/trade/openOrders"

#: The account's position mode — the one account read the live VST smoke
#: test added (``bug_spec_bingx_vst_smoke.xml``, bug 2).  The hedge-mode
#: question is asked here, never inferred from a position's
#: ``positionSide``: a flat hedge-mode account holds no row to inspect,
#: and BingX labels a one-way account's positions LONG and SHORT as well.
#: v1, not the v2 family above — this is the path the venue itself
#: answers for ``positionSide/dual``.
POSITION_MODE_PATH = "/openApi/swap/v1/positionSide/dual"

#: The venue's margin modes, as it spells them on the wire.  Feature 1's
#: sentence lists exactly these two (``ISOLATED`` and ``CROSSED``); the book's
#: own arrangement is feature 315's lowercase vocabulary and reaches the venue
#: through :data:`BINGX_MARGIN_TYPE_ISOLATED` rather than being sent raw.
BINGX_MARGIN_TYPE_ISOLATED = "ISOLATED"
BINGX_MARGIN_TYPE_CROSSED = "CROSSED"

#: The venue's answer, as its own error code, for an order it holds no record
#: of.  Feature 3 distinguishes this from any other refusal so it can report a
#: ``not_found`` status rather than propagate a failure — an order that never
#: landed is a *fact about the order*, not a fault of the read.  Held as a set
#: because the venue has more than one spelling of the same answer across
#: versions, and a caller tests membership rather than equality.
ORDER_NOT_FOUND_CODE = 109400

#: The greppable code words this module's refusals open with.  ``live_host_refused``
#: and ``vst_credentials_missing`` are spelled by feature 1's own sentence;
#: ``bingx_refused`` is the venue's refusal; ``bingx_transport`` and
#: ``bingx_response`` are this module's two contract faults (see the classes).
LIVE_HOST_REFUSED_CODE = "live_host_refused"
VST_CREDENTIALS_MISSING_CODE = "vst_credentials_missing"
BINGX_REFUSED_CODE = "bingx_refused"
TRANSPORT_CODE = "bingx_transport"

#: The refusal reading's schedule.  A 429 is raised as
#: :class:`~router.errors.RouterRateLimitedError`, which *carries* a
#: :class:`~router.limiter.RateLimitHeadroom` — feature 319's backoff reads the
#: wait off the refusal rather than querying the bucket, and it can only do
#: that if the reading is well-formed.  The client holds no bucket (the mirror
#: owns the shared one), so it states a schedule conservative against BingX's
#: published limits — one weight unit per request, ten per second, the same
#: numbers the mirror declares — and builds the reading from it.  No weight is
#: actually spent here; the venue itself stated the refusal.
VST_REQUEST_WEIGHT = 1
VST_WEIGHT_ALLOWANCE = 10
VST_WEIGHT_WINDOW = timedelta(seconds=1)
VST_WEIGHT_SCHEDULE = VenueWeightSchedule(
    allowance=VST_WEIGHT_ALLOWANCE,
    window=VST_WEIGHT_WINDOW,
    weights={
        OPERATION_ACCOUNT: VST_REQUEST_WEIGHT,
        OPERATION_CANCEL_ORDER: VST_REQUEST_WEIGHT,
        OPERATION_OPEN_ORDERS: VST_REQUEST_WEIGHT,
        OPERATION_PLACE_ORDER: VST_REQUEST_WEIGHT,
        OPERATION_QUERY_ORDER: VST_REQUEST_WEIGHT,
    },
)


# -- Errors -------------------------------------------------------------------


class RouterBingXClientError(RouterError):
    """The shared stem of every refusal this client raises.

    One class so a caller reaches the client's whole vocabulary through a
    single ``except``, split below by *which contract* was violated: the host
    guard, the credential contract, the venue's own refusal, the response
    contract and the transport contract.
    """


class RouterLiveHostError(RouterBingXClientError):
    """A request was addressed to a host that is not the VST venue.

    Feature 1's *"A request addressed to any other host, open-api.bingx.com
    included, returns a live_host_refused refusal before anything is sent."*
    Raised by the guard that runs on the assembled URL **before** the
    transport is reached, so no socket is opened for a refused address and no
    flag, setting or environment variable can produce one.

    :attr:`host` carries the offending host as a value, because the repair is
    *address the VST venue* and a caller holding only the message would have
    to parse it.
    """

    def __init__(self, host: Any) -> None:
        self.host = host
        super().__init__(
            f"{LIVE_HOST_REFUSED_CODE}: the BingX client reaches only "
            f"{VST_HOST!r} and {host!r} is not that host; there is no live "
            "flag, no host setting and no environment variable that changes "
            "it (feature 1), so address the VST venue or inject a transport "
            "that rewrites the VST host in a test"
        )


class RouterVSTCredentialsMissingError(RouterBingXClientError):
    """A credential the client needs was absent or empty.

    Feature 1: *"Credentials are read from BINGX_VST_API_KEY and
    BINGX_VST_SECRET_KEY; a missing one returns a vst_credentials_missing
    refusal naming the variable."*  :attr:`variable` is the environment
    variable's *name* — never its value — because the repair is *set that
    variable in the process's environment*.
    """

    def __init__(self, variable: str) -> None:
        self.variable = variable
        super().__init__(
            f"{VST_CREDENTIALS_MISSING_CODE}: {variable} is missing or empty; "
            "the client signs every request with the VST key and secret, so "
            "neither can be absent (feature 1) — set "
            f"{API_KEY_ENV} and {SECRET_KEY_ENV} in the process's environment "
            "before constructing the client"
        )


class RouterBingXRefusedError(RouterBingXClientError):
    """The venue answered with a code other than zero.

    Feature 1: *"A response whose code is not 0 returns a bingx_refused error
    carrying that code and msg."*  :attr:`code` is the venue's own code and
    :attr:`msg` its own message, carried verbatim so a caller — feature 3's
    read-back, deciding whether a missing order is ``not_found`` — can judge
    the refusal rather than only catch it.
    """

    def __init__(self, code: Any, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(
            f"{BINGX_REFUSED_CODE}: the venue answered code {code!r} with "
            f"{msg!r} (feature 1)"
        )

    def __repr__(self) -> str:  # pragma: no cover - trivial, but pinned
        return f"RouterBingXRefusedError(code={self.code!r}, msg={self.msg!r})"


class RouterBingXResponseError(RouterBingXClientError):
    """A response body was not the ``{"code", "msg", "data"}`` envelope.

    The *response contract* fault, split from the venue's own refusal because
    the repairs differ: a refusal carrying a code is the venue declining a
    well-formed request, while an unreadable body is a response this client
    cannot judge at all.  The offending status is carried so a caller can tell
    a truncated body from a proxy's HTML error page.
    """

    def __init__(self, status: int, detail: str) -> None:
        self.status = status
        super().__init__(
            f"{BINGX_REFUSED_CODE}: the response (HTTP {status}) carried no "
            f"{{'code', 'msg', 'data'}} envelope — {detail} (feature 1)"
        )


class RouterBingXTransportError(RouterBingXClientError):
    """The transport failed before a response arrived.

    A socket that timed out or dropped mid-request.  :attr:`outcome_unknown`
    is ``True`` for a write (``POST``/``DELETE``), where the venue may or may
    not have acted — feature 4's mirror queries the ``clientOrderID`` before
    re-posting for exactly this case — and ``False`` for a read, where a retry
    is plainly safe.
    """

    def __init__(self, method: str, url: str, detail: str, *, outcome_unknown: bool) -> None:
        self.method = method
        self.url = url
        self.outcome_unknown = outcome_unknown
        super().__init__(
            f"{TRANSPORT_CODE}: the {method} request to {url} failed before a "
            f"response arrived — {detail}; "
            + (
                "the outcome is unknown, so query the order before re-sending"
                if outcome_unknown
                else "the read may simply be retried"
            )
        )


# -- Transports ---------------------------------------------------------------


def make_urllib_transport(
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Callable[[str, str, Mapping[str, str], bytes], tuple[int, bytes]]:
    """The default transport: :mod:`urllib.request` with a timeout.

    Returns a callable ``(method, url, headers, body) -> (status, body)`` as
    the injected-transport contract requires.  A non-2xx response is *returned*
    rather than raised — :class:`urllib.error.HTTPError` is caught and its
    code and body handed back — so the client, not the transport, decides what
    a status means (a 429 becomes a rate-limit refusal, a 400 with an envelope
    becomes the venue's own ``bingx_refused``).  A transport-level failure
    (a timeout, a refused connection) still raises and is translated by the
    client.
    """

    def transport(
        method: str, url: str, headers: Mapping[str, str], body: bytes
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            url,
            data=body if body else None,
            headers=dict(headers),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return transport


# -- The client ---------------------------------------------------------------


def _system_clock_millis() -> int:
    """Wall-clock milliseconds since the epoch, as BingX's ``timestamp`` wants."""
    return int(time.time() * 1000)


def _require_credential(value: Any, variable: str) -> str:
    """Return ``value`` as a non-empty credential, or refuse naming the variable."""
    if not isinstance(value, str) or not value.strip():
        raise RouterVSTCredentialsMissingError(variable)
    return value


def _order_parameters(order: Any) -> dict[str, Any]:
    """The venue request parameters for ``order``, or refuse a shape we cannot send.

    Accepts either a servo-built order carrying ``parameters()`` — a
    :class:`~router.bingx_order.BingXOrder`, whose ``client_order_id`` is
    already the 40-character projection — or a plain mapping of the venue's
    own field spellings.  The client does not re-derive the projection: the
    caller that knows feature 316's full identifier projects it once, and a
    second projection here would be a second spelling of one order.
    """
    if isinstance(order, Mapping):
        return dict(order)
    parameters = getattr(order, "parameters", None)
    if callable(parameters):
        return dict(parameters())
    raise RouterBingXClientError(
        f"{TRANSPORT_CODE}: an order must be a mapping of the venue's "
        f"parameters or carry a callable parameters(), got {order!r} "
        f"({type(order).__name__}); the client sends the fields it is given "
        "and does not invent them"
    )


@dataclass(frozen=True, repr=False)
class BingXClient:
    """A signed client for the BingX VST perpetual swap venue, and only it.

    Built with credentials, an optional injected ``transport`` and an optional
    ``clock`` (for tests that must pin the signed ``timestamp``).  The
    ``base_url`` defaults to :data:`VST_BASE_URL`; the host guard reads
    :data:`VST_HOST` out of it on every request, so a client built against any
    other host — :data:`LIVE_HOST` included — refuses before the transport is
    reached.

    Every endpoint method answers the envelope's ``data`` field on success.
    A non-zero ``code`` is raised as :class:`RouterBingXRefusedError` carrying
    the code and message; HTTP 429 is raised as
    :class:`~router.errors.RouterRateLimitedError` carrying a well-formed
    refusal reading; a body that is not the envelope is
    :class:`RouterBingXResponseError`; and a transport failure is
    :class:`RouterBingXTransportError`.
    """

    api_key: str = field(default=None, repr=False)
    secret_key: str = field(default=None, repr=False)
    transport: Any = field(default=None, repr=False)
    base_url: str = VST_BASE_URL
    recv_window: int = RECV_WINDOW_MILLISECONDS
    #: Deliberately not keyword-visible in ``repr``: a callable is noise, and
    #: the two credentials above are the values that must never be rendered.
    clock: Callable[[], int] = field(default=_system_clock_millis, repr=False)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "api_key", _require_credential(self.api_key, API_KEY_ENV)
        )
        object.__setattr__(
            self, "secret_key", _require_credential(self.secret_key, SECRET_KEY_ENV)
        )
        if not isinstance(self.base_url, str) or not self.base_url.strip():
            raise RouterBingXClientError(
                f"{LIVE_HOST_REFUSED_CODE}: base_url must be a non-empty URL, "
                f"got {self.base_url!r}; the client builds every request under "
                f"{VST_HOST!r} and a blank base names no host at all"
            )
        if not callable(self.clock):
            raise RouterBingXClientError(
                f"{TRANSPORT_CODE}: clock must be callable returning whole "
                f"milliseconds, got {self.clock!r} ({type(self.clock).__name__})"
            )
        if self.transport is None:
            object.__setattr__(self, "transport", make_urllib_transport(self.timeout))
        elif not callable(self.transport):
            raise RouterBingXClientError(
                f"{TRANSPORT_CODE}: transport must be callable as "
                f"(method, url, headers, body) -> (status, body), got "
                f"{self.transport!r} ({type(self.transport).__name__})"
            )

    def __repr__(self) -> str:
        # The one place a client can be printed, and the reason this class
        # overrides the dataclass: neither credential may appear here, and a
        # generated repr would print both.
        return (
            f"BingXClient(base_url={self.base_url!r}, "
            f"api_key=<redacted {API_KEY_ENV}>, "
            f"secret_key=<redacted {SECRET_KEY_ENV}>)"
        )

    # -- Construction ---------------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        transport: Any = None,
        base_url: str = VST_BASE_URL,
        recv_window: int = RECV_WINDOW_MILLISECONDS,
        clock: Callable[[], int] = _system_clock_millis,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> BingXClient:
        """Build a client from ``BINGX_VST_API_KEY`` and ``BINGX_VST_SECRET_KEY``.

        The two names are read from ``env`` (the process environment by
        default) and a missing or empty one refuses with
        :class:`RouterVSTCredentialsMissingError` naming the *variable* — never
        its value.  There is deliberately no ``base_url`` environment variable
        and no host parameter read from ``env``: the host is not configurable.
        """
        source = env if env is not None else _environ()
        return cls(
            api_key=source.get(API_KEY_ENV),
            secret_key=source.get(SECRET_KEY_ENV),
            transport=transport,
            base_url=base_url,
            recv_window=recv_window,
            clock=clock,
            timeout=timeout,
        )

    # -- Signing --------------------------------------------------------------

    def sign(
        self,
        parameters: Mapping[str, Any] | None = None,
        *,
        timestamp: int | None = None,
    ) -> tuple[str, str]:
        """Return ``(query_string, signature_hex)`` for ``parameters``.

        Feature 1's first clause, as one function: ``timestamp`` (whole
        milliseconds, from the injected clock unless stated) and ``recvWindow``
        are merged into ``parameters``, the whole set is sorted by key and
        URL-encoded, and the HMAC-SHA256 hex of that string keyed by the
        secret is returned with it.  Exposed so a caller — and this module's
        own test — can recompute the signature independently rather than
        trust the request path to have done it.

        The secret is used as key material and never returned, and neither the
        key nor the secret appears in the returned string.
        """
        merged: dict[str, Any] = dict(parameters or {})
        merged["timestamp"] = str(
            self.clock() if timestamp is None else timestamp
        )
        merged["recvWindow"] = str(self.recv_window)
        query = urllib.parse.urlencode(sorted(merged.items()))
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return query, signature

    # -- The request path -----------------------------------------------------

    def _guard(self, url: str) -> str:
        """Refuse any URL whose host is not the VST venue — before any send.

        The guard is the whole of *"the only host the client can reach"*: it
        runs on the assembled URL and raises :class:`RouterLiveHostError`
        before :meth:`_send` is reached, so a refused address opens no socket.
        """
        host = urllib.parse.urlsplit(url).hostname
        if host != VST_HOST:
            raise RouterLiveHostError(host)
        return url

    def _absolute(self, path: str) -> str:
        """The absolute URL for a relative endpoint ``path``, host-guarded."""
        return self._guard(f"{self.base_url.rstrip('/')}{path}")

    def _signed_target(
        self, method: str, path: str, parameters: Mapping[str, Any]
    ) -> tuple[str, dict[str, str], bytes]:
        """Assemble the signed URL, headers and body for a request.

        A ``POST`` is the one method BingX reads from a form body, so its
        parameters ride there.  Every other method — ``GET`` and ``DELETE``
        alike — carries the parameters in the query string and sends no body,
        because BingX reads a ``DELETE``'s parameters from the query string
        only: a DELETE whose signed string rode in an
        ``x-www-form-urlencoded`` body was refused with code 109400, *"timestamp:
        This field is required. symbol: This field is required."* (the live
        capture ``cancel_order_body_params_refused.json``), while the same call
        with the string in the URL answered code 0 (``cancel_order_ok.json``).

        In every case the payload is the *same* sorted, encoded string the
        signature was computed over, with ``signature=<hex>`` appended, and
        carries the key in the ``X-BX-APIKEY`` header.
        """
        query, signature = self.sign(parameters)
        payload = f"{query}&signature={signature}" if query else f"signature={signature}"
        headers = {"X-BX-APIKEY": self.api_key}
        if method != "POST":
            return self._absolute(f"{path}?{payload}"), headers, b""
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        return self._absolute(path), headers, payload.encode("ascii")

    def _public_target(
        self, method: str, path: str, parameters: Mapping[str, Any] | None
    ) -> tuple[str, dict[str, str], bytes]:
        """Assemble an unsigned request — public market data carries no key."""
        url = self._absolute(path)
        if parameters:
            url = f"{url}?{urllib.parse.urlencode(sorted(parameters.items()))}"
        return url, {}, b""

    def _send(
        self, method: str, url: str, headers: dict[str, str], body: bytes
    ) -> tuple[int, bytes]:
        """Hand the request to the transport, translating a failure.

        The transport is called exactly once, and any exception it raises that
        is not already a router error becomes
        :class:`RouterBingXTransportError` — carrying whether the outcome is
        unknown, which is ``True`` for a write (the venue may or may not have
        acted) and ``False`` for a read.
        """
        try:
            answer = self.transport(method, url, headers, body)
        except RouterError:
            raise
        except Exception as exc:  # transport failure vocabulary
            raise RouterBingXTransportError(
                method,
                url,
                f"{type(exc).__name__}: {exc}",
                outcome_unknown=method != "GET",
            ) from exc
        return _normalize_response(answer)

    def _interpret(self, status: int, raw: bytes, operation: str) -> Any:
        """Turn a raw response into the envelope's ``data``, or refuse.

        429 is feature 1's rate-limit refusal; a body that is not the envelope
        is this module's response fault; a non-zero ``code`` is the venue's own
        ``bingx_refused``; ``code`` zero returns ``data``.
        """
        if status == 429:
            raise _rate_limited(operation)
        decoded = _decode_envelope(status, raw)
        if decoded is None:
            raise RouterBingXResponseError(
                status, "the body was not JSON or was not an object"
            )
        if "code" not in decoded:
            raise RouterBingXResponseError(
                status, "the object carried no 'code' field"
            )
        code = decoded["code"]
        if _is_zero_code(code):
            return decoded.get("data")
        raise RouterBingXRefusedError(code, str(decoded.get("msg", "")))

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        parameters: Mapping[str, Any] | None = None,
        signed: bool = True,
    ) -> Any:
        """The one door every endpoint goes through."""
        if signed:
            url, headers, body = self._signed_target(method, path, parameters or {})
        else:
            url, headers, body = self._public_target(method, path, parameters)
        status, raw = self._send(method, url, headers, body)
        return self._interpret(status, raw, operation)

    # -- The nine endpoints ---------------------------------------------------

    def server_time(self) -> int:
        """GET the venue's server time as whole milliseconds since the epoch.

        Feature 1's first exposed read; feature 2's ``clock_skew`` check is its
        caller.  The venue answers ``{"serverTime": <ms>}``; this returns that
        integer, and the public endpoint carries no signature and no key.
        """
        data = self._request(
            "GET", SERVER_TIME_PATH, operation=OPERATION_ACCOUNT, signed=False
        )
        if not isinstance(data, Mapping) or "serverTime" not in data:
            raise RouterBingXResponseError(
                200, "the server-time payload carried no 'serverTime' field"
            )
        try:
            return int(data["serverTime"])
        except (TypeError, ValueError) as exc:
            raise RouterBingXResponseError(
                200, f"'serverTime' {data['serverTime']!r} is not a whole number"
            ) from exc

    def contracts(self) -> Any:
        """GET the venue's swap contracts document (public, unsigned)."""
        return self._request(
            "GET", CONTRACTS_PATH, operation=OPERATION_ACCOUNT, signed=False
        )

    def premium_index(self) -> Any:
        """GET the venue's premiumIndex (mark price) document (public, unsigned)."""
        return self._request(
            "GET", PREMIUM_INDEX_PATH, operation=OPERATION_ACCOUNT, signed=False
        )

    def depth(self, symbol: str) -> Any:
        """GET one symbol's order book (public, unsigned).

        The mirror's passive repricing reads this just before placing: a
        PostOnly order rests only on its own side of the book — a BUY at the
        best bid, a SELL at the best ask — while the mark can sit on the far
        side and cross.  The venue answers ``data`` as a mapping with
        ``bids`` and ``asks`` arrays of ``[price, quantity]`` string pairs;
        the caller judges the sides.  ``symbol`` passes through exactly as
        ``positions`` spells it, the venue's own refusal covering a name it
        does not know.
        """
        return self._request(
            "GET",
            DEPTH_PATH,
            operation=OPERATION_ACCOUNT,
            parameters={"symbol": symbol},
            signed=False,
        )

    def balance(self) -> Any:
        """GET the account balance — the ``data`` envelope, signed."""
        return self._request("GET", BALANCE_PATH, operation=OPERATION_ACCOUNT)

    def positions(self, symbol: str | None = None) -> Any:
        """GET the account's positions, optionally narrowed to one ``symbol``."""
        parameters = {"symbol": symbol} if symbol is not None else None
        return self._request(
            "GET", POSITIONS_PATH, operation=OPERATION_ACCOUNT, parameters=parameters
        )

    def position_mode(self) -> bool:
        """GET the account's position mode — the boolean ``dualSidePosition``.

        Signed, host-guarded and envelope-read exactly like every other
        account read, because the answer names this account's own
        arrangement.  The venue spells the fact as the strings
        ``"true"``/``"false"`` (the live captures the smoke test took);
        a JSON boolean is the same fact's other spelling and reads the
        same.  Anything else is a response fault rather than a mode
        guessed at — the preflight's hedge refusal stands on this
        boolean, and a value this cannot judge must not pass for
        one-way.
        """
        data = self._request(
            "GET", POSITION_MODE_PATH, operation=OPERATION_ACCOUNT
        )
        if not isinstance(data, Mapping) or "dualSidePosition" not in data:
            raise RouterBingXResponseError(
                200, "the position-mode payload carried no 'dualSidePosition' field"
            )
        return _dual_side_position(data["dualSidePosition"])

    def set_margin_type(
        self,
        symbol: str,
        margin_type: str = BINGX_MARGIN_TYPE_ISOLATED,
    ) -> Any:
        """POST ``symbol``'s margin mode — ``ISOLATED`` by default.

        A venue that answers *already set* with a non-zero code raises
        :class:`RouterBingXRefusedError`; feature 2's preflight decides whether
        that specific code counts as success, because only it knows the repair
        the operator would make.
        """
        return self._request(
            "POST",
            MARGIN_TYPE_PATH,
            operation=OPERATION_ACCOUNT,
            parameters={"symbol": symbol, "marginType": margin_type},
        )

    def set_leverage(
        self,
        symbol: str,
        leverage: int = 1,
        *,
        side: str = BINGX_POSITION_SIDE_BOTH,
    ) -> Any:
        """POST ``symbol``'s leverage — one, one-way (``side`` ``BOTH``)."""
        return self._request(
            "POST",
            LEVERAGE_PATH,
            operation=OPERATION_ACCOUNT,
            parameters={
                "symbol": symbol,
                "side": side,
                "leverage": str(leverage),
            },
        )

    def place_order(self, order: Any) -> Any:
        """POST a new order and return the venue's ``data``.

        ``order`` is a :class:`~router.bingx_order.BingXOrder` — whose
        parameters are already in the venue's own field spellings and whose
        ``clientOrderID`` is already the 40-character projection — or a
        mapping of the same fields.  A transport failure on this write is a
        :class:`RouterBingXTransportError` with ``outcome_unknown`` true, which
        is the case feature 4's mirror answers by querying before re-posting.
        """
        parameters = _order_parameters(order)
        return self._request(
            "POST", ORDER_PATH, operation=OPERATION_PLACE_ORDER, parameters=parameters
        )

    def query_order(
        self, client_order_id: str, *, symbol: str | None = None
    ) -> Any:
        """GET an order by ``clientOrderID`` and return the venue's ``data``.

        Feature 3's read-back is the caller.  An order the venue holds no
        record of answers a non-zero code and raises
        :class:`RouterBingXRefusedError` whose :attr:`~RouterBingXRefusedError.code`
        feature 3 compares against :data:`ORDER_NOT_FOUND_CODE` to report a
        ``not_found`` status.
        """
        parameters: dict[str, Any] = {
            "clientOrderID": _require_order_id(client_order_id)
        }
        if symbol is not None:
            parameters["symbol"] = symbol
        return self._request(
            "GET", ORDER_PATH, operation=OPERATION_QUERY_ORDER, parameters=parameters
        )

    def cancel_order(
        self, client_order_id: str, *, symbol: str | None = None
    ) -> Any:
        """DELETE an order by ``clientOrderID`` and return the venue's ``data``."""
        parameters: dict[str, Any] = {
            "clientOrderID": _require_order_id(client_order_id)
        }
        if symbol is not None:
            parameters["symbol"] = symbol
        return self._request(
            "DELETE",
            ORDER_PATH,
            operation=OPERATION_CANCEL_ORDER,
            parameters=parameters,
        )

    def open_orders(self, symbol: str | None = None) -> Any:
        """GET the account's open orders, optionally narrowed to one ``symbol``."""
        parameters = {"symbol": symbol} if symbol is not None else None
        return self._request(
            "GET", OPEN_ORDERS_PATH, operation=OPERATION_OPEN_ORDERS, parameters=parameters
        )


# -- Helpers ------------------------------------------------------------------


def _environ() -> Mapping[str, str]:
    """The process environment, imported lazily so a test can monkeypatch it."""
    import os

    return os.environ


def _require_order_id(value: Any) -> str:
    """The venue field payload, refused if it is not a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise RouterBingXClientError(
            f"{TRANSPORT_CODE}: clientOrderID must be non-empty text, got "
            f"{value!r} ({type(value).__name__}); the venue looks an order up "
            "by this field, so a blank value names no order"
        )
    return value.strip()


def _dual_side_position(value: Any) -> bool:
    """The venue's ``dualSidePosition`` as a boolean, or a response fault.

    The live captures spell the fact as the strings ``"true"`` and
    ``"false"`` (``fixtures/bingx_vst/live/position_mode_*.json``); a
    JSON boolean is the same fact's other spelling.  Nothing else is
    read, and no truthiness is guessed at — the preflight's hedge-mode
    refusal stands on the venue's own words, so an answer this cannot
    judge must not pass for one-way (nor refuse as hedge on a value the
    account never sent).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise RouterBingXResponseError(
        200,
        f"'dualSidePosition' {value!r} is neither of the spellings the "
        "venue's position-mode document answers",
    )


def _normalize_response(answer: Any) -> tuple[int, bytes]:
    """Coerce whatever a transport returned into ``(status, body)``.

    The contract is a two-tuple ``(status, body)``; a mapping with ``status``
    and ``body`` keys, or an object carrying those attributes, is accepted too
    so a recorder in a test can return whichever is convenient.
    """
    if isinstance(answer, (tuple, list)) and len(answer) == 2:
        status, body = answer
    elif isinstance(answer, Mapping) and "status" in answer and "body" in answer:
        status, body = answer["status"], answer["body"]
    elif hasattr(answer, "status") and hasattr(answer, "body"):
        status, body = answer.status, answer.body
    else:
        raise RouterBingXResponseError(
            -1,
            f"the transport returned {answer!r} ({type(answer).__name__}); a "
            "transport answers (status, body)",
        )
    return int(status), _as_bytes(body)


def _as_bytes(body: Any) -> bytes:
    """A response body as bytes, whatever text-or-bytes shape the transport used."""
    if isinstance(body, bytes):
        return body
    if isinstance(body, str):
        return body.encode("utf-8")
    if body is None:
        return b""
    return bytes(body)


def _decode_envelope(status: int, raw: bytes) -> dict | None:
    """Decode a response body as the venue's JSON envelope, or ``None``.

    ``None`` means *not the envelope*: unreadable JSON, or JSON that is not an
    object.  It deliberately does not mean *code zero* — an object with a
    non-zero code is the venue refusing, which is a different fact.
    """
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _is_zero_code(code: Any) -> bool:
    """Whether the venue's ``code`` is its success value, ``0`` or ``"0"``.

    Feature 1's clause is exact — *"A response whose code is not 0"* — so only
    the integer ``0`` and its string spelling are success.  Anything else,
    including an unparseable string, a ``bool``, ``null`` or a missing field,
    is *not* zero and is refused as :class:`RouterBingXRefusedError` carrying
    whatever the venue sent.  Treating a garbled code as success would let a
    malformed answer pass for an accepted order.
    """
    if isinstance(code, bool):
        return False
    if isinstance(code, int):
        return code == 0
    if isinstance(code, str):
        return code.strip() == "0"
    return False


def _rate_limited(operation: str) -> RouterRateLimitedError:
    """A refusal reading for an HTTP 429, well-formed enough for feature 319.

    The venue stated the refusal, so no weight was spent out of a local bucket
    — but :class:`~router.errors.RouterRateLimitedError` *carries* a
    :class:`~router.limiter.RateLimitHeadroom`, and feature 319's backoff reads
    the wait off it.  The reading is built from :data:`VST_WEIGHT_SCHEDULE`: a
    bucket holding one unit less than the request's weight, so ``deficit`` is
    one weight unit and ``retry_after`` is that unit's refill interval — a
    conservative floor for the retry to wake above.
    """
    weight = VST_WEIGHT_SCHEDULE.weight_for(operation)
    accrued = weight - 1
    reading = RateLimitHeadroom(
        scope=DEFAULT_WEIGHT_SCOPE,
        operation=operation,
        weight=weight,
        allowed=False,
        remaining=accrued,
        capacity=VST_WEIGHT_SCHEDULE.allowance,
        accrued=accrued,
        observed_at=datetime.now(UTC),
        schedule=VST_WEIGHT_SCHEDULE,
    )
    return RouterRateLimitedError(
        "rate_limited: the venue answered HTTP 429 for "
        f"{operation!r}; the request was refused by the venue's own budget, "
        f"and {reading.retry_after} brings the weight it needs back "
        "(feature 318)",
        headroom=reading,
    )
