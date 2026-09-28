"""The provider interface's batch operation — one call, many requests.

The seam feature 192 fixes has one operation: :meth:`Provider.complete` takes
a :class:`~providers.Request` and returns a :class:`~providers.Completion`.
This file drives the seam's *batch* half — :meth:`Provider.complete_batch`,
which takes a :class:`~providers.BatchRequest` (an ordered tuple of requests)
and returns a :class:`~providers.BatchCompletion` (one completion per request,
in order, each carrying the model that served it) — so a provider that serves
a batch endpoint answers many requests through one batched transport call.

**The batch is a mirror of the single call, and the mirror is the design.**
Every assertion here has a single-call twin in ``test_provider.py``: the base
validates the argument before the backend runs, validates the answer after the
backend returns, and a provider that answered wrong is refused at the seam.
The batch does the same, so the suite is deliberately structured as a set of
parallels — a batched request in, a batched completion out, and anything that
is not that round trip is refused — because the load-bearing claim of the
feature is that the batched path enforces *exactly* the same contract as the
single one, neither looser (a malformed batched answer would travel
downstream) nor stricter (a well-formed one passes straight through).

**The batch is an addition, not a replacement.**  The single path is
untouched, and a provider with no batch endpoint refuses a batch by name
(:class:`~providers.NotImplementedBatchError`) rather than silently answering
one request at a time.  The suite pins that refusal as the seam's own
vocabulary — a subclass of :class:`~providers.ProviderError`, so a caller that
catches the provider contract with one ``except`` catches "cannot batch" along
with "nothing to call" and "answered wrong" — and pins that a batch-capable
provider and a synchronous one are both usable through the same interface, so
a caller written against it is portable across the two.

**Each completion carries the model that served it, and the batch is where it
matters most.**  A batched call is the one where many requests are most likely
to have been spread across models — the whole point of routing depth through a
batch endpoint (architecture §14.1, feature 201) — so the batched answer
reports its own authors rather than leaving the caller to remember which model
answered which request.  The suite asserts the per-request model comes back,
because a batch that dropped it would defeat the tiering the batch exists to
serve.
"""

from __future__ import annotations

import pytest
from providers import (
    BatchCompletion,
    BatchRequest,
    Completion,
    CompletionMalformedError,
    Message,
    NotImplementedBatchError,
    Provider,
    ProviderError,
    Request,
    UnknownModelError,
    Usage,
    require_batch_completion,
)


def _req(model="m", body="hi"):
    return Request(messages=(Message(role="user", content=body),), model=model)


def _comp(content="answer", model="served"):
    return Completion(
        content=content,
        model=model,
        usage=Usage(input_tokens=1, output_tokens=2),
    )


def test_complete_batch_returns_one_completion_per_request_in_order():
    # The one batched operation: a batch of requests in, a batch of completions
    # out, one per request, in request order.  The base validates both ends, so
    # the caller only ever sees a well-formed batched answer.  The provider is a
    # batch-capable one — ScriptedProvider only answers single calls, so this is
    # an inline backend, the honest shape of a concrete batch provider.
    class Batchable(Provider):
        def _complete_batch(self, batch):
            return BatchCompletion(
                completions=(
                    _comp(content="a", model="served-a"),
                    _comp(content="b", model="served-b"),
                    _comp(content="c", model="served-c"),
                )
            )

    batch = BatchRequest(
        requests=(
            _req(body="one"),
            _req(body="two"),
            _req(body="three"),
        )
    )

    result = Batchable().complete_batch(batch)

    assert isinstance(result, BatchCompletion)
    assert result.completions == (
        _comp(content="a", model="served-a"),
        _comp(content="b", model="served-b"),
        _comp(content="c", model="served-c"),
    )
    assert [c.content for c in result.completions] == ["a", "b", "c"]


def test_a_batch_completion_carries_the_model_that_served_each_request():
    # Each completion names its own author, and the batch is where that matters
    # most: a batched call is the one most likely to have spread requests across
    # models — the point of routing depth through a batch endpoint — so the
    # answer reports its authors rather than leaving the caller to remember.
    class Batchable(Provider):
        def _complete_batch(self, batch):
            return BatchCompletion(
                completions=tuple(
                    _comp(content=f"ans-{i}", model=f"served-{i}")
                    for i in range(len(batch.requests))
                )
            )

    result = Batchable().complete_batch(
        BatchRequest(requests=(_req(body="x"), _req(body="y"), _req(body="z")))
    )

    assert [c.model for c in result.completions] == ["served-0", "served-1", "served-2"]


