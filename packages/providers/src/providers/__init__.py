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

Feature 198 — *"System rejects a depth model without a 1 million token
context at flat pricing, because calls at depth 2 or greater carry a large
history"* — is the depth role's selection criterion, and the reason the
category is called *tiering*: feature 192's interface normalizes the call,
and this one decides which model may take the cheap half of them.  Its
records join the interface's as direct imports rather than components (see
:func:`provider_interface` for why a contract registers no service — a
criterion consulted before any call is placed has nothing to instantiate):

* :class:`DepthModel` — a candidate for the depth role as the registry
  describes it: the model's name, the context window it serves in tokens,
  and the long-context surcharge threshold its rate card reprices the whole
  request above (:func:`flat_pricing` spells the flat case — no threshold,
  flat at any context).  Shape-validated on construction and deliberately
  not bar-validated: a 262K-window model is a well-formed candidate — §14.1
  lists exactly such a tier for early depth, narrow campaigns and the
  bootstrap worlds — because describing one is not serving one.

* :func:`require_depth_model` — the gate.  A candidate serves the depth ≥ 2
  role only with at least :data:`MIN_DEPTH_CONTEXT_TOKENS` (one million)
  tokens of context **at flat pricing** — the window at least the bar, and
  no surcharge threshold below it, because §14.2's average depth call
  (~300K tokens, late calls beyond 600K) sits above every major provider's
  repricing threshold.  Refused as
  :class:`~providers.InsufficientContextError` or
  :class:`~providers.LongContextSurchargeError` — the two ways the
  sentence's one property can be missing, window first, since a model that
  physically cannot hold the history fails before what it costs matters.

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

Feature 204 — *"System persists ``agent_ckpt_hash`` for self-hosted weights plus
``agent_sampling`` recording temperature, top_p, thinking and seed"* — is the
rest of that same record.  Feature 203's sentence pins *which model*; feature
204's pins *which weights* and *which dice*, and the two are two halves of one
row because ``0115`` adds all three columns in one migration.  Its records:

* :class:`AgentSampling` — the four settings, frozen and value-equal, every one
  validated on construction and every one always present in the stored form:
  ``temperature`` in ``[0, 2]``, ``top_p`` in ``(0, 1]``, ``thinking`` a strict
  ``bool``, ``seed`` a non-negative int inside the signed 64-bit range.
  :func:`require_agent_sampling` parses the canonical JSON the column holds and
  requires all four keys of a document, because a record naming three settings
  is not a smaller answer than one naming four — the setting most often left
  out is ``seed``, the one that makes replay reproduce the node.  See
  :mod:`providers._sampling`.

* :func:`require_agent_ckpt_hash` — the checkpoint digest, 64 hex characters,
  case-folded like :func:`artifacts.canonical_code_hash`, with the
  ``sha256:``-prefixed *image-reference* spelling refused by name.  ``None`` is
  not a malformed hash but the hosted-API case, spelled
  :func:`hosted_api_weights` so that *"these weights are a provider's"* is a
  state a caller **states** rather than a field it forgets.  See
  :mod:`providers._ckpt`.

* :class:`AgentWeights` and :class:`NodeProvenance` — the pair feature 204's
  two columns are written and read as, and the ``recorded`` tri-state that says
  whether *this* call wrote them (``True``), found them already there
  (``False``), or had nothing to record (``None``).

* :class:`~providers.AgentSamplingMalformedError`,
  :class:`~providers.CkptHashMalformedError`,
  :class:`~providers.CkptHashConflictError`,
  :class:`~providers.SamplingConflictError` and
  :class:`~providers.NodeProvenanceError` — feature 204's five, and they join
  feature 203's taxonomy **under the same base** rather than minting a second
  one.  The split is by column and the columns are one row: a caller asking
  *could this node's authoring record be pinned?* is asking one question, and a
  second base would make it two ``except`` clauses and one more way to write
  only one of them.  Neither base is :class:`~providers.ProviderError`'s
  ancestor, for the reason above.

