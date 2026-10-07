"""Feature 5's suite: only the sampling controls a Claude model actually accepts.

additions_spec_real_campaign_path.xml, "Campaign Evaluation Path", feature 5:
*System sends Claude models only the sampling controls each model accepts, so
authoring calls to claude-opus-5-5 and claude-sonnet-5-5 return 200 instead of
the 400 "`temperature` is deprecated for this model".*  An operator's real
deployment discovered that the live backend (:mod:`providers._anthropic`)
unconditionally sent ``temperature``, and two of the models architecture
§14.1's roots row recommends answer HTTP 400 to it at any value.  This suite
pins the fix at four seams:

* the per-model sampling table's wire effect, through a recording transport —
  one request body per model class, and an unrecognised model's safe default
  (and its one log line);
* :func:`providers._anthropic.sent_sampling` — the "what was actually sent"
  answer a caller reads instead of the raw config knobs;
* :class:`providers.AuthoringRecord`'s widened ``sampling`` field — an
  :class:`providers.AgentSampling` for a temperature-accepting model's call,
  unchanged, or :func:`sent_sampling`'s own mapping for a no-sampling one, so
  ``attempt_provenance_terms()['agent_sampling']`` never claims a temperature
  the vendor did not apply;
* :class:`providers.AuthoringConfig`'s new ``effort`` key and its
  ``temperature`` becoming optional;
* the load-time refusal — :class:`providers._authoring.UnsupportedSamplingError`
  — for a ``depth`` or ``policy`` pin that cannot honour a stated temperature,
  scoped away from ``root_tier``'s rotation.

No test here opens a socket or reads a credential: every live call is driven
through an injected transport exactly like :mod:`test_anthropic`'s own, and
every config is built in memory or from a ``tmp_path`` file.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
from providers import (
    AgentSampling,
    AuthoringConfig,
    AuthoringConfigError,
    AuthoringRecord,
    Usage,
)
from providers._anthropic import (
    EFFORT_LEVELS,
    NO_SAMPLING_MODE,
    AnthropicProvider,
    sent_sampling,
)
from providers._authoring import UNSUPPORTED_SAMPLING_CODE, UnsupportedSamplingError

#: A fake credential — never a real one, and never sent anywhere this suite
#: could leak it to, since every transport here is a recording fake.
FAKE_KEY = "fake-ant-key-not-a-credential"

#: One model from each class the per-model sampling table (documented in
#: providers._anthropic's module docstring, source date 2026-10-06) names.
NO_SAMPLING_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-sonnet-5")
FABLE_MODEL = "claude-fable-5-1"
TEMPERATURE_MODEL = "claude-haiku-4-5"
UNKNOWN_MODEL = "claude-nonexistent-9"


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording every call.

    The same shape :mod:`test_anthropic`'s own double takes: each script
    entry is a ``(status, headers, body)`` answer, and the calls list is the
    backend seen from outside.
    """
    calls: list[dict[str, Any]] = []

    def _send(url: str, headers: dict[str, str], body_bytes: bytes, timeout: float):
        calls.append({"url": url, "headers": dict(headers), "body": body_bytes, "timeout": timeout})
        answer = script[min(len(calls), len(script)) - 1]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    _send.calls = calls
    return _send


def _answer(model: str, **overrides: Any) -> tuple[int, dict[str, str], bytes]:
    """A 2xx Messages-API success body naming ``model`` as the server."""
    body: dict[str, Any] = {
        "content": [{"type": "text", "text": "ok"}],
        "model": model,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }
    body.update(overrides)
    return 200, {}, json.dumps(body).encode("utf-8")


def _sent_body(transport: Any, call: int = 0) -> dict[str, Any]:
    return json.loads(transport.calls[call]["body"])


# ── The wire: one body per model class ─────────────────────────────────────────


@pytest.mark.parametrize("model", NO_SAMPLING_MODELS)
def test_a_no_sampling_model_carries_no_temperature(make_request, model):
    # claude-opus-5-5 and claude-sonnet-5-5 are the two models an operator
    # verified answer HTTP 400 to temperature; their dateless siblings share
    # the table's entry.  None of the four ever see the field.
    transport = _transport(_answer(model))
    provider = AnthropicProvider(FAKE_KEY, model=model, transport=transport)

    provider.complete(make_request(model=model, temperature=0.9))

    body = _sent_body(transport)
    assert "temperature" not in body
    assert "top_p" not in body
    assert "top_k" not in body
    assert "output_config" not in body


