"""The one provider interface — feature 192's seam.

The whole of feature 192 in one object: :class:`Provider` is the single seam
every model call in the deployment passes through, and it returns a
:class:`providers.Completion` and nothing else.  A caller holds a
:class:`Provider`, hands it a :class:`~providers.Request`, and gets back a
:class:`~providers.Completion` — whatever provider is bound underneath (a
recorded-fixture backend, a live transport, a tiering router) is invisible to
the caller and swappable without touching it.  That is the interface's entire
job, and the reason the deployment has one: the signal agent, the hypothesis
author and every other caller are written against *this* shape, so a change to
which model serves them — a tier rotation, a failover, a fixture swap — is a
change to what is bound, not to what every caller calls.

The seam enforces the contract in both directions, and the enforcement is in
the base class so every provider inherits it whether or not its author thought
about it:

* :meth:`Provider.complete` takes the caller's request, validates it is a
  :class:`~providers.Request`, delegates the work to the provider's
  :meth:`_complete`, and then validates the answer is a
  :class:`~providers.Completion` before returning it.  The normalization is
  the base class's promise, not the caller's discipline — a caller never has
  to check "did this provider return the right shape?", because a provider
  that did not is refused here, at the seam, and the caller only ever receives
  a well-formed completion.  This is the load-bearing ordering: the check runs
  *after* the backend, so it catches a provider that answered wrong, but
  *before* the caller, so the malformed answer never travels downstream.

* :meth:`Provider.check_model` lets a provider declare the models it serves
  and refuse an unknown one *before* the call is attempted — a configuration
  error the caller can fix, not a runtime failure discovered mid-request.  A
  provider that serves everything (a passthrough, a router that forwards)
  leaves the default, which accepts any model; a provider that pins a set
  overrides it.  The default is permissive because the interface must not
  invent a restriction the feature does not state.

A provider is a base class, not a bare protocol, because the normalization
and validation are base behaviour that every provider must inherit — the same
reason ``infra.security.provider_boundary.ProviderClient`` is a base class and
not a protocol: the law is the base, so a subclass cannot opt out of it.  A
concrete provider implements :meth:`_complete` (and optionally
:meth:`check_model`) and gets the rest — the request validation, the
completion validation, the error vocabulary — for free.

The interface is import-safe and stdlib-only: it holds no transport, no
credential and no provider SDK.  The transport belongs to a concrete provider
on the trusted side of the boundary (feature 150's orchestrator); this module
is the contract the transport is written against.
"""

from __future__ import annotations

from ._batch_completion import (
    BatchCompletion,
    BatchRequest,
    NotImplementedBatchError,
    require_batch_completion,
)
from ._completion import Completion
from ._errors import (
    CompletionMalformedError,
)
from ._request import Request

__all__ = ["Provider"]


