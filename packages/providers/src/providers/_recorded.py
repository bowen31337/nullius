"""The recorded-fixture backend — feature 193's source.

Feature 192 fixes the seam every model call passes through; :mod:`providers._recorder`
wraps a live provider so every exchange is kept; :mod:`providers._recorded` is
the other half of that story — a provider that *answers* from the kept exchanges,
so the full loop runs with no network access at all.  It is the offline source
the recorder's tap feeds: a deployment records once (feature 194), then replays
the record many times, and every call is answered from what was captured rather
than from a live transport.

The backend is a :class:`~providers.Provider`, and that is the whole design: it
is drop-in for whatever served the calls originally, because it *is* a provider
— a caller holding the interface cannot tell a replay from a live run, and need
not.  It holds a mapping of prompt to recorded completion, and :meth:`_complete`
answers a request by looking up the prompt it asked.  A prompt with no recorded
response is refused as :class:`~providers.FixtureNotFoundError` rather than
forwarded to a live transport — the load-bearing half of the sentence.  A
recorded backend has no transport to fall back to, so a missing fixture is a
hard stop the caller fixes by recording the prompt (feature 194), not a gap to
paper over with an inference request; a backend that silently reached for the
network would be the access this feature exists to remove.

The lookup keys the request by :func:`prompt_hash` rather than by object
identity, because the record was written in one process and is replayed in
another, and two requests that ask the same prompt are the same prompt whatever
objects carried them — the value-equality :class:`~providers.Request` already
guarantees, distilled to a stable string so it can be a mapping key and a
fixture-file name (feature 194).  The hash is canonical: the request's own
value-equal form, not a repr that would scatter one prompt across many keys.

What the backend is not is a recorder.  The two responsibilities — "keep every
exchange" and "answer from kept exchanges" — are two objects, for the reason
:mod:`providers._recorder` sets out: a single object that did both would be
unable to refuse a missing fixture the way feature 195 requires, because it
would fall back to the live call it is meant to be recording around.  So this
backend is a source, not a tap: it reads the record and answers from it, and
records nothing.

Stdlib-only, like the rest of this tree.  The backend holds no transport, no
credential and no provider SDK — those belong to a concrete provider on the
trusted side of the boundary (feature 150's orchestrator); this module is the
offline answer the transport's exchanges are replayed through.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ._completion import Completion
from ._errors import ProviderError
from ._provider import Provider
from ._recorded_errors import FixtureNotFoundError
from ._request import Request

__all__ = ["RecordedProvider", "prompt_hash"]


def prompt_hash(request: Request) -> str:
    """The canonical key for a prompt: the request's value-equal form, hashed.

    The recorded-fixture layer keys a fixture by "the prompt that was asked":
    the response captured for a request is the response replayed for any later
    request that asks the same prompt.  Two requests ask the same prompt when
    they are value-equal — the same ordered messages, the same model, the same
    sampling knobs — which :class:`~providers.Request` already guarantees.  This
    function distils that value-equal form to a single stable string, so it can
    be a mapping key and a fixture-file name (feature 194) and so a request
    recorded in one process is found by an equal request in another.

    The canonical form is the request's own fields, not a ``repr``: a repr
    carries object addresses and a type name that would scatter one prompt
    across many keys, defeating the value-equality the interface exists to
    give.  So the request is reduced to its data — the messages as role/content
    pairs, the model, the temperature, the max_tokens — and that data is hashed.
    A sha256 hex digest keeps the key fixed-length and filename-safe, the way
    ``infra.security`` hashes a policy to a digest rather than keying by the
    policy text.
    """
    if not isinstance(request, Request):
        raise ProviderError(
            f"prompt_hash() takes a Request, got {request!r} "
            f"({type(request).__name__}). The recorded-fixture layer keys a "
            f"response by the prompt that was asked, and a prompt is a "
            f"normalized request — the one shape the provider interface carries. "
            f"A non-request is not that shape and has no stable prompt to key by."
        )
    payload = json.dumps(
        {
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
            "model": request.model,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RecordedResponse:
    """One stored answer: the completion captured for a prompt, plus its ask.

    The unit a :class:`~providers.RecordedProvider` answers from.  ``request``
    is the :class:`~providers.Request` that was asked and ``completion`` is the
    :class:`~providers.Completion` it got back — the two persisted together by
    the recorder (feature 194) and replayed together here, because a fixture
    that split the answer from the ask would be unable to say which response
    matched which prompt.  Frozen and value-equal, so a stored response compares
    to an expected one by what was asked and answered, not by object identity.
    """

    request: Request
    completion: Completion


class RecordedProvider(Provider):
    """A provider that answers from stored responses, with no network fallback.

    Feature 193's backend: a :class:`~providers.Provider` that answers a model
    call from a response captured earlier, so the full loop runs with no network
    access.  It is built from the responses a recorder kept — a mapping of
    :func:`prompt_hash` to :class:`~providers.Completion` — and :meth:`_complete`
    answers a request by hashing its prompt and looking the response up.  A
    prompt with no recorded response is refused as
    :class:`~providers.FixtureNotFoundError`, never forwarded to a live
    transport: the backend has no transport, and reaching for the network would
    be the access this feature exists to remove.

    Drop-in for what recorded it: a caller holding the interface cannot tell a
    replay from a live run, because this *is* a provider — the same seam, the
    same normalized request in and completion out.  A deployment therefore
    records once against a live transport and replays the record many times
    against this one, the loop unchanged.

    It records nothing: keeping exchanges is the recorder's job, and a source is
    not a tap.  The record it answers from is supplied at construction and read,
    never written, so a replay cannot corrupt the fixture it replays.
    """

    def __init__(self, responses: object = None) -> None:
        # The stored responses are the whole of what the backend can answer.
        # They are held as a mapping of prompt hash to completion, canonicalized
        # on the way in so the record a caller supplies and the record the
        # backend reads are the same thing — and so a caller can hand either a
        # mapping of hashes, or the richer RecordedResponse pairs the recorder
        # produces, and get the same backend.
        self._responses: dict[str, Completion] = {}
        if responses is not None:
            for key, completion in self._coerce(responses):
                self._responses[key] = completion

    @staticmethod
    def _coerce(responses: object) -> list[tuple[str, Completion]]:
        # One way in for two shapes a caller legitimately has: a mapping of
        # prompt hash to completion (the backend's own storage form), or an
        # iterable of RecordedResponse pairs (what a recorder's exchange yields).
        # Each is refused unless it is one of these, because a backend built
        # around the wrong shape would answer nothing and fail nowhere.
        if isinstance(responses, dict):
            items = responses.items()
        elif isinstance(responses, (list, tuple)):
            items = responses
        else:
            raise ProviderError(
                f"a RecordedProvider takes a mapping of prompt hash to completion "
                f"or a sequence of RecordedResponse, got {responses!r} "
                f"({type(responses).__name__}). The backend answers from what was "
                f"recorded; a record that is neither a hash-keyed map nor a "
                f"sequence of recorded responses is not that record."
            )
        coerced: list[tuple[str, Completion]] = []
        for entry in items:
            if isinstance(entry, RecordedResponse):
                coerced.append(
                    (prompt_hash(entry.request), entry.completion)
                )
            else:
                try:
                    key, completion = entry
                except (TypeError, ValueError) as exc:
                    raise ProviderError(
                        f"a RecordedProvider record must be a (prompt_hash, "
                        f"Completion) pair or a RecordedResponse, got {entry!r} "
                        f"({type(entry).__name__}){': ' + str(exc) if str(exc) else ''}."
                    ) from exc
                if not isinstance(completion, Completion):
                    raise ProviderError(
                        f"a RecordedProvider record's completion must be a "
                        f"Completion, got {completion!r} ({type(completion).__name__}). "
                        f"The backend answers with the interface's one object; a "
                        f"record that is not one has nothing to replay."
                    )
                coerced.append((key, completion))
        return coerced

    def _complete(self, request: Request) -> Completion:
        # The base class has already validated the request and the model, so
        # this hashes the prompt and answers from the record.  A prompt with no
        # recorded response is a hard stop, not a live fallback: the backend has
        # no transport, and reaching for the network would be the access this
        # feature exists to remove.
        key = prompt_hash(request)
        if key not in self._responses:
            raise FixtureNotFoundError(
                f"no recorded response for the requested prompt "
                f"({key}). A RecordedProvider answers only from responses "
                f"captured earlier; this prompt was not among them, and the "
                f"backend has no transport to fall back to — the loop must run "
                f"offline. Record the prompt (feature 194) rather than catching "
                f"this and retrying against a live model."
            )
        return self._responses[key]

    def has(self, request: Request) -> bool:
        """Whether a response is recorded for this prompt — without answering it.

        A caller's chance to probe the record before committing to a call:
        whether the prompt this request asks has a stored response.  Answers the
        question the backend's lookup asks — is the prompt hash in the record —
        without raising, so a launcher can decide "replay offline" versus
        "record this prompt first" without consuming the response.
        """
        return prompt_hash(request) in self._responses

    def recorded(self) -> tuple[str, ...]:
        """Every prompt hash this backend can answer, in insertion order.

        The record's keys — the prompts that have a stored response — so a
        suite can assert on exactly what was captured, and a launcher can see
        which prompts a replay will answer.  A tuple, so the set is fixed and
        value-equal: two backends built from the same record list the same
        prompts in the same order.
        """
        return tuple(self._responses)