def test_the_fable_family_is_matched_by_prefix_not_enumerated(make_request):
    # The Fable family shares the 5.x generation's restriction, matched by
    # the "claude-fable-" prefix rather than one entry per snapshot.
    transport = _transport(_answer(FABLE_MODEL))
    provider = AnthropicProvider(FAKE_KEY, model=FABLE_MODEL, transport=transport)

    provider.complete(make_request(model=FABLE_MODEL, temperature=0.9))

    assert "temperature" not in _sent_body(transport)


def test_a_no_sampling_model_carries_effort_when_the_caller_named_one(make_request):
    transport = _transport(_answer("claude-opus-5-5"))
    provider = AnthropicProvider(
        FAKE_KEY, model="claude-opus-5-5", effort="high", transport=transport
    )

    provider.complete(make_request(model="claude-opus-5-5", temperature=0.9))

    body = _sent_body(transport)
    assert "temperature" not in body
    assert body["output_config"] == {"effort": "high"}


def test_a_no_sampling_model_carries_no_output_config_when_no_effort_is_named(make_request):
    # An empty output_config is a statement the vendor would have to
    # interpret; absent effort means the key is omitted outright.
    transport = _transport(_answer("claude-opus-5-5"))
    provider = AnthropicProvider(FAKE_KEY, model="claude-opus-5-5", transport=transport)

    provider.complete(make_request(model="claude-opus-5-5"))

    assert "output_config" not in _sent_body(transport)


def test_a_temperature_model_is_unaffected_by_the_table(make_request):
    # claude-haiku-4-5 keeps exactly the pre-feature-5 behaviour: temperature
    # travels, and an effort the provider was built with is never sent to a
    # model that has no slot for it.
    transport = _transport(_answer(TEMPERATURE_MODEL))
    provider = AnthropicProvider(
        FAKE_KEY, model=TEMPERATURE_MODEL, effort="high", transport=transport
    )

    provider.complete(make_request(model=TEMPERATURE_MODEL, temperature=0.4))

    body = _sent_body(transport)
    assert body["temperature"] == 0.4
    assert "output_config" not in body


def test_an_unknown_model_falls_through_to_no_sampling_and_is_logged_once(
    make_request, caplog
):
    # The safe default: a model this table has no entry for withholds
    # temperature rather than risk an HTTP 400, and the fallback is logged
    # exactly once for the one request that triggered it.
    transport = _transport(_answer(UNKNOWN_MODEL))
    provider = AnthropicProvider(FAKE_KEY, model=UNKNOWN_MODEL, transport=transport)

    with caplog.at_level(logging.WARNING, logger="providers._anthropic"):
        provider.complete(make_request(model=UNKNOWN_MODEL, temperature=0.9))

    assert "temperature" not in _sent_body(transport)
    warnings = [r for r in caplog.records if UNKNOWN_MODEL in r.getMessage()]
    assert len(warnings) == 1
    assert NO_SAMPLING_MODE in warnings[0].getMessage()


def test_an_invalid_effort_is_refused_at_construction():
    with pytest.raises(ValueError) as refusal:
        AnthropicProvider(FAKE_KEY, model="claude-opus-5-5", effort="extreme")

    assert "extreme" in str(refusal.value)
    assert sorted(EFFORT_LEVELS) == ["high", "low", "max", "medium", "xhigh"]


# ── sent_sampling: what was actually sent ───────────────────────────────────────


def test_sent_sampling_drops_temperature_for_a_no_sampling_model():
    assert sent_sampling("claude-opus-5-5", temperature=0.7, effort="high") == {
        "effort": "high"
    }


def test_sent_sampling_is_empty_for_a_no_sampling_model_with_no_effort():
    assert sent_sampling("claude-opus-5-5", temperature=0.7) == {}


def test_sent_sampling_keeps_temperature_for_a_temperature_model():
    assert sent_sampling(TEMPERATURE_MODEL, temperature=0.4, effort="high") == {
        "temperature": 0.4
    }


def test_sent_sampling_is_empty_for_a_temperature_model_with_no_temperature():
    assert sent_sampling(TEMPERATURE_MODEL) == {}


