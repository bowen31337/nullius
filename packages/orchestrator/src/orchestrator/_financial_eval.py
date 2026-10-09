"""Scoring one (dreaming candidate, financial world) pair -- feature 3 of
``additions_spec_m2_baseline_financial_worlds.xml``, "Out-of-Sample
Evaluation".

*System scores a dreaming candidate on an admitted financial world with
orchestrator._financial_eval.score_on_financial_world(policy, campaign_id,
*, context), replaying the candidate over the campaign's own stored tree
(feature 245's replay transition, feature 249's committed pick -- no node is
generated) and scoring the committed node by its out-of-sample IR, through
:func:`orchestrator._evaluate.evaluate_on_dates` over the configured
``oos_dates``.*

**A financial world's tree is read exactly as a live campaign's own round
loop reads it.**  :func:`orchestrator._live_tree.live_question` already
freezes a :class:`policy_runtime.CampaignTree` from a campaign's ``node``
rows and answers the identical ``question.*`` surface (docs §11) over it --
a completed campaign's tree is read off the same table a running one is, so
this module reuses that loader rather than re-deriving a second freeze of
the same rows.

**The walk is driven through the replay engine, not the live round loop.**
:mod:`orchestrator._campaign`'s own loop drives a *live* episode directly
against a freshly-built question each round; this module replays a *stored*
tree, which is exactly :mod:`replay`'s own category (features 245, 248, 249)
-- :func:`replay.run_replay` opens feature 245's
:class:`~replay.ReplayTransition` at the tree's roots and loops the
candidate's ``select`` until it answers no batch or the round cap is
reached, and :func:`replay.committed_pick` performs feature 249's terminal
read: the scorer is called once, on the node the candidate committed to, and
never at all on a candidate that never commits (−∞, not a crash, is the
score replay already gives a non-committing policy -- see
:mod:`replay.pick`).

**The commit door is feature 222's, opened over the question the tree
freezes.**  A dreaming candidate's own ``select(question)`` calls
``question.commit(node_id)`` directly on the object it is handed (the same
contract :mod:`orchestrator._bootstrap_eval` drives a bootstrap world's own
question through) -- but :class:`policy_runtime.PolicyQuestion` carries no
``commit`` of its own, by that member's own design: the commit protocol is a
separate state machine from the read side (feature 217's question holds only
the reveal set), opened as :class:`policy_runtime.EpisodeCommit` over the
question's address seam.  :class:`_FinancialQuestion` is the one object that
joins them for a candidate's own call site: every read
(``observed``/``legal_roots``/``legal_actions``/``meta``/``probe_batch``) is
forwarded to the live tree's own question, and ``commit`` is forwarded to the
:class:`~policy_runtime.EpisodeCommit` opened over it -- so a candidate's
``question.commit(node_id)`` reaches the one door feature 222 guards, through
the one question the tree answers every other call through.

**The reading a candidate sees carries both pools' field names.**  A
dreaming candidate's source is screened and run the identical way regardless
of which pool it replays against (:mod:`dreaming.revise_policy`'s own
determinism does not know its candidates will be swept over bootstrap worlds
*and* financial ones), and the two pools' own observation shapes name an
in-sample reading differently -- ``bootstrap.Observation.r2_train`` against
:class:`policy_runtime.PolicyObservation`'s ``r2_insample``.
:class:`_FinancialObservation` answers both spellings of the one honest
reading :func:`orchestrator._live_tree.live_question` already derives
(``ic_mean ** 2``, that module's own stand-in for a live node's R²), so a
candidate authored against either pool's naming reads the same number
whichever word it reaches for.

**The per-node cache is the run's, not this call's.**  Two candidates --
the incumbent and a near-identical jittered revision -- commonly commit to
the identical node of one campaign's tree, and the out-of-sample read
(:func:`orchestrator._evaluate.evaluate_on_dates`) is the expensive act here:
it re-runs the stored signal inside a sandbox over the OOS grid.
:class:`FinancialEvalContext` is one dreaming cycle's own cache, keyed by
``(node_id, oos_dates)`` -- a caller builds one per cycle and hands the same
instance to every :func:`score_on_financial_world` call the cycle makes, so
a second policy committing a node :func:`score_on_financial_world` has
already scored this run reads the cached figure rather than re-running the
sandbox.

**No null sidecar.**  ``./run.sh dream`` needs no secret (CLAUDE.md's own
table), unlike ``./run.sh closeout``, which reads the sealed sidecar to gate
a committed pick's targets through the campaign's own null assignment
(:mod:`orchestrator.closeout`'s ``_oos_target_endpoint``).  This module
builds no such gate: the oracle it hands :func:`evaluate_on_dates` always
answers the snapshot's own real forward returns
(:func:`orchestrator._targets.snapshot_forward_returns`), never a permuted
branch.  That is an honest simplification for what a dreaming cycle measures
-- a comparison of exploration policies against one another and against the
fixed ``m2-fixed`` baseline, both arms read through the identical real-return
gate, so a planted null a candidate happens to commit to shifts both arms'
reading alike rather than corrupting the comparison between them -- and not
a claim this module makes about any one committed pick's own calibration,
which stays close-out's (:mod:`orchestrator.closeout`) alone to certify.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from artifacts import ArtifactStore
from policy_runtime import POLICY_MODULE_NAME, episode_commit, guard_policy
from replay import TerminalPick, committed_pick, run_replay

from ._bootstrap_eval import _load_select
from ._context import EvaluationContext
from ._evaluate import evaluate_on_dates
from ._live_tree import live_question
from ._targets import snapshot_forward_returns

__all__ = ["FinancialEvalContext", "score_on_financial_world"]

#: The round cap a financial-world replay is driven at.  An internal
#: implementation detail of this module -- ``dream``'s own ``--round-cap``
#: flag governs the bootstrap sweep (:mod:`orchestrator._bootstrap_eval`),
#: never this one, because the feature's own signature
#: (``score_on_financial_world(policy, campaign_id, *, context)``) carries no
#: caller-supplied cap.  Generous rather than tight: a real campaign's own
#: tree is small (one round loop already terminates a live campaign in dozens
#: of rounds at most), so this cap exists only to bound a candidate that
#: never stops selecting, not to ration a walk that would otherwise finish on
#: its own.
_FINANCIAL_ROUND_CAP = 100


@dataclass
class FinancialEvalContext:
    """One dreaming cycle's inputs for scoring candidates on financial worlds.

    Wraps the live evaluation inputs :func:`orchestrator._evaluate.
    evaluate_on_dates` needs (:class:`orchestrator._context.
    EvaluationContext`) with the per-run cache the module docstring
    describes.  A caller builds exactly one instance per dreaming cycle and
    passes it to every :func:`score_on_financial_world` call the cycle
    makes -- the cache's scope *is* the instance's lifetime, so two separate
    cycles (two separate instances) never share a cached reading, and a
    cycle that scores ``M`` candidates against ``n_financial`` worlds shares
    one cache across the whole ``M × n_financial`` sweep.
    """

    #: The pipeline inputs :func:`~orchestrator._evaluate.evaluate_on_dates`
    #: runs the stored signal over -- the sealed snapshot, the closes, the
    #: cost model, the sandbox runtime, and the configured ``oos_dates`` the
    #: feature scores every committed pick over.
    evaluation: EvaluationContext
    #: The per-run cache, keyed by ``(node_id, oos_dates)`` -- a committed
    #: pick's out-of-sample cost-adjusted IR, the quantity this module's
    #: scorer answers.  Private to this dataclass: a caller reads and writes
    #: it only through :func:`score_on_financial_world`, never directly.
    _cache: dict[tuple[str, tuple[Any, ...]], float] = field(default_factory=dict)


class _FinancialObservation:
    """A revealed node's reading, named both pools' ways -- see module docstring.

    Fronts one :class:`policy_runtime.PolicyObservation` (the reading
    :func:`orchestrator._live_tree.live_question` derives from a node's
    stored ``ic_mean``) and answers it under that class's own field names
    (``r2_insample``, ``ic_insample``, ``n_periods``, ``n_features``) *and*
    under :class:`bootstrap.Observation`'s (``r2_train``, ``ic_train``) --
    the one honest in-sample number, read however a candidate's own source
    was authored to read it.
    """

    __slots__ = ("_observation",)

    def __init__(self, observation: Any) -> None:
        self._observation = observation

    @property
    def node_id(self) -> str:
        return self._observation.node_id

    @property
    def r2_insample(self) -> float | None:
        return self._observation.r2_insample

    @property
    def ic_insample(self) -> float | None:
        return self._observation.ic_insample

    @property
    def n_periods(self) -> int | None:
        return self._observation.n_periods

    @property
    def n_features(self) -> int | None:
        return self._observation.n_features

    @property
    def r2_train(self) -> float | None:
        return self._observation.r2_insample

    @property
    def ic_train(self) -> float | None:
        return self._observation.ic_insample

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"_FinancialObservation(node_id={self.node_id!r})"


class _FinancialQuestion:
    """The object a financial-world candidate's ``select`` is handed.

    Fronts :func:`orchestrator._live_tree.live_question`'s own
    :class:`policy_runtime.PolicyQuestion` for every read, and a
    :class:`policy_runtime.EpisodeCommit` opened over that same question for
    the one write (``commit``) -- joining the two the way the module
    docstring describes, so a candidate's own ``question.commit(node_id)``
    reaches feature 222's door through the one question every other call
    answers through.
    """

    __slots__ = ("_commit", "_question")

    def __init__(self, question: Any, commit: Any) -> None:
        self._question = question
        self._commit = commit

    @property
    def tree(self) -> Any:
        return self._question.tree

    def observed(self) -> dict[str, _FinancialObservation]:
        return {
            node_id: _FinancialObservation(observation)
            for node_id, observation in self._question.observed().items()
        }

    def legal_roots(self) -> Any:
        return self._question.legal_roots()

    def legal_actions(self, node_id: Any = None) -> Any:
        return self._question.legal_actions(node_id)

    def meta(self, node_id: Any) -> Any:
        return self._question.meta(node_id)

    def probe_batch(self, cells: Any, on_reveal: Any = None) -> Any:
        return self._question.probe_batch(cells, on_reveal)

    def commit(self, node_id: Any) -> Any:
        return self._commit.commit(node_id)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "_FinancialQuestion()"


def score_on_financial_world(
    candidate_source: str, campaign_id: str, *, context: FinancialEvalContext
) -> TerminalPick:
    """Score one (candidate, financial world) pair -- the feature's call.

    Screens ``candidate_source`` and imports it the same way
    :func:`orchestrator._bootstrap_eval.score_on_world` does (this module's
    sibling evaluator for the bootstrap pool), then replays it over
    ``campaign_id``'s own stored tree through :func:`replay.run_replay`
    (feature 245's transition, feature 248's round loop) and reads its
    terminal commit through :func:`replay.committed_pick` (feature 249).  A
    candidate that never commits answers :data:`replay.NON_COMMITTING_SCORE`
    with no pick, exactly as the bootstrap evaluator's own miss does; a
    committed node is scored by its out-of-sample cost-adjusted IR, read (and
    cached) through ``context``.

    Raises :class:`~orchestrator._policy.PolicyLoadError` naming the
    admission reason for a source :func:`policy_runtime.screen_policy`
    refuses, for a source that raises importing, or for an admitted source
    with no top-level ``select``.  Raises
    :class:`~orchestrator._live_tree.LiveTreeError` for a ``campaign_id``
    this deployment's tree holds no node for.  Any other exception the walk,
    the commit or the out-of-sample read raises (a
    :class:`policy_runtime.PolicyRuntimeError` from the runtime guard, a
    :class:`~orchestrator._evaluate.SandboxExecutionError` from a committed
    node's re-run) propagates unchanged -- neither is this module's fault to
    translate.
    """
    select = _load_select(candidate_source)
    evaluation = context.evaluation
    question = live_question(
        campaign_id,
        database_url=evaluation.database_url,
        evaluation_periods=len(evaluation.evaluation_dates),
    )
    record = episode_commit(question)
    merged = _FinancialQuestion(question, record)

    def select_closure(asked_question: Any) -> Any:
        with guard_policy(policy_module=POLICY_MODULE_NAME):
            return select(asked_question)

    run_replay(select_closure, merged, question.tree, round_cap=_FINANCIAL_ROUND_CAP)

    def scorer(pick: Any) -> float:
        return _oos_ir(pick.node_id, campaign_id=campaign_id, context=context)

    return committed_pick(record, scorer)


def _dream_oracle(evaluation: EvaluationContext, dates: Any) -> Any:
    """A real, never-permuted oracle over ``evaluation``'s own closes.

    See the module docstring's "No null sidecar" section for why this
    module gates every committed pick's out-of-sample read through the
    snapshot's real forward returns rather than a sidecar-backed one.
    """
    from evaluator import OracleResponse

    targets = snapshot_forward_returns(evaluation)
    grid = frozenset(dates)

    def _oracle(request: Any) -> Any:
        narrowed = {day: row for day, row in targets(request).items() if day in grid}
        return OracleResponse(target_series=narrowed, charges_budget=True)

    return _oracle


def _oos_ir(node_id: str, *, campaign_id: str, context: FinancialEvalContext) -> float:
    """The committed node's out-of-sample cost-adjusted IR -- cached by ``(node_id, oos_dates)``.

    The one expensive act this module performs: reads the node's stored
    ``code.py`` artifact back and runs it through
    :func:`orchestrator._evaluate.evaluate_on_dates` over
    ``context.evaluation.oos_dates``.  A second call naming a node this
    run has already scored answers the cached figure without touching the
    artifact store or the sandbox again.
    """
    evaluation = context.evaluation
    key = (node_id, tuple(evaluation.oos_dates))
    cached = context._cache.get(key)
    if cached is not None:
        return cached
    code = ArtifactStore(evaluation.artifact_dir).read(campaign_id, node_id, "code.py")
    oracle = _dream_oracle(evaluation, evaluation.oos_dates)
    _metrics, cost_adjusted_ir = evaluate_on_dates(
        node_id,
        code.decode("utf-8"),
        context=evaluation,
        oracle=oracle,
        dates=evaluation.oos_dates,
    )
    context._cache[key] = cost_adjusted_ir
    return cost_adjusted_ir
