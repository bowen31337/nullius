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

Feature 193 — *"System implements a recorded-fixture provider backend, which
returns stored responses so the full loop runs with no network access"* — is
the offline half of the recording story, and the reason this package carries a
second provider beyond the recorder.  Where :class:`RecordingProvider` is a tap
— it forwards to a live provider and keeps every exchange — :class:`RecordedProvider`
is the source the tap feeds: it answers a call from a response captured earlier,
so the loop runs the full depth without a single network round trip.  A
deployment records once (feature 194) and replays the record many times, and
every call is answered from what was captured rather than from a live transport.

* :class:`RecordedProvider` — the backend itself.  A :class:`Provider`, so it
  is drop-in for whatever served the calls originally: a caller holding the
  interface cannot tell a replay from a live run.  It holds a mapping of prompt
  to recorded completion, and answers a request by looking up the prompt it
  asked.  A prompt with no recorded response is refused as
  :class:`FixtureNotFoundError`, **never** forwarded to a live transport — the
  load-bearing half of the sentence.  The backend has no transport to fall back
  to, so a missing fixture is a hard stop the caller fixes by recording the
  prompt, not a gap to paper over with an inference request; a backend that
  silently reached for the network would be the access this feature exists to
  remove.  It records nothing: keeping exchanges is the recorder's job, and a
  source is not a tap.

* :func:`prompt_hash` — the key the record is addressed by.  The recorded
  layer keys a fixture by "the prompt that was asked", and the response
  captured for a request is the response replayed for any later request that
  asks the same prompt.  Two requests ask the same prompt when they are
  value-equal — the same ordered messages, the same model, the same sampling
  knobs — which :class:`Request` already guarantees; this function distils that
  value-equal form to a single canonical sha256 hex digest, so it can be a
  mapping key and a fixture-file name (feature 194), and a request recorded in
  one process is found by an equal request in another.  The form is the
  request's own data, not a ``repr`` — a repr carries object addresses and a
  type name that would scatter one prompt across many keys, defeating the
  value-equality the interface exists to give.

* :class:`RecordedResponse` — the stored answer as the recorder yields it: the
  :class:`Request` that was asked and the :class:`Completion` it got back, kept
  together because a fixture that split the answer from the ask would be unable
  to say which response matched which prompt.  The backend accepts either these
  pairs or a bare mapping of prompt hash to completion, and canonicalizes both
  to the same record on the way in.

* :class:`FixtureNotFoundError` — the backend's one refusal, and deliberately a
  :class:`ProviderError` rather than a second base.  The split in
  :mod:`providers._errors` is by *which contract* was violated, and a recorded
  backend that cannot answer is a violation of the provider contract — a caller
  that catches :class:`ProviderError` is catching "the provider could not
  complete this call", which is exactly the state a missing fixture is.  So a
  single ``except ProviderError`` covers a malformed completion, a missing
  provider and a missing recording, and a CI check that the loop never fell
  back to a live network has one handle for every way the offline path can
  stop.  Its message opens with :data:`FIXTURE_MISSING_CODE` — the greppable
  ``fixture_missing`` token feature 195 names for this stop — and the code and
  the type are one edit, so they never drift apart.  This module owns the
  error, its code and its no-fallback behaviour, which is feature 193's.

Feature 194 — *"System records a live provider exchange into a fixture file
keyed by a prompt hash, persisting request and response together"* — is the
persistence half of the same story, and feature 195's *fixture_missing*
message — the :data:`FIXTURE_MISSING_CODE` the refusal carries — is the third:
together they make the record the backend replays.  Where
:class:`RecordingProvider` keeps an exchange in memory and
:class:`RecordedProvider` answers from one it was handed, feature 194 is what
puts the exchange **on disk** — which is what makes a record outlive the process
that captured it and what the end-to-end sentence needs when it says a campaign
*"runs under fixed exploration against fixture-backed agents"*.  Its surface is
the file and the store that writes it:

* :class:`FixtureStore` — the directory :data:`FIXTURE_DIR_ENV` names.  A
  store, not a provider: it writes files and reads them back, and answers no
  prompts.  It does **not** hash anything itself — the key is
  :func:`prompt_hash`, feature 193's, and this store is where that digest
  becomes a filename.

* :class:`FixtureFile` — one fixture as the store holds it: its key, its path,
  and the request and completion the bytes carry, re-made from this package's
  classes so a caller holds one value type whatever copy wrote the file.

* :data:`FIXTURE_DIR_ENV`, :data:`FIXTURE_SUFFIX` — the two spellings of the
  store's address: ``PROVIDER_FIXTURE_DIR``, which ``app_spec.xml``'s
  prerequisites list beside ``DATABASE_URL`` and ``LAKE_ROOT``, and the ``.json``
  every fixture file carries.

* :class:`~providers.FixtureStoreError` and its two subclasses
  (:class:`~providers.FixtureConflictError`, :class:`~providers.FixtureCorruptError`)
  — a **ninth** base, for the question none of the other eight answers: *can
  this exchange be filed as a fixture under its prompt hash, and read back as
  one?*  Deliberately unrelated to feature 193's
  :class:`~providers.FixtureNotFoundError`, which *is* a
  :class:`~providers.ProviderError` — correctly, because that backend **is** a
  provider — while this store is a directory, whose failures are about files
  and whose repair is fixing a file rather than recording a prompt.  See
  :mod:`providers._fixture_errors`.

