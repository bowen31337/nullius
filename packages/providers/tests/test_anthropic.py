"""The Anthropic Messages backend: one request translated out, one answer back.

Feature 2 of the live-providers addition is a translation on both sides of
feature 1's door: a :class:`~providers.Request` becomes one Messages-API
body — system turns joined into the top-level ``system`` field, the rest
forwarded in order, the cacheable prefix marked at exactly its two
breakpoints — and one decoded answer becomes a
:class:`~providers.Completion`, its text blocks joined, its serving model
copied verbatim, its stop reason and usage counters mapped onto the
interface's closed vocabulary.  These tests pin both halves, and the
refusals the backend owns outright: a temperature above the Messages API's
own ceiling is refused *before any call* and never clamped, a model other
than the one the provider was built for is refused before that, and an
answer with a stop reason the interface has no word for is refused naming
it.

No test here opens a socket.  Every call injects a transport that answers
from a script, so a test reads what left the machine (the URL, the
headers, the body bytes) and what the backend did with what came back —
the same discipline the door's own suite states, and the reason this
suite's credential is a fake it can then hunt for: the constraint is that
no API key appears in any repository file, log line, repr or message, and
the way a suite proves the *rendering* discipline is by sending a
key-shaped value it can then assert is absent from every output the
backend and the door produce.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from providers import (
    BatchRequest,
    Completion,
    CompletionMalformedError,
    NotImplementedBatchError,
    Provider,
    ProviderError,
    UnknownModelError,
    Usage,
)
from providers._anthropic import (
    ANTHROPIC_ALLOWED_HOSTS,
    ANTHROPIC_VERSION,
    DEFAULT_BASE_URL,
    UNSUPPORTED_TEMPERATURE_CODE,
    AnthropicProvider,
    ProviderRequestError,
)
from providers._live_http import ProviderHostRefusedError, ProviderHTTPError

# ── The script a test drives the backend with ─────────────────────────────────
#
# One fake credential, one model, one URL and one answer stand in for a
# deployment's live call; the transport is a per-test spy so a test reads
# both halves of the backend's behaviour — what went out through the door,
# and what the backend did with what came back.

#: A fake credential, and only a fake one: it travels to the injected
#: transport (rendering is not sending) and is then hunted through every
#: captured output, which is how this suite proves it never renders.
FAKE_KEY = "fake-ant-key-not-a-credential"

#: The one model the provider under test is built for — the pin's model.
MODEL = "claude-opus-5"

#: A model the per-model sampling table (see providers._anthropic's module
#: docstring) verifies still accepts ``temperature`` — used only by the
#: handful of tests below that exercise the temperature wire behaviour
#: itself, since :data:`MODEL` is now one of the models the table withholds
#: temperature from.
TEMPERATURE_MODEL = "claude-haiku-4-5"

#: The Messages-API endpoint of the default base URL.
URL = "https://api.anthropic.com/v1/messages"


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording every call.

    The door's own test double, spelled here too: each script entry is a
    ``(status, headers, body)`` answer or an exception to raise, and when
    the script runs out the last entry repeats.  The calls list is the
    backend seen from outside — the URL, the headers, the body bytes and
    the timeout of every send — which is how these tests assert what left
    the machine without opening a socket, and assert *that nothing left
    it* when a refusal fires before the door.
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


def _answer(**overrides: Any) -> dict[str, Any]:
    """A Messages-API success body, overridden per test by whole fields."""
    body: dict[str, Any] = {
        "content": [{"type": "text", "text": "ok"}],
        "model": MODEL,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 3},
    }
    body.update(overrides)
    return body


def _ok(**overrides: Any) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying the success body, overridden per test."""
    return 200, {}, json.dumps(_answer(**overrides)).encode("utf-8")


def _provider(transport: Any = None, *, model: str = MODEL, base_url: str = DEFAULT_BASE_URL):
    """The backend under test, built the way a deployment builds it.

    The credential is the fake; the transport is the test's spy.  Every
    default here is the constructor's own, so a test that overrides one is
    the test that is about that one.
    """
    return AnthropicProvider(
        FAKE_KEY, model=model, base_url=base_url, transport=transport
    )


