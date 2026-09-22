"""The recorded-fixture backend's one error — feature 193's refusal.

Feature 193 — *"System implements a recorded-fixture provider backend, which
returns stored responses so the full loop runs with no network access"* — is
the offline half of the recording story :mod:`providers._recorder` begins.  Its
backend answers a model call from a response that was captured earlier, so the
loop runs the full depth without a single network round trip.  The one thing
that can go wrong on *that* seam is a prompt nothing captured: the loop asked a
question the record has no answer to.

That failure is refused as :class:`FixtureNotFoundError`, and the refusal is
deliberately a :class:`~providers.ProviderError` rather than a second base.  The
split in :mod:`providers._errors` is by *which contract* was violated, never by
which line failed, and a recorded backend that cannot answer is a violation of
the provider contract — a caller that holds the interface and catches
:class:`ProviderError` is catching "the provider could not complete this call",
which is exactly the state a missing fixture is.  Keeping it under the one base
is what lets a single ``except ProviderError`` cover a malformed completion, a
missing provider *and* a missing recording, so a CI check that the loop never
fell back to a live network has one handle for every way the offline path can
stop.

What the refusal must never be is a fallback to a live call.  That is the
load-bearing half of the sentence — *no network access* — and it is enforced at
the seam: a :class:`RecordedProvider` has no transport to forward to, so a
prompt with no recorded response is a hard stop the caller must fix by recording
it (feature 194), not a gap to paper over with an inference request.  The
user-facing *fixture_missing* wording of that stop is feature 195's, which
builds on this error type; this module owns the error and its no-fallback
behaviour, which is feature 193's.

Stdlib-only, like the rest of this tree: the error is the contract, and a
contract should not depend on the transport it stands in for.
"""

from __future__ import annotations

from ._errors import ProviderError

__all__ = ["FixtureNotFoundError"]


class FixtureNotFoundError(ProviderError):
    """A prompt was requested with no response recorded for it.

    The recorded backend's one failure mode, and the "no network" half of
    feature 193's promise made concrete: a :class:`~providers.RecordedProvider`
    answers from stored responses and has no transport to fall back to, so a
    prompt nothing captured cannot be answered and must not be — forwarding it
    to a live model would be the network access this feature exists to remove.
    The refusal is therefore a hard stop, raised at the seam, that the caller
    fixes by recording the prompt rather than by catching and retrying online.

    Distinct from :class:`~providers.ProviderNotConfiguredError` because "there
    is no backend at all" and "the backend has no answer for *this* prompt" are
    two different problems a caller may want to tell apart — the first is a
    deployment gap, the second a recording that is incomplete — and collapsing
    them would leave the caller unable to say which.  And distinct from
    :class:`~providers.CompletionMalformedError` because a missing recording is
    not an answer that came back wrong; nothing answered.
    """
