"""The request object — the one ask every call sends.

The normalized request: an ordered conversation of messages with closed-set
roles, a model, and two sampling knobs, validated on construction.  These
tests assert the shape holds itself and that a request compares equal to a
recorded one — how the recording layer keys a fixture by "the prompt asked".
"""

from __future__ import annotations

import pytest
from providers import CompletionMalformedError, Message, Request


def test_a_request_carries_its_conversation_and_model():
    request = Request(
        messages=(
            Message(role="system", content="be brief"),
            Message(role="user", content="hi"),
        ),
        model="test-model",
        temperature=0.5,
        max_tokens=128,
    )

    assert request.model == "test-model"
    assert request.temperature == 0.5
    assert request.max_tokens == 128
    assert request.messages[0].role == "system"
    assert request.messages[1].content == "hi"


def test_messages_are_frozen_to_a_tuple():
    request = Request(
        messages=[Message(role="user", content="hi")],  # a list goes in
        model="test-model",
    )

    assert isinstance(request.messages, tuple)


def test_unknown_role_is_refused():
    with pytest.raises(CompletionMalformedError):
        Message(role="developer", content="hi")


def test_non_string_role_is_refused():
    with pytest.raises(CompletionMalformedError):
        Message(role=None, content="hi")  # type: ignore[arg-type]


def test_non_string_message_content_is_refused():
    with pytest.raises(CompletionMalformedError):
        Message(role="user", content=42)  # type: ignore[arg-type]


def test_three_roles_are_allowed():
    assert Message(role="system", content="s").role == "system"
    assert Message(role="user", content="u").role == "user"
    assert Message(role="assistant", content="a").role == "assistant"


def test_blank_model_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="")


def test_temperature_above_ceiling_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", temperature=3.0)


def test_negative_temperature_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", temperature=-1.0)


def test_temperature_ceiling_is_allowed():
    request = Request(messages=(), model="m", temperature=2.0)
    assert request.temperature == 2.0


def test_non_number_temperature_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", temperature="warm")  # type: ignore[arg-type]


def test_bool_temperature_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", temperature=True)


def test_non_positive_max_tokens_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", max_tokens=0)


def test_non_int_max_tokens_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", max_tokens=1.5)  # type: ignore[arg-type]


def test_bool_max_tokens_is_refused():
    with pytest.raises(CompletionMalformedError):
        Request(messages=(), model="m", max_tokens=True)


def test_request_defaults():
    request = Request(messages=(), model="m")

    assert request.temperature == 0.0
    assert request.max_tokens == 1024


def test_request_is_value_equal():
    a = Request(messages=(Message(role="user", content="hi"),), model="m")
    b = Request(messages=(Message(role="user", content="hi"),), model="m")

    assert a == b


def test_request_is_frozen():
    from dataclasses import FrozenInstanceError

    request = Request(messages=(), model="m")

    with pytest.raises(FrozenInstanceError):
        request.model = "other"