def _sent_body(transport: Any, call: int = 0) -> dict[str, Any]:
    """The decoded body of the backend's ``call``-th send."""
    return json.loads(transport.calls[call]["body"])


def _breakpoints(node: Any) -> int:
    """Count the ``cache_control`` markers anywhere in a JSON value.

    Walks the whole decoded body, because the spec's law is a count over
    the request as a whole — at most 2 breakpoints — not over any one
    field; a marker in the wrong place is still a marker this count sees.
    """
    if isinstance(node, dict):
        return sum(
            1 for key in node if key == "cache_control"
        ) + sum(_breakpoints(value) for value in node.values())
    if isinstance(node, list):
        return sum(_breakpoints(item) for item in node)
    return 0


# ── The seam: a Provider, and nothing more than one ───────────────────────────


def test_the_backend_is_a_provider():
    provider = _provider()
    assert isinstance(provider, Provider)


def test_batches_keep_the_base_classs_refusal(make_request):
    # The addition's own scope line: the live backends answer one request
    # at a time and keep the base class's NotImplementedBatchError, rather
    # than silently answering a batch one call at a time behind it.
    provider = _provider(_transport(_ok()))

    with pytest.raises(NotImplementedBatchError):
        provider.complete_batch(BatchRequest(requests=(make_request(model=MODEL),)))


def test_the_allowlist_is_the_one_vendor_host():
    # The door's allowlist is fixed at the one host an Anthropic credential
    # may travel to, whatever base URL a deployment hands in — pinned here
    # as a constant because it is the deployment's egress statement.
    assert ANTHROPIC_ALLOWED_HOSTS == frozenset({"api.anthropic.com"})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"api_key": ""},
        {"api_key": None},
        {"api_key": 12345},
        {"model": ""},
        {"model": None},
        {"base_url": ""},
        {"base_url": None},
        {"transport": "not-callable"},
    ],
)
def test_malformed_configuration_is_refused_at_construction(kwargs):
    # A ValueError, never a ProviderError: a blank key or model never got
    # well-formed enough to be a provider-contract question — the split the
    # budget wrapper takes for its own ceilings.
    full: dict[str, Any] = {"api_key": FAKE_KEY, "model": MODEL}
    full.update(kwargs)
    with pytest.raises(ValueError):
        AnthropicProvider(**full)


# ── The request half: one translated body out the door ────────────────────────


def test_one_call_leaves_for_the_messages_url_with_the_anthropic_headers(make_request):
    transport = _transport(_ok())
    provider = _provider(transport)

    provider.complete(make_request(model=MODEL))

    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == URL
    assert call["headers"] == {
        "content-type": "application/json",
        "x-api-key": FAKE_KEY,
        "anthropic-version": ANTHROPIC_VERSION,
    }
    # The per-attempt timeout is the door's own default: this backend adds
    # no transport policy of its own, on purpose — policy is the door's.
    assert call["timeout"] == 120.0


def test_the_wire_carries_the_real_credential(make_request):
    # Scrubbing is a property of rendering, never of sending: the vendor
    # must receive the real key or the call cannot be authenticated, and
    # what this suite pins elsewhere is where the key does *not* go.
    transport = _transport(_ok())
    _provider(transport).complete(make_request(model=MODEL))

    assert transport.calls[0]["headers"]["x-api-key"] == FAKE_KEY


def test_a_trailing_slash_base_url_still_joins_to_one_path(make_request):
    transport = _transport(_ok())
    provider = AnthropicProvider(FAKE_KEY, model=MODEL, base_url=f"{DEFAULT_BASE_URL}/", transport=transport)

    provider.complete(make_request(model=MODEL))

    assert transport.calls[0]["url"] == URL


def test_an_http_base_url_to_the_vendor_host_is_refused_for_its_scheme(make_request):
    # The door's guard has two halves and this backend meets both: the
    # allowlist is fixed at the one vendor host, and plaintext http is
    # refused even to that host, because it is not loopback.  A credential
    # never travels in the clear, whatever base URL was handed in.
    transport = _transport(_ok())
    provider = AnthropicProvider(
        FAKE_KEY, model=MODEL, base_url="http://api.anthropic.com", transport=transport
    )

    with pytest.raises(ProviderHostRefusedError):
        provider.complete(make_request(model=MODEL))

    assert transport.calls == []


