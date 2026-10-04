"""The registry: a pin in, a bound live provider out, and a served-model check.

The live-providers addition's fourth feature is the seam between a pinned
model (feature 203's ``provider/model/version`` triple) and the two live
backends (features 2 and 3).  These tests pin the three things that seam
decides itself: the **dispatch** (the pin's vendor chooses the backend, the
wire model is the pin's model and the version is provenance the provider never
sees), the **credential lookup** (one ``NULLIUS_``-prefixed variable per
vendor, a missing or empty one refused naming the variable and never its
value, and the bare ``ANTHROPIC_API_KEY`` a research member must never read)
and the **served-model check** (``require_served`` admitting the pinned model
or a dash-suffixed snapshot of it and refusing any other serving model with
the ``served_model_mismatch`` code word).

No test here opens a socket.  Where a test needs to watch a call leave the
machine it injects feature 1's transport — a callable answering from a script
and recording every send — so what left is read off the spy's call list
rather than inferred, and the keys are fake and key-shaped so the scrubbing
assertions hunt for a value that would be a real leak if it were ever
rendered.  The environment is always a mapping handed to ``live_provider``
(or a monkeypatched ``os.environ``), never the ambient one.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from providers import (
    Completion,
    Message,
    ModelPin,
    Provider,
    ProviderError,
    ProviderNotConfiguredError,
    Request,
    Usage,
)
from providers._anthropic import AnthropicProvider
from providers._live import (
    LIVE_PROVIDER_ENV_VARS,
    SELF_HOSTED_API_KEY_ENV,
    SELF_HOSTED_BASE_URL_ENV,
    SERVED_MODEL_MISMATCH_CODE,
    ServedModelMismatchError,
    live_provider,
    require_served,
)
from providers._openai_compat import OpenAICompatProvider

# ── The script a test drives the registry with ────────────────────────────────

#: Fake credentials — key-shaped, not key-real.  Neither would open a door
#: anywhere; the point is that a suite can hunt for the literal value in every
#: rendering and prove it never escaped.
FAKE_KEY = "fake-nullius-key-not-a-credential"
FAKE_LOCAL_KEY = "fake-local-key-not-a-credential"

#: The model and snapshot a suite pin names.  One hosted vendor (anthropic)
#: and one OpenAI-compatible vendor (deepseek) cover the two backends; the
#: dash-suffixed sibling is the pin's own dated snapshot, the one spelling
#: ``require_served`` must admit alongside the bare model name.
PIN = ModelPin("anthropic", "claude-opus-5", "20260401")
DEEPSEEK_PIN = ModelPin("deepseek", "deepseek-chat", "20260401")

#: A self-hosted base URL: loopback over http, the one plaintext destination
#: feature 1's door serves, standing in for the vLLM box a deployment runs.
SELF_HOSTED_BASE = "http://localhost:8000/v1"

#: The variable names, spelled once so an assertion that a refusal *names* one
#: compares against the same string the module reads.
ANTHROPIC_KEY_ENV = "NULLIUS_ANTHROPIC_API_KEY"
DEEPSEEK_KEY_ENV = "NULLIUS_DEEPSEEK_API_KEY"


def _anthropic_answer(model: str = "claude-opus-5") -> dict[str, Any]:
    """A Messages-API success body carrying ``model`` as the serving model."""
    return {
        "content": [{"type": "text", "text": "ok"}],
        "model": model,
        "usage": {"input_tokens": 3, "output_tokens": 1},
        "stop_reason": "end_turn",
    }


def _openai_answer(model: str = "deepseek-chat") -> dict[str, Any]:
    """A chat-completions success body carrying ``model`` as the serving model."""
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
        ],
        "model": model,
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }


def _ok(body: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
    """A 2xx transport answer carrying ``body`` as UTF-8 JSON."""
    return 200, {}, json.dumps(body).encode("utf-8")


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording sends.

    The calls list is the backend seen from outside — URL, headers and body
    bytes of every send — which is how a test reads what left the machine
    without opening a socket.  When the script runs out the last entry
    repeats.
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


def _request(model: str) -> Request:
    """The one-ask request a test sends through a built provider."""
    return Request(
        messages=(Message("user", "Reply with the single word: ok"),),
        model=model,
        temperature=0.0,
        max_tokens=16,
    )


# ── LIVE_PROVIDER_ENV_VARS: the vendor table as data ──────────────────────────


def test_env_var_mapping_names_one_variable_per_vendor():
    """Every vendor the addition serves has exactly one required variable."""
    assert dict(LIVE_PROVIDER_ENV_VARS) == {
        "anthropic": ANTHROPIC_KEY_ENV,
        "openai": "NULLIUS_OPENAI_API_KEY",
        "deepseek": DEEPSEEK_KEY_ENV,
        "google": "NULLIUS_GOOGLE_API_KEY",
        "self-hosted": SELF_HOSTED_BASE_URL_ENV,
    }


def test_env_var_mapping_is_read_only():
    """The table is a fact of the deployment, not configuration a caller tunes."""
    with pytest.raises(TypeError):
        LIVE_PROVIDER_ENV_VARS["extra"] = "NULLIUS_EXTRA"  # type: ignore[index]


def test_every_exported_variable_carries_the_nullius_prefix():
    """The prefix is what keeps the research keys apart from claw-forge's own."""
    assert all(name.startswith("NULLIUS_") for name in LIVE_PROVIDER_ENV_VARS.values())
    assert all("ANTHROPIC_API_KEY" != name for name in LIVE_PROVIDER_ENV_VARS.values())


