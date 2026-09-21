"""The provider interface — one seam every model call passes through.

Implements app_spec.xml feature 192, "System defines one provider interface
that every model call passes through, which returns a normalized completion
object", on the layout of ``docs/nullius-tech-architecture.md`` §17-§19: the
LLM API call happens outside the sandbox, in the orchestrator (feature 150),
and this package is the *contract* that call is made through — the one shape a
caller sends a request in and gets a completion out of, whatever provider is
bound underneath.

That contract is the whole of this package, and it is thin by design.  A
caller holds a :class:`Provider`, hands it a :class:`Request`, and gets back a
:class:`Completion` — and never sees a provider SDK's response type, a
transport's payload, or a model-specific shape.  The answer is the same object
in every case, so a caller written against the interface is portable across
providers and across tiers without a rewrite.  The four records are the
interface's entire surface:

* :class:`Provider` — the seam.  A base class (not a bare protocol, so the
  normalization is base behaviour every provider inherits) whose
  :meth:`Provider.complete` validates the request on the way in, delegates to
  the provider's :meth:`_complete`, and validates the answer is a completion
  on the way out.  The enforcement that a call returns a normalized completion
  lives in the base, so a caller never has to check the shape — a provider
  that answered wrong is refused here, at the seam.

* :class:`Completion` — the one answer.  ``content``, ``model`` (the serving
  model, which a tiering layer may have changed from what was asked),
  ``usage`` (the token accounting) and ``finish_reason`` (a closed set:
  ``stop`` or ``length``).  Frozen and value-equal.

* :class:`Request` — the one ask.  An ordered ``messages`` conversation (each
  turn a :class:`Message` with a closed-set ``role``), the ``model`` wanted,
  and the two sampling knobs the deployment's prompts turn.  Frozen and
  value-equal, so a request compares equal to a recorded one — how the
  recording layer keys a fixture by "the prompt that was asked".

* :class:`RecordingProvider` — the bridge to the recorded-fixture layer
  (features 193 and 194).  A :class:`Provider` that wraps another and keeps
  every request with its completion, in order, as an :class:`Exchange`.  It is
  a tap, not a source: it forwards and records, and does not answer from the
  record (that is feature 193's separate provider) or write a fixture file
  (that is feature 194's).

The error taxonomy (:mod:`providers._errors`) is the failure modes of *this*
seam and no other — a malformed completion, a missing provider, an unknown
model — raised at the interface's own guardrails, never by a provider's
transport or the model.  Keeping it narrow is deliberate: a caller catching
:class:`ProviderError` is catching "the provider contract was violated", not
"the HTTP client sneezed".

This package is a workspace member discovered by convention. The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml`` declares
(``packages/*``), imports each package, and composes whatever the package's
``@register`` builder contributes — so the registration below is the entire
wiring story. Nothing edits a registry, router or factory to make the provider
plugin exist; importing this module *is* joining the application.  The plugin
deliberately contributes no long-lived component to the composed application:
the provider interface is a contract and a set of records, not a service the
deployment instantiates once — a caller binds whatever provider it wants
(a recorded-fixture backend, a live transport, wrapped in a
:class:`RecordingProvider`) and holds it directly.  The builder returns
``None`` so composition contributes nothing, and the interface's records are
importable directly for scripts, tests and the sibling features of this
category, which build on these seams.

Stdlib-only, like the rest of this tree.  The interface holds no transport, no
credential and no provider SDK — those belong to a concrete provider on the
trusted side of the boundary (feature 150's orchestrator); this module is the
contract the transport is written against.
"""

from __future__ import annotations

from app.module_loader import register

from ._completion import Completion, Usage
from ._errors import (
    CompletionMalformedError,
    ProviderError,
    ProviderNotConfiguredError,
    UnknownModelError,
)
from ._provider import Provider
from ._recorder import Exchange, RecordingProvider
from ._request import Message, Request

__all__ = [
    "Completion",
    "CompletionMalformedError",
    "Exchange",
    "Message",
    "Provider",
    "ProviderError",
    "ProviderNotConfiguredError",
    "RecordingProvider",
    "Request",
    "UnknownModelError",
    "Usage",
]


@register("providers")
def provider_interface() -> object | None:
    """Component builder: the provider interface, contributing no component.

    Takes no arguments — that is the factory's registration protocol.  The
    provider interface is a contract and a set of records, not a service the
    deployment instantiates once, so the builder returns ``None`` and
    contributes nothing to the composed application.  The interface's records
    (:class:`Provider`, :class:`Completion`, :class:`Request`,
    :class:`RecordingProvider`) are imported directly wherever they are used —
    by a caller that binds a provider, by a suite that drives one, by the
    sibling features of this category (the recorded-fixture backend of feature
    193, the fixture recorder of feature 194) that build on this seam.

    The registration is the wiring: it makes ``import providers`` join the
    application, so the interface exists in every composed process without any
    central registry, router or factory being edited to add it.
    """
    return None
