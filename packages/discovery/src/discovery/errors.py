"""The discovery member's error vocabulary.

One base class (:class:`DiscoveryError`) so a caller — the campaign loop,
the dreaming loop, an operator script, a later feature in this category —
can catch every failure of the orchestrator's planning path with a single
``except``.  The subclasses split by *what the caller must do about it*,
not by which line of code raised, the discipline
:mod:`bootstrap.errors`, :mod:`nulloracle.errors` and
:mod:`artifacts._errors` state for their own trees:

* :class:`CampaignPlanningError` — the ask was malformed.  A campaign id
  that is not a UUID, a declared type that is neither of §7.3's two
  regimes, a ``workspace_count`` that is not a genuine positive integer,
  or a stored ``null_fraction`` that is not a finite real strictly inside
  ``(0, 1)``.  Every one of these is a fact about the *request*: nothing
  was read, nothing was written, and the repair is to re-consider what
  was asked for.  docs/nullius-tech-architecture.md §4.1.1's clip is
  ``clip(max(2/W, 0.15), 0.15, 0.35)``, so a ``W`` that is not a count has no
  fraction to compute, and a type that is not a regime names no world the
  orchestrator could plant.

* :class:`CampaignOrderError` — the ask was well formed and the *store's
  state* contradicts the feature's own ordering law.  Feature 232's
  sentence is *"System creates a campaign record capturing type, workspace
  count and null fraction **before any node is expanded**"*, and that
  clause is a property of the store rather than of the request: either
  the campaign's tree already holds a node (so the record was not created
  first, and creating it now would write a planning-time fact onto a
  campaign that has already been run), or a re-issued plan disagrees with
  the row already stored (§7.3 fixes a campaign's declared type and its
  workspace count at planning time, and a second declaration naming
  different ones would silently retype a world that was already planned).
  The repair differs from the first class's in kind: nothing about the
  request is wrong; the *world* is.  An operator reads this refusal to
  learn which campaign and which fact, then repairs the store or re-plans
  under a new campaign id — not by re-sending the same request.

The split matters to this member's two callers.  The *campaign loop*
(feature 232's own caller, and the features that follow it in this
category) calls :meth:`~discovery.campaign.CampaignRecords.create` before
expanding anything, and needs the two classes to be distinguishable
because the retries differ: a malformed ask is a bug in the loop's own
plumbing and will fail identically however often it is retried, while an
ordering refusal is a fact the loop *can* act on — it either joins the
existing campaign or re-plans it under a fresh id.  An *operator* auditing
a deployment's campaign table wants the second class alone: it is the one
that says a campaign was planned out of order.  Folding the two together
would make both callers catch and re-inspect something they cannot tell
apart.

Both are subclasses of :class:`DiscoveryError` and neither subclasses the
other.  This member deliberately does **not** raise
:class:`~nulloracle.errors.KsGuardError`, even though seven stores in the
null-oracle member open the very same ``campaign`` table: the workspace
contract is that no member imports another, and a caller reading
``KsGuardError`` out of a campaign *creation* would look in the wrong
module for the cause — the fraction's store refuses a write onto a
campaign nobody planned, while this member refuses a *plan* that cannot be
recorded.  Different acts, different vocabularies.

Feature 241 adds a third class, and it sits **beside** the first two rather
than under either of them.  :class:`IllegalThemeError` is raised when a
research theme is assigned (or a legal set is configured) and the value is
not in the configured legal set — the refusal app_spec.xml names with the
code ``illegal_theme``.  It is not a
:class:`CampaignPlanningError` because the offending fact is not about the
*request*: a perfectly well-formed theme name is refused here solely
because the **deployment's configured space** does not contain it, and the
repair is to widen ``NULLIUS_LEGAL_THEMES`` or to pick a different theme —
not, as with a malformed ``W`` or a mistyped regime, to re-send a corrected
ask.  PRD §9 states the distinction from the other side: *"Choosing the
space is the highest-value human input in the system, and it should be
encoded as the set of legal ``theme_root`` values."*  A caller that catches
:class:`DiscoveryError` gets every failure of this member's path, which is
the one ``except`` the base class exists for.

Feature 238 adds a fourth class, and it is the dispatch twin of the first:
:class:`BatchDispatchError` is raised when the orchestrator's *evaluation
dispatch* — *"System runs W parallel evaluation workers as concurrent
slots, which returns batch results as each worker completes"* — is handed
an ask that cannot be run as W slots at all.  A ``width`` that is not the
genuine positive integer a campaign's ``workspace_count`` is, a ``worker``
that is not callable, a ``jobs`` that is not a batch: each is refused
**before any slot starts**, which is the property that makes this the same
repair as :class:`CampaignPlanningError`'s (re-consider the ask) rather
than :class:`CampaignOrderError`'s (repair the world).  It sits beside the
other three rather than under either planning or ordering for a second
reason the split above states generally: a worker that *fails mid-batch*
is never this class — a failed run is a value the stream reports
(:class:`~discovery.workers.WorkerResult` carries it), because every
attempt must be answered for the tree to log it — so this class is
reserved for asks the pool could not even begin.

Feature 244 adds the fifth class, and it is the one member of this
vocabulary that is **not a refusal at all**.  :class:`WorkerInterrupted`
is a fact — the evaluation worker was interrupted before its evaluation
finished, §14's spot-instance reclamation arriving as data — and where
every other class here answers *"what did this member refuse, and what
must the caller do about it?"*, this one answers *"what happened, and
which verb exists for it?"*: the worker of record raises it, feature
238's pool captures it on its :class:`~discovery.workers.WorkerResult`
like any failure, and :func:`discovery.retry.retry_interrupted` — the
retry that same sentence names — is the act it exists for.  It is a
subclass of :class:`DiscoveryError` anyway, so the caller that catches
the orchestrator's path with one ``except`` catches an interruption
too; the distinction it keeps is the load-bearing one:
:func:`discovery.retry.is_interruption` is true of **exactly** this
class, so nothing else — not an evaluation failure (§6.1 step 11: a
failed evaluation still consumed a hypothesis, and is a completed,
debited, logged attempt) and not an operator's raw ``KeyboardInterrupt``
— is ever retried as though the cloud had taken the machine.

Feature 239 adds the sixth class, and it is raised by the worker of
record the other five stand around.  :class:`ExpansionError` is the
expansion's own refusal — *System expands a selected node by resuming
its workspace, which creates exactly one refined signal for evaluation*
— and it carries **both faces of that one act**, the way
:class:`IllegalThemeError` carries both faces of its predicate: the
*tree's* face (the ask does not name a node the tree holds — no node id
at all, no ``node`` table, an unknown id, or a row too corrupt to be a
workspace) and the *seam's* face (the agent did not answer exactly one
refined signal — none, several, or a value that carries no ``code``).
One class rather than two because the caller's repair is the same for
both, and it is not a repair at all: the attempt fails **as a value** on
its :class:`~discovery.workers.WorkerResult` — feature 238's *a failed
run is a value*, feature 240's *"including failures"* — and the caller
that reads the failure names the node every message of this class
carries.  What this class deliberately **never** carries is the agent's
own exception: an agent that raises passes through untouched, because
:class:`WorkerInterrupted` must arrive as itself for
:func:`discovery.retry.is_interruption` to classify it, and an
evaluation failure must arrive as itself for §6.1's step 11 to have
charged a real attempt.  The expansion wraps nothing it did not refuse.
"""

