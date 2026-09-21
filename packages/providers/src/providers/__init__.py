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

Feature 203 — *"System persists ``agent_model_id`` per node as a provider,
model and version triple rather than a rolling alias"* — is the other half of
that story, and the reason this member's second registered component exists.
Feature 192 normalizes *the call*; feature 203 pins *the node* the call
produced, so the tree records which model authored it in a form a
stratification can group by.  Its three records are the second half of this
package's surface:

* :class:`ModelPin` — the triple itself (``provider``, ``model``, ``version``),
  frozen and value-equal, refused at construction unless all three parts are
  non-empty, separator-free and canonical.  A one-part value like
  ``'deepseek-flash'`` is a *rolling alias* — architecture §14.1 records
  DeepSeek retiring that very id on 2026-09-10 while continuing to accept it —
  and :func:`require_agent_model_id` refuses it in both directions, on the way
  in and on the way out of the store.

* :class:`AgentModelPins` — the store that writes the triple onto a node's
  ``agent_model_id`` column, and :class:`NodePin` the answer it gives back
  (the pin, and whether *this* call wrote it or was answered by the row that
  was already there).  The column is the core migration ``0115``'s (feature
  100) and the ``node`` table ``0118``'s (feature 97); this store writes
  through them and never creates or alters a schema it does not own.

* :class:`~providers.ModelPinError` and its four subclasses
  (:class:`~providers.RollingAliasError`,
  :class:`~providers.ModelPinConflictError`,
  :class:`~providers.NodeNotRecordedError`,
  :class:`~providers.PinColumnError`) — feature 203's own vocabulary,
  deliberately sharing no ancestor with :class:`~providers.ProviderError`:
  a node stamped with an alias is not a model call that failed, and one
  ``except`` must not answer both questions.  See :mod:`providers._pin_errors`.

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
plugin exist; importing this module *is* joining the application.  **Two**
components are registered from this one package, and the split is the split
between the category's first feature and its last-but-one.  Feature 192's
interface (``providers``) contributes no long-lived component to the composed
application: the provider interface is a contract and a set of records, not a
service the deployment instantiates once — a caller binds whatever provider it
wants (a recorded-fixture backend, a live transport, wrapped in a
:class:`RecordingProvider`) and holds it directly, so that builder returns
``None`` and the interface's records are imported directly by scripts, tests
and the sibling features of this category.  Feature 203's pin store
(``agent-model-pins``) is the opposite: it *is* a deployment-bound service —
a store over the tree the process is pointed at — so its builder resolves
``DATABASE_URL`` and composes an :class:`AgentModelPins` (or nothing, when no
store is named).  Both registrations live in this ``__init__`` and neither in
a submodule, because a submodule's ``@register`` fires only on the first
``create_app()`` of a process and would silently drop out of every later one.

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
from ._pin_errors import (
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    PinColumnError,
    RollingAliasError,
)
from ._pin_store import AgentModelPins, NodePin
from ._pinning import (
    AGENT_MODEL_ID_COLUMN,
    MODEL_PIN_PARTS,
    MODEL_PIN_REVISION,
    SEPARATOR,
    ModelPin,
    require_agent_model_id,
)
from ._provider import Provider
from ._recorder import Exchange, RecordingProvider
from ._request import Message, Request

__all__ = [
    "AGENT_MODEL_ID_COLUMN",
    "MODEL_PIN_PARTS",
    "MODEL_PIN_REVISION",
    "SEPARATOR",
    "AgentModelPins",
    "Completion",
    "CompletionMalformedError",
    "Exchange",
    "Message",
    "ModelPin",
    "ModelPinConflictError",
    "ModelPinError",
    "NodeNotRecordedError",
    "NodePin",
    "PinColumnError",
    "Provider",
    "ProviderError",
    "ProviderNotConfiguredError",
    "RecordingProvider",
    "Request",
    "RollingAliasError",
    "UnknownModelError",
    "Usage",
    "build_agent_model_pins",
    "require_agent_model_id",
]

#: The component name this package registers its pin store under.  The plugin
#: name plus what it contributes, following the ``bootstrap`` /
#: ``artifacts`` / ``sandbox`` precedent for a member's *second* component (a
#: member's first usually takes the bare plugin name — :data:`PROVIDERS_COMPONENT`
#: below does).  Spelled here so the seat
#: (``src/app/modules/providers``) and the composed application agree on the
#: key, with the behaviour — a test, not a shared constant — as the thing
#: that keeps them from drifting silently.
AGENT_MODEL_PIN_COMPONENT = "agent-model-pins"

#: The component name feature 192's interface seam registers under.  It
#: contributes ``None`` (see :func:`provider_interface`), so nothing is stored
#: under it; the name exists so ``create_app()``'s composition order carries
#: the interface's registration beside the store's.
PROVIDERS_COMPONENT = "providers"


@register(PROVIDERS_COMPONENT)
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


@register(AGENT_MODEL_PIN_COMPONENT)
def build_agent_model_pins() -> AgentModelPins | None:
    """Component builder: the store that pins each node's authoring model.

    Feature 203's contribution to the composed application: the
    :class:`~providers.AgentModelPins` store this deployment writes node pins
    into.  Takes no arguments — that is the factory's registration protocol —
    and resolves ``DATABASE_URL`` at build time, so a composed application
    carries the pin store for the deployment the process is actually running
    in.

    Returns ``None`` when nothing names a relational store.  That is
    deliberately **not** an empty store: an empty store answers *no node is
    pinned here* about every id, while this ``None`` says there is no database
    to have pinned one in — and a caller that must persist feature 203's triple
    has to treat it as a refusal to proceed rather than as a store that
    happened to find nothing.  The distinction is the one
    :func:`discovery.build_campaign_records` draws for its own deployment
    state, and it matters more here, because a node pinned into nothing is a
    node whose model stratum the ablation will never find.

    Never raises for the URL itself: a URL whose scheme this member cannot
    speak is refused by name the first time an operation needs the path, not
    here.  Construction performs no I/O — the path is resolved on first use —
    so composing the application never opens a database, and nothing is
    written until a caller demands a pin.
    """
    return AgentModelPins.resolve()