def test_the_whole_request_translates_into_one_messages_body(make_request):
    # The sentence as one picture: system turns join into the top-level
    # system field, the rest are forwarded in order with their roles, the
    # two cache breakpoints land on the system text and the message before
    # the final one, and the knobs travel as the vendor spells them.  A
    # temperature-accepting model, since the picture includes "temperature"
    # travelling at all.
    transport = _transport(_ok())
    provider = _provider(transport, model=TEMPERATURE_MODEL)

    provider.complete(
        make_request(
            model=TEMPERATURE_MODEL,
            temperature=0.4,
            max_tokens=128,
            bodies=(
                ("system", "standing instructions"),
                ("system", "and the second half of them"),
                ("user", "first question"),
                ("assistant", "an earlier answer"),
                ("user", "the question being asked now"),
            ),
        )
    )

    assert _sent_body(transport) == {
        "model": TEMPERATURE_MODEL,
        "max_tokens": 128,
        "system": [
            {
                "type": "text",
                "text": "standing instructions\nand the second half of them",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "first question"}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "an earlier answer",
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "the question being asked now"}],
            },
        ],
        "temperature": 0.4,
    }


def test_there_is_no_system_field_when_there_are_no_system_messages(make_request):
    # An empty system field is a statement the vendor would read; a request
    # with no standing instructions has nothing to say that way, and the
    # field is omitted rather than sent blank.
    transport = _transport(_ok())
    _provider(transport).complete(
        make_request(model=MODEL, bodies=(("user", "just asking"),))
    )

    assert "system" not in _sent_body(transport)


def test_a_single_message_call_carries_no_message_breakpoint(make_request):
    # "The message just before the final one (when there is one)": with one
    # turn there is no turn before the final one, so the call spends its
    # cache breakpoint on the system text only — one, not two.
    transport = _transport(_ok())
    _provider(transport).complete(
        make_request(model=MODEL, bodies=(("system", "orders"), ("user", "asking")))
    )

    body = _sent_body(transport)
    assert body["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "asking"}]}
    ]
    assert _breakpoints(body) == 1


@pytest.mark.parametrize(
    ("bodies", "expected"),
    [
        # A conversation and standing instructions: both breakpoints.
        (
            (("system", "orders"), ("user", "one"), ("assistant", "two"), ("user", "three")),
            2,
        ),
        # No standing instructions: only the message-before-final marker.
        ((("user", "one"), ("user", "two")), 1),
        # One turn and no instructions: nothing stable to cache but the
        # system text — and there is none of that either.
        ((("user", "only"),), 0),
        # Instructions alone with one turn: one breakpoint, on the system.
        ((("system", "orders"), ("user", "only")), 1),
    ],
)
def test_the_breakpoint_count_is_the_shapes_own(make_request, bodies, expected):
    transport = _transport(_ok())
    _provider(transport).complete(make_request(model=MODEL, bodies=bodies))

    assert _breakpoints(_sent_body(transport)) == expected


def test_no_shape_ever_spends_more_than_two_breakpoints(make_request):
    # However much standing instruction and history a prompt carries, the
    # breakpoints stay at the two the spec allows: one on the system text,
    # one on the message before the final one, and never one per turn.
    transport = _transport(_ok())
    _provider(transport).complete(
        make_request(
            model=MODEL,
            bodies=(
                ("system", "first instruction"),
                ("system", "second instruction"),
                ("system", "third instruction"),
                ("user", "one"),
                ("assistant", "two"),
                ("user", "three"),
                ("assistant", "four"),
                ("user", "five"),
            ),
        )
    )

    body = _sent_body(transport)
    assert _breakpoints(body) == 2
    # And both of them are where the prefix is: the joined system text,
    # and the last-but-one message of the conversation.
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][-2]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert all(
        "cache_control" not in block
        for message in body["messages"][:-2]
        for block in message["content"]
    )


