"""The provider interface's error taxonomy.

Feature 192 gives the deployment one seam every model call passes through
(:class:`providers.Provider`), and one answer every call returns
(:class:`providers.Completion`).  The errors in this module are the failure
modes of *that* seam, and no other: they are raised by the interface's own
guardrails (:func:`providers.require_completion`, the base
:meth:`providers.Provider.complete`), never by a provider's transport, a
network, or the model itself.  Keeping the taxonomy this narrow is the point
— a caller that catches :class:`ProviderError` is catching "the provider
contract was violated", not "the HTTP client sneezed", and the two must not
share a base class or the caller's ``except`` would be answering two
questions at once.

The splits follow the contract's own shape rather than the code that
happened to fail, in the same discipline as the rest of the tree's error
vocabularies (``infra.security.network_policy``, ``snapshot._errors``):

* :class:`ProviderError` — the base.  One base so a caller — the signal
  agent's prompt runner, a suite, a CI check that the loop never fell back
  to a live network — can catch every failure of this interface with a
  single ``except``.

* :class:`CompletionMalformedError` — the answer a provider returned did not
  carry the contract's fields.  This is the load-bearing one: feature 192's
  whole promise is that *every* call returns a normalized completion, so a
  provider that returned anything else is not a provider the deployment can
  use, and the refusal is raised here, at the seam, rather than surfacing
  later as an ``AttributeError`` when some downstream reader touches
  ``completion.content``.  It is the interface that enforces the shape, not
  the caller that has to remember to check it.

* :class:`ProviderNotConfiguredError` — the seam was asked to run with no
  provider bound.  Distinct from :class:`CompletionMalformedError` because
  "there is nothing to call" and "what was called answered wrong" are two
  different problems a caller may want to tell apart — the first is a
  deployment gap, the second a provider bug — and collapsing them would
  leave the caller unable to say which.

* :class:`UnknownModelError` — the model name a call named is not one this
  provider serves.  Raised before the call is attempted, because a model the
  provider does not know is a configuration error the caller can act on, not
  a runtime failure to be discovered halfway through a request.

Stdlib-only, like the rest of this tree: nothing here dials a network or
imports a provider SDK.  The errors are the contract, and a contract should
not depend on the transport that happens to carry it.
"""

from __future__ import annotations

__all__ = [
    "CompletionMalformedError",
    "ProviderError",
    "ProviderNotConfiguredError",
    "UnknownModelError",
]


class ProviderError(Exception):
    """Base of the provider-interface taxonomy.

    One base class so a caller can catch every failure of the provider
    contract — a malformed completion, a missing provider, an unknown model —
    with a single ``except``, the way ``infra.security``'s boundary errors
    and ``snapshot``'s sealing errors each give their callers one handle.
    The subclasses split by *which contract* was violated, never by which
    line of code failed.
    """


class CompletionMalformedError(ProviderError):
    """A provider returned something that is not a normalized completion.

    Feature 192's one promise: every model call returns a completion with the
    contract's fields.  A provider that returned ``None``, a bare string, a
    dict, or an object missing one of the fields has broken that promise, and
    this is the refusal.  Raised by :func:`require_completion` at the seam,
    so the malformed answer never travels downstream to a reader that would
    otherwise meet an ``AttributeError`` on ``completion.content`` — the
    interface enforces the shape, so the caller does not have to.
    """


class ProviderNotConfiguredError(ProviderError):
    """A call was attempted with no provider bound to the interface.

    The seam was asked to complete but holds no provider — no backend, no
    transport, no default model.  Distinct from :class:`CompletionMalformedError`
    because "there is nothing to call" is a deployment gap, not a provider
    that answered wrong, and a caller that wants to report the difference
    ("configure a provider" versus "the provider is broken") must be able to
    catch the two separately.
    """


class UnknownModelError(ProviderError):
    """The model a call named is not one the provider serves.

    Raised *before* the call is attempted, at the point the request is
    validated: a model name the provider does not know is a configuration the
    caller can fix, not a runtime failure to be discovered mid-request.  The
    provider's served set is its own to declare — a concrete provider names
    the models it handles, and a name outside that set is refused here rather
    than being forwarded to a transport that would answer with a less
    informative error.
    """
