"""The one door a live model call leaves the machine through.

The provider interface of feature 192 is a contract with no transport: a
caller hands it a :class:`~providers.Request` and gets a
:class:`~providers.Completion`, and nothing in :mod:`providers` says how the
bytes travel.  This module is the *how*.  Every live backend the live-providers
addition introduces — the Anthropic Messages backend of
:mod:`providers._anthropic`, the OpenAI-compatible backend of
:mod:`providers._openai_compat` — posts its one JSON request through
:func:`post_json` and reads its decoded JSON object back, so the four things a
deployment must be able to hold true of *every* live call are decided once,
here, rather than re-decided (and re-forgotten) per vendor:

* **The host guard.**  A request is sent only to a host the deployment named
  in ``allowed_hosts``, and only over https — the one exception is a loopback
  host, so a self-hosted vLLM on ``http://localhost`` is a deployment the door
  can serve.  The refusal is :class:`ProviderHostRefusedError` and it fires
  *before anything is sent*: the guard runs ahead of the first transport call,
  so a mis-declared base URL cannot so much as open a socket.  An allowlist
  rather than a denylist because the failure it guards is egress to a host no
  human ever declared — the value in the guard is that the deployment's list
  is the whole truth of where keys may travel.

* **The retry policy.**  Status 429 (the vendor's own rate limit), 500, 502
  and 503 (a proxy or a vendor restarting) and 529 (Anthropic's
  overloaded-error, the addition's one non-standard code) are transient in
  the sense that the same request may well be answered a second later, and so
  is a timeout or a dropped connection; the door re-sends up to
  ``max_attempts`` times and waits between sends.  The wait is the vendor's
  own ``retry-after`` in seconds when it sends one — the vendor knows its own
  congestion better than any schedule of ours — and otherwise the exponential
  ladder 1, 2, 4 s plus additive jitter drawn from an injectable random, so a
  deployment's agents that all failed together do not all retry together.
  Every other failure is not transient: another 4xx is the *request* being
  refused (a bad model name, a bad key, a malformed body) and re-sending it
  would be the same refusal with more noise, so it raises at once.

* **The failure vocabulary.**  A refusal that survives the retries is one of
  two words, and the two are different repairs:
  :class:`ProviderTransportError` for a timeout or a connection that never
  completed — the network, not the vendor, and the repair is to try again
  later or fix the egress — and :class:`ProviderHTTPError` for a status the
  vendor itself returned, carrying that status and the vendor's own error
  message, because "401 from Anthropic: invalid x-api-key" and "connection
  refused" are facts an operator acts on differently.  A 2xx whose body is
  not a JSON object is neither: it is a malformed answer to a call that
  succeeded, and it leaves as :class:`CompletionMalformedError` — the
  interface's existing word for a provider that answered something other
  than the contract's shape.

* **Secret scrubbing.**  A live call carries a credential in a header —
  ``x-api-key`` for Anthropic, ``authorization`` for the OpenAI-compatible
  family, ``x-goog-api-key`` for Google — and a credential that traveled into
  an exception message, a repr or a log line is a credential that traveled
  into a bug report.  Every message, repr and log line this module produces
  renders those headers as ``***`` (and, as the belt under the braces,
  replaces the literal secret value wherever it has crept into a rendered
  text), while the bytes on the wire of course carry the real key: scrubbing
  is a property of *rendering*, never of sending.

Testability is the transport parameter.  The default transport is
``urllib.request`` — stdlib, as this member is stdlib-only by declaration —
but a test injects a callable ``(url, headers, body_bytes, timeout) ->
(status, response_headers, body_bytes)`` and no test of this door, or of any
backend built on it, opens a socket.  ``sleep`` and the jitter's ``random``
are injectable for the same reason: a suite asserts the ladder 1, 2, 4 s
rather than waiting through it.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Final

from ._errors import CompletionMalformedError, ProviderError

__all__ = [
    "HOST_REFUSED_CODE",
    "PROVIDER_HTTP_CODE",
    "PROVIDER_TRANSPORT_CODE",
    "RETRYABLE_STATUSES",
    "SECRET_HEADER_NAMES",
    "ProviderHTTPError",
    "ProviderHostRefusedError",
    "ProviderTransportError",
    "Transport",
    "post_json",
]

#: The door's own logger.  Every line it emits is scrubbed — the request's
#: headers are logged only in their ``***`` form — because a log line is one
#: of the three places a credential must never reach (the other two are
#: exception messages and reprs), and the one a developer reads first.
log = logging.getLogger("providers.live_http")

#: The header names whose values are credentials, lowercased for
#: case-insensitive matching.  One set for the three vendor families this
#: addition serves: ``x-api-key`` (Anthropic), ``authorization`` (the
#: OpenAI-compatible family, as a bearer token) and ``x-goog-api-key``
#: (Google's Gemini).  A name rather than a pattern, because secret-bearing
#: headers are a closed set the wire formats themselves define — and a
#: pattern that guessed would either miss a header or scrub a benign one.
SECRET_HEADER_NAMES: Final[frozenset[str]] = frozenset(
    {"x-api-key", "authorization", "x-goog-api-key"}
)

#: The statuses the door retries, and the only ones.  429 is the vendor's own
#: rate limit (Anthropic and OpenAI both send it with a ``retry-after``);
#: 500, 502 and 503 are a vendor or a proxy in front of it restarting; 529 is
#: Anthropic's overloaded-error, the one non-standard code the addition's
#: backends meet in practice and the reason this is a set rather than "5xx".
#: Everything else — the whole 4xx family and the unlisted 5xx — says
#: something true about the request or the vendor that re-sending cannot
#: change, and is refused at once.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 529})

#: The greppable word that opens every :class:`ProviderHostRefusedError`
#: message: ``host_refused``.  An operator greps one word for *a live call
#: tried to leave the machine for a host the deployment never declared* — an
#: egress event, worth its own token the way ``fixture_missing`` is worth
#: one — and finds the guard's refusal whichever half fired: the host is not
#: in the allowlist, or the scheme is not https on a non-loopback host.
HOST_REFUSED_CODE: Final[str] = "host_refused"

#: The greppable word that opens every :class:`ProviderTransportError`
#: message: ``provider_transport``.  Names the layer that failed — the
#: transport, not the vendor and not the contract — so an operator reading a
#: log tells "the network never delivered this" apart from ``provider_http``'s
#: "the vendor answered no" with one grep, and the two repairs (check egress
#: and retry, versus read the vendor's status) stay distinguishable.
PROVIDER_TRANSPORT_CODE: Final[str] = "provider_transport"

#: The greppable word that opens every :class:`ProviderHTTPError` message:
#: ``provider_http``.  The message that follows carries the status and the
#: vendor's own error text, so the word an operator greps lands on the fact
#: they act on — *which vendor, which status, in the vendor's own words*.
PROVIDER_HTTP_CODE: Final[str] = "provider_http"

#: The transport's shape, as one name the backends and the tests share: a
#: callable taking the URL, the request headers, the serialized JSON body and
#: the per-attempt timeout, and answering the status, the response headers
#: and the raw response body.  The default is :func:`_urllib_transport`; a
#: test injects a callable of this shape and nothing it does opens a socket —
#: which is how the whole live-providers addition stays testable offline.
Transport = Callable[[str, Mapping[str, str], bytes, float], "tuple[int, Any, bytes]"]

#: What the retry loop treats as "the network, not the vendor":
#: :class:`OSError` — which is ``urllib``'s :class:`~urllib.error.URLError`
#: and every ``ConnectionError``/``TimeoutError`` it wraps, they are all
#: OSError subclasses — plus :class:`http.client.HTTPException` for a peer
#: that answered something that never became an HTTP message.  Nothing else
#: is caught: a ``TypeError`` out of a transport is a bug in the transport,
#: and papering over it with a retry would hide it.
_TRANSPORT_FAILURES: Final[tuple[type[BaseException], ...]] = (
    OSError,
    http.client.HTTPException,
)


class ProviderHostRefusedError(ProviderError):
    """A live call tried to leave for a host the deployment never declared.

    The guard's refusal, raised *before anything is sent*: the URL's host is
    not in the ``allowed_hosts`` the caller handed :func:`post_json`, or the
    scheme is not https on a host that is not loopback.  Both are the same
    finding — the destination was never a place the deployment said a model
    call may go — so both wear this one class and :data:`HOST_REFUSED_CODE`
    rather than minting a second word for the scheme half; an operator's
    repair is the same too, and it is to the *configuration* (the allowlist,
    the base URL), never to the network.

    A :class:`~providers.ProviderError` rather than a new base, on the split
    the member's other transport-adjacent refusals already take: a caller
    that catches the interface's base with one ``except`` is catching "the
    provider could not complete this call", and a call the door refused to
    send is exactly that — while the *distinction* an operator needs is
    carried by the code word, not by a second inheritance tree.

    Distinct from :class:`ProviderTransportError` because a refused host is
    not a network failure: nothing was sent, so there is nothing to retry and
    no egress to check.  The refusal names the host and the allowlist, the
    two facts the repair needs.
    """

    def __init__(self, message: str) -> None:
        # The code word is prefixed by the constructor rather than by each
        # raise site, so the token and the type are one edit and cannot drift
        # apart — the discipline FIXTURE_MISSING_CODE established in
        # _recorded_errors and every code word in this member follows.
        super().__init__(f"{HOST_REFUSED_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`HOST_REFUSED_CODE`."""
        return HOST_REFUSED_CODE


