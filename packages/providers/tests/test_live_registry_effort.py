"""bug_spec_effort_wiring.xml, bug 2: the configured authoring effort reaches Anthropic.

Feature 5 (additions_spec_real_campaign_path.xml) gave
:class:`~providers.AuthoringConfig` an ``effort`` key and
:class:`~providers._anthropic.AnthropicProvider` an ``effort=`` constructor
argument that :func:`providers._anthropic._request_body` sends as
``output_config.effort`` for a no-sampling model — but never wired the two
together: :func:`providers._live.live_provider` built every
``AnthropicProvider`` with no ``effort`` at all, so a deployment that named
one authored at the model's default regardless.

This suite drives the whole path a real campaign takes — an
:class:`~providers.AuthoringSession` over a config naming ``effort: "high"``,
resolved through a fake ``live_provider``-shaped resolver, completing one
call through a recording transport — and reads the Messages-API body the
transport actually saw, never a provider's private state.  No network, no
credential.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from providers import (
    AuthoringConfig,
    AuthoringRecord,
    AuthoringSession,
    Message,
    ModelPin,
    Request,
)
from providers._anthropic import AnthropicProvider, sent_sampling
from providers._live import require_served

#: A fake credential — key-shaped, never real — handed to every provider this
#: suite builds.  It travels to the injected transport and nowhere else.
FAKE_KEY = "fake-ant-key-not-a-credential"

#: One of the per-model sampling table's no-sampling models (feature 5):
#: the vendor rejects ``temperature`` outright and takes ``effort`` instead.
NO_SAMPLING_MODEL = "claude-opus-5-5"

#: The one model the per-model sampling table still sends ``temperature``
#: to — used only by the edge case proving effort is withheld from it.
TEMPERATURE_MODEL = "claude-haiku-4-5"

ROOT_PIN = f"anthropic/{NO_SAMPLING_MODEL}/20260601"
DEPTH_PIN = f"anthropic/{NO_SAMPLING_MODEL}/20260601"
POLICY_PIN = f"anthropic/{NO_SAMPLING_MODEL}/20260601"


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording sends.

    Mirrors ``test_live.py``'s own spy: a test reads the body that left the
    machine off ``.calls`` rather than inferring it from the provider's
    private fields.
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


def _ok(model: str) -> tuple[int, dict[str, str], bytes]:
    """A Messages-API success body naming ``model`` as the serving model."""
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "model": model,
        "usage": {"input_tokens": 3, "output_tokens": 1},
        "stop_reason": "end_turn",
    }
    return 200, {}, json.dumps(body).encode("utf-8")


def _request(model: str) -> Request:
    return Request(
        messages=(Message("user", "author a signal"),),
        model=model,
        temperature=0.0,
        max_tokens=64,
    )


def make_config(**overrides: Any) -> AuthoringConfig:
    """A full authoring config over the one no-sampling model, effort overridable."""
    fields: dict[str, Any] = {
        "root_tier": (ROOT_PIN,),
        "depth": DEPTH_PIN,
        "policy": POLICY_PIN,
        "temperature": None,
        "max_tokens": 4096,
        "max_input_tokens": 1_000_000,
        "max_output_tokens": 1_000_000,
    }
    fields.update(overrides)
    return AuthoringConfig(**fields)


def live_resolve(transport: Any):
    """A resolver of ``live_provider``'s own shape: a pin in, a provider out.

    Imports :func:`providers._live.live_provider` rather than faking a
    provider, so this suite proves the real registry — the one production
    composes through ``providers.LiveProviderResolver.resolve`` — not a
    stand-in that merely agrees with the bug report's wording.  Credentials
    are a fake mapping, never ``os.environ``.
    """
    from providers._live import live_provider

    def resolve(pin: object):
        return live_provider(
            pin, {"NULLIUS_ANTHROPIC_API_KEY": FAKE_KEY}, transport
        )

    return resolve


# ── The request body: effort reaches the wire ────────────────────────────────


def test_a_configured_effort_reaches_output_config_effort():
    transport = _transport(_ok(NO_SAMPLING_MODEL))
    session = AuthoringSession(make_config(effort="high"), live_resolve(transport))
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    provider.complete(_request(pin.model))

    body = json.loads(transport.calls[0]["body"])
    assert body["output_config"] == {"effort": "high"}
    assert "temperature" not in body


def test_no_effort_configured_sends_no_output_config():
    transport = _transport(_ok(NO_SAMPLING_MODEL))
    session = AuthoringSession(make_config(), live_resolve(transport))
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    provider.complete(_request(pin.model))

    body = json.loads(transport.calls[0]["body"])
    assert "output_config" not in body
    assert "temperature" not in body


def test_effort_is_withheld_from_a_model_that_still_takes_temperature():
    # "exactly when the config names [effort] and the model accepts effort":
    # the per-model sampling table (providers._anthropic) marks
    # claude-haiku-4-5 as still taking temperature, and _request_body sends
    # it that field, never output_config, whatever the config's effort says.
    # This wiring does not change that — it threads effort onto every pin,
    # and the backend's own per-model table is what decides whether it ships.
    config = make_config(
        depth=f"anthropic/{TEMPERATURE_MODEL}/20260601",
        policy=f"anthropic/{TEMPERATURE_MODEL}/20260601",
        temperature=0.4,
        effort="high",
    )
    transport = _transport(_ok(TEMPERATURE_MODEL))
    session = AuthoringSession(config, live_resolve(transport))
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    request = Request(
        messages=(Message("user", "author a signal"),),
        model=pin.model,
        temperature=config.temperature,
        max_tokens=64,
    )
    provider.complete(request)

    body = json.loads(transport.calls[0]["body"])
    assert body["temperature"] == 0.4
    assert "output_config" not in body


@pytest.mark.parametrize("role", ["root", "depth", "policy"])
def test_every_role_threads_the_configured_effort(role):
    # Architecture §14.1's three call sites — root_tier, depth and policy —
    # must each resolve a provider that carries the config's effort, not only
    # the one role the bug was first noticed on.
    transport = _transport(_ok(NO_SAMPLING_MODEL))
    session = AuthoringSession(make_config(effort="xhigh"), live_resolve(transport))
    provider, pin = session.provider_for(
        role, campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    provider.complete(_request(pin.model))

    body = json.loads(transport.calls[0]["body"])
    assert body["output_config"] == {"effort": "xhigh"}


def test_the_authored_records_agent_sampling_carries_the_effort():
    # Bug 1's companion fix (signal_agent._llm_author) records exactly what
    # sent_sampling says a no-sampling model's call actually carried — the
    # honest half of feature 5's "never a temperature the vendor did not
    # apply" — so a caller building an AuthoringRecord from this session's
    # completion and the config's own effort must see {"effort": "high"},
    # never the four-key AgentSampling a temperature-accepting call would.
    # The assertion reads the *wire body* the transport actually saw, not
    # just the config's own effort field, so the record is proven to name
    # what was sent rather than merely echo what was configured.
    config = make_config(effort="high")
    transport = _transport(_ok(NO_SAMPLING_MODEL))
    session = AuthoringSession(config, live_resolve(transport))
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    completion = provider.complete(_request(pin.model))
    sent_effort = json.loads(transport.calls[0]["body"])["output_config"]["effort"]

    sampling = sent_sampling(
        pin.model, temperature=config.temperature, effort=config.effort
    )
    record = AuthoringRecord(
        node_id=str(uuid.uuid4()),
        campaign_id=str(uuid.uuid4()),
        depth=2,
        role="depth",
        pin=pin,
        sampling=sampling,
        usage=completion.usage,
        served_model=completion.model,
    )
    assert record.attempt_provenance_terms()["agent_sampling"] == {"effort": sent_effort}
    assert sent_effort == "high"


def test_the_served_model_check_is_unaffected():
    # require_served reads (provider, model, version) off the pin feature 7's
    # caller already has, and is called with exactly that pin and the
    # completion this session's provider answered — proving the wrapping
    # this fix adds never reaches the check feature 4 runs after every call.
    transport = _transport(_ok(NO_SAMPLING_MODEL))
    session = AuthoringSession(make_config(effort="high"), live_resolve(transport))
    provider, pin = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    assert pin == ModelPin.parse(DEPTH_PIN)
    completion = provider.complete(_request(pin.model))
    assert require_served(pin, completion) is completion


def test_the_resolved_provider_is_still_an_anthropic_provider():
    session = AuthoringSession(
        make_config(effort="high"), live_resolve(_transport(_ok(NO_SAMPLING_MODEL)))
    )
    provider, _ = session.provider_for(
        "depth", campaign_id=str(uuid.uuid4()), node_id=str(uuid.uuid4())
    )
    # BudgetedProvider wraps the live backend; unwrap one layer to confirm
    # the registry still built the right backend class, not a stand-in.
    assert isinstance(provider._inner, AnthropicProvider)
