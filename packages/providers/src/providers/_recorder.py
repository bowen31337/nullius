"""The recorder: the provider seam wrapped so every exchange is kept.

Feature 192 fixes the seam every model call passes through; features 193 and
194 build the recorded-fixture layer on top of it — a provider that answers
from stored responses, and one that writes an exchange to a fixture file keyed
by a prompt hash.  This module is the piece both of those need: a
:class:`~providers.Provider` wrapper that sits *on top of* another provider
(the live transport, in a deployment) and keeps every request and its
completion together, in order, so the exchange can be persisted (feature 194)
or replayed (feature 193) later.

The wrapper is a :class:`~providers.Provider`, and that is the whole design:
it is drop-in for whatever it wraps, because it *is* a provider — a caller
holding the interface cannot tell the recorder from the provider underneath,
and need not.  It forwards :meth:`complete` to the wrapped provider, and on
the way records the :class:`~providers.Request` it was handed and the
:class:`~providers.Completion` it got back, as one :class:`Exchange` entry.
The recording is a side effect of the normal path, so nothing about how a call
is made changes when the recorder is in front — the loop runs exactly as it
would against the bare provider, and the exchange is kept as a by-product.

What the recorder does *not* do is as load-bearing as what it does:

* It does not answer from the record — that is feature 193's provider, a
  separate object.  A recorder with no wrapped provider has nothing to
  forward to and raises :class:`~providers.ProviderNotConfiguredError`; it is
  a tap, not a source.  Keeping the two apart is deliberate: "keep every
  exchange" and "answer from kept exchanges" are two responsibilities, and a
  single object that did both would be unable to refuse a missing fixture the
  way feature 195 requires (it would fall back to the live call it is meant to
  be recording around).

* It does not hash the prompt or write a file — that is feature 194's job,
  and it builds on the :class:`Exchange` this module produces.  The recorder
  hands up a clean, ordered list of request/completion pairs; the
  persistence layer decides how to key and store them.  A recorder that also
  wrote fixtures would be re-specifying feature 194's storage contract inside
  feature 192's seam, which is the divergence the interface exists to avoid.

The recorder holds the wrapped provider by construction and refuses a
non-provider, because the one thing a tap must be is connected to what it taps
— a recorder around nothing is a run that records nothing and fails silently,
which is the failure mode the raised refusal prevents.  Its record is a tuple
of :class:`Exchange` entries, value-equal, so a suite can assert the whole
kept exchange against an expected list rather than replaying field by field.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._completion import Completion
from ._errors import ProviderError
from ._provider import Provider
from ._request import Request

__all__ = ["Exchange", "RecordingProvider"]


@dataclass(frozen=True)
class Exchange:
    """One recorded model exchange: the request that was made and its answer.

    The unit a :class:`RecordingProvider` keeps.  ``request`` is the
    :class:`~providers.Request` the caller sent, and ``completion`` is the
    :class:`~providers.Completion` it got back — the two persisted together,
    because feature 194 keys a fixture by "the prompt that was asked" and
    stores "the answer it got" beside it, and a fixture that split the two
    into separate records would be unable to say which answer matched which
    ask.  Frozen and value-equal, so a recorded exchange compares to an
    expected one by what was asked and answered, not by object identity.
    """

    request: Request
    completion: Completion


class RecordingProvider(Provider):
    """A provider that keeps every exchange it forwards.

    A :class:`~providers.Provider` that wraps another provider and records each
    :class:`~providers.Request` with the :class:`~providers.Completion` it
    returned, as one :class:`Exchange`, in order.  It is drop-in for what it
    wraps — a caller cannot tell it from the provider underneath — so a
    deployment slides it in front of the live transport to capture an
    exchange, and a suite wraps any provider to assert on the calls it saw.
    The recording is a side effect of the normal :meth:`complete` path, so the
    loop runs unchanged while the exchange is kept.
    """

    def __init__(self, provider: Provider) -> None:
        # The wrapped provider is the thing being tapped, held by type so a
        # recorder around anything that is not a provider is refused at
        # construction — a tap must be connected to what it taps, and a
        # recorder that silently forwarded to nothing would record nothing and
        # fail nowhere.
        if not isinstance(provider, Provider):
            raise ProviderError(
                f"a RecordingProvider must wrap a Provider, got {provider!r} "
                f"({type(provider).__name__}). The recorder is a tap over the "
                f"provider interface; something that is not a provider is not "
                f"that interface and has no complete() to forward through."
            )
        self._provider = provider
        self._exchanges: list[Exchange] = []

    def _complete(self, request: Request) -> Completion:
        # The base class has already validated the request and the model, so
        # this forwards to the wrapped provider and keeps the pair as one
        # exchange.  The completion is appended only after the wrapped provider
        # returns, so a call that raised leaves no half-recorded entry — the
        # record holds completed round trips, not attempts.
        completion = self._provider.complete(request)
        self._exchanges.append(Exchange(request=request, completion=completion))
        return completion

    def exchanges(self) -> tuple[Exchange, ...]:
        """Every exchange this recorder forwarded, in order.

        One entry per completed round trip, in the order it was made, each
        carrying the request and its completion together.  A suite asserts on
        this to confirm which calls reached the provider and what they
        returned; the persistence layer (feature 194) reads the same list to
        write a fixture.  A call that raised left no entry, so the record is
        the calls that actually completed, not the ones that were tried.
        """
        return tuple(self._exchanges)

    def requests(self) -> tuple[Request, ...]:
        """The requests this recorder forwarded, in order — the exchanges, unwrapped."""
        return tuple(exchange.request for exchange in self._exchanges)

    def completions(self) -> tuple[Completion, ...]:
        """The completions this recorder returned, in order — the exchanges, unwrapped."""
        return tuple(exchange.completion for exchange in self._exchanges)