class ProviderTransportError(ProviderError):
    """The transport never delivered an answer: a timeout or a dropped connection.

    The network's refusal, survived the retries: every attempt timed out or
    the connection dropped, and the door gave up after ``max_attempts``.  The
    message names the URL, which failure kind it was, how many attempts were
    made and the timeout each was given — the facts a retry-later or an
    egress check needs — and carries the underlying exception as its cause
    for the traceback that wants it.

    Distinct from :class:`ProviderHTTPError` because "the vendor never
    answered" and "the vendor answered no" have different repairs: the first
    is the network's to fix (or time's), the second is a status to read.  And
    distinct from :class:`ProviderHostRefusedError` because this failure sent
    bytes and lost them, where a refused host sent nothing at all.
    """

    def __init__(self, message: str) -> None:
        super().__init__(f"{PROVIDER_TRANSPORT_CODE}: {message}")

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`PROVIDER_TRANSPORT_CODE`."""
        return PROVIDER_TRANSPORT_CODE


class ProviderHTTPError(ProviderError):
    """The vendor itself answered a status this call does not survive.

    Carries the status on ``.status`` and the vendor's own error message on
    ``.detail`` — the two facts the caller reads — because "401 from
    Anthropic: invalid x-api-key" is an actionable sentence only with both:
    the status says which kind of refusal it was, and the text is the vendor
    saying it in its own words.  Raised in the two ways the retry policy
    ends here: every status of :data:`RETRYABLE_STATUSES` was retried and
    still answers (the message names the attempt count), or a status outside
    that set — the request-refusing 4xx family, an unlisted 5xx — answered
    once and was refused at once, because re-sending a request the vendor
    refused for its own sake would be the same refusal with more noise.

    Distinct from :class:`ProviderTransportError` on the repair's side of the
    split, and from :class:`CompletionMalformedError` because a status answer
    is not a malformed *completion*: the call did not succeed and come back
    wrong, it was refused.
    """

    def __init__(self, message: str, *, status: int, detail: str = "") -> None:
        super().__init__(f"{PROVIDER_HTTP_CODE}: {message}")
        #: The HTTP status the vendor answered, as an int — the fact a caller
        #: branches on, so no caller parses it out of the message.
        self.status = status
        #: The vendor's own error message, read out of the error body
        #: (``error.message`` for both vendor shapes this addition serves),
        #: or the honest fallback when the body said nothing readable.
        self.detail = detail

    @property
    def code(self) -> str:
        """The refusal's greppable code — :data:`PROVIDER_HTTP_CODE`."""
        return PROVIDER_HTTP_CODE