def test_the_temperature_travels_verbatim(make_request):
    # What the caller asked is what the vendor gets — 0.5 is sent as 0.5.
    # The ceiling is a refusal, below it nothing is touched.  A
    # temperature-accepting model: see TEMPERATURE_MODEL's own comment.
    transport = _transport(_ok())
    _provider(transport, model=TEMPERATURE_MODEL).complete(
        make_request(model=TEMPERATURE_MODEL, temperature=0.5)
    )

    assert _sent_body(transport)["temperature"] == 0.5


# ── The temperature ceiling: refused, never clamped ───────────────────────────
#
# Every test below uses TEMPERATURE_MODEL rather than MODEL: the ceiling this
# section pins only applies to a model the per-model sampling table admits
# temperature for at all (providers._anthropic._sampling_mode), and MODEL is
# now one of the models the table withholds it from entirely.


@pytest.mark.parametrize("temperature", [1.5, 2.0])
def test_a_temperature_above_one_is_refused_before_any_call(make_request, temperature):
    # The interface admits up to 2.0; the Messages API stops at 1.0.  The
    # gap closes by refusal, ahead of the door — nothing is serialized,
    # nothing is sent — so the vendor never sees a temperature it would
    # have to interpret, and the caller meets the ceiling where it can be
    # fixed: at the ask.
    transport = _transport(_ok())
    provider = _provider(transport, model=TEMPERATURE_MODEL)

    with pytest.raises(ProviderRequestError) as refusal:
        provider.complete(make_request(model=TEMPERATURE_MODEL, temperature=temperature))

    message = str(refusal.value)
    assert message.startswith(f"{UNSUPPORTED_TEMPERATURE_CODE}: ")
    assert str(temperature) in message
    assert str(1.0) in message
    assert transport.calls == []


def test_a_refused_temperature_is_not_clamped_into_a_legal_call(make_request):
    # The behaviour the spec states twice: never clamped.  The refusal is
    # the whole outcome — no completion came back sampled at a temperature
    # nobody requested — and the next legal ask travels at exactly the
    # temperature it named, not one the provider chose for it.
    transport = _transport(_ok())
    provider = _provider(transport, model=TEMPERATURE_MODEL)

    with pytest.raises(ProviderRequestError):
        provider.complete(make_request(model=TEMPERATURE_MODEL, temperature=1.5))

    assert transport.calls == []
    provider.complete(
        make_request(
            model=TEMPERATURE_MODEL, temperature=0.5, bodies=(("user", "again"),)
        )
    )
    assert _sent_body(transport)["temperature"] == 0.5


def test_a_temperature_of_exactly_one_is_allowed(make_request):
    # The ceiling is a boundary, not a margin: 1.0 is the Messages API's
    # own top of the range and travels to the vendor untouched.
    transport = _transport(_ok())
    _provider(transport, model=TEMPERATURE_MODEL).complete(
        make_request(model=TEMPERATURE_MODEL, temperature=1.0)
    )

    assert _sent_body(transport)["temperature"] == 1.0


def test_the_temperature_refusal_carries_its_own_code():
    assert UNSUPPORTED_TEMPERATURE_CODE == "unsupported_temperature"


def test_provider_request_error_is_a_provider_error_with_its_code():
    error = ProviderRequestError("a message")

    assert isinstance(error, ProviderError)
    assert error.code == "unsupported_temperature"
    assert str(error) == "unsupported_temperature: a message"


# ── check_model: built for one model, and only that one ───────────────────────


def test_check_model_accepts_the_model_it_was_built_for():
    provider = _provider()

    assert provider.check_model(MODEL) == MODEL


def test_check_model_refuses_any_other_model():
    provider = _provider()

    with pytest.raises(UnknownModelError) as refusal:
        provider.check_model("claude-haiku-4-5")

    message = str(refusal.value)
    assert "claude-haiku-4-5" in message
    assert MODEL in message


def test_complete_refuses_a_request_for_another_model_before_any_call(make_request):
    transport = _transport(_ok())
    provider = _provider(transport)

    with pytest.raises(UnknownModelError):
        provider.complete(make_request(model="claude-haiku-4-5"))

    assert transport.calls == []


# ── The answer half: one completion back through the seam ─────────────────────


