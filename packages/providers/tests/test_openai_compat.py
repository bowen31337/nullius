"""The OpenAI-compatible backend: one provider, four vendors, one protocol.

The live-providers addition's third feature is one backend for the four
model families that speak the chat-completions protocol — openai, deepseek,
google (Gemini's OpenAI-compatible endpoint) and self-hosted — and these
tests pin the three things that backend decides itself: the **vendor table**
(each vendor's default base URL, its allowed host, its length-cap key and its
cache-figure spelling, with self-hosted the one vendor with no default and
its own URL's host for an allowlist), the **request translation** (the
messages verbatim with their roles, the cap under the vendor's own key) and
the **answer translation** (the serving model copied verbatim and unchecked,
the two shared finish reasons mapping to themselves, every third one and
every null content refused naming it, the usage figures copied and the cache
figure read from the vendor's own shelf).

Everything else the backend inherits from feature 1's door, and these tests
pin the inheritance at its seams: a base URL on an unallowed host is the
door's refusal *before anything is sent*, a vendor's 4xx surfaces as the
door's :class:`~providers._live_http.ProviderHTTPError`, and a credential
never reaches an exception message, a repr or a log line while the wire —
asserted directly — carries the real one.

No test here opens a socket.  Every call injects a transport that answers
from a script, so what left the machine is read off the spy's call list
rather than inferred from what came back; the keys are fake and key-shaped,
so the scrubbing assertions hunt for a value that would be a real leak if it
were ever rendered.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

import pytest
from providers import (
    BatchRequest,
    Completion,
    CompletionMalformedError,
    Message,
    NotImplementedBatchError,
    Provider,
    ProviderError,
    ProviderNotConfiguredError,
    Request,
    UnknownModelError,
    Usage,
)
from providers._live_http import (
    HOST_REFUSED_CODE,
    PROVIDER_HTTP_CODE,
    ProviderHostRefusedError,
    ProviderHTTPError,
)
from providers._openai_compat import OpenAICompatProvider

# ── The script a test drives the backend with ─────────────────────────────────
#
# One fake credential per deployment shape — a hosted key and a self-hosted
# one — and one model per vendor, so a test reads "which vendor" at a glance
# in the model name and the assertion it fails names the dialect it broke.

#: Fake credentials, and only fake ones: the constraint is that no API key
#: appears in any repository file, log line or output, and the way a suite
#: proves the *scrubbing* is by sending a key-shaped value it can then hunt
#: for.  Key-shaped, not key-real: neither would open a door anywhere.
FAKE_KEY = "fake-oai-key-not-a-credential"
FAKE_LOCAL_KEY = "fake-local-key-not-a-credential"

#: The one model per vendor these tests build their providers for.  The
#: spellings are the deployment's own idiom — a pinned OpenAI model, a
#: DeepSeek chat model, a Gemini, a self-hosted Qwen — because the point of
#: the table is that the four vendors are real families with real model
#: names, not slots.
MODELS = {
    "openai": "gpt-5-mini",
    "deepseek": "deepseek-chat",
    "google": "gemini-3-flash",
    "self-hosted": "qwen3-32b",
}

#: The base URL a self-hosted drive names: loopback over http, the one
#: plaintext destination the door serves, standing in for the vLLM box a
#: deployment runs behind no auth.
SELF_HOSTED_BASE = "http://localhost:8000/v1"


def _answer(
    *,
    content: Any = "ok",
    model: str = "gpt-5-mini",
    finish_reason: Any = "stop",
    prompt_tokens: int = 12,
    completion_tokens: int = 3,
    usage_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A chat-completions success body, with the one dial a test is turning.

    ``usage_extra`` merges into ``usage`` — that is where a cache-figure
    spelling is injected — and ``content``/``finish_reason`` take ``Any``
    deliberately: the malformed-answer tests are about the values that are
    *not* the happy shape, and the helper should build those too.
    """
    usage: dict[str, Any] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if usage_extra:
        usage.update(usage_extra)
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "model": model,
        "usage": usage,
    }


