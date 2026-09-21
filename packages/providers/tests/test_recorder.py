"""The recorder: the provider seam wrapped so every exchange is kept.

The bridge to the recorded-fixture layer (features 193 and 194).  These tests
drive :class:`RecordingProvider` over a scripted provider and assert it is a
tap, not a source: it forwards and keeps every request with its completion, in
order, and a call that raised leaves no half-recorded entry.
"""

from __future__ import annotations

import pytest
from providers import (
    CompletionMalformedError,
    Exchange,
    Provider,
    ProviderError,
    RecordingProvider,
)


def test_recorder_forwards_and_keeps_the_exchange(
    scripted_provider, make_completion, make_request
):
    provider = scripted_provider(
        lambda request: make_completion(content="ans", model=request.model)
    )
    recorder = RecordingProvider(provider)

    result = recorder.complete(make_request(model="m1", bodies=(("user", "q1"),)))

    # Drop-in for what it wraps: the caller got the completion back unchanged.
    assert result.content == "ans"
    # And the exchange was kept, request and completion together.
    (entry,) = recorder.exchanges()
    assert isinstance(entry, Exchange)
    assert entry.request.model == "m1"
    assert entry.request.messages[0].content == "q1"
    assert entry.completion.content == "ans"


def test_recorder_keeps_exchanges_in_order(
    scripted_provider, make_completion, make_request
):
    provider = scripted_provider(lambda request: make_completion(content=request.model))
    recorder = RecordingProvider(provider)

    recorder.complete(make_request(model="first"))
    recorder.complete(make_request(model="second"))

    models = [exchange.completion.content for exchange in recorder.exchanges()]
    assert models == ["first", "second"]


def test_recorder_keeps_request_and_completion_together(
    scripted_provider, make_completion, make_request
):
    answer = make_completion(content="kept", model="m")
    request = make_request(model="m", bodies=(("user", "ask"),))
    recorder = RecordingProvider(scripted_provider(lambda r: answer))

    recorder.complete(request)

    assert recorder.exchanges() == (Exchange(request=request, completion=answer),)


def test_recorder_is_itself_a_provider(scripted_provider, make_completion):
    # Drop-in for what it wraps: a caller holding the interface cannot tell the
    # recorder from the provider underneath.
    recorder = RecordingProvider(scripted_provider(lambda r: make_completion()))
    assert isinstance(recorder, Provider)


def test_recorder_refuses_a_non_provider():
    with pytest.raises(ProviderError):
        RecordingProvider("not a provider")  # type: ignore[arg-type]


def test_a_raised_call_leaves_no_entry(make_request):
    class Raising(Provider):
        def _complete(self, request):
            raise CompletionMalformedError("boom")

    recorder = RecordingProvider(Raising())

    with pytest.raises(CompletionMalformedError):
        recorder.complete(make_request())

    assert recorder.exchanges() == ()  # the failed round trip was not kept


def test_requests_and_completions_accessors(
    scripted_provider, make_completion, make_request
):
    provider = scripted_provider(lambda request: make_completion(content=request.model))
    recorder = RecordingProvider(provider)

    recorder.complete(make_request(model="a"))
    recorder.complete(make_request(model="b"))

    assert [r.model for r in recorder.requests()] == ["a", "b"]
    assert [c.content for c in recorder.completions()] == ["a", "b"]


def test_recorder_records_only_completed_round_trips_not_attempts(
    make_request, make_completion
):
    # A subtle point: the entry is appended only after the wrapped provider
    # returns, so the record holds completed round trips, not attempts.  Two
    # good calls and one that raises in the middle keep exactly the two good
    # ones, in order.
    answers = {"a": make_completion(content="a"), "b": make_completion(content="b")}

    class SometimesRaises(Provider):
        def _complete(self, request):
            if request.model == "bad":
                raise CompletionMalformedError("no")
            return answers[request.model]

    recorder = RecordingProvider(SometimesRaises())

    recorder.complete(make_request(model="a"))
    with pytest.raises(CompletionMalformedError):
        recorder.complete(make_request(model="bad"))
    recorder.complete(make_request(model="b"))

    assert [c.content for c in recorder.completions()] == ["a", "b"]
