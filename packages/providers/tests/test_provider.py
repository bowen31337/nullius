"""The provider interface: one seam, one normalized completion.

Feature 192's load-bearing claim is that every model call passes through
:class:`Provider` and returns a :class:`Completion` — so these tests drive the
interface through a scripted provider and assert the contract in both
directions: a request goes in, a completion comes out, and anything that is
not that round trip is refused at the seam.
"""

from __future__ import annotations

import pytest
from providers import (
    Completion,
    CompletionMalformedError,
    Provider,
    UnknownModelError,
)


def test_complete_returns_a_completion(
    scripted_provider, make_completion, make_request
):
    # The one operation: a request in, a completion out, whatever the provider
    # does underneath.  The base class validates both ends, so the caller only
    # ever sees a well-formed completion.
    answer = make_completion(content="hello", model="served-model")
    provider = scripted_provider(lambda request: answer)

    result = provider.complete(make_request(bodies=(("user", "hi?"),)))

    assert result == answer
    assert isinstance(result, Completion)


def test_base_validates_the_request_before_the_backend_runs(
    make_request, make_completion
):
    # A non-request is refused at the seam, not forwarded to the provider to
    # guess at — the backend never sees it.
    calls: list[object] = []

    class Backend(Provider):
        def _complete(self, request):
            calls.append(request)
            return make_completion()

    with pytest.raises(CompletionMalformedError):
        Backend().complete("not a request")

    assert calls == []  # the backend never ran


def test_base_refuses_a_non_completion_answer(make_request):
    # The load-bearing ordering: the completion check runs *after* the backend
    # (so a provider that answered wrong is caught) but *before* the caller
    # (so the malformed answer never travels downstream).
    class BadProvider(Provider):
        def _complete(self, request):
            return "a raw string, not a Completion"

    with pytest.raises(CompletionMalformedError):
        BadProvider().complete(make_request())


def test_base_refuses_none_answer(make_request):
    # A provider that returned nothing is still a broken completion, not a
    # special case — the interface's promise is one completion per call.
    class NoneProvider(Provider):
        def _complete(self, request):
            return None

    with pytest.raises(CompletionMalformedError):
        NoneProvider().complete(make_request())


def test_the_good_answer_is_returned_unwrapped(
    scripted_provider, make_completion, make_request
):
    # A well-formed completion passes straight through; the check admits it,
    # it does not rebuild it.
    answer = make_completion(content="ok")
    provider = scripted_provider(lambda request: answer)

    assert provider.complete(make_request()) is answer


def test_check_model_refuses_unknown_before_the_call(make_request, make_completion):
    # A provider that pins a set refuses an unknown model *before* attempting
    # the call — a configuration error the caller can fix.
    backend_calls: list[object] = []

    class Pinned(Provider):
        def check_model(self, model):
            if model != "allowed":
                raise UnknownModelError(f"not served: {model}")
            return model

        def _complete(self, request):
            backend_calls.append(request)
            return make_completion(model=request.model)

    provider = Pinned()

    with pytest.raises(UnknownModelError):
        provider.complete(make_request(model="denied"))

    assert backend_calls == []  # the refused call never reached the backend


def test_check_model_default_accepts_any_model(
    scripted_provider, make_completion, make_request
):
    # The default is permissive: a passthrough or router inherits the interface
    # without inventing a restriction the feature does not state.
    provider = scripted_provider(lambda request: make_completion(model=request.model))

    result = provider.complete(make_request(model="whatever-model"))

    assert result.model == "whatever-model"


def test_a_provider_is_a_provider_the_interface_can_drive(
    scripted_provider, make_completion
):
    # ScriptedProvider is a Provider, so it is drop-in for the interface — a
    # caller holding the interface cannot tell it from any other provider.
    assert isinstance(scripted_provider(lambda r: make_completion()), Provider)


def test_completion_helper_builds_a_valid_completion():
    # Provider.completion builds from the interface's fields and delegates
    # validation to the completion, so there is one way to make one.
    built = Provider.completion(
        content="x", model="m", input_tokens=3, output_tokens=4, cache_read_tokens=1
    )

    assert built == Completion(
        content="x",
        model="m",
        usage=built.usage,
        finish_reason="stop",
    )
    assert built.usage.total_tokens == 7
    assert built.usage.cache_read_tokens == 1