def _ok(body: dict[str, Any] | None = None) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying ``body``."""
    payload = _answer() if body is None else body
    return 200, {}, json.dumps(payload).encode("utf-8")


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording every call.

    Each script entry is a ``(status, headers, body)`` answer or an exception
    to raise; when the script runs out the last entry repeats, so a one-entry
    script is "always this".  The calls list is the backend seen from outside
    — the URL, the headers, the body bytes and the timeout of every send —
    which is how these tests assert what left the machine without opening a
    socket.
    """
    calls: list[dict[str, Any]] = []

    def _send(url: str, headers: dict[str, str], body_bytes: bytes, timeout: float):
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "body": body_bytes,
                "timeout": timeout,
            }
        )
        answer = script[min(len(calls), len(script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    _send.calls = calls
    return _send


def _provider(
    vendor: str = "openai",
    *,
    model: str | None = None,
    key: str = FAKE_KEY,
    base_url: str | None = None,
    transport: Any = None,
) -> OpenAICompatProvider:
    """A provider for ``vendor`` and its suite model, with everything injected.

    The model defaults to the vendor's suite spelling so a drive reads as
    "the deepseek provider", and the key defaults to the hosted fake; a test
    that wants the self-hosted shapes passes the base URL and the local key
    itself.
    """
    return OpenAICompatProvider(
        vendor,
        key,
        # `.get` rather than `[...]`: a drive of an *unknown* vendor must
        # reach the provider's own construction guard, not a KeyError about
        # a model the suite never spelled for it.
        model=MODELS.get(vendor, "gpt-5-mini") if model is None else model,
        base_url=base_url,
        transport=transport,
    )


def _request(
    *,
    model: str = "gpt-5-mini",
    temperature: float = 0.0,
    max_tokens: int = 64,
    messages: tuple[Message, ...] | None = None,
) -> Request:
    """The one-ask request every drive sends unless a test is about the ask."""
    if messages is None:
        messages = (Message("user", "Reply with the single word: ok"),)
    return Request(
        messages=tuple(messages),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _drive(
    *script: Any,
    vendor: str = "openai",
    model: str | None = None,
    key: str = FAKE_KEY,
    base_url: str | None = None,
    request: Request | None = None,
) -> tuple[Completion, Any]:
    """Complete one request through a provider whose transport answers ``script``.

    The defaults every test wants — the vendor's suite model on both the
    provider and the request, the fake hosted key — so a test's own
    parameters are the part it is actually about.  The spy transport is
    handed back with the answer so a test reads what left the machine.
    """
    transport = _transport(*script)
    provider = _provider(
        vendor, model=model, key=key, base_url=base_url, transport=transport
    )
    served = MODELS[vendor] if model is None else model
    answered = provider.complete(
        _request(model=served) if request is None else request
    )
    return answered, transport


# ── The vendor table: one endpoint per vendor ─────────────────────────────────


@pytest.mark.parametrize(
    ("vendor", "base_url", "expected_url"),
    [
        pytest.param("openai", None, "https://api.openai.com/v1/chat/completions"),
        pytest.param("deepseek", None, "https://api.deepseek.com/chat/completions"),
        pytest.param(
            "google",
            None,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        ),
        pytest.param(
            "self-hosted",
            SELF_HOSTED_BASE,
            "http://localhost:8000/v1/chat/completions",
        ),
    ],
)
def test_each_vendor_posts_to_its_own_chat_completions_endpoint(
    vendor, base_url, expected_url
):
    # The wire fact itself: the base URL is per-vendor, the path is the
    # protocol's own name, and the join of the two is the one endpoint each
    # family answers.  Google's is the spelling worth pinning — Gemini's
    # OpenAI-compatible layer hangs off /v1beta/openai, not /v1 — and the
    # self-hosted row proves the path is joined to whatever base the
    # operator named.
    completion, transport = _drive(
        _ok(_answer(model=MODELS[vendor])), vendor=vendor, base_url=base_url
    )

    assert isinstance(completion, Completion)
    assert transport.calls[0]["url"] == expected_url
    assert len(transport.calls) == 1


def test_a_trailing_slash_on_the_base_url_does_not_double_the_path():
    # An operator copies a base URL out of a vendor's docs either way, and a
    # backend that answered "//chat/completions" would be a backend whose
    # endpoint depends on how the docs were formatted.
    _, transport = _drive(_ok(), base_url="https://api.openai.com/v1/")

    assert transport.calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_a_base_url_on_another_host_is_the_doors_refusal_before_anything_is_sent():
    # The allowlist follows the vendor, never the URL: a base_url parameter
    # may re-spell the vendor's own destination but not rehost it, so this
    # openai provider pointed at DeepSeek's host is refused by feature 1's
    # guard — asserted by the spy's empty call list, the strongest form of
    # "nothing was sent".
    transport = _transport(_ok())
    provider = _provider(
        "openai", base_url="https://api.deepseek.com", transport=transport
    )

    with pytest.raises(ProviderHostRefusedError) as raised:
        provider.complete(_request())

    assert str(raised.value).startswith(f"{HOST_REFUSED_CODE}:")
    assert "api.openai.com" in str(raised.value)
    assert transport.calls == []


def test_a_self_hosted_provider_is_allowed_exactly_its_own_base_urls_host():
    # The operator naming the box *is* the declaration the guard exists to
    # enforce: any host a self-hosted base URL names is that provider's
    # allowlist, so an internal GPU box over https is served without asking
    # any vendor table for permission — there is no vendor.
    completion, transport = _drive(
        _ok(_answer(model=MODELS["self-hosted"])),
        vendor="self-hosted",
        base_url="https://gpu-box.internal:8443/v1",
    )

    assert isinstance(completion, Completion)
    assert (
        transport.calls[0]["url"] == "https://gpu-box.internal:8443/v1/chat/completions"
    )


def test_plain_http_to_a_non_loopback_box_is_the_doors_refusal():
    # The scheme half of the guard belongs to the door, and the backend
    # inherits it rather than restating it: an http base URL is served only
    # on loopback, and a self-hosted box on the LAN is refused before
    # anything is sent — the same refusal an undeclared host is, because it
    # is the same finding.
    transport = _transport(_ok())
    provider = _provider(
        "self-hosted", base_url="http://gpu-box.internal:8000/v1", transport=transport
    )

    with pytest.raises(ProviderHostRefusedError):
        provider.complete(_request(model=MODELS["self-hosted"]))

    assert transport.calls == []


# ── Construction: the closed vendor set and what each vendor requires ─────────


@pytest.mark.parametrize(
    "vendor",
    [
        pytest.param("mistral", id="a-real-family-with-no-backend"),
        pytest.param("anthropic", id="the-other-backends-vendor"),
        pytest.param("openai ", id="a-trailing-space"),
        pytest.param("OpenAI", id="different-case"),
        pytest.param("", id="empty"),
    ],
)
def test_an_unknown_vendor_is_refused_naming_the_four_it_serves(vendor):
    # The vendor names a wire dialect, and the table is a closed set: a pin
    # whose provider spelling nobody taught the table is a configuration to
    # fix at construction, with the four real spellings in the message so
    # the fix is a copy rather than a search.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        _provider(vendor)

    message = str(raised.value)
    for name in ("openai", "deepseek", "google", "self-hosted"):
        assert name in message
    assert vendor in message


def test_a_non_string_vendor_is_refused_for_its_type():
    # Refused for the right reason: a non-string vendor is a wrong type, not
    # an unknown spelling, and the message names the type so the caller sees
    # the mistake without the value ever being rendered.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        OpenAICompatProvider(3, FAKE_KEY, model="gpt-5-mini")

    assert "int" in str(raised.value)


def test_self_hosted_without_a_base_url_is_refused():
    # There is nothing to default to: a hosted vendor's base is a fact about
    # the vendor, and self-hosting is the one spelling whose destination
    # only the operator knows.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        _provider("self-hosted")

    message = str(raised.value)
    assert "base_url" in message
    assert "self-hosted" in message


@pytest.mark.parametrize(
    ("vendor", "base_url"),
    [
        pytest.param("self-hosted", "", id="empty"),
        pytest.param("self-hosted", "not-a-url", id="no-scheme-just-a-word"),
        pytest.param("openai", "", id="an-empty-override"),
    ],
)
def test_a_base_url_that_names_no_host_is_refused(vendor, base_url):
    # A URL with no host is not a destination the door could vouch for, and
    # the door would refuse it before sending; construction refuses it
    # first, where the caller can fix it.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        _provider(vendor, base_url=base_url)

    assert "names no host" in str(raised.value)


@pytest.mark.parametrize("vendor", ["openai", "deepseek", "google"])
def test_a_hosted_vendor_with_an_empty_key_is_refused(vendor):
    # The key may be empty only for self-hosted, where the box itself
    # decides whether to ask for one.  A hosted vendor without a credential
    # would be a refusal the vendor answers after the request left the
    # machine, which is a worse place to learn it than construction.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        _provider(vendor, key="")

    message = str(raised.value)
    assert vendor in message
    assert "self-hosted" in message


def test_a_key_of_the_wrong_type_is_refused_without_its_value():
    # A key of the wrong type is still shaped like a credential, and a
    # refusal is one of the places a credential must never reach: the
    # message names the type and never renders the value.
    with pytest.raises(ProviderNotConfiguredError) as raised:
        _provider(key=12345678901234567890)

    message = str(raised.value)
    assert "int" in message
    assert "12345678901234567890" not in message


@pytest.mark.parametrize("model", ["", None])
def test_a_blank_model_is_refused(model):
    # The backend serves exactly one model and no other, so a provider built
    # with no model name is a provider that could answer no call at all.
    with pytest.raises(ProviderNotConfiguredError):
        OpenAICompatProvider("openai", FAKE_KEY, model=model)


# ── The headers one call wears ─────────────────────────────────────────────────


@pytest.mark.parametrize("vendor", ["openai", "deepseek", "google"])
def test_hosted_vendors_send_one_bearer_header_and_the_json_content_type(vendor):
    # The exact header set, asserted as a whole: the family authenticates
    # with one bearer token under `authorization` — Google's
    # OpenAI-compatible layer included, whose native x-goog-api-key belongs
    # to the Gemini protocol this backend does not speak — and nothing else
    # rides along.  And the wire carries the *real* credential: scrubbing is
    # a property of rendering, never of sending.
    _, transport = _drive(_ok(_answer(model=MODELS[vendor])), vendor=vendor)

    assert transport.calls[0]["headers"] == {
        "content-type": "application/json",
        "authorization": f"Bearer {FAKE_KEY}",
    }


def test_a_self_hosted_provider_with_a_key_sends_the_bearer_header():
    # A self-hosted deployment that does run auth reads the same header the
    # hosted vendors do — the server is speaking this protocol on purpose.
    _, transport = _drive(
        _ok(_answer(model=MODELS["self-hosted"])),
        vendor="self-hosted",
        key=FAKE_LOCAL_KEY,
        base_url=SELF_HOSTED_BASE,
    )

    assert transport.calls[0]["headers"] == {
        "content-type": "application/json",
        "authorization": f"Bearer {FAKE_LOCAL_KEY}",
    }


def test_a_self_hosted_provider_with_no_key_sends_no_authorization_header():
    # The empty self-hosted key is not a bearer token with nothing after
    # "Bearer" — it is no header at all, because a lab box behind no auth is
    # a real deployment and an empty credential would be a lie the server
    # would try to check.
    _, transport = _drive(
        _ok(_answer(model=MODELS["self-hosted"])),
        vendor="self-hosted",
        key="",
        base_url=SELF_HOSTED_BASE,
    )

    assert transport.calls[0]["headers"] == {"content-type": "application/json"}


# ── The request translation: verbatim messages, the vendor's cap key ──────────


def test_messages_are_sent_verbatim_with_their_roles():
    # The interface normalized the conversation; the wire carries it.  Every
    # role survives in place — system turns included, because this protocol
    # has no top-level system field to lift them to (the contrast with the
    # Anthropic backend is the point of "verbatim") — and the content rides
    # byte-for-byte: newlines, quotes, all of it.
    messages = (
        Message("system", "You are the signal agent."),
        Message("user", "Score this mechanism:\nline two"),
        Message("assistant", 'Prior answer with "quotes"'),
        Message("user", "And now the second question"),
    )

    _, transport = _drive(_ok(), request=_request(messages=messages))

    body = json.loads(transport.calls[0]["body"])
    assert body["messages"] == [
        {"role": "system", "content": "You are the signal agent."},
        {"role": "user", "content": "Score this mechanism:\nline two"},
        {"role": "assistant", "content": 'Prior answer with "quotes"'},
        {"role": "user", "content": "And now the second question"},
    ]
    assert "system" not in body


def test_the_openai_body_is_the_family_shape_with_max_completion_tokens():
    # The whole body, asserted as one object: the model, the verbatim
    # messages, the temperature as asked, and the cap under openai's own
    # key.  Exact equality pins that nothing else rides along — no
    # provider-specific field the vendor never agreed to read.
    _, transport = _drive(_ok())

    assert json.loads(transport.calls[0]["body"]) == {
        "model": "gpt-5-mini",
        "messages": [
            {"role": "user", "content": "Reply with the single word: ok"}
        ],
        "temperature": 0.0,
        "max_completion_tokens": 64,
    }


@pytest.mark.parametrize(
    ("vendor", "base_url"),
    [
        pytest.param("deepseek", None, id="deepseek"),
        pytest.param("google", None, id="google"),
        pytest.param("self-hosted", SELF_HOSTED_BASE, id="self-hosted"),
    ],
)
def test_the_other_vendors_send_the_cap_as_max_tokens(vendor, base_url):
    # The one place the dialects have actually drifted: openai's current API
    # reads max_completion_tokens, and every clone still reads the old
    # max_tokens — so the cap's *key* is a per-vendor fact while its value
    # is the request's own ceiling, verbatim, like the temperature and model.
    _, transport = _drive(
        _ok(_answer(model=MODELS[vendor])),
        vendor=vendor,
        base_url=base_url,
        request=_request(
            model=MODELS[vendor], temperature=0.5, max_tokens=512
        ),
    )

    body = json.loads(transport.calls[0]["body"])
    assert body["max_tokens"] == 512
    assert "max_completion_tokens" not in body
    assert body["temperature"] == 0.5
    assert body["model"] == MODELS[vendor]


# ── check_model: one provider, one model, refused before anything is sent ─────


def test_the_backend_is_a_provider_serving_the_model_it_was_built_for():
    # The seam's promise and the backend's, in one test: it is a Provider,
    # the model it was built for passes check_model unchanged, and the
    # answer is the interface's one object.
    provider = _provider(transport=_transport(_ok()))

    assert isinstance(provider, Provider)
    assert provider.check_model("gpt-5-mini") == "gpt-5-mini"
    assert isinstance(provider.complete(_request()), Completion)


@pytest.mark.parametrize(
    "asked",
    [
        pytest.param("gpt-5", id="a-sibling-model"),
        pytest.param("gpt-5-mini-2", id="a-newer-revision"),
        pytest.param("GPT-5-MINI", id="different-case"),
    ],
)
def test_any_other_model_is_refused_before_anything_is_sent(asked):
    # The backend is built for one pinned model at a time, so every other
    # name — sibling, revision, different case — is refused with the
    # interface's word for it, and the refusal precedes the transport:
    # asserted by the spy's empty call list.
    transport = _transport(_ok())
    provider = _provider(transport=transport)

    with pytest.raises(UnknownModelError) as raised:
        provider.complete(_request(model=asked))

    message = str(raised.value)
    assert "gpt-5-mini" in message
    assert asked in message
    assert transport.calls == []


# ── The answer translation: three copies and one refusal ──────────────────────


@pytest.mark.parametrize(
    "served",
    [
        pytest.param("gpt-5-mini-2026-07-10", id="the-dated-deployment"),
        pytest.param("gpt-5-mini-turbo", id="an-undocumented-variant"),
        pytest.param("entirely-another-model", id="a-vendor-serving-something-else"),
    ],
)
def test_the_serving_model_is_copied_verbatim_and_never_checked(served):
    # Completion.model is the model that *served* the answer, and this
    # backend copies it without checking it against the model it asked for:
    # a vendor silently serving another model is feature 4's finding to
    # catch (require_served), and a backend that normalized the serving
    # model away would destroy the evidence.
    completion, _ = _drive(_ok(_answer(model=served)))

    assert completion.model == served


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [("stop", "stop"), ("length", "length")],
)
def test_the_two_shared_finish_reasons_map_to_themselves(finish_reason, expected):
    # The family and the interface already share these two spellings, so the
    # mapping is the identity — asserted anyway, because an implementation
    # could still get the identity wrong, and a "length" the caller reads as
    # "stop" is a fill the depth accounting believes happened.
    completion, _ = _drive(_ok(_answer(finish_reason=finish_reason)))

    assert completion.finish_reason == expected


def test_a_full_answer_translates_into_the_one_completion():
    # Every field at once: the content from the message, the model verbatim,
    # the two billed figures and the cached figure from the vendor's shelf,
    # the finish reason as itself.  Equality against a built Completion is
    # the strongest form — the drive answers with exactly one object.
    completion, _ = _drive(
        _ok(
            _answer(
                prompt_tokens=120,
                completion_tokens=34,
                usage_extra={"prompt_tokens_details": {"cached_tokens": 90}},
            )
        )
    )

    assert completion == Completion(
        content="ok",
        model="gpt-5-mini",
        usage=Usage(
            input_tokens=120, output_tokens=34, cache_read_tokens=90
        ),
        finish_reason="stop",
    )


@pytest.mark.parametrize(
    "finish_reason",
    [
        pytest.param("content_filter", id="a-refused-answer"),
        pytest.param("tool_calls", id="tools-instead-of-text"),
        pytest.param("function_call", id="the-legacy-spelling"),
    ],
)
def test_a_third_finish_reason_is_refused_naming_it(finish_reason):
    # A model stopping for a reason the deployment has no vocabulary for is
    # a fact to read, not to fold onto "stop": the refusal names the code
    # the vendor sent so an operator greps the vendor's own word.
    with pytest.raises(CompletionMalformedError, match=re.escape(finish_reason)):
        _drive(_ok(_answer(finish_reason=finish_reason)))


def test_a_missing_finish_reason_is_refused_naming_its_absence():
    # An answer that says nothing about why the model stopped is not an
    # answer that stopped for no reason; the closed set is a set, not a
    # default.
    body = _answer()
    del body["choices"][0]["finish_reason"]

    with pytest.raises(CompletionMalformedError, match="finish_reason"):
        _drive((200, {}, json.dumps(body).encode("utf-8")))


def test_a_null_message_content_is_refused_naming_it():
    # The family's own way of saying the model said nothing — a refused
    # content filter, a tool call instead of an answer — and "said nothing"
    # must not become "said ''": a caller cannot tell the two apart later,
    # so the refusal names the null.
    with pytest.raises(CompletionMalformedError, match="null"):
        _drive(_ok(_answer(content=None)))


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(["ok"], id="a-parts-list"),
        pytest.param(7, id="a-number"),
        pytest.param({"text": "ok"}, id="an-object"),
    ],
)
def test_a_non_text_content_is_refused(content):
    # The interface's completion carries text, and the wire answer's message
    # content is where that text comes from; anything else is the vendor's
    # other shapes, which the backend refuses rather than stringifies.
    with pytest.raises(CompletionMalformedError, match="message"):
        _drive(_ok(_answer(content=content)))


def test_an_absent_content_is_refused():
    # A message object with no content key at all is the null case wearing
    # no key, and it is refused with its own spelling of the complaint.
    body = _answer()
    del body["choices"][0]["message"]["content"]

    with pytest.raises(CompletionMalformedError, match="no content"):
        _drive((200, {}, json.dumps(body).encode("utf-8")))


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param({}, id="no-choices"),
        pytest.param({"choices": []}, id="empty-choices"),
        pytest.param({"choices": "no"}, id="choices-not-a-list"),
        pytest.param({"choices": [7]}, id="choice-not-an-object"),
        pytest.param(
            {"choices": [{"finish_reason": "stop", "message": "text"}]},
            id="message-not-an-object",
        ),
    ],
)
def test_an_answer_without_one_object_choice_carrying_a_message_is_refused(answer):
    # The one shape every vendor of the family answers is choices[0], an
    # object whose message is an object; anything less is not a shape a
    # reader can meet later as an IndexError instead of a refusal.
    with pytest.raises(CompletionMalformedError):
        _drive((200, {}, json.dumps(answer).encode("utf-8")))


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param("no-usage-key", id="no-usage-key"),
        pytest.param("null-usage", id="null-usage"),
        pytest.param("prompt-not-a-count", id="prompt-not-a-count"),
        pytest.param("prompt-negative", id="prompt-negative"),
        pytest.param("completion-missing", id="completion-missing"),
    ],
)
def test_a_usage_object_without_two_non_negative_counts_is_refused(kind):
    # The billed figures are what the budget (feature 7) and the cache-rate
    # measurement (feature 200) account with, so a usage object that does
    # not carry both as non-negative ints is refused naming usage rather
    # than invented as zero — a silent zero would understate both.
    body = _answer()
    if kind == "no-usage-key":
        del body["usage"]
    elif kind == "null-usage":
        body["usage"] = None
    elif kind == "prompt-not-a-count":
        body["usage"]["prompt_tokens"] = "12"
    elif kind == "prompt-negative":
        body["usage"]["prompt_tokens"] = -1
    else:
        del body["usage"]["completion_tokens"]

    with pytest.raises(CompletionMalformedError) as raised:
        _drive((200, {}, json.dumps(body).encode("utf-8")))

    assert "usage" in str(raised.value)