def test_sent_sampling_treats_an_unknown_model_as_no_sampling():
    assert sent_sampling(UNKNOWN_MODEL, temperature=0.7, effort="max") == {"effort": "max"}


def test_sent_sampling_never_invents_a_temperature_the_vendor_did_not_apply():
    # The honest half of the feature's own sentence: a caller asking what a
    # no-sampling model's call rolled never reads a temperature back, however
    # the caller's own config was set.
    for temperature in (0.0, 0.5, 1.0, 2.0):
        assert "temperature" not in sent_sampling(
            "claude-sonnet-5-5", temperature=temperature
        )


# ── AuthoringConfig: effort, and temperature made optional ─────────────────────

#: A full, otherwise-ordinary document this suite's config tests start from —
#: distinct providers for depth and policy so an individual test's override of
#: one does not collide with the sampling-table check on the other.
_ROOT_PINS = (
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)
_DEEPSEEK_DEPTH = "deepseek/deepseek-v4-flash/20260910"
_GOOGLE_POLICY = "google/gemini-3.1-pro/20260801"


def _document(**overrides: Any) -> dict:
    base = {
        "root_tier": list(_ROOT_PINS),
        "depth": _DEEPSEEK_DEPTH,
        "policy": _GOOGLE_POLICY,
        "max_input_tokens": 60000,
        "max_output_tokens": 8192,
    }
    base.update(overrides)
    return base


def test_effort_is_accepted_from_the_closed_set():
    for level in sorted(EFFORT_LEVELS):
        config = AuthoringConfig.from_document(_document(effort=level))
        assert config.effort == level


def test_effort_outside_the_closed_set_is_refused_by_name():
    with pytest.raises(AuthoringConfigError) as raised:
        AuthoringConfig.from_document(_document(effort="ultra"))

    assert "ultra" in str(raised.value)
    assert "effort" in str(raised.value)


def test_effort_defaults_to_none_when_the_document_omits_it():
    config = AuthoringConfig.from_document(_document())
    assert config.effort is None


def test_temperature_explicitly_null_is_accepted_and_sends_nothing():
    config = AuthoringConfig.from_document(_document(temperature=None))
    assert config.temperature is None


def test_an_omitted_temperature_still_defaults_as_before():
    # Omitting the key and stating null are different statements: omitting it
    # is the pre-feature-5 default, and only an explicit null means "this
    # deployment turns no temperature knob at all".
    config = AuthoringConfig.from_document(_document())
    assert config.temperature == 0.7


# ── The load-time refusal: depth and policy, never root_tier ────────────────────


def test_a_depth_pin_that_rejects_temperature_is_refused_at_load():
    pin = "anthropic/claude-opus-5-5/20260901"

    with pytest.raises(UnsupportedSamplingError) as raised:
        AuthoringConfig.from_document(_document(depth=pin, temperature=0.7))

    message = str(raised.value)
    assert message.startswith(f"{UNSUPPORTED_SAMPLING_CODE}: ")
    assert pin in message
    assert "depth" in message


def test_a_policy_pin_that_rejects_temperature_is_refused_at_load():
    pin = "anthropic/claude-sonnet-5-5/20260901"

    with pytest.raises(UnsupportedSamplingError) as raised:
        AuthoringConfig.from_document(_document(policy=pin, temperature=0.7))

    message = str(raised.value)
    assert message.startswith(f"{UNSUPPORTED_SAMPLING_CODE}: ")
    assert pin in message
    assert "policy" in message


def test_the_refusal_is_also_an_authoring_config_error():
    # A caller catching the module's base catches this refusal too — the
    # code word is this class's own, but the taxonomy is one.
    with pytest.raises(AuthoringConfigError):
        AuthoringConfig.from_document(
            _document(depth="anthropic/claude-opus-5-5/20260901", temperature=0.7)
        )


def test_stating_no_temperature_admits_a_no_sampling_depth_pin():
    config = AuthoringConfig.from_document(
        _document(depth="anthropic/claude-opus-5-5/20260901", temperature=None, effort="high")
    )

    assert config.depth.model == "claude-opus-5-5"
    assert config.temperature is None
    assert config.effort == "high"