def test_base_validates_the_batch_before_the_backend_runs(make_request):
    # A non-batch is refused at the seam, not forwarded to the provider to guess
    # at — the backend never sees it.  The mirror of test_provider's single-call
    # version.
    calls: list[object] = []

    class Backend(Provider):
        def _complete_batch(self, batch):
            calls.append(batch)
            return BatchCompletion(completions=(_comp(),))

    with pytest.raises(CompletionMalformedError):
        Backend().complete_batch("not a batch")

    assert calls == []  # the backend never ran


def test_base_validates_each_request_model_before_the_backend_runs():
    # The batch's per-request model check runs before the backend, the same way
    # the single call's check_model runs before _complete — a configuration
    # error the caller can fix, not a runtime failure discovered mid-batch.
    seen: list[BatchRequest] = []

    class Pinned(Provider):
        def check_model(self, model):
            if model != "allowed":
                from providers import UnknownModelError

                raise UnknownModelError(f"not served: {model}")
            return model

        def _complete_batch(self, batch):
            seen.append(batch)
            return BatchCompletion(
                completions=tuple(_comp(model=r.model) for r in batch.requests)
            )

    with pytest.raises(UnknownModelError):
        Pinned().complete_batch(
            BatchRequest(requests=(_req(model="allowed"), _req(model="denied")))
        )

    assert seen == []  # the refused batch never reached the backend


def test_base_refuses_a_non_batch_completion_answer(make_request):
    # The load-bearing ordering, batched: the answer check runs *after* the
    # backend (so a provider that answered wrong is caught) but *before* the
    # caller (so the malformed answer never travels downstream).
    class BadProvider(Provider):
        def _complete_batch(self, batch):
            return ["a raw list, not a BatchCompletion"]

    with pytest.raises(CompletionMalformedError):
        BadProvider().complete_batch(BatchRequest(requests=(_req(),)))


def test_base_refuses_none_batch_answer(make_request):
    # A provider that returned nothing is still a broken batched completion, not
    # a special case — the interface's promise is one completion per request.
    class NoneProvider(Provider):
        def _complete_batch(self, batch):
            return None

    with pytest.raises(CompletionMalformedError):
        NoneProvider().complete_batch(BatchRequest(requests=(_req(),)))


def test_the_good_batch_answer_is_returned_unwrapped():
    # A well-formed batched completion passes straight through; the check admits
    # it, it does not rebuild it.
    answer = BatchCompletion(completions=(_comp(), _comp()))

    class Passthrough(Provider):
        def _complete_batch(self, batch):
            return answer

    assert (
        Passthrough().complete_batch(BatchRequest(requests=(_req(), _req()))) is answer
    )


def test_a_provider_without_a_batch_endpoint_refuses_the_batch():
    # A synchronous provider — one that serves no batch endpoint — refuses a
    # batch by name rather than silently answering one request at a time.  The
    # refusal is the seam's own vocabulary, so a caller that chose the batched
    # path knows the bound provider cannot batch, rather than getting N single
    # calls it did not ask for.
    class Sync(Provider):
        def _complete(self, request):
            return _comp()

    with pytest.raises(NotImplementedBatchError):
        Sync().complete_batch(BatchRequest(requests=(_req(), _req())))


def test_not_implemented_batch_error_is_a_provider_error():
    # The refusal is a ProviderError, so a caller that catches the provider
    # contract with one except catches "cannot batch" along with "nothing to
    # call" and "answered wrong" — they are all "the batched call could not
    # run", and the caller's fallback is one branch.
    assert issubclass(NotImplementedBatchError, ProviderError)


def test_a_batch_capable_and_a_synchronous_provider_are_both_usable():
    # A caller written against the interface is portable across a batch-capable
    # provider and a synchronous one: the batch-capable answers many in one
    # call, the synchronous one refuses the batch and is called once per
    # request, and the interface the caller holds is the same object.
    class Batchable(Provider):
        def _complete_batch(self, batch):
            return BatchCompletion(
                completions=tuple(_comp(model="batched") for _ in batch.requests)
            )

        def _complete(self, request):
            return _comp(model="sync")

    class Sync(Provider):
        def _complete(self, request):
            return _comp(model="sync")

    batchable = Batchable()
    sync = Sync()

    assert isinstance(batchable, Provider) and isinstance(sync, Provider)
    assert [
        c.model
        for c in batchable.complete_batch(
            BatchRequest(requests=(_req(), _req()))
        ).completions
    ] == ["batched", "batched"]
    assert batchable.complete(_req()).model == "sync"  # the single path is unchanged
    assert sync.complete(_req()).model == "sync"
    with pytest.raises(NotImplementedBatchError):
        sync.complete_batch(BatchRequest(requests=(_req(),)))