def test_an_answer_that_names_no_model_is_refused():
    # The serving model is copied verbatim, and an answer that carries none
    # has nothing to copy: a completion that cannot name its own author is
    # refused by the completion's own guard — the interface's word, not a
    # KeyError a caller would meet later.
    body = _answer()
    del body["model"]

    with pytest.raises(CompletionMalformedError):
        _drive((200, {}, json.dumps(body).encode("utf-8")))


# ── The usage translation: the vendor's own cache-figure shelf ────────────────


@pytest.mark.parametrize("vendor", ["openai", "google"])
def test_openai_and_google_read_the_cache_figure_from_the_details(vendor):
    # openai's and google's OpenAI-compatible layers nest the cached-input
    # figure one level down, inside usage.prompt_tokens_details.cached_tokens
    # — the shelf the table sends them to.
    completion, _ = _drive(
        _ok(
            _answer(
                model=MODELS[vendor],
                usage_extra={"prompt_tokens_details": {"cached_tokens": 90}},
            )
        ),
        vendor=vendor,
    )

    assert completion.usage == Usage(
        input_tokens=12, output_tokens=3, cache_read_tokens=90
    )


def test_deepseek_reads_the_cache_figure_from_its_own_spelling():
    # deepseek shelves the same figure at the top level of usage, under its
    # own name — the one usage field the dialects do not agree on, and the
    # reason the table carries a per-vendor shelf at all.
    completion, _ = _drive(
        _ok(
            _answer(
                model=MODELS["deepseek"],
                usage_extra={"prompt_cache_hit_tokens": 150},
            )
        ),
        vendor="deepseek",
    )

    assert completion.usage == Usage(
        input_tokens=12, output_tokens=3, cache_read_tokens=150
    )