# ── Dispatch: the pin's vendor chooses the backend ────────────────────────────


def test_anthropic_pin_answers_an_anthropic_provider():
    """``anthropic`` is the one vendor the Messages backend covers."""
    provider = live_provider(PIN, {ANTHROPIC_KEY_ENV: FAKE_KEY})
    assert isinstance(provider, AnthropicProvider)
    assert isinstance(provider, Provider)


@pytest.mark.parametrize("vendor", ["openai", "deepseek", "google"])
def test_openai_compatible_pins_answer_an_openai_compat_provider(vendor):
    """The three hosted clones all route to the one chat-completions backend."""
    provider = live_provider(
        ModelPin(vendor, "some-model", "20260401"),
        {LIVE_PROVIDER_ENV_VARS[vendor]: FAKE_KEY},
    )
    assert isinstance(provider, OpenAICompatProvider)
    # The table's own variable was read and no other: the provider built.
    assert vendor in repr(provider)


def test_self_hosted_pin_answers_an_openai_compat_provider_with_its_own_host():
    """Self-hosted is the one vendor whose destination comes from the environment."""
    provider = live_provider(
        ModelPin("self-hosted", "qwen3-32b", "20260401"),
        {SELF_HOSTED_BASE_URL_ENV: SELF_HOSTED_BASE},
    )
    assert isinstance(provider, OpenAICompatProvider)
    assert SELF_HOSTED_BASE in repr(provider)


def test_wire_model_is_the_pin_model_and_the_version_is_not_sent():
    """The version is provenance, never a part of the wire model."""
    provider = live_provider(DEEPSEEK_PIN, {DEEPSEEK_KEY_ENV: FAKE_KEY})
    # check_model admits exactly pin.model — not "model/version", not the
    # version on its own — which is the provider's own statement of what it
    # will put on the wire.
    assert provider.check_model("deepseek-chat") == "deepseek-chat"
    assert provider.check_model(DEEPSEEK_PIN.model) == DEEPSEEK_PIN.model


def test_provider_refuses_a_model_the_pin_did_not_name():
    """A live backend is built for one model, and the pin's model is that one."""
    provider = live_provider(PIN, {ANTHROPIC_KEY_ENV: FAKE_KEY})
    with pytest.raises(ProviderError):
        provider.check_model("some-other-model")


