"""The worker — one parent, expanded and evaluated — feature 5 of spec B.

additions_spec_campaign_driver.xml, "Campaign Loop", feature 5: *System
expands and evaluates one parent node with
orchestrator._worker.NodeWorker(author, evaluator, *, context,
artifact_directory, history_store), and it creates the child's
ChildOutcome(node_id, depth, fail_class, score, charges_budget, record).*
This is the per-node act the campaign loop (feature 6) dispatches across
``discovery.workers.run_batch``'s W slots: one selected parent in,
:class:`ChildOutcome` out, every collaborator this spec already built
(spec A's live evaluator, the LLM author, discovery's expansion and
attempt log, providers' authoring door) called in the one order §6's
pipeline and §14's idempotence both need.

**The call, in order.**  :meth:`NodeWorker.__call__` resumes the parent's
workspace and authors its one refined child with
``discovery.NodeExpansion(author, context.database_url)(parent_id)`` —
feature 239's verb, which the campaign loop never calls directly because
the orchestrator holds the one thing it is missing: the deployment's
provenance.  It then builds an ``AttemptProvenance`` from ``context``'s
three hashes and the author's own
``record.attempt_provenance_terms()`` (the bridge
:mod:`providers._authoring` documents for exactly this join), wraps the
refined signal and that provenance into an ``Attempt`` with
``discovery.Attempt.from_signal``, and records it with a fresh
``discovery.AttemptLog(context.database_url, artifact_directory)`` — the
node row and its ``code.py``/``exec_trace.json`` land *before* anything
else touches the row, which is what lets ``providers.record_authoring``
run next: its own premise is that the record's node row already exists.
Only then does it call ``evaluator.evaluate(child_id, campaign_id, depth,
code)`` and persist the proposal beside the score it measured with
``history_store.persist(child_id, proposal, score=evaluation.score)``.

**The record that ``NodeExpansion`` throws away is the one this feature
needs, so it is captured on the way in.**  ``discovery.NodeExpansion``
reads only ``.code`` and ``.stated_mechanism`` off whatever the agent
answers (feature 239's own duck-typed seam) and answers a
``RefinedSignal`` that carries neither ``.proposal`` nor ``.record`` — the
authoring's own history entry and its ``providers.AuthoringRecord`` would
simply be gone the moment the expansion returns.  So the ``author`` this
worker was constructed with is never handed to ``NodeExpansion`` directly;
it is wrapped in a closure, built fresh inside ``__call__``, that
remembers the one answer it is given and nothing more.  Fresh per call
rather than an attribute on ``self`` for the reason feature 238's pool is
built of threads: ``run_batch`` may run this very worker concurrently
across several parents, and a shared "last answer" slot would be two
expansions racing to overwrite one box.

**An ``AuthoringRefusedError`` is recorded as a failed attempt, and
nowhere near the discovery tree.**  Feature 7 of the authoring addition
names this class for the one state that *is not* a refined signal: the
model was shown its own defect, every retry failed, and the authoring
spent its whole budget on answers no gate admitted.  There is no code, so
there is nothing ``discovery.Attempt`` could legally hold — ``code_hash
CHAR(64) NOT NULL`` is a fact about the tree, not a inconvenience this
worker can route around, and ``"authoring_refused"`` is not one of
``discovery.FAIL_CLASSES`` either.  So this worker's own vocabulary is
where the failure lands: the parent's workspace is re-read (the read
``NodeExpansion`` already performed before calling the agent, repeated
here because its *answer* was never kept past that failed call) purely to
derive the child's ``node_id`` and ``depth`` the same arithmetic the
expansion itself would have used, and the answer is a
:class:`ChildOutcome` carrying ``fail_class="authoring_refused"``,
``score=None`` and the conservative ``charges_budget=True`` — the ledger
is never touched, because nothing was ever authored to evaluate.

**``BudgetExhaustedError`` and ``discovery.WorkerInterrupted`` are caught
nowhere in this module, which is the point.**  The first is the campaign's
own token budget running out mid-authoring — "another call would be
refused before it was sent" — and the feature's own words are that it
*stops the campaign*; swallowing it here would turn a hard stop into a
single failed node.  The second is an agent's own translation of §14's
spot-instance reclamation, and it must reach ``discovery.retry
.retry_interrupted`` as itself for :func:`discovery.retry.is_interruption`
to classify it — a caught-and-rewrapped interruption would quietly stop
retrying. Both simply propagate out of ``__call__`` unchanged.

**Idempotence is inherited whole, the same stance
:mod:`orchestrator._charge` documents for its own seam.**  Running this
worker twice for the same parent authors a second time (the model may
answer differently — content is free, §10.1's online transition is
stochastic) but expands to the *same* child id
(``discovery.refined_node_id`` is a pure function of the parent), so the
second ``AttemptLog.record`` refreshes the one row the first created
rather than adding a second, the second ``evaluator.evaluate`` is answered
by the ledger's existing debit for that node, and ``providers
.record_authoring`` and ``history_store.persist`` meet the same
conflict rules their own stores already keep. Nothing in this module
remembers a prior call.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import discovery
import providers
from signal_agent import AuthoringRefusedError

__all__ = ["ChildOutcome", "NodeWorker"]

#: The fail_class an authoring refusal carries on a :class:`ChildOutcome`.
#: Deliberately not one of :data:`discovery.FAIL_CLASSES` — no node was ever
#: authored, so there is no ``code_hash`` for :class:`discovery.Attempt` to
#: hold, and this word never reaches the discovery tree. It is this worker's
#: own vocabulary for the one state :mod:`discovery.persist` cannot log.
AUTHORING_REFUSED_FAIL_CLASS = "authoring_refused"


@dataclass(frozen=True)
class ChildOutcome:
    """One expanded-and-evaluated child, or one authoring that was refused.

    The feature's own six fields. ``fail_class`` is ``None`` on an
    evaluated node that answered (mirroring
    ``orchestrator._evaluate.NodeEvaluation.fail_class``'s own stance:
    ``None`` is the positive fact of success, not an absence), the raised
    exception's class name when evaluation itself failed, or
    :data:`AUTHORING_REFUSED_FAIL_CLASS` when the authoring never produced
    a signal to evaluate. ``score`` and ``record`` are ``None`` in exactly
    that last case — nothing was measured and nothing was authored to file
    a ``providers.AuthoringRecord`` for. ``record`` is otherwise the
    author's own ``providers.AuthoringRecord`` (the same value
    ``providers.record_authoring`` was handed), which is what lets the
    campaign loop gather the depth-role records a round produced for
    ``providers.record_campaign_cache_rate``.
    """

    #: The child node's id — ``discovery.refined_node_id`` of the parent,
    #: whether or not the authoring produced a signal.
    node_id: str
    #: The child's depth — the parent's, plus one.
    depth: int
    #: ``None`` on success, the failure's class name, or
    #: :data:`AUTHORING_REFUSED_FAIL_CLASS`.
    fail_class: str | None
    #: The evaluation's score, or ``None`` when nothing was evaluated.
    score: Any
    #: The oracle's directive, or the conservative ``True`` when the
    #: authoring never reached an evaluation to ask it.
    charges_budget: bool
    #: The author's ``providers.AuthoringRecord``, or ``None`` when the
    #: authoring was refused and produced no record to file.
    record: Any


def _capturing(
    author: Callable[[Any], Any],
) -> tuple[Callable[[Any], Any], list[Any]]:
    """Wrap ``author`` so its one answer survives ``NodeExpansion``'s seam.

    ``discovery.NodeExpansion`` reads only ``.code`` and
    ``.stated_mechanism`` off whatever this wrapper answers and discards
    the rest, so the authored signal's ``.proposal`` and ``.record`` would
    otherwise be lost the moment the expansion returns its
    ``RefinedSignal``. Built fresh per :meth:`NodeWorker.__call__` — never
    held on ``self`` — because this worker may run concurrently across
    several parents (feature 238's pool is threads), and a shared "last
    answer" box would be two expansions racing over one slot.
    """
    captured: list[Any] = []

    def wrapped(workspace: Any) -> Any:
        answered = author(workspace)
        captured.append(answered)
        return answered

    return wrapped, captured


class NodeWorker:
    """Expand one parent, record its attempt, evaluate the child, persist both.

    Constructed with the deployment's author and evaluator (both duck-typed
    and held as given — this class does no I/O at construction) and the
    facts the call needs: ``context`` (an
    ``orchestrator._context.EvaluationContext``-shaped object — only
    ``database_url``, ``evaluator_hash``, ``snapshot_hash`` and
    ``cost_model_hash`` are read), ``artifact_directory`` (the
    ``discovery.ArtifactDirectory``-shaped store ``discovery.AttemptLog``
    publishes through) and ``history_store`` (a
    ``signal_agent.ProposalHistoryStore``-shaped object). The callable
    shape is ``discovery.workers.run_batch``'s contract: one call per
    selected parent, so a round's W slots each hold one of these.
    """

    def __init__(
        self,
        author: Callable[[Any], Any],
        evaluator: Any,
        *,
        context: Any,
        artifact_directory: Any,
        history_store: Any,
    ) -> None:
        self._author = author
        self._evaluator = evaluator
        self._context = context
        self._artifact_directory = artifact_directory
        self._history_store = history_store

    def __call__(self, parent_id: Any) -> ChildOutcome:
        """Expand, record, evaluate and persist the parent's one child.

        See the module docstring for the full order and for what each of
        the three named exceptions does. Everything else the collaborators
        raise (an :class:`~discovery.errors.ExpansionError` for an unknown
        parent, an evaluator's own debit refusal) is this worker's own
        business to leave alone — it propagates, because this feature
        states no refusal of its own to translate it into.
        """
        wrapped_author, captured = _capturing(self._author)
        expansion = discovery.NodeExpansion(wrapped_author, self._context.database_url)

        try:
            signal = expansion(parent_id)
        except AuthoringRefusedError:
            workspace = expansion.workspace(parent_id)
            return ChildOutcome(
                node_id=discovery.refined_node_id(workspace.node_id),
                depth=workspace.depth + 1,
                fail_class=AUTHORING_REFUSED_FAIL_CLASS,
                score=None,
                charges_budget=True,
                record=None,
            )

        authored = captured[-1]
        provenance = discovery.AttemptProvenance(
            evaluator_hash=self._context.evaluator_hash,
            snapshot_hash=self._context.snapshot_hash,
            cost_model_hash=self._context.cost_model_hash,
            **authored.record.attempt_provenance_terms(),
        )
        attempt = discovery.Attempt.from_signal(signal, provenance)
        attempt_log = discovery.AttemptLog(
            self._context.database_url, self._artifact_directory
        )
        attempt_log.record(attempt)
        providers.record_authoring(
            authored.record, database_url=self._context.database_url
        )

        evaluation = self._evaluator.evaluate(
            signal.node_id, signal.campaign_id, signal.depth, signal.code
        )
        self._history_store.persist(
            signal.node_id, authored.proposal, score=evaluation.score
        )

        return ChildOutcome(
            node_id=signal.node_id,
            depth=signal.depth,
            fail_class=evaluation.fail_class,
            score=evaluation.score,
            charges_budget=evaluation.charges_budget,
            record=authored.record,
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(author={self._author!r}, evaluator={self._evaluator!r})"
