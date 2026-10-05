"""The orchestrator member: live node evaluation and the campaign driver.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 1,
creates this workspace member (``packages/orchestrator``, import name
``orchestrator``); docs/nullius-tech-architecture.md §3 draws its edges —
the discovery orchestrator calls the frozen evaluator, the null oracle
and the trial ledger, persists through the tree and artifact stores, and
drives the signal agent and the policy runtime.  Spec A of the campaign
driver (this spec) supplies what a live run was missing: the evaluator's
``TreeNodeWriter`` and ``ArtifactWriter`` implementations, a caller of
``evaluator.debit_trial``, a null-aware oracle for nodes below a
campaign's root, configuration loading, and the one-call ``evaluate_node``
that assembles them.  Spec B (``additions_spec_campaign_driver.xml``)
builds the loop itself on top.

**Feature 8 is where those six features become one deployable thing.**
Features 2 through 7 each landed a seam with one job — the subtree
oracle, the two writers, the context loader, the charge caller, and the
one-call pipeline that drives them — but nothing yet answered the
question a running process actually asks: *is there a live evaluator to
call, and if so, what is it?*  :class:`LiveEvaluator` is that answer, and
``"live-evaluator"`` is the component a composed application carries it
under.  Its builder, :func:`build_live_evaluator`, reads the one
environment variable :func:`~orchestrator._context.load_evaluation_context`
reads — ``NULLIUS_EVALUATION_CONFIG`` — plus the variables feature 5's
loader reads behind it, and nothing else: it calls the loader exactly
once and answers ``None`` when the loader does, the same degrade-don't-
break stance every optional store in this workspace takes toward its own
unconfigured state.  A *configured but broken* document is a different
fact — :class:`~orchestrator._context.EvaluationConfigError` propagates
out of the builder uncaught, because a deployment that pointed the
variable at a file it meant to work deserves a composition that refuses
to start, not one that silently ran with live evaluation disabled.

**The builder evaluates nothing, and resolves no sibling component.**
Loading the context reads the sealed snapshot's manifest and its bars,
parses the cost model and folds the evaluator's identity — real I/O, but
none of it is *evaluating a node*: no sandbox spawns, no signal runs, no
charge is booked.  Nor does the builder reach for the ``"nulloracle-
target-route"`` or ``"ledger"`` components it will need later: a builder
that called :func:`~app.module_loader.create_app` to resolve a sibling
would recurse into the very scan that is building this component, and
every component in this workspace that reaches a sibling does so at call
time instead (:func:`dreaming.sweep._replay_of`'s own ``"replay"`` lookup
is the precedent).  So :meth:`LiveEvaluator.evaluate` resolves
``"nulloracle-target-route"`` and ``"ledger"`` itself, fresh, on every
call — the same way a campaign loop composed over this component would
see whatever the deployment has wired at the moment a node is actually
evaluated, not whatever stood when the application was first assembled.

**The component this spec adds is registered here, in this ``__init__``,
and in no submodule.**  The factory's scan imports this package fresh on
every :func:`~app.module_loader.create_app` call, but a module already
cached in ``sys.modules`` is not re-executed; a ``@register`` living in
one of this member's private submodules would fire on the first
``create_app()`` of a process and silently drop out of every later one.
That is why every feature of this member built a private module with no
registration of its own (``_oracle``, ``_tree_writer``,
``_artifact_writer``, ``_context``, ``_charge``, ``_evaluate``) and why
this file, re-executed on every scan, is the only place the member's
``@register`` calls may live.

The member's standing rule, fixed by the spec's addition summary: the
evaluator, nulloracle, ledger, artifacts and discovery members are the
read-only trust zone Z0, *called and never changed*.  The pyproject
declares those dependencies — plus signal-agent, providers and
policy-runtime — as workspace sources, and no third-party package: this
member is wiring, and wiring carries no weight of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.module_loader import register

from ._artifact_writer import ArtifactStoreWriter
from ._charge import charge_failed_node, charge_node
from ._context import (
    EvaluationConfigError,
    EvaluationContext,
    load_evaluation_context,
)
from ._evaluate import NodeEvaluation, evaluate_node
from ._oracle import OracleTargetError, SubtreeOracle
from ._tree_writer import NodeMetricsWriter

__all__ = [
    # Feature 2 — the null-aware subtree oracle
    "OracleTargetError",
    "SubtreeOracle",
    # Feature 3 — the tree writer
    "NodeMetricsWriter",
    # Feature 4 — the artifact writer
    "ArtifactStoreWriter",
    # Feature 5 — the evaluation context
    "EvaluationConfigError",
    "EvaluationContext",
    "load_evaluation_context",
    # Feature 6 — the charge
    "charge_failed_node",
    "charge_node",
    # Feature 7 — the one-call evaluation
    "NodeEvaluation",
    "evaluate_node",
    # Feature 8 — the live-evaluator component
    "LiveEvaluator",
]

#: The name a composed :class:`~app.module_loader.Application` carries this
#: member's one component at — the key a campaign loop (spec B) asks for
#: rather than importing :class:`LiveEvaluator` by name.
_COMPONENT_NAME = "live-evaluator"


@dataclass(frozen=True)
class LiveEvaluator:
    """One deployment's live evaluator — the loaded context, called per node.

    Built only by :func:`build_live_evaluator`, which loads ``context``
    once per :func:`~app.module_loader.create_app` call and never again:
    every :meth:`evaluate` call this instance ever serves runs against the
    exact snapshot, cost model and identity triple that one load resolved,
    which is what keeps every score a deployment produces between two
    compositions comparable — a context that drifted mid-process would
    stamp two evaluations of the same node with two different hashes.
    """

    #: The inputs feature 5's loader resolved — the sealed snapshot, the
    #: closes, the cost model, and the provenance triple every charge this
    #: instance books is stamped with.
    context: EvaluationContext

    def evaluate(
        self, node_id: str, campaign_id: str, depth: int, code: str
    ) -> NodeEvaluation:
        """Evaluate one live node — feature 7's call, wired to this deployment.

        Resolves this call's two siblings fresh, from the composed
        application a bare :func:`~app.module_loader.create_app` answers:
        ``"nulloracle-target-route"`` (nulloracle's own
        ``TARGET_COMPONENT_NAME``), wrapped in a
        :class:`~orchestrator._oracle.SubtreeOracle` bound to this
        instance's own ``context.database_url`` so the oracle walks the
        same tree the node's row lands in, and ``"ledger"`` (ledger's own
        ``COMPONENT_NAME``), handed through untouched.  Resolving at call
        time rather than at build time is what lets a deployment wire or
        rewire either sibling without rebuilding this component, and is
        the only way to resolve them at all: resolving them in the
        builder would mean calling :func:`~app.module_loader.create_app`
        from inside the very scan that builds ``"live-evaluator"``.

        Neither sibling's absence is this method's to soften: an
        unconfigured route answers ``None`` here, and
        :class:`~orchestrator._oracle.SubtreeOracle` itself refuses a
        ``None`` endpoint with
        :class:`~orchestrator._oracle.SubtreeOracleError`; an
        unconfigured ledger is handed to :func:`evaluate_node` as
        ``None`` and refused by :func:`evaluator.debit_trial`'s own
        validation.  Both are Z0's refusals, named and not duplicated
        here.

        Hands ``node_id``, ``campaign_id``, ``depth`` and ``code`` through
        to :func:`evaluate_node` exactly as received, alongside this
        instance's own ``context`` — the whole of what this method adds
        over calling :func:`evaluate_node` directly is resolving the two
        siblings a live deployment must supply.
        """
        from app.module_loader import create_app

        composed = create_app()
        endpoint = composed.get("nulloracle-target-route")
        ledger = composed.get("ledger")
        oracle = SubtreeOracle(endpoint, database_url=self.context.database_url)
        return evaluate_node(
            node_id,
            campaign_id,
            depth,
            code,
            context=self.context,
            oracle=oracle,
            ledger=ledger,
        )


@register(_COMPONENT_NAME)
def build_live_evaluator() -> LiveEvaluator | None:
    """Component builder: the live evaluator, or ``None`` when unconfigured.

    Calls :func:`load_evaluation_context` exactly once — the only call
    this builder makes, and the only source of the environment variables
    it reads (``NULLIUS_EVALUATION_CONFIG`` and, behind it, feature 5's
    own ``DATABASE_URL``, ``NULLIUS_COST_MODEL_PATH``,
    ``NULLIUS_EVALUATOR_IMAGE``, ``NULLIUS_EVALUATOR_CONFIG`` and
    ``PATH``) — and wraps whatever it answers in a :class:`LiveEvaluator`.
    Takes no arguments, per the factory's registration protocol.

    Answers ``None`` when the loader does: an unset or blank
    ``NULLIUS_EVALUATION_CONFIG`` means this deployment runs no live
    evaluation, which is a state every caller of
    ``create_app().get("live-evaluator")`` must be ready to see, not an
    error.  A *configured but broken* document is not softened the same
    way — :class:`EvaluationConfigError` propagates out of this builder
    uncaught, so a deployment whose configuration cannot load fails to
    compose rather than composing with live evaluation silently missing.

    Evaluates nothing: no sandbox spawns, no signal runs, no node is
    scored and no charge is booked while this function runs.  Resolves no
    sibling component either — ``"nulloracle-target-route"`` and
    ``"ledger"`` are :meth:`LiveEvaluator.evaluate`'s to resolve, at call
    time, once a node is actually being evaluated.
    """
    context = load_evaluation_context()
    if context is None:
        return None
    return LiveEvaluator(context)