def test_self_hosted_reads_the_cache_figure_from_the_details():
    # A vLLM box answers the OpenAI shape, cache figure included — the
    # self-hosted deployment is the reason the openai spelling is the
    # default shelf and deepseek's the exception.
    completion, _ = _drive(
        _ok(
            _answer(
                model=MODELS["self-hosted"],
                usage_extra={"prompt_tokens_details": {"cached_tokens": 64}},
            )
        ),
        vendor="self-hosted",
        base_url=SELF_HOSTED_BASE,
    )

    assert completion.usage == Usage(
        input_tokens=12, output_tokens=3, cache_read_tokens=64
    )


@pytest.mark.parametrize(
    ("vendor", "base_url"),
    [
        pytest.param("openai", None, id="openai"),
        pytest.param("deepseek", None, id="deepseek"),
        pytest.param("google", None, id="google"),
        pytest.param("self-hosted", SELF_HOSTED_BASE, id="self-hosted"),
    ],
)
def test_an_answer_reporting_no_cache_figure_counts_zero(vendor, base_url):
    # The figure is optional in both spellings: a provider that did not
    # report a cache hit has not earned the caller a number, and the absence
    # of a figure is not a figure — it counts zero, never negative and
    # never invented.
    completion, _ = _drive(
        _ok(_answer(model=MODELS[vendor])), vendor=vendor, base_url=base_url
    )

    assert completion.usage.cache_read_tokens == 0


