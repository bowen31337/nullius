"""The recorded-fixture backend: answers from stored responses, no network.

Feature 193's load-bearing claim is that the full loop runs with no network
access — so these tests drive :class:`RecordedProvider` over a record captured
earlier and assert the two halves of that promise: it answers a recorded prompt
from the stored response (drop-in for what recorded it, because it *is* a
provider), and a prompt with no recorded response is refused rather than
forwarded to a live transport.  The backend has no transport to fall back to,
so a missing fixture is a hard stop the caller fixes by recording the prompt
(feature 194), not a gap to paper over with an inference request.

The record is built from :class:`RecordedResponse` pairs — what a recorder's
exchange yields — and from a bare mapping of prompt hash to completion, and the
two build the same backend; the lookup keys the request by :func:`prompt_hash`,
so a request recorded in one process is found by an equal request in another.
"""

from __future__ import annotations

import pytest
from providers import (
    FIXTURE_MISSING_CODE,
    FixtureNotFoundError,
    Provider,
    ProviderError,
    RecordedProvider,
    RecordedResponse,
    prompt_hash,
)


def test_backend_answers_from_the_recorded_response(
    make_request, make_completion
):
    # The offline half of the recording story: the response captured for a
    # prompt is the response replayed for it, with no network round trip.
    request = make_request(model="m1", bodies=(("user", "q1"),))
    answer = make_completion("a1", model="m1")
    backend = RecordedProvider([RecordedResponse(request=request, completion=answer)])

    result = backend.complete(request)

    assert result == answer


def test_backend_is_itself_a_provider(make_request, make_completion):
    # Drop-in for what recorded it: a caller holding the interface cannot tell a
    # replay from a live run, because this *is* a provider.
    request = make_request(bodies=(("user", "q"),))
    backend = RecordedProvider(
        [RecordedResponse(request=request, completion=make_completion("a"))]
    )
    assert isinstance(backend, Provider)


def test_backend_answers_an_equal_request_recorded_in_another_process(
    make_request, make_completion
):
    # The lookup keys the request by prompt_hash, not by object identity, so a
    # request that asks the same prompt — a fresh object, equal by value — is
    # answered by the response captured for the original.  That is how a record
    # written in one process is replayed in another.
    answer = make_completion("a1", model="m1")
    backend = RecordedProvider(
        [
            RecordedResponse(
                request=make_request(model="m1", bodies=(("user", "q1"),)),
                completion=answer,
            )
        ]
    )

    same_prompt = make_request(model="m1", bodies=(("user", "q1"),))

    assert backend.complete(same_prompt) == answer


def test_a_prompt_with_no_recorded_response_is_refused_not_forwarded(
    make_request, make_completion
):
    # The load-bearing half of "no network access": the backend has no transport
    # to fall back to, so a prompt nothing captured is a hard stop, not a live
    # call.  The refusal is raised at the seam, so the loop never reaches a
    # model.
    recorded = make_request(model="m1", bodies=(("user", "q1"),))
    backend = RecordedProvider(
        [
            RecordedResponse(
                request=recorded, completion=make_completion("a1", model="m1")
            )
        ]
    )

    with pytest.raises(FixtureNotFoundError):
        backend.complete(make_request(model="m2", bodies=(("user", "q2"),)))


def test_fixture_not_found_is_a_provider_error():
    # The refusal is a ProviderError, so a single ``except ProviderError`` covers
    # a malformed completion, a missing provider and a missing recording — and a
    # CI check that the loop never fell back to a live network has one handle
    # for every way the offline path can stop.
    assert issubclass(FixtureNotFoundError, ProviderError)


def test_the_refusal_carries_the_fixture_missing_code(make_request, make_completion):
    # Feature 195's load-bearing half: the stop is not an anonymous exception but
    # a greppable *fixture_missing* message, the way signal_agent's refusals open
    # with their own code (illegal_theme).  A campaign log and a CI check that
    # scans for prompts requested with nothing recorded find them by this word.
    recorded = make_request(model="m1", bodies=(("user", "q1"),))
    backend = RecordedProvider(
        [RecordedResponse(request=recorded, completion=make_completion("a1", model="m1"))]
    )

    with pytest.raises(FixtureNotFoundError) as excinfo:
        backend.complete(make_request(model="m2", bodies=(("user", "q2"),)))

    assert str(excinfo.value).startswith(FIXTURE_MISSING_CODE)
    assert str(excinfo.value).startswith("fixture_missing")


def test_fixture_missing_code_is_the_token_feature_195_names():
    # The code is the feature's own subject written as a word, spelled once and
    # matched by value, not a substring a caller greps by eye: the constant and
    # the literal agree, so a rename is one edit.
    assert FIXTURE_MISSING_CODE == "fixture_missing"


def test_the_error_exposes_its_code_without_matching_message_text():
    # A caller can branch on the verdict by a fact about the error, not a
    # substring hunt — the code is exposed directly, the way a caller reads
    # illegal_theme off a theme refusal.
    assert FixtureNotFoundError("x").code == FIXTURE_MISSING_CODE