Those are separate features; this package contributes the backend, the key, the
error, the code this one names, and the file store that ties them together.

The interface's batch half mirrors the single call: :meth:`Provider.complete_batch`
takes a :class:`BatchRequest` — an ordered tuple of :class:`Request` — and
returns a :class:`BatchCompletion`, one :class:`Completion` per request in
order, each carrying the model that served it.  The base class enforces the
same contract around it that it enforces around the single call, and a
batch-capable provider answers many requests through one batched transport
call — the seam the depth role's batch routing (feature 201) pushes through,
since §14.1's *"batch APIs halve rates"* lever has nothing to route without a
batch shape on the seam.  A provider that serves no batch endpoint leaves the
base :meth:`_complete_batch`, which refuses the batch by name
(:class:`NotImplementedBatchError`) rather than silently answering one request
at a time; the single path is untouched, so a non-batch call behaves exactly
as before.  The batch records join the interface's as direct imports (see
:mod:`providers._batch_completion`, which sits beside feature 201's
:mod:`providers._batch` routing); the batch is an addition to the interface,
not a replacement for it.

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

Feature 199 — *"System rejects a depth model whose verified served context
limit is below the campaign history size, rather than trusting a published
figure"* — is the **verification layer** of that same criterion, and its
records join the interface's as direct imports beside 198's.  Where 198 reads
the window a candidate's **card declares** and compares it to a fixed bar,
199 reads the limit a deployment **verified it serves** and compares it to
**this campaign's** history — architecture §14.1's *"Verify the served context
limit (``--max-model-len``), not the marketing number"*, applied to the
history §14.1 measures at roughly 500K tokens in a 500-node campaign:

* :class:`ServedContextLimit` — what a deployment serves for one model: the
  model's name, the ``served_tokens`` window, and ``verified`` — ``True`` for
  a served measurement, :data:`UNVERIFIED_SERVED_LIMIT` (best spelled
  :func:`published_figure`) for the marketing number.  ``verified`` has no
  default, because the published figure must not be admissible by omission.
  Shape-validated on construction and deliberately not bar-validated: measuring
  a 262K window is a well-formed measurement, since §14.1 serves exactly such a
  window for early-depth nodes, narrow campaigns and the bootstrap worlds.