Feature 202 — *"System schedules depth campaigns outside a configured peak
pricing window, persisting the chosen window with each run"* — is the
category's second economics lever, and §14.2's second of its *"two free
levers worth ~50%"*: the depth role *"is pure asynchronous batch work.
Nothing waits on it"*, so its campaigns can wait out the hours a rate card
prices higher (*"DeepSeek prices by time of day — peak is 01:00–04:00 and
06:00–10:00 UTC, off-peak is 50% lower. Schedule campaigns outside those
windows."*).  Its records join the depth criterion's as direct imports
alongside one registered component — the store, because a scheduling
decision is a fact that must actually land in a table (see
:mod:`providers._schedule` for the surface's shape and its reasons):

* :class:`PeakWindow` and :class:`PeakPricing` — **the configuration**: a
  rate card's peak windows as daily UTC time-of-day intervals, stated
  rather than baked (§14.2's own preamble: *"rates move monthly … the
  selection logic is stable, the numbers are not"*), with empty meaning
  flat by time of day for the same reason
  :func:`flat_pricing` exists — the null is load-bearing.

* :func:`choose_run_window` and :class:`RunWindow` — **the choice**: the
  earliest window at or after the scheduling instant that touches no
  configured peak minute, refused as
  :class:`~providers.NoOffPeakWindowError` when the declared run length
  exceeds the largest off-peak gap the card leaves.

* :class:`DepthRunWindows` and :class:`ScheduledRun` — **the
  persistence**: the store that owns the ``depth_run_window`` table (the
  bootstrap pool's member-owned-table precedent, no edit to the shared
  migration chain), schedules one campaign's runs in one call, and
  answers the row the table holds — window, premise and decision instant
  together, so a decision can be audited against the card that was
  current when it was made.

* :class:`~providers.DepthScheduleError` and its three subclasses
  (:class:`~providers.NoOffPeakWindowError`,
  :class:`~providers.UnknownCampaignError`,
  :class:`~providers.RunWindowConflictError`) — a **fourth** base, for
  the question none of the other three answers: *when may this
  campaign's runs happen?*  See :mod:`providers._schedule_errors`.

Feature 201 — *"System routes depth calls through a batch endpoint when
available, which returns roughly half the synchronous rate"* — is §14.2's
**first** of its *"two free levers worth ~50%"* (202 is the second), and it
rests on the same fact 202's does: the depth role *"is pure asynchronous
batch work.  Nothing waits on it"*.  Its records join the depth criterion's
as direct imports and add no component — a routing decision is a property of
a single call, not a deployment-bound fact that must land in a table (see
:mod:`providers._batch` for the surface's shape and its reasons):

* :class:`BatchEndpoint` and :class:`BatchPricing` — **the
  configuration**: one provider's batch offering (its name, whether it
  offers a batch endpoint at all, and the fraction of the synchronous rate
  it bills) and the card collecting them.  §14.2's *"roughly half"* is a
  description, not a constant: no fraction is baked into the module, for
  the same reason feature 202 bakes in no peak window — *"rates move
  monthly … the selection logic is stable, the numbers are not"*.

* :func:`route_depth_call` and :class:`RoutedCall` — **the choice**: the
  endpoint a depth call goes to, the provider it is served by, and the
  **rate multiple** it is billed at (``1.0`` synchronously, the card's
  fraction batched).  A provider with no batch endpoint, and a call the
  caller did not declare batchable, both route synchronously — the
  sentence's own *"when available"* is a condition the routing reads, not
  an error it reports.

* :class:`~providers.BatchRoutingError` and its one subclass
  (:class:`~providers.UnknownProviderError`) — a **fifth** base, for the
  question none of the other four answers: *which endpoint does this call
  go to?*  See :mod:`providers._batch_errors`.

The error taxonomy (:mod:`providers._errors`) is the failure modes of *this*
seam and no other — a malformed completion, a missing provider, an unknown
model — raised at the interface's own guardrails, never by a provider's
transport or the model.  Keeping it narrow is deliberate: a caller catching
:class:`ProviderError` is catching "the provider contract was violated", not
"the HTTP client sneezed".  Feature 198's taxonomy
(:mod:`providers._depth_errors`) is a third base alongside the interface's
and the pin store's, unrelated to both: a model refused for the depth role
has not been called (so no provider contract failed) and pins no node (so
no authoring record is unreadable) — it is a *selection* that failed,
before the campaign spent anything on it.  Feature 202's
(:mod:`providers._schedule_errors`) is a fourth, for the same kind of
reason: a scheduling that found no window, named a campaign nobody
planned, or met a decision already made, has not called, pinned, or
selected anything — it is the campaign's *time* that could not be
decided.

This package is a workspace member discovered by convention. The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml`` declares
(``packages/*``), imports each package, and composes whatever the package's
``@register`` builder contributes — so the registration below is the entire
wiring story. Nothing edits a registry, router or factory to make the provider
plugin exist; importing this module *is* joining the application.  **Three**
components are registered from this one package, and the split is the split
between the category's contract and its services.  Feature 192's
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
store is named).  Feature 202's run-window store
(``depth-run-windows``) is the same kind of service for the same kind of
reason — a scheduling decision that must actually land in a table is a
deployment-bound fact, not a contract a caller holds — so its builder
resolves ``DATABASE_URL`` the same way and composes a
:class:`DepthRunWindows` (or nothing, when no store is named).  All three
registrations live in this ``__init__`` and none in a submodule, because a
submodule's ``@register`` fires only on the first
``create_app()`` of a process and would silently drop out of every later one.

Stdlib-only, like the rest of this tree.  The interface holds no transport, no
credential and no provider SDK — those belong to a concrete provider on the
trusted side of the boundary (feature 150's orchestrator); this module is the
contract the transport is written against.
"""

from __future__ import annotations

from app.module_loader import register

from ._batch import (
    BATCH_ENDPOINT,
    BATCH_RATE_MULTIPLE,
    BATCHED_COLUMN,
    ENDPOINT_COLUMN,
    PROVIDER_COLUMN,
    RATE_MULTIPLE_COLUMN,
    SYNCHRONOUS_ENDPOINT,
    SYNCHRONOUS_RATE_MULTIPLE,
    BatchEndpoint,
    BatchPricing,
    RoutedCall,
    route_depth_call,
)
from ._batch_errors import (
    BatchRoutingError,
    UnknownProviderError,
)
from ._ckpt import (
    AGENT_CKPT_HASH_COLUMN,
    CKPT_HASH_LENGTH,
    HOSTED_API_CKPT_HASH,
    hosted_api_weights,
    require_agent_ckpt_hash,
)
from ._completion import Completion, Usage
from ._depth import (
    FLAT_AT_ANY_CONTEXT,
    LARGE_HISTORY_FROM_DEPTH,
    MIN_DEPTH_CONTEXT_TOKENS,
    DepthModel,
    flat_pricing,
    require_depth_model,
)
from ._depth_errors import (
    DepthModelError,
    InsufficientContextError,
    LongContextSurchargeError,
)
from ._errors import (
    CompletionMalformedError,
    ProviderError,
    ProviderNotConfiguredError,
    UnknownModelError,
)
from ._pin_errors import (
    AgentSamplingMalformedError,
    CkptHashConflictError,
    CkptHashMalformedError,
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    NodeProvenanceError,
    PinColumnError,
    RollingAliasError,
    SamplingConflictError,
)
from ._pin_store import AgentModelPins, AgentWeights, NodePin, NodeProvenance
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
from ._sampling import (
    AGENT_SAMPLING_COLUMN,
    DEFAULT_SAMPLING,
    MAX_TEMPERATURE,
    SAMPLING_KEYS,
    SEED_MAX,
    AgentSampling,
    require_agent_sampling,
)
from ._schedule import (
    CAMPAIGN_ID_COLUMN,
    CAMPAIGN_TABLE,
    CAMPAIGN_TABLE_ID_COLUMN,
    DEPTH_RUN_WINDOW_TABLE,
    END_AT_COLUMN,
    MINUTES_PER_DAY,
    PEAK_WINDOWS_COLUMN,
    SCHEDULED_AT_COLUMN,
    START_AT_COLUMN,
    DepthRunWindows,
    PeakPricing,
    PeakWindow,
    RunWindow,
    ScheduledRun,
    choose_run_window,
    schedule_depth_run,
)
from ._schedule_errors import (
    DepthScheduleError,
    NoOffPeakWindowError,
    RunWindowConflictError,
    UnknownCampaignError,
)

__all__ = [
    "AGENT_CKPT_HASH_COLUMN",
    "AGENT_MODEL_ID_COLUMN",
    "AGENT_SAMPLING_COLUMN",
    "BATCHED_COLUMN",
    "BATCH_ENDPOINT",
    "BATCH_RATE_MULTIPLE",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TABLE_ID_COLUMN",
    "CKPT_HASH_LENGTH",
    "DEFAULT_SAMPLING",
    "DEPTH_RUN_WINDOW_TABLE",
    "ENDPOINT_COLUMN",
    "END_AT_COLUMN",
    "FLAT_AT_ANY_CONTEXT",
    "HOSTED_API_CKPT_HASH",
    "LARGE_HISTORY_FROM_DEPTH",
    "MAX_TEMPERATURE",
    "MINUTES_PER_DAY",
    "MIN_DEPTH_CONTEXT_TOKENS",
    "MODEL_PIN_PARTS",
    "MODEL_PIN_REVISION",
    "PEAK_WINDOWS_COLUMN",
    "PROVIDER_COLUMN",
    "RATE_MULTIPLE_COLUMN",
    "SAMPLING_KEYS",
    "SCHEDULED_AT_COLUMN",
    "SEED_MAX",
    "SEPARATOR",
    "START_AT_COLUMN",
    "SYNCHRONOUS_ENDPOINT",
    "SYNCHRONOUS_RATE_MULTIPLE",
    "AgentModelPins",
    "AgentSampling",
    "AgentSamplingMalformedError",
    "AgentWeights",
    "BatchEndpoint",
    "BatchPricing",
    "BatchRoutingError",
    "CkptHashConflictError",
    "CkptHashMalformedError",
    "Completion",
    "CompletionMalformedError",
    "DepthModel",
    "DepthModelError",
    "DepthRunWindows",
    "DepthScheduleError",
    "Exchange",
    "InsufficientContextError",
    "LongContextSurchargeError",
    "Message",
    "ModelPin",
    "ModelPinConflictError",
    "ModelPinError",
    "NoOffPeakWindowError",
    "NodeNotRecordedError",
    "NodePin",
    "NodeProvenance",
    "NodeProvenanceError",
    "PeakPricing",
    "PeakWindow",
    "PinColumnError",
    "Provider",
    "ProviderError",
    "ProviderNotConfiguredError",
    "RecordingProvider",
    "Request",
    "RollingAliasError",
    "RoutedCall",
    "RunWindow",
    "RunWindowConflictError",
    "SamplingConflictError",
    "ScheduledRun",
    "UnknownCampaignError",
    "UnknownModelError",
    "UnknownProviderError",
    "Usage",
    "build_agent_model_pins",
    "choose_run_window",
    "flat_pricing",
    "hosted_api_weights",
    "require_agent_ckpt_hash",
    "require_agent_model_id",
    "require_agent_sampling",
    "require_depth_model",
    "route_depth_call",
    "schedule_depth_run",
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

#: The component name feature 202's run-window store registers under.  The
#: plugin name plus what it contributes, on the ``agent-model-pins``
#: precedent for a member's *later* components: the interface took the bare
#: plugin name first, the pin store spelled its own contribution second, and
#: this one spells its the same way.  Spelled here so the seat
#: (``src/app/modules/providers``) and the composed application agree on the
#: key, with the behaviour — a test, not a shared constant — as the thing
#: that keeps them from drifting silently.
DEPTH_RUN_WINDOW_COMPONENT = "depth-run-windows"

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


@register(DEPTH_RUN_WINDOW_COMPONENT)
def build_depth_run_windows() -> DepthRunWindows | None:
    """Component builder: the store that schedules campaigns' depth runs.

    Feature 202's contribution to the composed application: the
    :class:`~providers.DepthRunWindows` store this deployment schedules runs
    into and reads them back from.  Takes no arguments — that is the
    factory's registration protocol — and resolves ``DATABASE_URL`` at build
    time, on exactly the :func:`build_agent_model_pins` pattern: a
    scheduling decision is a deployment-bound fact that must actually land
    in a table, so the composed application carries the store for the
    deployment the process is actually running in.

    Returns ``None`` when nothing names a relational store, and that
    ``None`` is the same refusal-to-proceed the pin store's is rather than
    an empty store: an empty store would answer *no run is scheduled here*
    about every campaign, while this ``None`` says there is no database to
    have scheduled one in — and a launcher that must persist a run's chosen
    window has to treat it as a refusal rather than as a schedule that
    happened to find nothing.

    Never raises for the URL itself: a URL whose scheme this member cannot
    speak is refused by name the first time an operation needs the path,
    not here.  Construction performs no I/O — the path is resolved on first
    use, and the member-owned ``depth_run_window`` table is created by the
    store's first write — so composing the application never opens a
    database, and nothing is written until a caller schedules a run.
    """
    return DepthRunWindows.resolve()