def test_unknown_vendor_is_refused_naming_the_vendors():
    """A vendor nobody taught a backend for is a configuration to fix."""
    with pytest.raises(ProviderNotConfiguredError) as caught:
        live_provider(ModelPin("mystery-vendor", "m", "1"), {})
    message = str(caught.value)
    assert "mystery-vendor" in message
    assert "anthropic" in message and "self-hosted" in message


def test_a_value_without_the_three_parts_is_refused():
    """A pin is recognised by its three parts, and a non-pin names no vendor."""
    with pytest.raises(ProviderNotConfiguredError):
        live_provider("deepseek-chat", {DEEPSEEK_KEY_ENV: FAKE_KEY})


def test_a_pin_with_a_blank_part_is_refused():
    """A blank part cannot choose a backend or name a wire model."""
    blank = type("Blank", (), {"provider": "openai", "model": "", "version": "1"})()
    with pytest.raises(ProviderNotConfiguredError):
        live_provider(blank, {"NULLIUS_OPENAI_API_KEY": FAKE_KEY})


# ── Credentials: named, never rendered ────────────────────────────────────────


@pytest.mark.parametrize(
    "vendor,var",
    [
        ("anthropic", ANTHROPIC_KEY_ENV),
        ("openai", "NULLIUS_OPENAI_API_KEY"),
        ("deepseek", DEEPSEEK_KEY_ENV),
        ("google", "NULLIUS_GOOGLE_API_KEY"),
        ("self-hosted", SELF_HOSTED_BASE_URL_ENV),
    ],
)
def test_missing_required_variable_is_refused_naming_it(vendor, var):
    """An absent variable is a deployment gap named by the variable."""
    with pytest.raises(ProviderNotConfiguredError) as caught:
        live_provider(ModelPin(vendor, "m", "1"), {})
    assert var in str(caught.value)


@pytest.mark.parametrize(
    "vendor,var",
    [
        ("anthropic", ANTHROPIC_KEY_ENV),
        ("openai", "NULLIUS_OPENAI_API_KEY"),
        ("deepseek", DEEPSEEK_KEY_ENV),
        ("google", "NULLIUS_GOOGLE_API_KEY"),
        ("self-hosted", SELF_HOSTED_BASE_URL_ENV),
    ],
)
def test_empty_required_variable_is_refused_the_same_way(vendor, var):
    """An empty value is the same gap as an absent one."""
    with pytest.raises(ProviderNotConfiguredError) as caught:
        live_provider(ModelPin(vendor, "m", "1"), {var: ""})
    assert var in str(caught.value)


def test_refusal_never_renders_the_value():
    """The refusal names the variable, never what a *different* variable held.

    The empty-value refusal is provoked with one variable blank while a
    key-shaped secret sits in another, so the message is byte-for-byte a
    place where a careless implementation could have printed a credential.
    """
    secret = "not-a-real-secret-please-do-not-print"
    with pytest.raises(ProviderNotConfiguredError) as caught:
        live_provider(PIN, {ANTHROPIC_KEY_ENV: "", "OPENAI_API_KEY": secret})
    assert ANTHROPIC_KEY_ENV in str(caught.value)
    assert secret not in str(caught.value)


def test_env_defaults_to_os_environ(monkeypatch):
    """``env=None`` reads the process environment at call time."""
    monkeypatch.setenv(ANTHROPIC_KEY_ENV, FAKE_KEY)
    provider = live_provider(PIN)
    assert isinstance(provider, AnthropicProvider)


