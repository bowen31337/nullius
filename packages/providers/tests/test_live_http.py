"""The live HTTP door: one JSON request out, one JSON object back.

Feature 1 of the live-providers addition is the only path a live model call
takes out of the machine, so these tests pin the four properties a deployment
holds true of *every* live call by holding them true of this one door: a host
the deployment never declared is refused before anything is sent; the
transient failures — 429, 500, 502, 503, 529, a timeout, a dropped
connection — are retried on the vendor's own ``retry-after`` or the
exponential ladder, and nothing else is; the final refusal says whether it
was the network (:class:`~providers._live_http.ProviderTransportError`) or
the vendor (:class:`~providers._live_http.ProviderHTTPError`, carrying the
status and the vendor's own message); and a credential never reaches an
exception message, a repr or a log line.

No test here opens a socket.  Every call injects a transport that answers
from a script, a sleep that records instead of waiting, and a jitter source
pinned to zero (or to a value the assertion does arithmetic with), so the
ladder 1, 2, 4 s is *read*, never slept through — the same discipline the
spec's own constraint states as "tests use fake keys and assert the key is
absent from every captured output", which the scrubbing section below drives
through every output the door can produce.
"""

from __future__ import annotations

import email.message
import io
import json
import logging
import traceback
import urllib.error
from pathlib import Path
from typing import Any

import providers._live_http as live_http
import pytest
from providers import CompletionMalformedError, ProviderError
from providers._live_http import (
    HOST_REFUSED_CODE,
    PROVIDER_HTTP_CODE,
    PROVIDER_TRANSPORT_CODE,
    RETRYABLE_STATUSES,
    SECRET_HEADER_NAMES,
    ProviderHostRefusedError,
    ProviderHTTPError,
    ProviderTransportError,
    post_json,
)

# ── The script a test drives the door with ─────────────────────────────────────
#
# One URL, one allowlist, one credential and one body stand in for a
# deployment's live call; the transport and the sleep are per-test spies so a
# test reads both halves of the door's behaviour — what went out, and what
# the door did about what came back.

#: A fake credential, and only a fake one: the constraint is that no API key
#: appears in any repository file, log line or output, and the way a suite
#: proves the *scrubbing* is by sending a key-shaped value it can then hunt
#: for.  The three spellings are the three secret-bearing header names the
#: door knows, so the scrubbing section can drive all of them at once.
FAKE_ANTHROPIC_KEY = "fake-ant-key-not-a-credential"
FAKE_BEARER_TOKEN = "fake-bearer-not-a-credential"
FAKE_GOOG_KEY = "fake-goog-key-not-a-credential"

#: The door's default test drive: an Anthropic-shaped call to the host a
#: deployment would declare for it.
URL = "https://api.anthropic.com/v1/messages"
ALLOWED_HOSTS = ("api.anthropic.com",)


def _headers() -> dict[str, str]:
    """The headers a live Anthropic call carries, with a fake credential."""
    return {
        "content-type": "application/json",
        "x-api-key": FAKE_ANTHROPIC_KEY,
        "anthropic-version": "2023-06-01",
    }


def _body() -> dict[str, Any]:
    """A minimal Messages-API request body."""
    return {
        "model": "claude-opus-5",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
    }


def _answer_body() -> dict[str, Any]:
    """A minimal Messages-API success body."""
    return {"content": [{"type": "text", "text": "ok"}], "model": "claude-opus-5"}