@pytest.mark.parametrize(
    "usage_extra",
    [
        pytest.param({"prompt_tokens_details": None}, id="null-details"),
        pytest.param({"prompt_tokens_details": {}}, id="empty-details"),
        pytest.param(
            {"prompt_tokens_details": {"cached_tokens": None}}, id="null-figure"
        ),
    ],
)
def test_details_without_a_cached_figure_count_zero(usage_extra):
    # A details object that exists but reports nothing is the same honest
    # absence as no details object at all.
    completion, _ = _drive(_ok(_answer(usage_extra=usage_extra)))

    assert completion.usage.cache_read_tokens == 0


def test_deepseek_reporting_only_the_openai_spelling_counts_zero():
    # The shelf is per-vendor, not first-found: deepseek's figure is
    # prompt_cache_hit_tokens, and a proxy that rewrites its answer into
    # openai's spelling has not reported deepseek's figure — the deployment
    # that wanted that reading wanted a different vendor row.
    completion, _ = _drive(
        _ok(
            _answer(
                model=MODELS["deepseek"],
                usage_extra={"prompt_tokens_details": {"cached_tokens": 90}},
            )
        ),
        vendor="deepseek",
    )

    assert completion.usage.cache_read_tokens == 0


# ── Through the door: the failure vocabulary the backend inherits ─────────────


