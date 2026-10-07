"""Usage gains a fourth, separately-reported counter: cache writes.

A completion's usage already told a caller what a call spent on plain input
and on reading back a cached prefix.  It did not say what the call spent
*writing* a new prefix into the cache — that figure was folded into
``input_tokens`` and nowhere else, even though a cache write bills at its own
rate downstream.  This gives it a field of its own,
:attr:`~providers.Usage.cache_write_tokens`, validated exactly like the other
three counters, defaulting to zero for a backend that does not report it.

The Anthropic Messages backend is the one live backend that has anything to
put there: its answers carry ``cache_creation_input_tokens``, and that figure
now lands verbatim in ``cache_write_tokens`` as well as still being folded
into ``input_tokens`` — ``input_tokens`` keeps counting every input token the
call consumed, so no existing reader of it changes.  These tests pin that
mapping on a recorded-shape Messages response, pin the old (pre-cache) shape
reading as zero, and pin that :class:`~providers.Usage`'s own equality and
``total_tokens`` are untouched by the new field.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from providers import Usage
from providers._anthropic import DEFAULT_BASE_URL, AnthropicProvider

FAKE_KEY = "fake-ant-key-not-a-credential"
MODEL = "claude-opus-5"


def _transport(*script: Any) -> Any:
    """A transport answering the scripted responses in order, recording every call."""
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
    return 200, {}, json.dumps(_answer(**overrides)).encode("utf-8")


def _provider(transport: Any) -> AnthropicProvider:
    return AnthropicProvider(
        FAKE_KEY, model=MODEL, base_url=DEFAULT_BASE_URL, transport=transport
    )


def test_a_recorded_response_with_all_three_input_counters_maps_to_four_fields(
    make_request,
):
    # input_tokens still sums all three input counters (unchanged meaning);
    # cache_read_tokens still carries the read figure; cache_write_tokens is
    # new and carries the write figure, both separately from input_tokens.
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

    assert completion.usage == Usage(
        input_tokens=146,
        output_tokens=7,
        cache_read_tokens=34,
        cache_write_tokens=12,
    )


def test_an_old_shape_response_without_cache_counters_gives_zeros(make_request):
    # A response that predates cache accounting entirely carries neither
    # cache_creation_input_tokens nor cache_read_input_tokens; both of the
    # interface's cache counters read as the absence they are, zero.
    transport = _transport(_ok(usage={"input_tokens": 10, "output_tokens": 4}))
    completion = _provider(transport).complete(make_request(model=MODEL))

    assert completion.usage == Usage(input_tokens=10, output_tokens=4)
    assert completion.usage.cache_read_tokens == 0
    assert completion.usage.cache_write_tokens == 0


# ── providers.Usage itself: the field, not just the backend that fills it ─────


def test_usage_cache_write_tokens_defaults_to_zero():
    usage = Usage(input_tokens=1, output_tokens=2)

    assert usage.cache_write_tokens == 0


def test_usage_cache_write_tokens_is_validated_like_the_others():
    with pytest.raises(ValueError):
        Usage(input_tokens=1, output_tokens=2, cache_write_tokens=-1)


def test_usage_equality_is_unchanged_for_callers_that_never_set_the_new_field():
    # Two usages built the old way, with no cache_write_tokens argument, are
    # still equal to each other and to one that names the field's own
    # default explicitly — adding the field did not change what "equal"
    # means for a caller that never touches it.
    assert Usage(input_tokens=5, output_tokens=6) == Usage(
        input_tokens=5, output_tokens=6
    )
    assert Usage(input_tokens=5, output_tokens=6) == Usage(
        input_tokens=5, output_tokens=6, cache_write_tokens=0
    )


def test_budget_total_tokens_is_unaffected_by_cache_write_tokens():
    # total_tokens is input plus output; a cache write is part of input
    # already (it is not billed again on top of the input it is a part of),
    # so the total does not move whether or not cache_write_tokens is set.
    without = Usage(input_tokens=100, output_tokens=7, cache_read_tokens=34)
    with_write = Usage(
        input_tokens=100, output_tokens=7, cache_read_tokens=34, cache_write_tokens=12
    )

    assert without.total_tokens == with_write.total_tokens == 107