def test_a_no_sampling_model_in_root_tier_alone_is_not_refused():
    # root_tier is a rotation across 2-3 providers; a single global
    # temperature being incompatible with *one* member of a heterogeneous
    # tier is not the same unambiguous contradiction a fixed depth or policy
    # pin states, and providers._anthropic already withholds the field from
    # whichever member cannot take it the moment that root is authored.
    config = AuthoringConfig.from_document(
        _document(root_tier=["anthropic/claude-opus-5-5/20260901", *_ROOT_PINS])
    )

    assert config.temperature == 0.7
    assert config.root_tier[0].model == "claude-opus-5-5"


def test_a_temperature_model_pinned_for_depth_or_policy_is_never_refused():
    config = AuthoringConfig.from_document(
        _document(depth="anthropic/claude-haiku-4-5/20260401")
    )

    assert config.temperature == 0.7
    assert config.depth.model == "claude-haiku-4-5"


def test_an_unsupported_sampling_error_names_its_own_code():
    assert UNSUPPORTED_SAMPLING_CODE == "unsupported_sampling"
    error = UnsupportedSamplingError("a message")
    assert error.code == "unsupported_sampling"
    assert str(error) == "unsupported_sampling: a message"
    assert isinstance(error, AuthoringConfigError)


# ── AuthoringRecord: the recorded agent_sampling holds what was actually sent ───


def _record(**overrides: Any) -> AuthoringRecord:
    fields: dict[str, Any] = {
        "node_id": "11111111-1111-1111-1111-111111111111",
        "campaign_id": "22222222-2222-2222-2222-222222222222",
        "depth": 2,
        "role": "depth",
        "pin": "anthropic/claude-opus-5-5/20260901",
        "sampling": AgentSampling(),
        "usage": Usage(input_tokens=10, output_tokens=5),
        "served_model": "claude-opus-5-5",
    }
    fields.update(overrides)
    return AuthoringRecord(**fields)


def test_a_no_sampling_calls_record_carries_what_was_actually_sent():
    # The record is built from sent_sampling's own answer, so the node's
    # recorded agent_sampling is the effort that was actually rolled, and it
    # is recognisably not the four-key record — there is no temperature in
    # it to misread as applied.
    payload = sent_sampling("claude-opus-5-5", temperature=0.7, effort="high")
    record = _record(sampling=payload)

    assert record.sampling == {"effort": "high"}
    assert record.attempt_provenance_terms()["agent_sampling"] == {"effort": "high"}


def test_a_no_sampling_call_with_no_effort_records_an_empty_payload():
    payload = sent_sampling("claude-opus-5-5", temperature=0.7)
    record = _record(sampling=payload)

    assert record.sampling == {}
    assert record.attempt_provenance_terms()["agent_sampling"] == {}


def test_a_temperature_models_record_is_unchanged_by_the_feature():
    # Backward compatibility: a call a temperature-accepting model served
    # still rolls (and records) all four of feature 204's settings, and the
    # record still normalizes it into an AgentSampling exactly as before.
    record = _record(
        pin="anthropic/claude-haiku-4-5/20260401",
        served_model="claude-haiku-4-5",
        sampling=AgentSampling(temperature=0.4),
    )

    assert isinstance(record.sampling, AgentSampling)
    assert record.sampling == AgentSampling(temperature=0.4)
    assert record.attempt_provenance_terms()["agent_sampling"] == {
        "temperature": 0.4,
        "top_p": 1.0,
        "thinking": False,
        "seed": 0,
    }


def test_a_duck_typed_four_key_mapping_still_normalizes_into_agentsampling():
    # The exact four-key mapping shape is feature 204's own record, however
    # it arrives, and is still judged (and re-made) by its full rules —
    # unaffected by feature 5's widening to a general mapping.
    record = _record(
        sampling={"temperature": 0.4, "top_p": 1.0, "thinking": False, "seed": 0}
    )

    assert isinstance(record.sampling, AgentSampling)
    assert record.sampling == AgentSampling(temperature=0.4)


def test_a_record_sampling_that_is_not_a_mapping_is_refused():
    with pytest.raises(AuthoringConfigError):
        _record(sampling=42)


def test_a_record_sampling_that_cannot_round_trip_as_json_is_refused():
    with pytest.raises(AuthoringConfigError):
        _record(sampling={"effort": "high", "nan": float("nan")})