from __future__ import annotations

__all__ = [
    "BatchDispatchError",
    "CampaignOrderError",
    "CampaignPlanningError",
    "DiscoveryError",
    "ExpansionError",
    "IllegalThemeError",
    "WorkerInterrupted",
]


class DiscoveryError(Exception):
    """Base class for every failure of the discovery orchestrator's path."""


class CampaignPlanningError(DiscoveryError):
    """The campaign plan could not be formed as the caller asked for it.

    Raised before anything is read or written: an id, a type, a workspace
    count or a stored fraction that is not the kind of value this feature's
    sentence is about.  The repair is to re-consider the ask — see the
    module docstring for why this is not the same class as
    :class:`CampaignOrderError`.
    """


class CampaignOrderError(DiscoveryError):
    """The store's state contradicts the campaign's ordering law.

    Feature 232's *"before any node is expanded"* is the law, and this is
    the refusal when the store says it was broken: the campaign's tree
    already holds a node, or a re-issued plan disagrees with the row
    already recorded.  Both name the campaign and the offending fact, so
    an operator learns *what* is out of order rather than merely that
    something is.
    """


class IllegalThemeError(DiscoveryError):
    """A research theme is not in the deployment's configured legal set.

    app_spec.xml feature 241: *"System rejects a root theme outside the
    configured legal set when assigning a research theme."*  Every message
    this class carries begins with the code
    :data:`discovery.themes.ILLEGAL_THEME` (``illegal_theme``) — the one
    spelling the spec names — so an operator grepping a log for the
    rejection finds it by the feature's own word, the convention §7.3's
    ``heterogeneous_world`` and §7.1's ``is_null_column`` refusals already
    follow in this workspace.

    The class carries **both** faces of that one question, the way
    :class:`~canary.CanaryImportError` carries both faces of §12's
    determinism floor:

    * a theme being *assigned* that the configured set does not admit —
      feature 241's own sentence, refused before any node is planted; and
    * a term in a *configured* legal set that is not a theme identifier at
      all — refused at configuration, because a legal set is how the space
      is enforced and a term it cannot judge is one no assignment could be
      checked against.

    They are one class because they are one predicate — *can this value be
    a legal theme here?* — split by *who* got it wrong (the planner's
    assignment, or the operator's configuration), and because the two
    refusals a caller acts on are "widen the set" and "pick a legal theme",
    which is one repair decision read from either side.

    Deliberately **not** a subclass of
    :class:`CampaignPlanningError`, and the reason is the repair rather
    than the shape: a malformed ask is fixed by re-sending a corrected one,
    while an illegal theme is a fact about a *configured space* that a
    well-formed ask ran into.  Kept out of :class:`CampaignOrderError` for
    the same reason: nothing about the store's state is in question — the
    theme is refused before any row or node exists.
    """