class Provider:
    """The one seam every model call passes through.

    A caller holds a :class:`Provider` and calls :meth:`complete` with a
    :class:`~providers.Request`; the answer is a
    :class:`~providers.Completion`, whatever provider is bound underneath.
    The base class enforces the contract in both directions — it validates the
    request on the way in and the completion on the way out — so a concrete
    provider only implements :meth:`_complete`, and a caller only reads the
    completion, and neither has to worry about the shape the other would
    otherwise have to check.

    The batch half of the seam mirrors the single one.  A caller calls
    :meth:`complete_batch` with a :class:`~providers.BatchRequest`; the answer
    is a :class:`~providers.BatchCompletion` — one completion per request, in
    order — whatever provider is bound underneath.  The base class enforces the
    same contract around it: it validates the batched request, delegates to the
    provider's :meth:`_complete_batch`, and validates the batched answer.  A
    provider that serves a batch endpoint overrides :meth:`_complete_batch` and
    answers many requests in one transport call; one that does not leaves the
    base, which refuses the batch by name rather than silently answering one at
    a time.  The single path is untouched, and a non-batch call behaves exactly
    as before.
    """

    def complete(self, request: object) -> Completion:
        """Complete one request, returning a normalized completion.

        The interface's one operation, and the whole of feature 192: a
        request goes in, a completion comes out.  The base class does the
        enforcement that makes that a promise rather than a hope — it checks
        the argument is a :class:`~providers.Request`, hands it to the
        provider's :meth:`_complete`, and then checks the answer is a
        :class:`~providers.Completion` before returning it.  The completion
        check runs after the backend, so a provider that answered wrong is
        caught, and before the caller, so the malformed answer never reaches
        one.  A caller therefore only ever receives a well-formed completion,
        which is the point of a normalized interface: the shape is enforced at
        the seam, not remembered by every reader.
        """
        if not isinstance(request, Request):
            raise CompletionMalformedError(
                f"complete() takes a Request, got {request!r} "
                f"({type(request).__name__}). The provider interface has one "
                f"kind of call: a caller sends a normalized request and gets a "
                f"normalized completion. A non-request is not that call, and "
                f"forwarding it to a provider would be asking the provider to "
                f"guess at a shape the interface exists to fix."
            )
        self.check_model(request.model)
        completion = self._complete(request)
        if not isinstance(completion, Completion):
            raise CompletionMalformedError(
                f"a provider returned {completion!r} ({type(completion).__name__}) "
                f"rather than a Completion. Feature 192's one promise is that "
                f"every model call returns a normalized completion; a provider "
                f"that returns anything else — a raw SDK response, a string, a "
                f"dict — has broken that promise, and the refusal is raised "
                f"here, at the seam, so the malformed answer never travels "
                f"downstream to a reader that would meet an AttributeError on "
                f"completion.content."
            )
        return completion

    def complete_batch(self, batch: object) -> BatchCompletion:
        """Complete a batch of requests, returning one completion per request.

        The batch half of the seam, and the mirror of :meth:`complete`: a
        :class:`~providers.BatchRequest` goes in, a
        :class:`~providers.BatchCompletion` comes out — one completion per
        request, in request order, each carrying the model that served it.
        The base class does the same enforcement the single call gets: it
        checks the argument is a :class:`~providers.BatchRequest`, hands it to
        the provider's :meth:`_complete_batch`, and then checks the answer is
        a :class:`~providers.BatchCompletion` before returning it.  The answer
        check runs after the backend, so a provider that answered wrong is
        caught, and before the caller, so the malformed answer never reaches
        one.

        A provider that serves a batch endpoint overrides
        :meth:`_complete_batch` and answers many requests in one batched
        transport call — the whole point of routing depth through a batch
        endpoint (architecture §14.1, feature 201).  A provider that does not
        leaves the base :meth:`_complete_batch`, which refuses the batch by
        name (:class:`~providers.NotImplementedBatchError`) rather than
        silently answering one request at a time.  The single path is
        untouched, and a non-batch call behaves exactly as before: the batch
        operation is an addition to the interface, not a replacement for it.
        """
        if not isinstance(batch, BatchRequest):
            raise CompletionMalformedError(
                f"complete_batch() takes a BatchRequest, got {batch!r} "
                f"({type(batch).__name__}). The provider interface's batch "
                f"operation has one kind of call: a caller sends a batch of "
                f"normalized requests and gets a batch of normalized "
                f"completions. A non-batch is not that call, and forwarding it "
                f"would be asking the provider to guess at the shape the "
                f"interface exists to fix."
            )
        for index, request in enumerate(batch.requests):
            self.check_model(request.model)
        answer = self._complete_batch(batch)
        return require_batch_completion(answer)

    def _complete_batch(self, batch: BatchRequest) -> BatchCompletion:
        """Perform the batched completion the interface has already admitted.

        The batch-capable provider's job: turn an admitted
        :class:`~providers.BatchRequest` into a
        :class:`~providers.BatchCompletion` — one completion per request, in
        request order, each carrying the model that served it.  The base class
        has already validated the batch and each request, so an implementation
        may assume them and only produce the answer — the enforcement around
        it (the batched-request check, the batched-answer check, the error
        vocabulary) is the base's.

        The default refuses the batch by name: a provider that serves no batch
        endpoint has not opted into this operation, and answering one request
        at a time behind it would hide that fact from a caller that chose the
        batched path expecting one transport call.  A caller that wants the
        batched path binds a batch-capable provider; a caller that must accept
        either catches :class:`~providers.NotImplementedBatchError` and falls
        back to one :meth:`complete` per request.
        """
        raise NotImplementedBatchError(
            "a provider must implement _complete_batch to answer a batch; the "
            "base Provider refuses a batch rather than silently completing one "
            "request at a time. The batch operation is an addition to the "
            "interface, not a replacement for it — a provider with no batch "
            "endpoint is called once per request through complete(), and a "
            "caller that wants the batched path binds a batch-capable provider "
            "(or catches NotImplementedBatchError and falls back)."
        )

    def _complete(self, request: Request) -> Completion:
        """Perform the completion the interface has already admitted.

        The provider's one job: turn an admitted :class:`~providers.Request`
        into a :class:`~providers.Completion`.  The base class has already
        validated the request and the model, so an implementation may assume
        both and only produce the answer — the enforcement around it (the
        request check, the completion check, the error vocabulary) is the
        base's, which is why a concrete provider is this method and nothing
        else.  A subclass puts its transport, its fixture store, or its
        routing here.
        """
        raise NotImplementedError(
            "a provider must implement _complete; the base Provider is the "
            "interface's contract and enforcement, and a deployment binds a "
            "concrete provider (a recorded-fixture backend, a live transport) "
            "in its place."
        )

    def check_model(self, model: str) -> str:
        """Refuse a model the provider does not serve, before the call.

        The provider's chance to declare the models it handles and to refuse
        an unknown one *before* the call is attempted — a configuration error
        the caller can fix, not a runtime failure discovered mid-request.  The
        default accepts any model, so a passthrough or a router that forwards
        to whatever it is handed inherits the interface without inventing a
        restriction the feature does not state; a provider that pins a set
        overrides this to raise :class:`~providers.UnknownModelError` on a
        name outside it.  Returning the model lets a provider normalize an
        alias to its canonical form, but the default passes it through
        unchanged.
        """
        return model

    # -- convenience, not contract -------------------------------------------
    # These helpers exist so a concrete provider — and the tests that drive it
    # — can build the small records the interface carries without importing
    # them from a second place.  They are the interface's own vocabulary,
    # re-exported, so a provider is written in terms of Provider alone.

    @staticmethod
    def completion(
        *,
        content: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        finish_reason: str = "stop",
    ) -> Completion:
        """Build a :class:`~providers.Completion` from the interface's fields.

        A convenience for a provider's :meth:`_complete`, which otherwise
        would reconstruct the same keyword arguments at every return site.
        Delegates validation to the completion, so a completion built here is
        validated by the same guard as one built anywhere else — there is one
        way to make a completion, and it always checks.
        """
        from ._completion import Usage

        return Completion(
            content=content,
            model=model,
            usage=Usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
            ),
            finish_reason=finish_reason,
        )