def test_the_code_prefixes_the_message_no_matter_who_raises_it():
    # The code is prefixed by the type's constructor, not by each raise site, so
    # the token and the error are one edit and cannot drift apart: any
    # FixtureNotFoundError — however it is built — carries fixture_missing.
    assert str(FixtureNotFoundError("anything")).startswith("fixture_missing: ")


def test_backend_builds_from_a_hash_keyed_mapping(make_request, make_completion):
    # The backend accepts either the RecordedResponse pairs a recorder yields or
    # the bare mapping of prompt hash to completion that is its own storage
    # form, and canonicalizes both to the same record.
    request = make_request(model="m", bodies=(("user", "ask"),))
    answer = make_completion("ans", model="m")
    backend = RecordedProvider({prompt_hash(request): answer})

    assert backend.complete(request) == answer


def test_has_reports_whether_a_prompt_is_recorded_without_answering(
    make_request, make_completion
):
    # A caller's chance to probe the record before committing to a call —
    # whether the prompt has a stored response — without raising or consuming
    # the response.
    recorded = make_request(model="m", bodies=(("user", "q"),))
    backend = RecordedProvider(
        [RecordedResponse(request=recorded, completion=make_completion("a"))]
    )

    assert backend.has(recorded) is True
    assert backend.has(make_request(model="other", bodies=(("user", "no"),))) is False


def test_recorded_lists_the_prompts_the_backend_can_answer(
    make_request, make_completion
):
    # The record's keys — the prompts that have a stored response — so a suite
    # can assert on exactly what was captured.  A tuple, fixed and value-equal.
    r1 = make_request(model="m1", bodies=(("user", "q1"),))
    r2 = make_request(model="m2", bodies=(("user", "q2"),))
    backend = RecordedProvider(
        {
            prompt_hash(r1): make_completion("a1", model="m1"),
            prompt_hash(r2): make_completion("a2", model="m2"),
        }
    )

    assert backend.recorded() == (prompt_hash(r1), prompt_hash(r2))


def test_prompt_hash_is_canonical_across_equal_requests(make_request):
    # Two requests that ask the same prompt — fresh objects, equal by value —
    # hash to the same key, which is how a record written in one process is
    # found in another.  The form is the request's own data, not a repr.
    assert prompt_hash(make_request(model="m", bodies=(("user", "q"),))) == prompt_hash(
        make_request(model="m", bodies=(("user", "q"),))
    )


def test_prompt_hash_differs_when_the_prompt_differs(make_request):
    # A different prompt is a different key, so two prompts never collide and a
    # missing one is refused rather than answered by the wrong response.
    a = prompt_hash(make_request(model="m", bodies=(("user", "q1"),)))
    b = prompt_hash(make_request(model="m", bodies=(("user", "q2"),)))
    assert a != b


def test_prompt_hash_refuses_a_non_request():
    # The recorded layer keys a response by the prompt that was asked, and a
    # prompt is a normalized request — the one shape the interface carries.  A
    # non-request is not that shape and has no stable prompt to key by.
    with pytest.raises(ProviderError):
        prompt_hash("not a request")  # type: ignore[arg-type]


def test_backend_refuses_a_record_of_the_wrong_shape():
    # A backend built around the wrong shape would answer nothing and fail
    # nowhere, so the shape is checked: a record is a mapping of hash to
    # completion, or a sequence of RecordedResponse.
    with pytest.raises(ProviderError):
        RecordedProvider("not a record")  # type: ignore[arg-type]


def test_backend_refuses_a_pair_with_a_non_completion():
    # The backend answers with the interface's one object, so a record whose
    # completion is not a Completion has nothing to replay and is refused.
    with pytest.raises(ProviderError):
        RecordedProvider([("the-hash", "not a completion")])  # type: ignore[list-item]


def test_a_replay_records_nothing(make_request, make_completion):
    # A source is not a tap: replaying the record answers from it and writes
    # nothing back, so a replay cannot corrupt the fixture it replays.  The
    # recorded set is unchanged after a call.
    request = make_request(model="m", bodies=(("user", "q"),))
    backend = RecordedProvider(
        [RecordedResponse(request=request, completion=make_completion("a"))]
    )
    before = backend.recorded()

    backend.complete(request)

    assert backend.recorded() == before


def test_a_raised_call_leaves_the_record_intact(make_request, make_completion):
    # The refusal is raised at the seam and answers nothing, so a missing prompt
    # is not a half-recorded entry — the record holds completed responses, not
    # attempts.
    recorded = make_request(model="m", bodies=(("user", "q"),))
    backend = RecordedProvider(
        [RecordedResponse(request=recorded, completion=make_completion("a"))]
    )

    with pytest.raises(FixtureNotFoundError):
        backend.complete(make_request(model="other", bodies=(("user", "no"),)))

    assert backend.recorded() == (prompt_hash(recorded),)