* :func:`require_served_context` — the gate.  A model serves a campaign only
  with a **verified** limit **at least** the campaign's history, which the
  caller **states** (:func:`providers.choose_run_window`'s ``duration``
  precedent — the module carries no bar of its own, because the bar here is the
  campaign's and changes per campaign).  Refused as
  :class:`~providers.ServedContextUnverifiedError` for a published figure,
  **before and independently of** the counts, since an unverified number cannot
  be compared at all; then as
  :class:`~providers.ServedContextBelowHistoryError` for a verified limit under
  the history.  The answer is a :class:`VerifiedServedContext` — the pair plus
  its derived ``headroom_tokens``, the margin §14.1's own reasoning reads.

Both of feature 199's refusals join :class:`~providers.DepthModelError` rather
than minting a seventh base: 198 and 199 ask **one** question — *may this model
take the depth role's calls?* — of one axis, at one moment, and differ only in
the fact (published window against served limit) and the bar (one million fixed
against the campaign's history).  See :mod:`providers._served`.

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

Feature 200 — *"System persists the measured cache hit rate per campaign,
because the depth model is selected on cache-hit input price rather than
list price"* — is §14.1's own headline lever, the one the corrected cost
model in §14.2 ends on (*"Tiering saves ~6.5×, and the saving comes
almost entirely from the depth role's cache-hit rate"*).  The depth role's
cost is almost entirely re-reading a large, append-only, stable prefix,
so *"prompt caching is worth 4–5× here.  Providers differ enormously on
cache-hit input pricing — an order of magnitude or more …  Select the
depth model on cache-hit price, not list price."*  Its records join the
category's as direct imports alongside one registered component — the
store, because a measurement that must be persisted is a fact that has to
land in a table (see :mod:`providers._cache` for the surface's shape and
its reasons):

* :class:`CachePrice` and :class:`CachePricing` — **the configuration**:
  one model's cache pricing (list and cache-hit input price, per million
  tokens) and the card collecting them, stated rather than baked (§14.2's
  own preamble: *"rates move monthly … the selection logic is stable, the
  numbers are not"*).  Both prices are always stated — a card entry that
  omitted the hit price would leave the selection to fall back on the
  list, the exact failure the feature's *because* exists to refuse.

* :func:`select_depth_model` and :class:`SelectedDepthModel` — **the
  choice**: the candidate whose card entry carries the lowest cache-hit
  input price, answered with **both** its prices so a caller sees the
  axis the choice turned on — which is the point, because the two
  orderings genuinely disagree (§14.2's depth row: the model with the
  *higher* list price is 4× cheaper on the hit).  A candidate the card
  does not price is refused as
  :class:`~providers.UnpricedModelError`, never silently skipped and
  never ranked on its list price.

* :class:`DepthCacheRates`, :class:`MeasuredCacheRate` and
  :func:`measure_cache_rate` — **the persistence**: the store that owns
  the ``depth_cache_rate`` table (the bootstrap pool's member-owned-table
  precedent, no edit to the shared migration chain), measures one
  campaign's rate from its calls' token accounting —
  ``cache_read_tokens ÷ input_tokens``, totalled over the usages rather
  than accepted as a caller's ratio, because *measured* is the sentence's
  own word — and answers the two counts and the instant the row holds
  (the rate itself derived, never stored: two counts can be re-verified,
  a rounded ratio agrees with nothing).

* :class:`~providers.DepthCacheError` and its three subclasses
  (:class:`~providers.UnpricedModelError`,
  :class:`~providers.UnplannedCampaignError`,
  :class:`~providers.CacheRateConflictError`) — a **sixth** base, for
  the question none of the other five answers: *what does the depth
  role's input cost on the axis it is actually spent on, and what rate
  did this campaign's calls measure there?*  See
  :mod:`providers._cache_errors`.

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
before the campaign spent anything on it.  Feature 199's two refusals join
that same base rather than adding a seventh, because they ask 198's one
question of a **measured** fact instead of a declared one — the model's
capacity to hold the role's history — so a caller's ``except
DepthModelError:`` catches a refusal from either layer.  Feature 202's
(:mod:`providers._schedule_errors`) is a fourth, for the same kind of
reason: a scheduling that found no window, named a campaign nobody
planned, or met a decision already made, has not called, pinned, or
selected anything — it is the campaign's *time* that could not be
decided.  Feature 201's (:mod:`providers._batch_errors`) is a fifth for
its own question, and feature 200's (:mod:`providers._cache_errors`) is
a sixth: a selection with no price on the axis it ranks by, a
measurement for a campaign nobody planned, or a re-measurement that
contradicts the row it would overwrite, has not called, pinned, gated,
timed or routed anything — it is the campaign's *money* that could not
be decided or accounted.

The live-providers addition is the other half of the boundary this package
always described: the backends that place a real call, on the trusted side
of it, through the one seam every call already passes.  Features 1 through
5 of the addition built them as private modules — the door
(:mod:`providers._live_http`), the two backends (:mod:`providers._anthropic`,
:mod:`providers._openai_compat`), the registry (:mod:`providers._live`) and
the budget wrapper (:mod:`providers._budget`) — and this, the addition's
sixth feature, is the export seam: the surface a caller composes and
imports against, never a private module path.  Twelve names join
``__all__``, and the split is the addition's own:

* :class:`AnthropicProvider` and :class:`OpenAICompatProvider` — the two
  live backends.  A :class:`Provider` each, so either is drop-in for the
  recorded-fixture backend a campaign replays with: the seam normalizes the
  call, and which backend serves it is invisible to the caller.

* :func:`live_provider`, :func:`require_served` and
  :data:`LIVE_PROVIDER_ENV_VARS` — the registry's whole surface: a pin in,
  a bound backend out; the served-model check that catches a vendor quietly
  serving another model under a pinned id; and the ``NULLIUS_``-prefixed
  variable table that keeps research credentials apart from claw-forge's
  own bare names.

* :class:`BudgetedProvider` and :class:`BudgetExhaustedError` — the token
  ceiling: a wrapper that refuses a call once the ceiling is spent, so a
  campaign's spend stops at a number the deployment stated.

* :class:`ProviderHostRefusedError`, :class:`ProviderTransportError`,
  :class:`ProviderHTTPError`, :class:`ProviderRequestError` and
  :class:`ServedModelMismatchError` — the live path's failure vocabulary,
  joining :class:`ProviderError`'s base rather than minting a seventh: a
  call that never left the machine, left and failed, or came back from the
  wrong model is still "the provider could not complete this call", and a
  caller catching the interface's error catches every way the live path
  stops.

This package is a workspace member discovered by convention. The module loader
(``app.module_loader``) scans the members the root ``pyproject.toml`` declares
(``packages/*``), imports each package, and composes whatever the package's
``@register`` builder contributes — so the registration below is the entire
wiring story. Nothing edits a registry, router or factory to make the provider
plugin exist; importing this module *is* joining the application.  **Eight**
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
:class:`DepthRunWindows` (or nothing, when no store is named).  Feature
200's cache-rate store (``depth-cache-rates``) is the same kind of service
for the same kind of reason — a measurement that must be persisted is a
deployment-bound fact, and the depth model's selection is justified by the
rate the campaign's calls actually measured — so its builder resolves
``DATABASE_URL`` the same way and composes a :class:`DepthCacheRates`
(or nothing, when no store is named).  Features 196 and 197's paired stores
(``root-serving-provider`` and ``root-rotation``) are the same kind of service
again — which family served a root call, and which families the campaign's
rotation assigned — and resolve the same variable.  Feature 194's fixture store
(``fixture-store``) is a service too, but of a different **kind** of resource:
it is a **directory**, not a table, so its builder resolves
:data:`FIXTURE_DIR_ENV` rather than ``DATABASE_URL`` and composes a
:class:`FixtureStore` (or nothing, when no fixture root is named — a
deployment that captures no fixtures is a real state, and one that names no
directory must not have its composition taken down for it).  The live
resolver (``live-providers``) is an eighth, and of the opposite shape from
every store above: its builder resolves **no** variable and makes **no**
call, because which credentials a deployment holds is a question only a
resolve asks — a composition must succeed on a box with no keys at all (a
CI run, an offline replay against fixtures), so the builder answers a
stateless resolver and every environment read happens inside its
``resolve()``, against the environment of the moment a provider is asked
for.  All eight registrations live in this ``__init__`` and none in a
submodule, because a submodule's ``@register`` fires only on the first
``create_app()`` of a process and would silently drop out of every later one.

Stdlib-only, like the rest of this tree.  The interface holds no transport, no
credential and no provider SDK — those belong to a concrete provider on the
trusted side of the boundary (feature 150's orchestrator); this module is the
contract the transport is written against.
"""

from __future__ import annotations

import os

from app.module_loader import register

from ._anthropic import AnthropicProvider, ProviderRequestError
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
from ._batch_completion import (
    BatchCompletion,
    BatchRequest,
    NotImplementedBatchError,
    require_batch_completion,
)
from ._batch_errors import (
    BatchRoutingError,
    UnknownProviderError,
)
from ._budget import BudgetedProvider, BudgetExhaustedError
from ._cache import (
    CACHE_READ_TOKENS_COLUMN,
    DEPTH_CACHE_RATE_TABLE,
    INPUT_TOKENS_COLUMN,
    MEASURED_AT_COLUMN,
    CachePrice,
    CachePricing,
    DepthCacheRates,
    MeasuredCacheRate,
    SelectedDepthModel,
    measure_cache_rate,
    select_depth_model,
)
from ._cache_errors import (
    CacheRateConflictError,
    DepthCacheError,
    UnplannedCampaignError,
    UnpricedModelError,
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
    ServedContextBelowHistoryError,
    ServedContextUnverifiedError,
)
from ._errors import (
    CompletionMalformedError,
    ProviderError,
    ProviderNotConfiguredError,
    UnknownModelError,
)
from ._fixture import (
    FIXTURE_DIR_ENV,
    FIXTURE_SUFFIX,
    FixtureFile,
    FixtureStore,
)
from ._fixture_errors import (
    FixtureConflictError,
    FixtureCorruptError,
    FixtureStoreError,
)
from ._live import (
    LIVE_PROVIDER_ENV_VARS,
    ServedModelMismatchError,
    live_provider,
    require_served,
)
from ._live_http import (
    ProviderHostRefusedError,
    ProviderHTTPError,
    ProviderTransportError,
)
from ._openai_compat import OpenAICompatProvider
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
from ._recorded import RecordedProvider, RecordedResponse, prompt_hash
from ._recorded_errors import FIXTURE_MISSING_CODE, FixtureNotFoundError
from ._recorder import Exchange, RecordingProvider
from ._request import Message, Request
from ._root import (
    DATABASE_URL_ENV,
    DEPTH_COLUMN,
    MODEL_COLUMN,
    NODE_TABLE,
    NODE_TABLE_ID_COLUMN,
    NODE_TABLE_REVISION,
    RECORDED_AT_COLUMN,
    ROOT_SERVING_PROVIDER_TABLE,
    ROOT_TIER_MAX_DEPTH,
    SERVING_PROVIDER_COLUMN,
    FrontierProvider,
    FrontierTier,
    RootCall,
    RootCallProvider,
    RootProviderRotation,
    record_root_provider,
)
from ._root_errors import (
    RootNotRecordedError,
    RootProviderConflictError,
    RootProviderError,
    UnknownRootProviderError,
    UnrotatedCampaignError,
)
from ._rotation import (
    ASSIGNED_AT_COLUMN,
    DECLARED_PROVIDERS_COLUMN,
    ROOT_PROVIDER_ROTATION_TABLE,
    ROTATION_DIGEST_COLUMN,
    RootAssignment,
    RootRotation,
    assign_root_provider,
    rotation_digest,
    rotation_index,
)
from ._rotation_errors import (
    RootRotationError,
    RotationConflictError,
    UnassignedRootProviderError,
)
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
from ._served import (
    UNVERIFIED_SERVED_LIMIT,
    ServedContextLimit,
    VerifiedServedContext,
    published_figure,
    require_served_context,
)

__all__ = [
    "AGENT_CKPT_HASH_COLUMN",
    "AGENT_MODEL_ID_COLUMN",
    "AGENT_SAMPLING_COLUMN",
    "ASSIGNED_AT_COLUMN",
    "BATCHED_COLUMN",
    "BATCH_ENDPOINT",
    "BATCH_RATE_MULTIPLE",
    "CACHE_READ_TOKENS_COLUMN",
    "CAMPAIGN_ID_COLUMN",
    "CAMPAIGN_TABLE",
    "CAMPAIGN_TABLE_ID_COLUMN",
    "CKPT_HASH_LENGTH",
    "DATABASE_URL_ENV",
    "DECLARED_PROVIDERS_COLUMN",
    "DEFAULT_SAMPLING",
    "DEPTH_CACHE_RATE_TABLE",
    "DEPTH_COLUMN",
    "DEPTH_RUN_WINDOW_TABLE",
    "ENDPOINT_COLUMN",
    "END_AT_COLUMN",
    "FIXTURE_DIR_ENV",
    "FIXTURE_MISSING_CODE",
    "FIXTURE_SUFFIX",
    "FLAT_AT_ANY_CONTEXT",
    "HOSTED_API_CKPT_HASH",
    "INPUT_TOKENS_COLUMN",
    "LARGE_HISTORY_FROM_DEPTH",
    "LIVE_PROVIDER_ENV_VARS",
    "MAX_TEMPERATURE",
    "MEASURED_AT_COLUMN",
    "MINUTES_PER_DAY",
    "MIN_DEPTH_CONTEXT_TOKENS",
    "MODEL_COLUMN",
    "MODEL_PIN_PARTS",
    "MODEL_PIN_REVISION",
    "NODE_TABLE",
    "NODE_TABLE_ID_COLUMN",
    "NODE_TABLE_REVISION",
    "PEAK_WINDOWS_COLUMN",
    "PROVIDER_COLUMN",
    "RATE_MULTIPLE_COLUMN",
    "RECORDED_AT_COLUMN",
    "ROOT_PROVIDER_ROTATION_TABLE",
    "ROOT_SERVING_PROVIDER_TABLE",
    "ROOT_TIER_MAX_DEPTH",
    "ROTATION_DIGEST_COLUMN",
    "SAMPLING_KEYS",
    "SCHEDULED_AT_COLUMN",
    "SEED_MAX",
    "SEPARATOR",
    "SERVING_PROVIDER_COLUMN",
    "START_AT_COLUMN",
    "SYNCHRONOUS_ENDPOINT",
    "SYNCHRONOUS_RATE_MULTIPLE",
    "UNVERIFIED_SERVED_LIMIT",
    "AgentModelPins",
    "AgentSampling",
    "AgentSamplingMalformedError",
    "AgentWeights",
    "AnthropicProvider",
    "BatchCompletion",
    "BatchEndpoint",
    "BatchPricing",
    "BatchRequest",
    "BatchRoutingError",
    "BudgetExhaustedError",
    "BudgetedProvider",
    "CachePrice",
    "CachePricing",
    "CacheRateConflictError",
    "CkptHashConflictError",
    "CkptHashMalformedError",
    "Completion",
    "CompletionMalformedError",
    "DepthCacheError",
    "DepthCacheRates",
    "DepthModel",
    "DepthModelError",
    "DepthRunWindows",
    "DepthScheduleError",
    "Exchange",
    "FixtureConflictError",
    "FixtureCorruptError",
    "FixtureFile",
    "FixtureNotFoundError",
    "FixtureStore",
    "FixtureStoreError",
    "FrontierProvider",
    "FrontierTier",
    "InsufficientContextError",
    "LongContextSurchargeError",
    "MeasuredCacheRate",
    "Message",
    "ModelPin",
    "ModelPinConflictError",
    "ModelPinError",
    "NoOffPeakWindowError",
    "NodeNotRecordedError",
    "NodePin",
    "NodeProvenance",
    "NodeProvenanceError",
    "NotImplementedBatchError",
    "OpenAICompatProvider",
    "PeakPricing",
    "PeakWindow",
    "PinColumnError",
    "Provider",
    "ProviderError",
    "ProviderHTTPError",
    "ProviderHostRefusedError",
    "ProviderNotConfiguredError",
    "ProviderRequestError",
    "ProviderTransportError",
    "RecordedProvider",
    "RecordedResponse",
    "RecordingProvider",
    "Request",
    "RollingAliasError",
    "RootAssignment",
    "RootCall",
    "RootCallProvider",
    "RootNotRecordedError",
    "RootProviderConflictError",
    "RootProviderError",
    "RootProviderRotation",
    "RootRotation",
    "RootRotationError",
    "RotationConflictError",
    "RoutedCall",
    "RunWindow",
    "RunWindowConflictError",
    "SamplingConflictError",
    "ScheduledRun",
    "SelectedDepthModel",
    "ServedContextBelowHistoryError",
    "ServedContextLimit",
    "ServedContextUnverifiedError",
    "ServedModelMismatchError",
    "UnassignedRootProviderError",
    "UnknownCampaignError",
    "UnknownModelError",
    "UnknownProviderError",
    "UnknownRootProviderError",
    "UnplannedCampaignError",
    "UnpricedModelError",
    "UnrotatedCampaignError",
    "Usage",
    "VerifiedServedContext",
    "assign_root_provider",
    "build_agent_model_pins",
    "build_depth_cache_rates",
    "build_fixture_store",
    "build_live_providers",
    "build_root_provider_rotation",
    "build_root_rotation",
    "choose_run_window",
    "flat_pricing",
    "hosted_api_weights",
    "live_provider",
    "measure_cache_rate",
    "prompt_hash",
    "published_figure",
    "record_root_provider",
    "require_agent_ckpt_hash",
    "require_agent_model_id",
    "require_agent_sampling",
    "require_batch_completion",
    "require_depth_model",
    "require_served",
    "require_served_context",
    "rotation_digest",
    "rotation_index",
    "route_depth_call",
    "schedule_depth_run",
    "select_depth_model",
]

#: The component name this package registers its pin store under.  The plugin
#: name plus what it contributes, following the ``bootstrap`` /
#: ``artifacts`` / ``sandbox`` precedent for a member's *second* component (a
#: member's first usually takes the bare plugin name — :data:`PROVIDERS_COMPONENT`
#: below does).  Spelled here once, and read by name through the composed
#: application.
AGENT_MODEL_PIN_COMPONENT = "agent-model-pins"

#: The component name feature 200's cache-rate store registers under.  The
#: plugin name plus what it contributes, on the ``agent-model-pins`` /
#: ``depth-run-windows`` precedent for a member's later components: the
#: interface took the bare plugin name first, the pin store and the
#: run-window store spelled their own contributions, and this one spells
#: its the same way.  Spelled here once, and read by name through the
#: composed application.
DEPTH_CACHE_RATE_COMPONENT = "depth-cache-rates"

#: The component name feature 202's run-window store registers under.  The
#: plugin name plus what it contributes, on the ``agent-model-pins``
#: precedent for a member's *later* components: the interface took the bare
#: plugin name first, the pin store spelled its own contribution second, and
#: this one spells its the same way.  Spelled here once, and read by name
#: through the composed application.
DEPTH_RUN_WINDOW_COMPONENT = "depth-run-windows"

#: The component name feature 192's interface seam registers under.  It
#: contributes ``None`` (see :func:`provider_interface`), so nothing is stored
#: under it; the name exists so ``create_app()``'s composition order carries
#: the interface's registration beside the store's.
PROVIDERS_COMPONENT = "providers"

#: The component name feature 196's root-serving-provider store registers
#: under.  The plugin name plus what it contributes, on the
#: ``agent-model-pins`` / ``depth-run-windows`` / ``depth-cache-rates``
#: precedent for a member's later components: the interface took the bare
#: plugin name first and every store since has spelled its own contribution.
#: The name is *root-serving-provider* rather than *root-providers* or
#: *root-calls* because that is the fact: the provider that **served** a root
#: call, not the set of providers a campaign may rotate across (feature 197's
#: ``root-rotation``, a different component under the same category) and not
#: the calls themselves (which are feature 97's nodes).  A reader scanning the
#: composed application's keys should be able to tell which of the three it is
#: looking at without opening a docstring.  Spelled here once, and read by
#: name through the composed application.
ROOT_SERVING_PROVIDER_COMPONENT = "root-serving-provider"

#: The component name feature 197's root-rotation store registers under.  The
#: plugin name plus what it contributes, on the ``agent-model-pins`` /
#: ``depth-run-windows`` / ``depth-cache-rates`` / ``root-serving-provider``
#: precedent for a member's later components.
#:
#: *root-rotation* is the name feature 196's own constant predicted for it in as
#: many words: *"The name is* root-serving-provider *rather than* root-rotation
#: *or* root-calls because that is the fact: the provider that **served** a root
#: call, not the set of providers a campaign may rotate across (feature 197's
#: ``root-rotation``, a different component under the same category) and not the
#: calls themselves (which are feature 97's nodes).  A reader scanning the
#: composed application's keys should be able to tell which of the three it is
#: looking at without opening a docstring."*  This is that third name, spelled
#: as predicted rather than invented here, and read by name through the
#: composed application.
ROOT_ROTATION_COMPONENT = "root-rotation"

#: The component name feature 194's fixture store registers under.  The plugin
#: name plus what it contributes, on the ``agent-model-pins`` /
#: ``depth-run-windows`` / ``depth-cache-rates`` / ``root-serving-provider`` /
#: ``root-rotation`` precedent for a member's later components.
#:
#: *fixture-store* rather than *fixtures* or *recording* because that is the
#: fact: the object is a **store** — a directory of files it writes and reads —
#: and not the act of recording (the caller's, through
#: :meth:`providers.RecordingProvider`) nor the record's notation (feature 193's
#: backend).  A reader scanning the composed application's keys should be able
#: to tell which of the three it is looking at without opening a docstring, the
#: discipline :data:`ROOT_SERVING_PROVIDER_COMPONENT` states for its own name.
#: Spelled here once, and read by name through the composed application.
FIXTURE_STORE_COMPONENT = "fixture-store"

#: The component name the live-providers resolver registers under.  The
#: plugin name plus what it contributes, on the ``agent-model-pins`` /
#: ``depth-run-windows`` / ``depth-cache-rates`` / ``root-serving-provider`` /
#: ``root-rotation`` / ``fixture-store`` precedent for a member's later
#: components.
#:
#: *live-providers* rather than *live-provider* because that is the fact:
#: the component answers the **set** of live backends — every vendor the
#: registry serves, chosen per pin at resolve time — and not one provider
#: bound at composition.  A reader scanning the composed application's keys
#: should be able to tell it is not holding a credential-bearing object,
#: the discipline :data:`ROOT_SERVING_PROVIDER_COMPONENT` states for its own
#: name.  Spelled here once, and read by name through the composed
#: application.
LIVE_PROVIDERS_COMPONENT = "live-providers"


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


@register(DEPTH_CACHE_RATE_COMPONENT)
def build_depth_cache_rates() -> DepthCacheRates | None:
    """Component builder: the store that measures campaigns' cache hit rates.

    Feature 200's contribution to the composed application: the
    :class:`~providers.DepthCacheRates` store this deployment measures
    campaigns into and reads their rates back from.  Takes no arguments —
    that is the factory's registration protocol — and resolves
    ``DATABASE_URL`` at build time, on exactly the
    :func:`build_depth_run_windows` pattern: a measurement that must be
    persisted is a deployment-bound fact, and the depth model's selection
    is justified by the rate the campaign's calls actually measured, so
    the composed application carries the store for the deployment the
    process is actually running in.

    Returns ``None`` when nothing names a relational store, and that
    ``None`` is the same refusal-to-proceed the run-window store's is
    rather than an empty store: an empty store would answer *no campaign
    is measured here* about every campaign, while this ``None`` says
    there is no database to have measured one in — and a caller that
    must persist a campaign's rate has to treat it as a refusal rather
    than as a measurement that happened to find nothing, because the
    alternative is a selection justified by a number that exists
    nowhere.

    Never raises for the URL itself: a URL whose scheme this member
    cannot speak is refused by name the first time an operation needs
    the path, not here.  Construction performs no I/O — the path is
    resolved on first use, and the member-owned ``depth_cache_rate``
    table is created by the store's first ``measure`` — so composing
    the application never opens a database, and nothing is written
    until a caller measures a campaign.
    """
    return DepthCacheRates.resolve()


@register(ROOT_SERVING_PROVIDER_COMPONENT)
def build_root_provider_rotation() -> RootProviderRotation | None:
    """Component builder: the store that records which provider served each root call.

    Feature 196's contribution to the composed application: the
    :class:`~providers.RootProviderRotation` store this deployment records
    root-call provenance into and reads it back from.  Takes no arguments —
    that is the factory's registration protocol — and resolves
    ``DATABASE_URL`` at build time, on exactly the
    :func:`build_depth_cache_rates` / :func:`build_depth_run_windows`
    pattern: which provider served a root call is a deployment-bound fact
    (the frontier tier is the deployment's own — §14.2's preamble is
    explicit that the models move and the logic does not), so the composed
    application carries the store for the deployment the process is
    actually running in.

    Returns ``None`` when nothing names a relational store, and that
    ``None`` is the same refusal-to-proceed the other two stores' is
    rather than an empty store: an empty store would answer *no provider
    served this root* about every root, while this ``None`` says there is
    no database to have recorded one in — and architecture §14.1 records
    the serving provider precisely so the tree's roots can be stratified
    by family *afterwards*, which is a reading a caller can only make of
    rows that landed.

    Never raises for the URL itself: a URL whose scheme this member cannot
    speak is refused by name the first time an operation needs the path,
    not here.  Construction performs no I/O — the path is resolved on first
    use, and the member-owned ``root_serving_provider`` table is created by
    the store's first ``record``, never by a ``get`` — so composing the
    application never opens a database, and nothing is written until a
    caller records a root call's provider.
    """
    return RootProviderRotation.resolve()


@register(ROOT_ROTATION_COMPONENT)
def build_root_rotation() -> RootRotation | None:
    """Component builder: the store that decides and records a campaign's root rotation.

    Feature 197's contribution to the composed application: the
    :class:`~providers.RootRotation` store this deployment assigns a campaign's
    roots into and reads the rotation back from.  Takes no arguments — that is
    the factory's registration protocol — and resolves ``DATABASE_URL`` at
    build time, on exactly the :func:`build_root_provider_rotation` /
    :func:`build_depth_cache_rates` pattern: which families a campaign rotates
    its roots across is a deployment-bound fact (the frontier tier is the
    deployment's own — §14.2's preamble is explicit that *"the models move and
    the logic does not"*), so the composed application carries the store for the
    deployment the process is actually running in.

    Returns ``None`` when nothing names a relational store, and that ``None`` is
    the same refusal-to-proceed the other stores' is rather than an empty store:
    an empty store would answer *this campaign's roots were never assigned*
    about every campaign, while this ``None`` says there is no database to have
    assigned one in — and §14.1 rotates providers at roots precisely so that
    *"different model families carry different priors and propose structurally
    different mechanisms"*, which is a reading a caller can only make of a
    rotation that landed.

    **It is a distinct component from**
    :data:`ROOT_SERVING_PROVIDER_COMPONENT`, and the distinction is the pair's:
    this store holds *what was assigned* per campaign, feature 196's holds *what
    served* per call.  A deployment that composes one and not the other is a
    real state — the pair's
    :meth:`~providers.RootRotation.record_root_provider` needs both, and a
    caller that only wants to re-derive a campaign's assignment needs this one.

    Never raises for the URL itself: a URL whose scheme this member cannot speak
    is refused by name the first time an operation needs the path, not here.
    Construction performs no I/O — the path is resolved on first use, and the
    member-owned ``root_provider_rotation`` table is created by the store's
    first ``assign``, never by a ``get`` — so composing the application never
    opens a database, and nothing is written until a caller assigns a root.
    """
    return RootRotation.resolve()


@register(FIXTURE_STORE_COMPONENT)
def build_fixture_store() -> FixtureStore | None:
    """Component builder: the directory recorded exchanges are filed in.

    Feature 194's contribution to the composed application: the
    :class:`~providers.FixtureStore` this deployment captures fixtures into and
    replays them from.  Takes no arguments — that is the factory's registration
    protocol — and resolves ``PROVIDER_FIXTURE_DIR`` at build time, so a
    composed application carries the store pointed at the directory the
    deployment actually keeps its recorded exchanges in.

    Returns ``None`` when nothing names a fixture root.  That is deliberately
    **not** an empty store: an empty store answers *no prompt is recorded here*
    about every prompt, while this ``None`` says there is no directory to have
    recorded one in — a distinction that matters more here than anywhere else
    in this member, because a caller that must capture an exchange has to treat
    it as a refusal to proceed rather than as a store that happened to find
    nothing.  Recording into an empty store is a capture nobody will ever
    replay.

    Never raises for the root itself, and that is the shape every builder in
    this package takes: the factory calls *every* registered builder on *every*
    ``create_app()``, so a builder that raised on an unset variable would take
    composition down for every unrelated feature in the workspace.
    :meth:`~providers.FixtureStore.resolve` is the ``None``-answering door for
    exactly this reason, and :meth:`~providers.FixtureStore.from_env` — which
    does raise — is the door for a caller that has decided it needs a fixture
    store.  A malformed root (a blank path) is refused by name at construction,
    because a store pointed at the wrong directory is worse than no store at
    all: its fixtures would be found or not depending on where the process
    started.

    Construction performs no I/O — the root is held, not made — so composing
    the application never touches the filesystem, and the directory appears only
    when a capture needs it.  Nothing brings it into being: not composition, and
    not a read, which answers ``None``/``()`` for a store that has never
    recorded.
    """
    return FixtureStore.resolve()


class LiveProviderResolver:
    """The composed application's door to the live backends: a pin in, a provider out.

    One method, :meth:`resolve`, and no state — deliberately the thinnest
    object the composed application could hold for the live path, and the
    thinness is the feature.  Nothing is decided at composition time because
    there is nothing to decide: which vendor serves a pin, which variable
    holds its credential, whether the deployment holds one at all — every one
    of those is a question about the moment a call is wanted, and the
    resolver holds no answer to any of them.  It reads the environment
    inside :meth:`resolve` and nowhere else, so an application composed on a
    box with no credentials at all (a CI run, an offline replay against
    recorded fixtures) carries the resolver exactly as a production
    deployment does, and the same composed application answers live
    providers the moment the variables appear.

    Nothing calls the live backends through this door yet — binding the
    resolver into the signal and policy-development agents is a later
    feature's work.  This class is the seam those features will hold: the
    one object a caller needs to turn a pinned model into a provider,
    reached as ``create_app().get("live-providers")`` rather than by
    importing a private module.
    """

    def resolve(self, pin: object) -> Provider:
        """Answer :func:`live_provider` for ``pin``, reading ``os.environ``.

        The one operation, forwarded to the registry with the process
        environment as the mapping — read **here**, at call time, which is
        the load-bearing half of this class's shape.  A resolver that read
        the environment at build time would freeze the deployment's
        credentials into the application, and a launcher that exported a
        variable afterwards would be silently ignored; the read happening
        per call is what keeps the composed resolver answering the
        environment the caller is actually running in.

        ``pin`` is recognised structurally (three string parts), on the
        registry's own rule, so a pin built from either copy of this member
        resolves identically.  Refusals are the registry's, verbatim: a
        vendor with no backend, or a missing or empty variable, leaves as
        :class:`~providers.ProviderNotConfiguredError` naming the variable —
        never its value.
        """
        return live_provider(pin, os.environ)


@register(LIVE_PROVIDERS_COMPONENT)
def build_live_providers() -> LiveProviderResolver:
    """Component builder: the resolver that turns a pin into a live provider.

    The live-providers addition's contribution to the composed application:
    the one object a caller holds to reach a live backend through.  Takes no
    arguments — that is the factory's registration protocol — and, unlike
    every store this member registers, resolves **no** environment variable
    and makes **no** call.  Composition must not need a credential, because
    a deployment that runs entirely against recorded fixtures (the offline
    path this package exists to make possible) has none — and the factory
    calls every builder on every ``create_app()``, so a builder that
    demanded a key would take composition down for exactly the runs that
    must never touch one.  Which credentials exist, and whether a vendor's
    variable is set, is asked only inside
    :meth:`~providers.LiveProviderResolver.resolve`.

    Answers the resolver unconditionally, never ``None``: there is no
    "unconfigured" state to report.  The stores above answer ``None`` when
    the resource they name is absent, but the resolver names no resource —
    it is the deferred question *which provider serves this pin?*, and a
    deployment with no credentials is a deployment whose answers all
    refuse, not one with no resolver.  The refusal arrives at
    :meth:`~providers.LiveProviderResolver.resolve` time, naming the
    variable, which is where an operator can act on it.
    """
    return LiveProviderResolver()