def _ok(body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying ``body``."""
    payload = _answer_body() if body is None else body
    return 200, {}, json.dumps(payload).encode("utf-8")


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording every call.

    Each script entry is either a ``(status, headers, body)`` answer or an
    exception instance to raise; when the script runs out the last entry
    repeats, so a one-entry script is "always this" and a suite never writes
    four identical lines to watch four attempts.  The calls list is the door
    seen from outside — the URL, the headers, the body bytes and the timeout
    of every send — which is how these tests assert what left the machine
    without opening a socket.
    """
    calls: list[dict[str, Any]] = []

    def _send(url: str, headers: dict[str, str], body_bytes: bytes, timeout: float):
        calls.append(
            {"url": url, "headers": dict(headers), "body": body_bytes, "timeout": timeout}
        )
        answer = script[min(len(calls), len(script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    _send.calls = calls
    return _send


def _sleep() -> Any:
    """A sleep that records the waits instead of taking them."""
    waits: list[float] = []

    def _sleep(seconds: float) -> None:
        waits.append(seconds)

    _sleep.waits = waits
    return _sleep


def _no_jitter() -> float:
    """The jitter source pinned to zero, so the ladder is asserted exactly.

    1.0, 2.0, 4.0 — not "somewhere above" — because a backoff the suite can
    only bound is a backoff it is not really reading.
    """
    return 0.0


#: The suite's default jitter source, spelled as a name so a drive that
#: overrides it reads as the deliberate arithmetic it is.
NO_JITTER = _no_jitter


def _drive(
    transport: Any,
    *,
    url: str = URL,
    allowed_hosts: Any = ALLOWED_HOSTS,
    headers: dict[str, str] | None = None,
    random: Any = NO_JITTER,
    **kwargs: Any,
) -> tuple[Any, Any]:
    """Call the door with everything injected: no socket, no real wait.

    The defaults every test wants — the fake credential's headers, a
    recording sleep, zero jitter — so a test's own parameters are the part
    it is actually about.  ``max_attempts`` and ``timeout`` pass through as
    keyword arguments untouched, and the recording sleep is handed back with
    the answer so a test reads the waits it never took.
    """
    sleeper = _sleep()
    answered = post_json(
        url,
        _headers() if headers is None else headers,
        _body(),
        allowed_hosts=allowed_hosts,
        transport=transport,
        sleep=sleeper,
        random=random,
        **kwargs,
    )
    return answered, sleeper


# ── The happy path: one JSON request out, one object back ──────────────────────


def test_posts_one_json_request_and_answers_the_decoded_object():
    # The sentence as one call: the door sends the caller's body as JSON to
    # the caller's URL and answers the vendor's JSON object — decoded, so a
    # backend reads fields and never bytes.
    transport = _transport(_ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert len(transport.calls) == 1
    assert sleeper.waits == []


def test_the_transport_receives_the_url_the_timeout_and_the_real_credential():
    # Scrubbing is a property of rendering, never of sending: the vendor on
    # the other end must receive the real credential, or the call cannot be
    # authenticated at all.  What the door promises is where the key does
    # *not* go — messages, reprs, logs — not where it does.
    transport = _transport(_ok())

    _drive(transport, timeout=30.0)

    call = transport.calls[0]
    assert call["url"] == URL
    assert call["timeout"] == 30.0
    assert call["headers"]["x-api-key"] == FAKE_ANTHROPIC_KEY
    assert call["headers"]["anthropic-version"] == "2023-06-01"
    assert json.loads(call["body"]) == _body()


def test_a_non_200_success_status_answers_its_object():
    # The success test is the 2xx class, not the one status: a vendor that
    # answers 201 (or any 2xx) succeeded, and only the *body's* shape decides
    # whether the answer is readable.
    transport = _transport((201, {}, json.dumps({"answer": 1}).encode("utf-8")))

    answered, _ = _drive(transport)

    assert answered == {"answer": 1}


def test_the_same_request_bytes_leave_every_retry():
    # The body is serialized once, before the first send, so every retry
    # carries byte-identical request bytes and the same headers and timeout —
    # a vendor that answered 429 for this request is being re-asked *this*
    # request, not a re-serialization that happens to look like it.
    transport = _transport((503, {}, b"overloaded"), (503, {}, b"overloaded"), _ok())

    _drive(transport)

    assert len(transport.calls) == 3
    first = transport.calls[0]
    assert all(call == first for call in transport.calls[1:])


# ── The host guard: refused before anything is sent ────────────────────────────


def test_a_host_the_deployment_did_not_declare_is_refused_before_anything_is_sent():
    # The allowlist's whole value: a URL whose host no human declared is an
    # egress event, and the refusal precedes the transport — asserted by the
    # spy's empty call list, the strongest form of "nothing was sent".
    transport = _transport(_ok())

    with pytest.raises(ProviderHostRefusedError) as raised:
        _drive(transport, allowed_hosts=("api.openai.com",))

    assert str(raised.value).startswith(f"{HOST_REFUSED_CODE}:")
    assert "api.anthropic.com" in str(raised.value)
    assert transport.calls == []


def test_the_allowlist_matches_case_insensitively_and_ignores_the_port():
    # Hosts are lowercased and ports stripped on both sides — the way DNS and
    # urlsplit already treat them — so a deployment's allowlist is a list of
    # hostnames, never of spellings.
    transport = _transport(_ok())

    answered, _ = _drive(
        transport,
        url="https://API.Anthropic.Com:443/v1/messages",
        allowed_hosts=("api.anthropic.com",),
    )

    assert answered == _answer_body()


def test_an_empty_allowlist_refuses_every_host():
    # A deployment that declares no live hosts has no live calls: the empty
    # allowlist is a closed door, not a default-open one.
    transport = _transport(_ok())

    with pytest.raises(ProviderHostRefusedError):
        _drive(transport, allowed_hosts=())

    assert transport.calls == []


def test_a_url_with_no_host_is_refused():
    # A URL that names no host is not a destination the guard can vouch for,
    # and the guard refuses what it cannot vouch for rather than sending to
    # see what happens.
    transport = _transport(_ok())

    with pytest.raises(ProviderHostRefusedError):
        _drive(transport, url="https:///v1/messages")

    assert transport.calls == []


def test_plain_http_to_a_reachable_host_is_refused():
    # The scheme half of the guard: the host may be declared, but plaintext
    # to it still leaves the machine carrying a credential, so it is refused
    # under the same code word — the finding (an undeclared destination
    # shape) is one finding, not two.
    transport = _transport(_ok())

    with pytest.raises(ProviderHostRefusedError) as raised:
        _drive(transport, url="http://api.anthropic.com/v1/messages")

    assert str(raised.value).startswith(f"{HOST_REFUSED_CODE}:")
    assert transport.calls == []


def test_plain_http_to_localhost_is_allowed():
    # The loopback exception, as the deployment that needs it meets it: a
    # self-hosted vLLM on plaintext localhost is a local process, not an
    # egress, and the door serves it.
    transport = _transport(_ok())

    answered, _ = _drive(
        transport, url="http://localhost:8000/v1/chat/completions", allowed_hosts=("localhost",)
    )

    assert answered == _answer_body()
    assert len(transport.calls) == 1


def test_plain_http_to_a_loopback_address_is_allowed():
    # The exception is for loopback, not for the one spelling of it:
    # 127.0.0.1 is as local as localhost.
    transport = _transport(_ok())

    answered, _ = _drive(
        transport, url="http://127.0.0.1:8000/v1", allowed_hosts=("127.0.0.1",)
    )

    assert answered == _answer_body()


def test_plain_http_to_the_ipv6_loopback_is_allowed():
    # …and so is ::1 — an IPv6 local deployment is not a less first-class
    # one.  urlsplit reports the bracketed host without its brackets.
    transport = _transport(_ok())

    answered, _ = _drive(
        transport, url="http://[::1]:8000/v1", allowed_hosts=("::1",)
    )

    assert answered == _answer_body()


# ── The retry policy: what is transient, and how long it waits ─────────────────


@pytest.mark.parametrize("status", sorted(RETRYABLE_STATUSES))
def test_each_retryable_status_is_retried_until_the_vendor_answers(status):
    # The five statuses the vendors' own operations make transient — the rate
    # limit, the restarts, the overload — each get one more chance, and the
    # call is answered when the vendor comes back.
    transport = _transport((status, {}, b"try later"), _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert len(transport.calls) == 2
    assert sleeper.waits == [1.0]


def test_a_status_outside_the_set_is_not_retried_even_though_it_is_5xx():
    # "5xx" is not the rule; the five statuses are.  A 501 says the vendor
    # does not implement this call, and no number of re-sends implements it.
    transport = _transport((501, {}, b"not implemented"))

    with pytest.raises(ProviderHTTPError):
        _drive(transport)

    assert len(transport.calls) == 1


def test_the_ladder_is_one_two_four_seconds():
    # The exponential backoff as the spec states it: 1, 2, 4 s between four
    # attempts, read off the recording sleep with jitter pinned to zero.
    transport = _transport(*[(503, {}, b"overloaded")] * 3, _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert sleeper.waits == [1.0, 2.0, 4.0]


def test_jitter_is_additive_from_the_injected_random():
    # The ladder plus the injected source's draw, and nothing else: the wait
    # is base + jitter, so a deployment's agents that failed together do not
    # all retry together — and a suite can predict the wait exactly.
    transport = _transport(*[(503, {}, b"overloaded")] * 3, _ok())

    _, sleeper = _drive(transport, random=lambda: 0.25)

    assert sleeper.waits == [1.25, 2.25, 4.25]


def test_the_vendors_retry_after_is_the_wait_verbatim():
    # The vendor's own congestion estimate is honoured exactly: no jitter on
    # top, no rounding — the door does not know better than the vendor when
    # the vendor will be free.  (The one bound is MAX_RETRY_AFTER_SECONDS,
    # read by the ceiling section below; 7 s is well under it.)
    transport = _transport((429, {"retry-after": "7"}, b"rate limited"), _ok())

    _, sleeper = _drive(transport, random=lambda: 99.0)

    assert sleeper.waits == [7.0]


def test_retry_after_is_read_case_insensitively():
    # Header names carry no case on the wire, and the transport's answer may
    # spell the name any way a real server stack does.
    transport = _transport((429, {"Retry-After": "5"}, b"rate limited"), _ok())

    _, sleeper = _drive(transport)

    assert sleeper.waits == [5.0]


def test_a_retry_after_of_zero_waits_zero():
    # A vendor that answers "now" is not answering "1 s": zero is a present
    # retry-after, honoured as written rather than fallen back from.
    transport = _transport((429, {"retry-after": "0"}, b"rate limited"), _ok())

    _, sleeper = _drive(transport)

    assert sleeper.waits == [0.0]


def test_an_unreadable_retry_after_falls_back_to_the_ladder():
    # An HTTP-date or garbage in the header is a value the door cannot honour
    # as seconds; it falls back to the ladder rather than guessing a number.
    transport = _transport(
        (429, {"retry-after": "Fri, 31 Dec 1999 23:59:59 GMT"}, b"rate limited"),
        _ok(),
    )

    _, sleeper = _drive(transport)

    assert sleeper.waits == [1.0]


# ── The retry-after ceiling: a vendor cannot stall the door ────────────────────
#
# A header is a number a vendor — or a proxy, or a gateway, or a hostile
# middlebox — chooses, and the door must not hand that choice a blank cheque:
# one header at 86400 s blocks a model call for a day, "inf" blocks it
# forever (or escapes as a raw OverflowError, outside the provider
# vocabulary), and "1e9" blocks it for thirty-one years.  MAX_RETRY_AFTER_
# SECONDS is the ceiling, and a retry-after at or below it is honoured
# verbatim while one above it is refused at once, as the vendor's own HTTP
# error — the caller decides what to do about "not soon".


def test_the_ceiling_is_a_module_constant_of_sixty_seconds():
    # The bound is a named module constant, not a literal buried in the loop,
    # so a deployment reads the number the door holds and the suite pins it as
    # the value the spec states.
    assert live_http.MAX_RETRY_AFTER_SECONDS == 60.0


def test_a_retry_after_of_a_day_is_refused_at_once_without_sleeping():
    # 86400 s is a vendor saying "not soon": the door sleeps nothing, sends
    # nothing more, and refuses as the vendor's own HTTP error — carrying the
    # status and naming both the value and the ceiling, the two numbers the
    # caller needs to decide.
    transport = _transport((429, {"retry-after": "86400"}, b"{}"), _ok())

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert str(raised.value).startswith(f"{PROVIDER_HTTP_CODE}:")
    assert raised.value.status == 429
    assert "86400" in str(raised.value)
    assert "60" in str(raised.value)
    assert len(transport.calls) == 1


def test_a_retry_after_of_thirty_one_years_is_refused_at_once():
    # 1e9 s — about thirty-one years — is the same finding as a day, only
    # louder; the ceiling catches the magnitude, not one spelling of it.
    transport = _transport((503, {"retry-after": "1e9"}, b"{}"), _ok())

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.status == 503
    assert "1000000000" in str(raised.value)
    assert len(transport.calls) == 1


def test_an_infinite_retry_after_is_refused_as_a_provider_error_not_an_overflow():
    # "inf" is the failure the raw door is worst at: sleep(inf) either hangs
    # forever or raises OverflowError, and an OverflowError is not a
    # ProviderError, so it escapes the seam's whole vocabulary.  The refusal
    # is the provider's own word.
    transport = _transport((429, {"retry-after": "inf"}, b"{}"), _ok())

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert isinstance(raised.value, ProviderError)
    assert raised.value.status == 429
    assert len(transport.calls) == 1


def test_the_ceiling_itself_is_honoured_verbatim():
    # 60 s is at the ceiling, not above it: the boundary is inclusive, so a
    # vendor that asks for exactly the door's bound is obeyed exactly.
    transport = _transport((429, {"retry-after": "60"}, b"rate limited"), _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert sleeper.waits == [60.0]


def test_a_retry_after_one_second_above_the_ceiling_is_refused():
    # 61 s is over the bound by one second and meets the same refusal — the
    # comparison is strict, so there is no gap just above the ceiling.
    transport = _transport((429, {"retry-after": "61"}, b"rate limited"), _ok())

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.status == 429
    assert len(transport.calls) == 1


def test_a_nan_retry_after_falls_back_to_the_ladder():
    # "nan" is not a finite non-negative number, so it is unreadable in the
    # header's sense and takes the ladder, exactly as an HTTP-date does — a
    # value the door cannot compare against a ceiling is not a value it
    # sleeps on.
    transport = _transport((429, {"retry-after": "nan"}, b"rate limited"), _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert sleeper.waits == [1.0]


def test_the_ladder_never_waits_above_the_ceiling():
    # The other half of the bound: the door's own exponential ladder must stay
    # under the ceiling too, so no path — vendor's header or the door's
    # schedule — can sleep above MAX_RETRY_AFTER_SECONDS.  A long ladder (the
    # caller may raise max_attempts) is read off the recording sleep.
    transport = _transport(*[(503, {}, b"overloaded")] * 8, _ok())

    answered, sleeper = _drive(transport, max_attempts=9, random=lambda: 10.0)

    assert answered == _answer_body()
    assert sleeper.waits, "the ladder was exercised"
    assert all(wait <= live_http.MAX_RETRY_AFTER_SECONDS for wait in sleeper.waits)


@pytest.mark.parametrize("value", ["inf", "nan", "-inf"])
def test_no_retry_after_value_escapes_the_provider_vocabulary(value):
    # The closing property of the ceiling: whatever a vendor writes in the
    # header — infinity either sign, a not-a-number — and however the door
    # ends up refusing (at once for "not soon", or on the ladder once the
    # attempts run out), the ending is a ProviderError, never an
    # OverflowError or a ValueError out of the sleep.
    transport = _transport((429, {"retry-after": value}, b"{}"))

    with pytest.raises(ProviderError) as raised:
        _drive(transport)

    assert isinstance(raised.value, ProviderError)
    assert raised.value.status == 429


def test_a_timeout_is_retried():
    # The transport's failures are as transient as the vendor's: a timeout on
    # one attempt does not end the call while attempts remain.
    transport = _transport(TimeoutError("timed out"), TimeoutError("timed out"), _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert sleeper.waits == [1.0, 2.0]


def test_a_dropped_connection_is_retried():
    # …and so is a reset connection — the two ways the network, not the
    # vendor, loses a call.
    transport = _transport(ConnectionResetError("reset by peer"), _ok())

    answered, sleeper = _drive(transport)

    assert answered == _answer_body()
    assert sleeper.waits == [1.0]


# ── The final refusals: which word, and what it carries ────────────────────────


def test_a_timeout_that_never_answers_refuses_as_the_transport():
    # The network's refusal, after every attempt: the code word names the
    # layer that failed, the message names the kind and the attempt count,
    # and the transport was tried exactly max_attempts times.
    transport = _transport(TimeoutError("timed out"))

    with pytest.raises(ProviderTransportError) as raised:
        _drive(transport)

    message = str(raised.value)
    assert message.startswith(f"{PROVIDER_TRANSPORT_CODE}:")
    assert "timed out" in message
    assert "after 4 attempts" in message
    assert len(transport.calls) == 4


def test_a_connection_that_never_completes_refuses_as_the_transport():
    # The dropped-connection twin of the timeout refusal, named as itself.
    transport = _transport(ConnectionError("connection refused"))

    with pytest.raises(ProviderTransportError) as raised:
        _drive(transport)

    assert str(raised.value).startswith(f"{PROVIDER_TRANSPORT_CODE}:")
    assert "connection refused" in str(raised.value)
    assert len(transport.calls) == 4


def test_a_retried_status_that_never_clears_refuses_as_the_vendor():
    # The vendor's refusal, after every retry: the status rides on .status,
    # the vendor's own message on .detail and in the sentence, and the
    # message says the retries happened.
    transport = _transport((503, {}, b'{"error": {"message": "overloaded"}}'))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert str(raised.value).startswith(f"{PROVIDER_HTTP_CODE}:")
    assert "503" in str(raised.value)
    assert "after 4 attempts" in str(raised.value)
    assert raised.value.status == 503
    assert raised.value.detail == "overloaded"
    assert len(transport.calls) == 4


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_any_other_4xx_refuses_at_once_without_a_retry(status):
    # A 4xx is the request being refused — bad model name, bad key, bad body
    # — and re-sending it is the same refusal with more noise.  One send, no
    # wait, and the status is carried for the caller to read.
    transport = _transport((status, {}, b'{"error": {"message": "no"}}'))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.status == status
    assert len(transport.calls) == 1


def test_max_attempts_one_sends_once_and_refuses():
    # The budget is the caller's: one attempt means one send, and a
    # retryable status is refused on the spot because no attempts remain.
    transport = _transport((503, {}, b"overloaded"))
    sleeper = _sleep()

    with pytest.raises(ProviderHTTPError) as raised:
        post_json(
            URL,
            _headers(),
            _body(),
            allowed_hosts=ALLOWED_HOSTS,
            timeout=120.0,
            max_attempts=1,
            transport=transport,
            sleep=sleeper,
            random=NO_JITTER,
        )

    assert raised.value.status == 503
    assert "1 attempt" in str(raised.value)
    assert len(transport.calls) == 1
    assert sleeper.waits == []


def test_max_attempts_below_one_is_refused_before_the_guard_runs():
    # An attempt budget of zero is no call at all — a caller error about the
    # door's own parameters, said before anything else is decided.
    with pytest.raises(ValueError):
        post_json(
            URL,
            _headers(),
            _body(),
            allowed_hosts=ALLOWED_HOSTS,
            max_attempts=0,
            transport=_transport(_ok()),
            sleep=_sleep(),
        )


def test_the_vendors_own_message_is_carried_verbatim():
    # "401 from Anthropic: invalid x-api-key" is actionable only with the
    # vendor's own words: the Anthropic error shape's message rides on
    # .detail exactly as the vendor wrote it.
    body = json.dumps(
        {
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        }
    ).encode("utf-8")
    transport = _transport((401, {}, body))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.detail == "invalid x-api-key"
    assert "invalid x-api-key" in str(raised.value)


def test_the_openai_error_shape_is_read_the_same_way():
    # One door, both vendor shapes: the OpenAI-compatible family folds its
    # text the same way, so the caller never parses a vendor dialect.
    body = json.dumps(
        {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}
    ).encode("utf-8")
    transport = _transport((401, {}, body))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.detail == "Incorrect API key provided"


def test_a_bare_error_string_is_read():
    # A vendor that sends error as a string rather than an object still said
    # something; the door reads it instead of paraphrasing it away.
    transport = _transport((503, {}, b'{"error": "overloaded"}'))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.detail == "overloaded"


def test_an_error_body_that_is_not_json_falls_back_to_its_snippet():
    # A proxy's HTML error page is the truth of what happened; the honest
    # fallback is a short snippet of what actually came back, not a guess.
    transport = _transport((502, {}, b"<html>502 Bad Gateway</html>"))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert "502 Bad Gateway" in raised.value.detail


def test_an_empty_error_body_says_so():
    # A vendor that closed the body said nothing, and the refusal says that
    # rather than quoting an empty string as though it were a message.
    transport = _transport((500, {}, b""))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert raised.value.detail == "the vendor answered an empty body"


# ── The malformed answer: a 2xx body that is not a JSON object ─────────────────


@pytest.mark.parametrize(
    "body_bytes",
    [
        pytest.param(b'["a", "b"]', id="a-json-array"),
        pytest.param(b'"text"', id="a-json-string"),
        pytest.param(b"42", id="a-json-number"),
        pytest.param(b"null", id="json-null"),
        pytest.param(b"true", id="json-true"),
        pytest.param(b"{not json", id="not-json-at-all"),
        pytest.param(b"", id="an-empty-body"),
    ],
)
def test_a_body_that_is_not_a_json_object_is_a_malformed_completion(body_bytes):
    # The call succeeded and the answer cannot be read — the interface's own
    # word for that, not a transport's and not a vendor's, because a caller
    # catching the interface's base catches this with everything else it
    # already catches.
    transport = _transport((200, {}, body_bytes))

    with pytest.raises(CompletionMalformedError) as raised:
        _drive(transport)

    assert isinstance(raised.value, ProviderError)


def test_a_malformed_answer_is_not_retried():
    # A 2xx is the vendor answering; a body that poor is a vendor bug, and
    # re-sending the request would be hoping the bug is transient.  It is
    # refused on the attempt that met it, with an answer scripted next that
    # would have been fine — proving the retry never happened.
    transport = _transport((200, {}, b"not json"), _ok())

    with pytest.raises(CompletionMalformedError):
        _drive(transport)

    assert len(transport.calls) == 1


# ── Secret scrubbing: the credential never reaches an output ───────────────────
#
# Three outputs exist — the exception message, the repr, the log line — and
# three header names carry credentials.  The tests below drive each failure
# kind and assert the fake key is in none of them, while the wire (asserted
# above) carries the real one.


def _three_secret_headers() -> dict[str, str]:
    """One call wearing every credential spelling the door knows."""
    return {
        "content-type": "application/json",
        "x-api-key": FAKE_ANTHROPIC_KEY,
        "Authorization": f"Bearer {FAKE_BEARER_TOKEN}",
        "x-goog-api-key": FAKE_GOOG_KEY,
    }


@pytest.mark.parametrize(
    "kind",
    [
        "a-refused-host",
        "a-final-timeout",
        "a-final-status",
        "an-at-once-4xx",
    ],
)
def test_the_credential_never_reaches_the_log(kind, caplog):
    # Every failure kind, the log output: a credential that reached a log
    # line is a credential that reached a bug report, so each of the door's
    # endings is driven with all three secret spellings worn at once and the
    # captured log is hunted for each value.
    if kind == "a-refused-host":
        transport, allowed_hosts = _transport(_ok()), ()
    elif kind == "a-final-timeout":
        transport, allowed_hosts = _transport(TimeoutError("timed out")), ALLOWED_HOSTS
    elif kind == "a-final-status":
        transport, allowed_hosts = _transport((500, {}, b"overloaded")), ALLOWED_HOSTS
    else:
        transport, allowed_hosts = _transport((400, {}, b"bad request")), ALLOWED_HOSTS

    with (
        caplog.at_level(logging.DEBUG, logger="providers.live_http"),
        pytest.raises(ProviderError),
    ):
        _drive(transport, headers=_three_secret_headers(), allowed_hosts=allowed_hosts)

    assert FAKE_ANTHROPIC_KEY not in caplog.text
    assert FAKE_BEARER_TOKEN not in caplog.text
    assert FAKE_GOOG_KEY not in caplog.text


def test_each_failure_kinds_message_and_repr_carry_no_credential():
    # The str, the repr and the rendered traceback of each refusal — asserted
    # directly, failure kind by failure kind, so a leak names itself in the
    # assertion it fails.
    cases = [
        (
            ProviderHostRefusedError,
            lambda: _drive(
                _transport(_ok()), headers=_three_secret_headers(), allowed_hosts=()
            ),
        ),
        (
            ProviderTransportError,
            lambda: _drive(
                _transport(TimeoutError("timed out")), headers=_three_secret_headers()
            ),
        ),
        (
            ProviderHTTPError,
            lambda: _drive(
                _transport((400, {}, b"bad request")), headers=_three_secret_headers()
            ),
        ),
        (
            CompletionMalformedError,
            lambda: _drive(
                _transport((200, {}, b"not json")), headers=_three_secret_headers()
            ),
        ),
    ]
    for expected, drive in cases:
        with pytest.raises(expected) as raised:
            drive()
        rendered = "".join(traceback.format_exception(raised.value))
        for text in (str(raised.value), repr(raised.value), rendered):
            assert FAKE_ANTHROPIC_KEY not in text, (expected.__name__, text)
            assert FAKE_BEARER_TOKEN not in text, (expected.__name__, text)
            assert FAKE_GOOG_KEY not in text, (expected.__name__, text)


def test_the_log_lines_render_the_credential_as_three_stars(caplog):
    # The request's headers are logged — which credential a call carried is a
    # fact an operator needs — but in their *** form only: the log line says
    # a key was sent without ever saying which key.
    transport = _transport((503, {}, b"overloaded"), (503, {}, b"overloaded"), _ok())

    with caplog.at_level(logging.DEBUG, logger="providers.live_http"):
        answered, _ = _drive(transport, headers=_three_secret_headers())

    assert answered == _answer_body()
    assert FAKE_ANTHROPIC_KEY not in caplog.text
    assert FAKE_BEARER_TOKEN not in caplog.text
    assert FAKE_GOOG_KEY not in caplog.text
    assert "***" in caplog.text
    # The retry the waits describe is visible in the log an operator reads.
    assert "retrying" in caplog.text


def test_a_vendor_body_that_echoes_the_credential_is_scrubbed():
    # The belt under the braces: a vendor (or a proxy) that echoes the
    # credential back inside its own error text meets the same scrubbing on
    # the way into a message as the credential met on the way out of the
    # headers — the value is hunted by what was actually sent, wherever it
    # crept in.
    echoed = json.dumps(
        {"error": {"message": f"request had key {FAKE_ANTHROPIC_KEY} in it"}}
    ).encode("utf-8")
    transport = _transport((400, {}, echoed))

    with pytest.raises(ProviderHTTPError) as raised:
        _drive(transport)

    assert FAKE_ANTHROPIC_KEY not in str(raised.value)
    assert FAKE_ANTHROPIC_KEY not in raised.value.detail
    assert "***" in raised.value.detail


# ── The vocabulary: code words and the taxonomy they live in ───────────────────


def test_the_code_words_are_the_features_own_literals():
    # The greppable tokens are part of the contract — an operator greps one
    # word per finding — so they are pinned as the literals the spec states,
    # three distinct words for three distinct findings.
    assert HOST_REFUSED_CODE == "host_refused"
    assert PROVIDER_TRANSPORT_CODE == "provider_transport"
    assert PROVIDER_HTTP_CODE == "provider_http"
    assert len({HOST_REFUSED_CODE, PROVIDER_TRANSPORT_CODE, PROVIDER_HTTP_CODE}) == 3


def test_every_refusal_carries_its_code_word_as_its_code():
    # The code is a fact about the error, not a substring to hunt: each
    # refusal opens with its word and answers it from .code.
    refusals = [
        (ProviderHostRefusedError("sent nowhere"), HOST_REFUSED_CODE),
        (ProviderTransportError("no answer"), PROVIDER_TRANSPORT_CODE),
        (ProviderHTTPError("no", status=500), PROVIDER_HTTP_CODE),
    ]
    for error, code in refusals:
        assert str(error).startswith(f"{code}: ")
        assert error.code == code


def test_the_transport_refusals_are_provider_errors_and_not_each_other():
    # The spec's convention: every new error joins the interface's one base —
    # a caller's single except covers "the provider could not complete this
    # call" — while the three findings stay siblings, because the repairs
    # (fix the configuration, check the egress, read the status) are three
    # different acts.
    for error in (ProviderHostRefusedError, ProviderTransportError, ProviderHTTPError):
        assert issubclass(error, ProviderError)
    assert not issubclass(ProviderHostRefusedError, ProviderTransportError)
    assert not issubclass(ProviderTransportError, ProviderHTTPError)
    assert not issubclass(ProviderHTTPError, ProviderHostRefusedError)


def test_the_secret_header_set_is_the_three_vendor_spellings():
    # The closed set the wire formats themselves define — Anthropic's
    # x-api-key, the bearer token, Google's key — pinned so a fourth name is
    # a decision this suite sees, not a silent gap in the scrubbing.
    assert SECRET_HEADER_NAMES == frozenset(
        {"x-api-key", "authorization", "x-goog-api-key"}
    )


# ── The default transport: urllib.request, and nothing it owns but the POST ────


def test_transport_none_resolves_to_the_modules_urllib_callable(monkeypatch):
    # The default is the module's own urllib-backed callable, resolved at
    # call time — so the deployment's call posts through urllib.request, and
    # a suite can still watch it by patching the module attribute rather
    # than opening a socket.
    sent = {}

    def _spy(url, headers, body_bytes, timeout):
        sent.update(url=url, headers=dict(headers), body=body_bytes, timeout=timeout)
        return _ok()

    monkeypatch.setattr(live_http, "_urllib_transport", _spy)

    answered = post_json(
        URL, _headers(), _body(), allowed_hosts=ALLOWED_HOSTS, sleep=_sleep(), random=NO_JITTER
    )

    assert answered == _answer_body()
    assert sent["url"] == URL


class _FakeUrlopenResponse:
    """The slice of a ``urlopen`` answer the default transport reads."""

    def __init__(self, status, headers, body):
        self.status = status
        self.headers = headers
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None


def test_the_urllib_transport_posts_one_request_and_reads_the_answer(monkeypatch):
    # The default transport's contract with the loop above it: one POST with
    # the caller's bytes and headers, answered as the door's
    # (status, headers, body) triple.  Driven against a patched urlopen, so
    # even the default is tested without a socket.
    seen = {}

    def _fake_urlopen(request, timeout=None):
        seen["request"] = request
        seen["timeout"] = timeout
        return _FakeUrlopenResponse(200, {}, json.dumps(_answer_body()).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    status, _response_headers, body = live_http._urllib_transport(
        URL, _headers(), b"{}", 30.0
    )

    assert status == 200
    assert json.loads(body) == _answer_body()
    assert seen["timeout"] == 30.0
    request = seen["request"]
    assert request.get_method() == "POST"
    assert request.data == b"{}"
    # urllib normalizes header names to title case on the Request; the values
    # are the caller's, verbatim — including the credential, which travels.
    assert request.headers["X-api-key"] == FAKE_ANTHROPIC_KEY


def test_the_urllib_transport_reads_an_http_error_status_as_an_answer(monkeypatch):
    # urlopen raises for a 4xx/5xx; the door's contract wants a status, so
    # the default transport reads the vendor's error body off the exception
    # and answers it like any other response — retries and refusals stay the
    # loop's to decide.
    error_body = b'{"error": {"message": "overloaded"}}'

    def _fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            URL,
            529,
            "Overloaded",
            email.message.Message(),
            io.BytesIO(error_body),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    status, _response_headers, body = live_http._urllib_transport(
        URL, _headers(), b"{}", 30.0
    )

    assert status == 529
    assert body == error_body


# ── The member: stdlib only, as declared ───────────────────────────────────────


def test_the_member_stays_stdlib_only():
    # This feature claims the member's pyproject.toml precisely so no other
    # feature touches it, and leaves it with an empty dependency list: the
    # live door is urllib.request because the member declares nothing else,
    # and this pins the declaration the whole addition leans on.
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "dependencies = []" in text