def test_a_vendor_refusal_surfaces_as_provider_http_error_scrubbed():
    # A 4xx the door does not retry is the vendor's own refusal, and it
    # surfaces through the backend exactly as the door shaped it: the code
    # word, the status on `.status`, and the vendor's message on `.detail` —
    # scrubbed, because a vendor that echoes the bearer token back in its
    # error body has echoed a credential into a text this module renders.
    echo = f"Incorrect API key provided: Bearer {FAKE_KEY}"
    body = json.dumps(
        {"error": {"message": echo, "type": "invalid_request_error"}}
    ).encode("utf-8")
    transport = _transport((401, {}, body))
    provider = _provider(transport=transport)

    with pytest.raises(ProviderHTTPError) as raised:
        provider.complete(_request())

    assert str(raised.value).startswith(f"{PROVIDER_HTTP_CODE}:")
    assert raised.value.status == 401
    assert FAKE_KEY not in str(raised.value)
    assert "***" in raised.value.detail
    assert len(transport.calls) == 1


def test_a_batch_stays_refused_by_the_base_class():
    # Batches are out of scope for the whole addition, and the refusal is
    # the base class's own word rather than a silent one-request-at-a-time
    # fallback — pinned here so the backend never grows a batch by accident.
    transport = _transport(_ok())
    provider = _provider(transport=transport)

    with pytest.raises(NotImplementedBatchError):
        provider.complete_batch(BatchRequest(requests=(_request(),)))

    assert transport.calls == []