def test_bare_anthropic_api_key_is_never_read(monkeypatch):
    """claw-forge's own ANTHROPIC_API_KEY is invisible to this module."""
    monkeypatch.delenv(ANTHROPIC_KEY_ENV, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claw-forge-harness-key")
    with pytest.raises(ProviderNotConfiguredError) as caught:
        live_provider(PIN)
    assert ANTHROPIC_KEY_ENV in str(caught.value)
    assert "claw-forge-harness-key" not in str(caught.value)


def test_self_hosted_key_is_optional():
    """A lab box behind no auth is a real deployment."""
    provider = live_provider(
        ModelPin("self-hosted", "qwen3-32b", "20260401"),
        {SELF_HOSTED_BASE_URL_ENV: SELF_HOSTED_BASE},
    )
    assert isinstance(provider, OpenAICompatProvider)


def test_self_hosted_optional_key_is_read_when_present():
    """When the box does ask for a key, the optional variable is the one read."""
    transport = _transport(_ok(_openai_answer("qwen3-32b")))
    provider = live_provider(
        ModelPin("self-hosted", "qwen3-32b", "20260401"),
        {SELF_HOSTED_BASE_URL_ENV: SELF_HOSTED_BASE, SELF_HOSTED_API_KEY_ENV: FAKE_LOCAL_KEY},
        transport,
    )
    provider.complete(_request("qwen3-32b"))
    assert transport.calls[0]["headers"]["authorization"] == f"Bearer {FAKE_LOCAL_KEY}"


def test_self_hosted_absent_key_sends_no_authorization_header():
    """An empty key means no ``Authorization`` header at all, not a blank one."""
    transport = _transport(_ok(_openai_answer("qwen3-32b")))
    provider = live_provider(
        ModelPin("self-hosted", "qwen3-32b", "20260401"),
        {SELF_HOSTED_BASE_URL_ENV: SELF_HOSTED_BASE},
        transport,
    )
    provider.complete(_request("qwen3-32b"))
    assert "authorization" not in transport.calls[0]["headers"]


# ── The transport is passed through and no socket is opened ───────────────────


def test_transport_is_passed_through_to_the_anthropic_backend():
    """The injected transport is the seam every live test drives."""
    transport = _transport(_ok(_anthropic_answer("claude-opus-5")))
    provider = live_provider(PIN, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport)
    completion = provider.complete(_request("claude-opus-5"))
    assert completion.model == "claude-opus-5"
    assert len(transport.calls) == 1
    assert transport.calls[0]["headers"]["x-api-key"] == FAKE_KEY


def test_transport_is_passed_through_to_the_openai_backend():
    """The OpenAI-compatible backend gets the same injected seam."""
    transport = _transport(_ok(_openai_answer("deepseek-chat")))
    provider = live_provider(DEEPSEEK_PIN, {DEEPSEEK_KEY_ENV: FAKE_KEY}, transport)
    completion = provider.complete(_request("deepseek-chat"))
    assert completion.model == "deepseek-chat"
    assert transport.calls[0]["headers"]["authorization"] == f"Bearer {FAKE_KEY}"


# ── require_served: the §14.1 check ───────────────────────────────────────────


def _completion(model: str) -> Completion:
    """A minimal completion carrying ``model`` as its serving model."""
    return Completion(content="ok", model=model, usage=Usage(input_tokens=1, output_tokens=1))


def test_exact_pin_model_is_admitted_unchanged():
    """The named model is the pinned model, and the completion is returned as-is."""
    completion = _completion(PIN.model)
    assert require_served(PIN, completion) is completion


def test_different_model_is_refused_with_the_code_word():
    """A vendor quietly serving another model is the finding this check exists for."""
    with pytest.raises(ServedModelMismatchError) as caught:
        require_served(DEEPSEEK_PIN, _completion("deepseek-v4.1-flash"))
    assert caught.value.code == SERVED_MODEL_MISMATCH_CODE
    assert str(caught.value).startswith(SERVED_MODEL_MISMATCH_CODE)
    assert str(caught.value).startswith("served_model_mismatch:")


def test_refusal_names_both_the_asked_and_served_model():
    """The operator reading the refusal sees both sides of the mismatch."""
    with pytest.raises(ServedModelMismatchError) as caught:
        require_served(DEEPSEEK_PIN, _completion("deepseek-v4.1-flash"))
    message = str(caught.value)
    assert "deepseek-chat" in message and "deepseek-v4.1-flash" in message


def test_exact_pin_model_and_version_snapshot_is_admitted():
    """``pin.model-pin.version`` is the dated snapshot the pin names, admitted."""
    snapshot = f"{PIN.model}-{PIN.version}"
    assert require_served(PIN, _completion(snapshot)) is not None


def test_a_different_dated_snapshot_is_refused():
    """A vendor serving a *different* snapshot of the same line is the §14.1 swap.

    A completion named ``pin.model`` plus some other date is not the pinned
    snapshot, so it must be refused rather than folded into "any suffix".
    """
    with pytest.raises(ServedModelMismatchError):
        require_served(PIN, _completion(f"{PIN.model}-20270101"))


def test_a_preview_suffix_is_refused():
    """A vendor-invented suffix like ``-preview`` is not the pinned snapshot."""
    with pytest.raises(ServedModelMismatchError):
        require_served(PIN, _completion(f"{PIN.model}-preview"))


def test_a_trailing_dash_with_no_version_is_refused():
    """An empty suffix after the dash is not the pinned version either."""
    with pytest.raises(ServedModelMismatchError):
        require_served(PIN, _completion(f"{PIN.model}-"))


def test_a_case_variant_of_the_snapshot_is_refused():
    """The comparison is exact, so a case variant is not the pinned snapshot."""
    with pytest.raises(ServedModelMismatchError):
        require_served(PIN, _completion(f"{PIN.model}-{PIN.version}".upper()))


def test_a_prefix_without_the_dash_is_not_the_same_line():
    """``gpt-5mini`` is not ``gpt-5`` — the separator is what makes a snapshot."""
    pin = ModelPin("openai", "gpt-5", "20260401")
    with pytest.raises(ServedModelMismatchError):
        require_served(pin, _completion("gpt-5mini"))


def test_a_completion_missing_its_serving_model_is_refused():
    """The serving model is the whole evidence, so an absent one cannot be checked."""
    nameless = type("Nameless", (), {"model": None})()
    with pytest.raises(ServedModelMismatchError):
        require_served(PIN, nameless)


def test_the_same_check_applies_to_every_vendor():
    """The check is the pin's, not the backend's — it runs identically everywhere."""
    for pin in (PIN, DEEPSEEK_PIN, ModelPin("google", "gemini-3-flash", "1")):
        assert require_served(pin, _completion(pin.model)) is not None
        with pytest.raises(ServedModelMismatchError):
            require_served(pin, _completion("not-" + pin.model))


def test_require_served_refuses_a_non_pin():
    """The check reads the pin's model, so a value without one is refused."""
    with pytest.raises(ProviderNotConfiguredError):
        require_served("claude-opus-5", _completion("claude-opus-5"))


# ── The key never reaches a rendering ─────────────────────────────────────────


def test_the_key_never_reaches_a_repr():
    """A provider printed into a log line arrives masked."""
    provider = live_provider(PIN, {ANTHROPIC_KEY_ENV: FAKE_KEY})
    assert FAKE_KEY not in repr(provider)
    assert "***" in repr(provider)


def test_the_key_never_reaches_stdout_or_stderr(capsys):
    """Building and driving the provider prints nothing carrying the key."""
    transport = _transport(_ok(_anthropic_answer("claude-opus-5")))
    provider = live_provider(PIN, {ANTHROPIC_KEY_ENV: FAKE_KEY}, transport)
    provider.complete(_request("claude-opus-5"))
    captured = capsys.readouterr()
    assert FAKE_KEY not in captured.out
    assert FAKE_KEY not in captured.err


def test_a_mismatch_refusal_never_renders_a_key():
    """A served-model refusal quotes models, never credentials."""
    with pytest.raises(ServedModelMismatchError) as caught:
        require_served(DEEPSEEK_PIN, _completion("another-model"))
    assert FAKE_KEY not in str(caught.value)