def post_json(
    url: str,
    headers: Mapping[str, str],
    body: object,
    *,
    allowed_hosts: Iterable[str],
    timeout: float = 120.0,
    max_attempts: int = 4,
    transport: Transport | None = None,
    sleep: Callable[[float], object] = time.sleep,
    random: Callable[[], float] = random.random,
) -> dict[str, Any]:
    """Post one JSON request to a model vendor and answer the decoded JSON object.

    The one door: serialize ``body`` once, send it to ``url`` behind the host
    guard, retry what is transient, and answer the vendor's JSON object — or
    refuse with the vocabulary above.  Every live backend of the
    live-providers addition posts through here, so a deployment that holds
    four things true of one live call holds them true of all of them.

    ``headers`` travels to the transport verbatim — the vendor needs the real
    credential — while every message, repr and log line this function emits
    renders the secret-named headers as ``***``; see
    :data:`SECRET_HEADER_NAMES`.

    ``transport`` defaults to :func:`_urllib_transport` (``urllib.request``,
    because the member is stdlib-only); a test injects a callable of
    :data:`Transport`'s shape and opens no socket.  ``sleep`` and ``random``
    are injectable the same way: the retry waits are the vendor's
    ``retry-after`` when present, otherwise the exponential ladder 1, 2, 4 s
    plus additive jitter from ``random()``.

    Raises :class:`ProviderHostRefusedError` before anything is sent when the
    URL's host is not in ``allowed_hosts`` or the scheme is not https on a
    non-loopback host; :class:`ProviderTransportError` when every attempt
    timed out or dropped; :class:`ProviderHTTPError` — carrying the status on
    ``.status`` and the vendor's own message on ``.detail`` — when a
    retryable status survived ``max_attempts`` attempts or any other status
    was answered; and :class:`CompletionMalformedError` when a 2xx body is
    not a JSON object.
    """
    if max_attempts < 1:
        raise ValueError(
            f"max_attempts must be at least 1, got {max_attempts!r}. The door "
            "sends at least once — an attempt budget of zero is no call at all."
        )
    _guard_host_and_scheme(url, allowed_hosts)
    request_headers = dict(headers)
    body_bytes = json.dumps(body).encode("utf-8")
    send: Transport = _urllib_transport if transport is None else transport
    log.debug(
        "POST %s: sending %d JSON bytes with headers %r",
        url,
        len(body_bytes),
        _scrubbed_headers(request_headers),
    )
    for attempt in range(1, max_attempts + 1):
        try:
            status, response_headers, response_body = send(
                url, request_headers, body_bytes, timeout
            )
        except _TRANSPORT_FAILURES as error:
            if attempt == max_attempts:
                failure = _transport_error(url, request_headers, max_attempts, timeout, error)
                log.error("POST %s: %s", url, failure)
                raise failure from error
            wait = _wait_seconds(attempt, None, random)
            log.warning(
                "POST %s: attempt %d of %d %s; retrying in %.3f s",
                url,
                attempt,
                max_attempts,
                _transport_kind(error),
                wait,
            )
            sleep(wait)
            continue
        if 200 <= status < 300:
            log.debug(
                "POST %s: answered status %d on attempt %d of %d",
                url,
                status,
                attempt,
                max_attempts,
            )
            return _decode_object(response_body, request_headers)
        if status in RETRYABLE_STATUSES and attempt < max_attempts:
            wait = _wait_seconds(
                attempt,
                _retry_after_seconds(_header_value(response_headers, "retry-after")),
                random,
            )
            log.warning(
                "POST %s: attempt %d of %d answered status %d; retrying in %.3f s",
                url,
                attempt,
                max_attempts,
                status,
                wait,
            )
            sleep(wait)
            continue
        failure = _http_error(url, request_headers, status, response_body, attempt, max_attempts)
        log.error("POST %s: %s", url, failure)
        raise failure
    raise AssertionError(  # pragma: no cover — every branch above returns or raises
        "the retry loop exited without a verdict, which its own structure forbids"
    )