def test_complete_batch_does_not_touch_the_single_path():
    # The batch operation is an addition, not a replacement: a non-batch call
    # behaves exactly as before.  A provider that implements only _complete
    # still answers single calls, and the single path's validation is unchanged.
    class OnlySync(Provider):
        def _complete(self, request):
            return _comp(model=request.model)

    assert OnlySync().complete(_req(model="solo")).model == "solo"


def test_batch_request_refuses_an_empty_batch():
    # A batch of no requests is not a batched call — there is no transport round
    # trip to make with nothing to answer — so it is refused at construction
    # rather than forwarded to a provider that would invent one.
    with pytest.raises(CompletionMalformedError):
        BatchRequest(requests=())


def test_batch_request_refuses_a_non_request_member():
    # A batch is an ordered tuple of normalized requests; a non-request in the
    # batch is not the shape the interface carries, and forwarding it would be
    # asking the provider to guess at the shape the interface exists to fix.
    with pytest.raises(CompletionMalformedError):
        BatchRequest(requests=(_req(), "not a request"))


def test_batch_request_freezes_and_tuples_its_requests():
    # Frozen and value-equal, so a batched prompt compares by what was asked
    # rather than by object identity — the same testability the single request
    # gets from being a value type.
    from dataclasses import FrozenInstanceError

    requests = (_req(body="a"), _req(body="b"))
    batch = BatchRequest(requests=list(requests))

    assert batch.requests == requests
    assert isinstance(batch.requests, tuple)  # a list was coerced on entry
    assert BatchRequest(requests=(_req(body="a"), _req(body="b"))) == batch
    with pytest.raises(FrozenInstanceError):
        batch.requests = ()  # type: ignore[misc]


def test_batch_completion_freezes_and_tuples_its_completions():
    # Frozen and value-equal, so a suite can assert the whole batched answer
    # against an expected tuple rather than replaying field by field.
    from dataclasses import FrozenInstanceError

    completions = (_comp(content="a"), _comp(content="b"))
    answer = BatchCompletion(completions=list(completions))

    assert answer.completions == completions
    assert isinstance(answer.completions, tuple)
    with pytest.raises(FrozenInstanceError):
        answer.completions = ()  # type: ignore[misc]


def test_require_batch_completion_refuses_a_non_batch():
    # The batch half of the base's out-bound guard: the completion check the
    # single path runs on its answer, applied to the batched one.  A provider
    # that returned the wrong shape is refused here, at the seam, in the
    # interface's own vocabulary.
    with pytest.raises(CompletionMalformedError):
        require_batch_completion(["not", "a", "batch"])
    with pytest.raises(CompletionMalformedError):
        require_batch_completion(None)


def test_require_batch_completion_admits_a_valid_batch():
    # A well-formed batched answer passes straight through — the check admits it,
    # it does not rebuild it.
    answer = BatchCompletion(completions=(_comp(), _comp()))
    assert require_batch_completion(answer) is answer


def test_batch_records_are_not_recognised_by_parts_like_a_depth_candidate():
    # The batch records are validated by ``isinstance`` against the interface's
    # own class, and deliberately *not* re-made from their parts the way
    # :func:`providers.require_depth_model` re-makes a depth candidate.  That is
    # a design decision, not an oversight, and it rests on where the record
    # lives: a depth candidate is a selection input that a registry may have
    # built from *either* copy of the member (the workspace's module loader
    # imports every member twice, so two ``DepthModel`` classes exist over one
    # source file and ``isinstance`` between them is ``False``), so the gate
    # must recognise it by its parts and answer in one class.  A batch record
    # never crosses that boundary — a :class:`BatchCompletion` is made by a
    # provider's ``_complete_batch`` and read by the same provider's
    # ``complete_batch``, on the seam, in one copy — so ``isinstance`` is enough
    # and re-making it would be solving a hazard that does not reach it.
    #
    # This pins the difference as behaviour: a stub carrying the three parts of
    # a BatchCompletion (but not the class) is refused, because the seam reads
    # the class, not the shape.  A caller that wants the batched path builds a
    # BatchCompletion from the interface, the same object the seam checks.
    from types import SimpleNamespace

    stub = SimpleNamespace(completions=(_comp(), _comp()))  # shaped like one, not one
    with pytest.raises(CompletionMalformedError):
        require_batch_completion(stub)