# ── The credential never reaches an output ────────────────────────────────────
#
# Two outputs exist — the exception message and the repr — plus the log line
# the door emits.  The tests below drive each ending with the fake key worn
# and hunt for the value in every rendering, while the wire (asserted above,
# exact header equality) carries the real one.


@pytest.mark.parametrize(
    ("vendor", "base_url"),
    [
        pytest.param("openai", None, id="openai"),
        pytest.param("deepseek", None, id="deepseek"),
        pytest.param("google", None, id="google"),
        pytest.param("self-hosted", SELF_HOSTED_BASE, id="self-hosted"),
    ],
)
def test_repr_shows_the_deployment_and_never_the_credential(vendor, base_url):
    # A repr is one of the three places a key must never reach, and the
    # three facts an operator reading one is looking for are the vendor,
    # the model and the destination — the deployment, in other words, with
    # the credential rendered as the same three stars the door uses.
    key = FAKE_LOCAL_KEY if vendor == "self-hosted" else FAKE_KEY
    provider = _provider(vendor, key=key, base_url=base_url)

    rendered = repr(provider)

    assert FAKE_KEY not in rendered
    assert FAKE_LOCAL_KEY not in rendered
    assert vendor in rendered
    assert MODELS[vendor] in rendered
    assert "***" in rendered


