"""The provider interface's batch operation — one call, many requests.

Feature 192 fixes the seam every model call passes through as a single
request in, a single completion out (:meth:`providers.Provider.complete`).
This module adds the seam's *batch* half: a caller hands the provider a batch
of normalized requests and gets back a batch of normalized completions, in
order, each completion carrying the model that served it — so a provider that
serves a batch endpoint answers many requests through one batched transport
call.

Why a batch operation belongs on the interface, and why it is thin
------------------------------------------------------------------

The depth role's work is, in architecture §14.1's words, *"pure asynchronous
batch work. Nothing waits on it"*, and §14.1 lists two free levers worth
about 50% of the depth bill: *"Batch APIs halve rates on OpenAI, Anthropic and
Gemini. Route depth through them."*  That routing is feature 201's concern —
*when* to prefer the batch endpoint and at what price — but the routing has
nothing to push through unless the seam itself carries a batch shape.  This
module is that shape: the one argument a caller sends and the one answer it
gets back, normalized exactly as feature 192 normalizes the single call, so a
caller written against the batch interface is portable across a batch-capable
provider and a synchronous one without a rewrite.

The operation is deliberately a mirror of the single one, and the mirror is
the design:

* :meth:`Provider.complete_batch` takes a :class:`BatchRequest`, validates it
  is one, validates each of its requests, delegates to the provider's
  :meth:`_complete_batch`, and then validates the answer is a
  :class:`BatchCompletion` before returning it.  The enforcement is in the
  base, exactly as :meth:`Provider.complete`'s is, so a caller never has to
  check the shape of the answer — a provider that answered wrong is refused
  here, at the seam.

* :class:`BatchRequest` is an ordered tuple of :class:`~providers.Request`,
  frozen and value-equal, refused at construction when it is empty — a batch
  of nothing is not a batched call, and the empty batch has no endpoint
  semantics.

* :class:`BatchCompletion` is an ordered tuple of
  :class:`~providers.Completion`, frozen and value-equal, carrying one answer
  per request in request order.  Each completion names the model that served
  it, so a batch that mixed tiers — the whole point of routing depth through a
  batch endpoint — reports its own authors rather than leaving the caller to
  remember which model answered which request.

What this feature deliberately does **not** do
-----------------------------------------------

The interface holds the contract, not the transport, and that split is the
reason the batch operation lives here as a shape and not as a call.  This
module dials no endpoint, opens no connection and imports no provider SDK —
the same stdlib-only discipline feature 192's single-call seam keeps, and for
the same reason: the transport belongs to a concrete provider on the trusted
side of the boundary (feature 150's orchestrator, feature 201's router), and
this module is the contract that transport is written against.  A provider
puts its batched transport in :meth:`Provider._complete_batch`; a caller puts
nothing but requests in and reads nothing but completions out.

The batch is also deliberately **not** a replacement for the single call.  A
non-batch call and a provider with no batch endpoint behave exactly as before:
:meth:`Provider.complete` is untouched, and a provider that does not override
:meth:`_complete_batch` refuses a batch by name (the base raises
:func:`not implemented <NotImplementedBatchError>` — the seam's own
vocabulary, not the standard library's ``NotImplementedError``) rather than
silently answering one request at a time.  A batch-capable provider answers
many in one call; a synchronous one refuses the batch and is called once per
request, and a caller written against the interface is portable across both.

Recognition across the workspace's double import
------------------------------------------------

The batch records are validated by construction and returned by the base's
:meth:`Provider.complete_batch` as the objects a provider produced, not
re-made from this module's class.  That is a deliberate departure from
:func:`providers.require_depth_model`'s recognition-by-parts, and it has the
same reason that gate needs it and this one does not: :func:`require_depth_model`
admits or refuses a *candidate a caller built elsewhere* — possibly from the
workspace's second copy of the class, over which a dataclass's generated
``__eq__`` answers ``False`` — so it must recognise by parts and answer in one
class.  A batch completion, by contrast, is made by the provider's own
:meth:`_complete_batch` *inside the same provider object the caller is driving*,
so it is already this module's class; the double-import hazard is a hazard of
a record crossing the member boundary, and a batch answer does not cross it —
it is produced and consumed on the seam.  The base still validates each answer
is a :class:`Completion` and the batch is a :class:`BatchCompletion`, so a
provider that returned the wrong shape is refused here regardless.

Stdlib-only, like the rest of this tree.  The batch holds no transport, no
credential and no provider SDK; it is the contract the batched transport is
written against.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._completion import Completion
from ._errors import CompletionMalformedError, ProviderError
from ._request import Request

__all__ = ["BatchCompletion", "BatchRequest", "NotImplementedBatchError"]


class NotImplementedBatchError(ProviderError):
    """A provider was asked to complete a batch it does not serve.

    Feature 192's single-call seam is the base contract every provider
    inherits; its batch half is optional — a provider that serves a batch
    endpoint overrides :meth:`providers.Provider._complete_batch`, and one
    that does not (a synchronous backend, a passthrough) leaves the base,
    which raises this rather than silently answering one request at a time.
    The refusal is the seam's own vocabulary, not the standard library's
    ``NotImplementedError``, and it is a subclass of
    :class:`~providers.ProviderError` for the same reason
    :class:`~providers.ProviderNotConfiguredError` is: a caller catching the
    provider contract with a single ``except`` must catch "this provider
    cannot batch" along with "there was nothing to call" and "the answer was
    malformed" — they are all "the batched call could not run", and the
    caller's recovery (fall back to one call per request, or surface that the
    deployment bound a non-batch provider) is one branch.

    Raised by the base :meth:`providers.Provider._complete_batch`, which a
    synchronous provider never overrides.  It is deliberately *not* raised by
    :meth:`providers.Provider.complete_batch`: the base's public operation
    admits the batch and delegates, so a provider that cannot batch is caught
    at the delegation, where the caller placed the call, rather than at the
    seam's guard.
    """


@dataclass(frozen=True)
class BatchRequest:
    """The one batched ask: an ordered tuple of normalized requests.

    The batched argument of a caller, normalized exactly as feature 192
    normalizes the single :class:`~providers.Request`: an ordered tuple of
    requests, each already a well-formed :class:`~providers.Request` (each is
    validated on its own construction).  Frozen and value-equal, so a batched
    prompt compares by what was asked rather than by object identity — the
    same testability the single request and the rest of the interface's
    records get from being value types.

    Refused at construction when empty: a batch of no requests is not a
    batched call.  It has no endpoint semantics — a batch API is called to
    answer many requests in one transport round trip, and there is no such
    round trip to make — and answering it would be inventing a shape the
    feature does not state.  A caller with nothing to send sends nothing.
    """

    requests: tuple[Request, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "requests", tuple(self.requests))
        if not self.requests:
            raise CompletionMalformedError(
                "a BatchRequest must carry at least one request, got an empty "
                "batch. A batched call answers many requests in one transport "
                "round trip, and there is no round trip to make with none — a "
                "caller with nothing to send sends nothing, rather than a "
                "batch of zero. Send one or more requests, or call "
                "complete() for a single one."
            )
        for index, request in enumerate(self.requests):
            if not isinstance(request, Request):
                raise CompletionMalformedError(
                    f"BatchRequest.requests[{index}] must be a Request, got "
                    f"{request!r} ({type(request).__name__}). A batch is an "
                    f"ordered tuple of normalized requests, each the one shape "
                    f"feature 192's seam carries; a non-request in the batch is "
                    f"not that shape, and forwarding it would be asking the "
                    f"provider to guess at the shape the interface exists to fix."
                )


@dataclass(frozen=True)
class BatchCompletion:
    """The one batched answer: an ordered tuple of normalized completions.

    The batched answer of a provider, normalized exactly as feature 192
    normalizes the single :class:`~providers.Completion`: one completion per
    request, in request order, each a well-formed :class:`~providers.Completion`
    (each validated on its own construction).  Frozen and value-equal, so a
    suite can assert the whole batched answer against an expected tuple rather
    than replaying field by field.

    Each completion carries the model that served it — the serving model,
    which a tiering or rotation layer may have changed from what was asked —
    so a batch that mixed tiers reports its own authors.  That is the whole
    reason the batched answer is a tuple of completions and not a tuple of
    strings: the model is an answer, not an assumption, and a batch is where a
    deployment most wants it per request, because the batched call is the one
    where many requests are most likely to have been spread across models.
    """

    completions: tuple[Completion, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "completions", tuple(self.completions))


def require_batch_completion(answer: object) -> BatchCompletion:
    """Return ``answer`` as a :class:`BatchCompletion`, refusing anything else.

    The batch half of the base class's out-bound guard: the completion check
    that :meth:`providers.Provider.complete` runs on the single answer,
    applied to the batched one.  A provider that returned the wrong shape — a
    bare list, a tuple of strings, a single completion, ``None`` — is refused
    here, at the seam, so the malformed answer never travels downstream to a
    reader that would meet an ``AttributeError`` on ``completion.content``.
    The refusal is the interface's own vocabulary
    (:class:`~providers.CompletionMalformedError`), never the standard
    library's ``TypeError`` — the seam's error taxonomy is this interface's,
    and a caller catching a malformed completion gets the same answer for the
    batched path as for the single one.
    """
    if not isinstance(answer, BatchCompletion):
        raise CompletionMalformedError(
            f"a provider's batch answer must be a BatchCompletion, got "
            f"{answer!r} ({type(answer).__name__}). Feature 192's batch "
            f"promise is that every batched call returns one normalized "
            f"completion per request, in order; a provider that returns "
            f"anything else — a raw list, a tuple of strings, a single "
            f"completion — has broken that promise, and the refusal is raised "
            f"here, at the seam, so the malformed answer never travels "
            f"downstream to a reader that would meet an AttributeError on "
            f"completion.content."
        )
    return answer