def test_the_whole_answer_translates_into_one_completion(make_request):
    # The sentence as one object: text joined, model verbatim, stop reason
    # mapped, every input counter counted — compared by value, because a
    # frozen dataclass that compares by value is what the interface
    # promises the caller.
    transport = _transport(
        _ok(
            content=[{"type": "text", "text": "the answer"}],
            model="claude-opus-5-20260401",
            stop_reason="stop_sequence",
            usage={
                "input_tokens": 100,
                "output_tokens": 7,
                "cache_creation_input_tokens": 12,
                "cache_read_input_tokens": 34,
            },
        )
    )
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion == Completion(
        content="the answer",
        model="claude-opus-5-20260401",
        usage=Usage(
            input_tokens=146,
            output_tokens=7,
            cache_read_tokens=34,
            cache_write_tokens=12,
        ),
        finish_reason="stop",
    )


def test_text_blocks_join_in_order_and_non_text_blocks_do_not(make_request):
    # A thinking block or a tool call is a real answer block that is not
    # text; the interface promises one content string, so the text blocks
    # join and the others leave without being guessed at.
    transport = _transport(
        _ok(
            content=[
                {"type": "thinking", "thinking": "internal reasoning"},
                {"type": "text", "text": "Hello"},
                {"type": "tool_use", "id": "t1", "name": "grep"},
                {"type": "text", "text": " there"},
            ]
        )
    )
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.content == "Hello there"


def test_the_responses_model_is_copied_verbatim(make_request):
    # The completion names the model that served it — dated snapshot
    # suffix and all — and whether that model is the one the pin asked for
    # is the registry's require_served question, not this backend's.
    transport = _transport(_ok(model="claude-opus-5-20260401"))
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.model == "claude-opus-5-20260401"


@pytest.mark.parametrize(
    ("stop_reason", "finish_reason"),
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "length"),
    ],
)
def test_stop_reasons_map_onto_the_interfaces_closed_set(
    make_request, stop_reason, finish_reason
):
    transport = _transport(_ok(stop_reason=stop_reason))
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.finish_reason == finish_reason


@pytest.mark.parametrize("stop_reason", ["refusal", "tool_use", "pause_turn", None])
def test_any_other_stop_reason_is_refused_naming_it(make_request, stop_reason):
    # A stop code the interface has no vocabulary for is refused *naming
    # it*, in the vendor's own spelling — an operator debugging the
    # refusal sees what the vendor actually said, not a paraphrase.
    transport = _transport(_ok(stop_reason=stop_reason))
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError) as refusal:
        provider.complete(make_request(model=MODEL))

    assert repr(stop_reason) in str(refusal.value)


def test_usage_counts_every_input_token(make_request):
    # input_tokens is the plain input *plus* the prefix newly written into
    # the prompt cache *plus* the prefix read back from it: all three are
    # input the call consumed, and a total that dropped any of them would
    # under-report the call's spend to every cost total downstream.
    transport = _transport(
        _ok(
            usage={
                "input_tokens": 100,
                "output_tokens": 7,
                "cache_creation_input_tokens": 12,
                "cache_read_input_tokens": 34,
            }
        )
    )
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.usage.input_tokens == 146
    assert completion.usage.output_tokens == 7
    assert completion.usage.cache_read_tokens == 34


def test_a_cold_answer_reports_no_cache_counters_and_zero_reads(make_request):
    # The cache counters are genuinely absent from a cold call, and an
    # absent figure reads as zero — never a guess, never a refusal.
    transport = _transport(_ok(usage={"input_tokens": 10, "output_tokens": 4}))
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.usage == Usage(input_tokens=10, output_tokens=4)


# ── Malformed answers: refused at the backend, never downstream ───────────────


def test_an_answer_whose_content_is_not_a_block_list_is_refused(make_request):
    transport = _transport(_ok(content="ok"))
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError):
        provider.complete(make_request(model=MODEL))


def test_a_text_block_without_string_text_is_refused(make_request):
    transport = _transport(_ok(content=[{"type": "text", "text": None}]))
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError):
        provider.complete(make_request(model=MODEL))


def test_an_answer_that_names_no_model_is_refused(make_request):
    transport = _transport(_ok(model=""))
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError):
        provider.complete(make_request(model=MODEL))


def test_an_answer_whose_usage_is_not_an_object_is_refused(make_request):
    transport = _transport(_ok(usage=[1, 2]))
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError):
        provider.complete(make_request(model=MODEL))


