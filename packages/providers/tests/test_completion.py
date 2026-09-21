"""The completion object — the one answer every call returns.

Feature 192's normalized completion: four fields, validated on construction,
frozen, value-equal.  These tests assert the shape holds itself — a completion
that exists is a valid one, because the guard lives in the object.
"""

from __future__ import annotations

import pytest
from providers import Completion, CompletionMalformedError, Usage


def test_a_completion_carries_its_four_fields():
    completion = Completion(
        content="the answer",
        model="served-model",
        usage=Usage(input_tokens=5, output_tokens=7),
        finish_reason="stop",
    )

    assert completion.content == "the answer"
    assert completion.model == "served-model"
    assert completion.usage.input_tokens == 5
    assert completion.usage.output_tokens == 7
    assert completion.finish_reason == "stop"


def test_usage_defaults_cache_read_to_zero():
    # A provider that does not report cache reads is not a negative — the
    # absence of a figure is not a figure.
    usage = Usage(input_tokens=1, output_tokens=2)

    assert usage.cache_read_tokens == 0
    assert usage.total_tokens == 3  # cache reads are not billed on top


def test_completion_defaults_finish_reason_to_stop():
    assert (
        Completion(
            content="x", model="m", usage=Usage(input_tokens=1, output_tokens=1)
        ).finish_reason
        == "stop"
    )


def test_length_finish_reason_is_allowed():
    completion = Completion(
        content="truncated",
        model="m",
        usage=Usage(input_tokens=1, output_tokens=1),
        finish_reason="length",
    )

    assert completion.finish_reason == "length"


def test_unknown_finish_reason_is_refused():
    with pytest.raises(CompletionMalformedError):
        Completion(
            content="x",
            model="m",
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason="timeout",
        )


def test_non_string_finish_reason_is_refused():
    with pytest.raises(CompletionMalformedError):
        Completion(
            content="x",
            model="m",
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=None,
        )


def test_non_string_content_is_refused():
    with pytest.raises(CompletionMalformedError):
        Completion(content=123, model="m", usage=Usage(input_tokens=1, output_tokens=1))


def test_blank_model_is_refused():
    with pytest.raises(CompletionMalformedError):
        Completion(content="x", model="", usage=Usage(input_tokens=1, output_tokens=1))


def test_non_usage_is_refused():
    with pytest.raises(CompletionMalformedError):
        Completion(content="x", model="m", usage={"input": 1})  # type: ignore[arg-type]


def test_negative_token_count_is_refused():
    with pytest.raises(ValueError):
        Usage(input_tokens=-1, output_tokens=1)


def test_bool_is_not_a_token_count():
    # A bool is an int subclass; a token count of True is not a count.
    with pytest.raises(ValueError):
        Usage(input_tokens=True, output_tokens=1)


def test_completion_is_frozen():
    from dataclasses import FrozenInstanceError

    completion = Completion(
        content="x", model="m", usage=Usage(input_tokens=1, output_tokens=1)
    )

    with pytest.raises(FrozenInstanceError):
        completion.content = "changed"


def test_completion_is_value_equal():
    a = Completion(content="x", model="m", usage=Usage(input_tokens=1, output_tokens=1))
    b = Completion(content="x", model="m", usage=Usage(input_tokens=1, output_tokens=1))

    assert a == b
    assert hash(a) == hash(b)


def test_different_usage_is_a_different_completion():
    a = Completion(content="x", model="m", usage=Usage(input_tokens=1, output_tokens=1))
    b = Completion(content="x", model="m", usage=Usage(input_tokens=2, output_tokens=1))

    assert a != b