@pytest.mark.parametrize(
    "kind",
    [
        "a-refused-host",
        "an-at-once-4xx",
        "a-malformed-answer",
        "an-unknown-model",
    ],
)
def test_the_credential_reaches_no_failure_output(kind):
    # Every ending the backend can meet, with the key worn: the str, the
    # repr and the rendered traceback of the refusal are hunted for the
    # value, so a leak names itself in the assertion it fails.  The 4xx
    # body echoes the bearer token back — the vendor-echo path, the one
    # rendering this module does not build itself and therefore the one
    # most worth pinning through it.
    if kind == "a-refused-host":
        transport = _transport(_ok())
        provider = _provider(
            "openai", base_url="https://api.deepseek.com", transport=transport
        )
        request = _request()
    elif kind == "an-at-once-4xx":
        echo = json.dumps(
            {"error": {"message": f"Bearer {FAKE_KEY}"}}
        ).encode("utf-8")
        transport = _transport((401, {}, echo))
        provider = _provider(transport=transport)
        request = _request()
    elif kind == "a-malformed-answer":
        transport = _transport((200, {}, b"{not json"))
        provider = _provider(transport=transport)
        request = _request()
    else:
        transport = _transport(_ok())
        provider = _provider(transport=transport)
        request = _request(model="gpt-5")

    with pytest.raises(ProviderError) as raised:
        provider.complete(request)

    rendered = "".join(traceback.format_exception(raised.value))
    for text in (str(raised.value), repr(raised.value), rendered):
        assert FAKE_KEY not in text, (kind, text)


def test_the_credential_never_reaches_the_log(caplog):
    # The door logs the headers it sends, in their scrubbed form — the
    # third of the three places a key must never reach, and the one a
    # developer reads first.  The assertion hunts the value and finds the
    # three stars in its place.
    with caplog.at_level(logging.DEBUG, logger="providers.live_http"):
        _drive(_ok())

    assert FAKE_KEY not in caplog.text
    assert "***" in caplog.text