@pytest.mark.parametrize(
    ("counter", "other"),
    [("input_tokens", "output_tokens"), ("output_tokens", "input_tokens")],
)
def test_a_usage_counter_that_is_not_a_count_is_refused(make_request, counter, other):
    # A counter that is present but is not a count is a malformed answer,
    # not an absent figure — refused naming the field, never coerced.
    transport = _transport(
        _ok(usage={other: 12, counter: "not-a-count"})
    )
    provider = _provider(transport)

    with pytest.raises(CompletionMalformedError) as refusal:
        provider.complete(make_request(model=MODEL))

    assert f"usage.{counter}" in str(refusal.value)


# ── The door's own refusals, surfacing unchanged ───────────────────────────────


def test_a_base_url_off_the_allowlist_is_refused_before_anything_is_sent(make_request):
    # The allowlist is fixed at the one vendor host whatever base URL was
    # handed in — it is the deployment's statement of where keys may
    # travel — so a base URL pointing anywhere else meets the door's
    # refusal here, before the transport is so much as resolved.
    transport = _transport(_ok())
    provider = _provider(transport, base_url="https://not-declared.example")

    with pytest.raises(ProviderHostRefusedError):
        provider.complete(make_request(model=MODEL))

    assert transport.calls == []


def test_an_http_refusal_from_the_vendor_surfaces_with_its_status(make_request):
    # The door owns the failure vocabulary; this backend adds none beside
    # it.  A 401 is not retryable, so it surfaces at once with the status
    # and the vendor's own message — the anthropic-shaped error body read
    # by the door, not re-parsed here.
    body = json.dumps(
        {
            "type": "error",
            "error": {"type": "authentication_error", "message": "invalid x-api-key"},
        }
    ).encode("utf-8")
    transport = _transport((401, {}, body))
    provider = _provider(transport)

    with pytest.raises(ProviderHTTPError) as refusal:
        provider.complete(make_request(model=MODEL))

    assert refusal.value.status == 401
    assert "invalid x-api-key" in refusal.value.detail
    assert len(transport.calls) == 1


# ── The key never renders ──────────────────────────────────────────────────────


def test_repr_never_shows_the_key():
    provider = _provider()

    rendered = repr(provider)

    assert FAKE_KEY not in rendered
    assert "api_key='***'" in rendered
    assert MODEL in rendered
    assert DEFAULT_BASE_URL in rendered


def test_no_captured_output_ever_contains_the_key(make_request):
    # Every refusal this backend can raise — its own temperature word, the
    # interface's unknown-model word, the malformed-answer word, and the
    # door's vendor refusal with the key echoed back in the error body —
    # renders without the credential, and so does the provider's own repr.
    # The door scrubs the echo; the backend's own messages are built from
    # the ask and the answer, never the key.  Built for TEMPERATURE_MODEL so
    # the temperature-ceiling refusal still fires; the model-mismatch check
    # below asks for MODEL instead, the model this provider was not built for.
    echoed = json.dumps(
        {
            "type": "error",
            "error": {"type": "authentication_error", "message": f"bad key {FAKE_KEY}"},
        }
    ).encode("utf-8")
    transport = _transport(_ok(stop_reason="refusal"), (401, {}, echoed))
    provider = _provider(transport, model=TEMPERATURE_MODEL)

    with pytest.raises(ProviderRequestError) as temperature_refusal:
        provider.complete(make_request(model=TEMPERATURE_MODEL, temperature=1.5))
    with pytest.raises(UnknownModelError) as model_refusal:
        provider.complete(make_request(model=MODEL))
    with pytest.raises(CompletionMalformedError) as answer_refusal:
        provider.complete(make_request(model=TEMPERATURE_MODEL))
    with pytest.raises(ProviderHTTPError) as http_refusal:
        provider.complete(make_request(model=TEMPERATURE_MODEL))

    for rendered in (
        repr(provider),
        str(temperature_refusal.value),
        str(model_refusal.value),
        str(answer_refusal.value),
        str(http_refusal.value),
        http_refusal.value.detail,
    ):
        assert FAKE_KEY not in rendered