def _urllib_transport(
    url: str, headers: Mapping[str, str], body_bytes: bytes, timeout: float
) -> tuple[int, Any, bytes]:
    """The default transport: one ``urllib.request`` POST, no retries of its own.

    Stdlib, because the member is stdlib-only by declaration — and the door,
    not the transport, owns the retry policy, so this callable answers one
    exchange and leaves the waiting to the loop that called it.  An HTTP
    error status is not an exception here: ``urlopen`` raises
    :class:`~urllib.error.HTTPError` for it, and the door's contract wants it
    as a ``(status, headers, body)`` answer like any other, so the error is
    read (its body carries the vendor's own message) and returned.  Timeouts
    and connection failures do escape, as the OSError family the retry loop
    catches.
    """
    request = urllib.request.Request(
        url, data=body_bytes, headers=dict(headers), method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.headers, response.read()
    except urllib.error.HTTPError as error:
        try:
            response_body = error.read()
        finally:
            error.close()
        return int(error.code), error.headers, response_body


def _guard_host_and_scheme(url: str, allowed_hosts: Iterable[str]) -> None:
    """Refuse a destination the deployment never declared, before anything is sent.

    Two checks, one refusal: the URL's host (lowercased, port stripped — the
    way :func:`urllib.parse.urlsplit` reports it) must be one the caller
    named in ``allowed_hosts``, and the scheme must be https unless the host
    is loopback, so a self-hosted vLLM on ``http://localhost:8000`` is a
    deployment this door serves while ``http`` to any reachable host is not.
    Both checks run before the body is serialized and before the transport is
    so much as resolved, which is what makes the refusal honest when it says
    nothing was sent.
    """
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname
    allowed = {candidate.strip().lower() for candidate in allowed_hosts}
    if not host or host not in allowed:
        error = ProviderHostRefusedError(
            f"POST {url} names host {host!r}, which the deployment's "
            f"allowed_hosts ({sorted(allowed)!r}) does not include. The door "
            "sends nothing to a host the deployment never declared."
        )
        log.error("POST %s: %s", url, error)
        raise error
    scheme = parsed.scheme.lower()
    if scheme != "https" and not _is_loopback(host):
        error = ProviderHostRefusedError(
            f"POST {url} uses scheme {scheme!r}. Only https leaves the "
            f"machine — the one exception is a loopback host, and {host!r} "
            "is not one."
        )
        log.error("POST %s: %s", url, error)
        raise error


def _is_loopback(host: str) -> bool:
    """Whether ``host`` is a loopback destination plaintext may reach.

    ``localhost`` by name, and every loopback address ``ipaddress`` can read
    — 127.0.0.0/8 and ``::1``, so an IPv6 local vLLM is as much a local
    deployment as an IPv4 one.  A name that is neither (a plain hostname, a
    non-loopback address) is not, and plaintext to it stays refused.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _wait_seconds(
    attempt: int, retry_after: float | None, jitter: Callable[[], float]
) -> float:
    """The wait before the attempt after the one that just failed.

    The vendor's ``retry-after`` in seconds when it sent one — verbatim, with
    no jitter on top, because the vendor knows its own congestion and a
    deployment that argued with it would be retrying into the same wall.
    Otherwise the exponential ladder: ``2 ** (attempt - 1)`` seconds — 1, 2,
    4 — plus additive jitter from the injectable ``random``, so callers that
    all failed together do not all retry together.
    """
    if retry_after is not None:
        return retry_after
    return float(2 ** (attempt - 1)) + max(0.0, jitter())


def _retry_after_seconds(value: object) -> float | None:
    """Read a ``retry-after`` header's value as seconds, or answer ``None``.

    ``None`` — never a guess — when the header is absent, unreadable, or an
    HTTP-date rather than a delta (the door's vendors send deltas; a date is
    a clock the door has no view of), so the caller falls back to the
    exponential ladder rather than sleeping on a number it invented.  A
    negative delta clamps to zero: a vendor that answers the past is saying
    *now*, not *backwards*.
    """
    if value is None:
        return None
    try:
        seconds = float(str(value).strip())
    except ValueError:
        return None
    return max(0.0, seconds)


def _header_value(headers: object, name: str) -> str | None:
    """Find ``name`` in ``headers`` case-insensitively, the way HTTP does.

    Header names carry no case on the wire, and the transport's answer may
    be a plain dict a test built (any case), ``urllib``'s
    ``email.message.Message`` (title case), or a pair iterable — so the
    lookup lowercases both sides and asks no mapping for special powers.
    """
    if headers is None:
        return None
    lowered = name.lower()
    pairs = headers.items() if hasattr(headers, "items") else headers
    for key, value in pairs:
        if str(key).lower() == lowered:
            return value
    return None


def _transport_kind(error: BaseException) -> str:
    """Name the failure kind for a message: a timeout, or a dropped connection.

    ``urllib`` wraps its causes in :class:`~urllib.error.URLError`'s
    ``reason``, so the timeout check looks through the wrapper; a bare
    ``TimeoutError`` (an injected transport's, or a socket's) is itself.
    Everything else is a connection that failed, named with its own repr so
    the message a caller reads carries the socket's actual complaint.
    """
    reason = getattr(error, "reason", None)
    if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
        return "timed out"
    if reason is not None:
        return f"could not connect ({reason!r})"
    return f"the connection failed ({error!r})"


def _transport_error(
    url: str,
    request_headers: Mapping[str, str],
    attempts: int,
    timeout: float,
    error: BaseException,
) -> ProviderTransportError:
    """Build the final network refusal, its sentence already scrubbed."""
    return ProviderTransportError(
        _scrub_text(
            f"POST {url} {_transport_kind(error)} after {attempts} "
            f"{_attempts_word(attempts)} (timeout {timeout} s each). The "
            "transport never delivered an answer; this is the network, not "
            "the vendor.",
            request_headers,
        )
    )


def _http_error(
    url: str,
    request_headers: Mapping[str, str],
    status: int,
    response_body: bytes,
    attempt: int,
    max_attempts: int,
) -> ProviderHTTPError:
    """Build the vendor's refusal, carrying its status and its own message.

    The sentence says which of the two endings it was — every retryable
    status survived its attempts, or the status was refused at once because
    re-sending it cannot change what it says — and the vendor's message rides
    on ``.detail`` as well as in the sentence, scrubbed in both: a vendor
    that echoes a credential back in an error body meets the same scrubbing
    on the way into a log as the credential did on the way out of the
    headers.
    """
    detail = _scrub_text(_vendor_error_message(response_body), request_headers)
    if attempt == max_attempts:
        sentence = (
            f"status {status} from POST {url} after {max_attempts} "
            f"{_attempts_word(max_attempts)}: {detail}"
        )
    else:
        sentence = (
            f"status {status} from POST {url} on the first attempt, not "
            f"retried: {detail}"
        )
    return ProviderHTTPError(
        _scrub_text(sentence, request_headers), status=status, detail=detail
    )


def _vendor_error_message(response_body: bytes) -> str:
    """Read the vendor's own error message out of an error body.

    Both vendor shapes this addition serves fold their text the same way —
    Anthropic ``{"type": "error", "error": {"type": ..., "message": ...}}``,
    the OpenAI-compatible family ``{"error": {"message": ..., "type": ...}}``
    — so ``error.message`` is read, then a bare ``error`` string, and when
    the body said neither (or was not JSON at all) the honest fallback is a
    short decoded snippet of the body itself: an operator debugging a status
    wants what the vendor actually wrote, not a paraphrase that dropped it.
    """
    try:
        decoded = json.loads(response_body)
    except ValueError:
        decoded = None
    if isinstance(decoded, dict):
        error = decoded.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message
        elif isinstance(error, str) and error.strip():
            return error
    snippet = response_body[:200].decode("utf-8", "replace").strip()
    return snippet if snippet else "the vendor answered an empty body"


def _decode_object(
    response_body: bytes, request_headers: Mapping[str, str]
) -> dict[str, Any]:
    """Decode a 2xx body as the JSON object the door promises its caller.

    A body that is not a JSON object — not JSON at all, or JSON that is a
    list, a string, a number — is refused as
    :class:`~providers.CompletionMalformedError`, the interface's existing
    word for an answer that did not carry the contract's shape: the call
    succeeded and the answer cannot be read, which is a different fact from
    either refusal above and one the caller must not meet later as an
    ``AttributeError`` on the object it was promised.
    """
    try:
        decoded = json.loads(response_body)
    except ValueError as error:
        raise CompletionMalformedError(
            _scrub_text(
                f"a live answer must be a JSON object, and the body did not "
                f"decode as JSON ({error}). Vendors answer a model call with "
                "one JSON object, and every live backend reads its answer "
                "through this door — a body the door cannot decode is one no "
                "backend can read.",
                request_headers,
            )
        ) from error
    if not isinstance(decoded, dict):
        raise CompletionMalformedError(
            _scrub_text(
                f"a live answer must be a JSON object, got "
                f"{type(decoded).__name__}. The live backends read one shape "
                "— an object — and a JSON document that is a list, a string "
                "or a number is not that shape.",
                request_headers,
            )
        )
    return decoded


def _scrubbed_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Copy ``headers`` with every secret-named value rendered as ``***``.

    The rendering form, for logs: the header *names* stay (which credential
    a call carried is a fact an operator needs) and the *values* go — the
    pair of facts that makes a scrubbed log line still worth reading.
    """
    return {
        name: "***" if name.lower() in SECRET_HEADER_NAMES else value
        for name, value in headers.items()
    }


def _scrub_text(text: str, headers: Mapping[str, str]) -> str:
    """Replace every secret header value found anywhere in ``text``.

    The belt under the braces.  Messages are built from scrubbed parts —
    headers only ever enter a sentence in their ``***`` form — but a
    traceback's cause or a vendor's error body can echo a credential back in
    text this module did not build, so every sentence is passed through here
    before it becomes an exception message: the value the caller actually
    sent is replaced wherever it appears, and a value that appears nowhere
    (the common case) leaves the text untouched.  Empty values are skipped —
    there is nothing to leak, and ``str.replace`` on the empty string would
    decorate every gap between characters.
    """
    for name, value in headers.items():
        if name.lower() not in SECRET_HEADER_NAMES:
            continue
        if isinstance(value, str) and value:
            text = text.replace(value, "***")
    return text


def _attempts_word(count: int) -> str:
    """``attempt`` or ``attempts`` for ``count`` — a message that reads like one."""
    return "attempt" if count == 1 else "attempts"