class BatchDispatchError(DiscoveryError):
    """The evaluation dispatch could not be run as W slots at all.

    app_spec.xml feature 238: *"System runs W parallel evaluation workers
    as concurrent slots, which returns batch results as each worker
    completes."*  This is the refusal when the *ask* cannot begin: a
    ``width`` that is not the genuine positive integer a campaign's
    ``workspace_count`` is, a ``worker`` that is not callable, or a
    ``jobs`` that is not a batch.  Every refusal fires **before any slot
    starts** — :func:`discovery.workers.run_batch` validates eagerly,
    precisely so that a malformed dispatch is refused as an ask rather
    than discovered broken mid-batch with slots already holding work.

    The repair is :class:`CampaignPlanningError`'s — re-consider what was
    asked for — which is why this is not an ordering refusal: the pool
    holds no store, so no store's state can contradict the law.  And it is
    emphatically not the class a *failing worker* raises through: a worker
    that fails mid-batch is a value the stream carries on its
    :class:`~discovery.workers.WorkerResult` (the signal sandbox's
    *a failed run is a value* discipline — ``evaluator._sandbox`` states
    it for its own failures — and PRD §5's *"every attempt is logged to
    the tree with its full artifact"*, feature 240's "including
    failures"), so a batch whose evaluations fail never sees this class.
    It is reserved for asks the pool could not even start — and feature
    244's re-dispatch joins it rather than minting a twin, because its
    refusals are the same repair spelled for one more act: a retry
    budget that is not a genuine positive integer, a value that is not
    a :class:`~discovery.workers.WorkerResult` at all, a result that is
    not an interruption (a completed run, or an evaluation failure the
    tree must log rather than re-spend), and two interrupted results
    naming one job — the state whose retry *would* be the duplicate
    ledger debit feature 244 exists to prevent.  All fire before any
    slot starts, on the call rather than at first consumption.
    """


class WorkerInterrupted(DiscoveryError):
    """An evaluation worker was interrupted before its evaluation finished.

    app_spec.xml feature 244: *"System retries an interrupted evaluation
    worker idempotently, so spot-instance reclamation returns no duplicate
    ledger debit"* — and this class is the *interrupted* of that sentence,
    §14's scheduled event arriving as data: *"Eval workers … Spot-eligible.
    Failures retry; ledger debits are idempotent by ``node_id``."*

    Raised by the **worker of record** (feature 239's expansion, a
    deployment's evaluator driver), which translates the machine-level
    fact — the sandbox child dying of the provider's reclaim signal, the
    host going away mid-evaluation — into the one vocabulary this member
    can act on.  It is not raised by the retry itself and it is never a
    refusal: it is the fact :func:`discovery.retry.retry_interrupted`
    exists to answer, captured by feature 238's pool onto its
    :class:`~discovery.workers.WorkerResult` like any failure and
    classified by :func:`discovery.retry.is_interruption` — which is true
    of exactly this class, so an **evaluation failure** (a completed,
    debited, logged attempt — §6.1 step 11 debits it because *"a failed
    evaluation still consumed a hypothesis"*) and an operator's raw
    ``KeyboardInterrupt`` are never mistaken for reclamation and retried.

    A subclass of :class:`DiscoveryError` so the one-``except`` property
    holds for the whole orchestrator's path, interruptions included.
    The message is the worker's own account of the interruption; the
    retry's refusals never carry this class, and a caller that sees it
    raised knows a worker, not a seam, is speaking.
    """


class ExpansionError(DiscoveryError):
    """The expansion could not create its one refined signal.

    app_spec.xml feature 239: *"System expands a selected node by
    resuming its workspace, which creates exactly one refined signal for
    evaluation."*  This is the refusal when either half of that sentence
    cannot be met — the *selected node's workspace* could not be resumed
    (the ask is not a node id, the tree holds no ``node`` table, the id
    names no row, or the row is too corrupt to be a workspace), or the
    agent seam did not answer *exactly one* refined signal (no signal,
    several candidates, or a value that carries no ``code``).  Every
    message names the node the expansion was asked to expand.

    Not a :class:`CampaignPlanningError` and not a
    :class:`BatchDispatchError`, though it neighbours both: a malformed
    *plan* is repaired by re-sending it and a malformed *dispatch* by
    re-considering the batch, while a failed expansion is a fact about
    one attempt — PRD §5's *"every attempt is logged to the tree with
    its full artifact"* is where it goes (feature 240's *"including
    failures"*), and the repair is the caller's per-node policy, not a
    corrected re-ask.  Raised inside the worker of record, it reaches
    the caller on :attr:`~discovery.workers.WorkerResult.error` rather
    than through the pool: a failed run is a value, and this class is
    one of the values a run can fail into.

    Deliberately **never** wraps what the agent raised.  An agent's
    :class:`WorkerInterrupted` must arrive as itself —
    :func:`~discovery.retry.is_interruption` is true of exactly that
    class, and a re-wrapped interruption would quietly stop retrying
    (§14's reclamation would then cost a hypothesis for nothing).  An
    agent's evaluation failure must arrive as itself for the same
    reason from the other side: §6.1's step 11 charges it, and the tree
    logs what actually happened.  This class speaks only for the
    expansion's own two faces.
    """
