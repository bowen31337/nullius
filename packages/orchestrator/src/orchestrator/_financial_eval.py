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
``(node_id, oos_dates, horizon)`` -- a caller builds one per cycle and hands
the same instance to every :func:`score_on_financial_world` call the cycle
makes, so a second policy committing a node :func:`score_on_financial_world`
has already scored this run reads the cached figure rather than re-running
the sandbox.

**A pick is judged at its own campaign's horizon, and a world is admitted
only on a grid its campaign never saw.**  Two laws, both from
``additions_spec_engine_edge_recovery.xml`` "Campaign Grid" feature 5, both
repairs for the leak the M3 RESULT's erratum records (17 of the 103
financial worlds were *not* out of sample for the picks scored on them --
their in-sample grids ended inside the OOS window):

* a committed node is scored at **its own campaign's recorded horizon**
  (:func:`_oos_ir` reads the ``campaign`` row's ``horizon`` and evaluates
  through ``dataclasses.replace(context.evaluation, horizon=that)``), so a
  pick is judged on the forward window it was selected for -- the oracle
  already serves whatever horizon the evaluator asks
  (:func:`orchestrator._targets.snapshot_forward_returns` reads the request's
  own), and a campaign that records none (``NULL``, every row written before
  ``0120_campaign_evaluation_grid.py``) is scored at the context's horizon,
  exactly as before.  Since bug_spec_metrics_horizon.xml bug 2, the
  re-horizoned context's ``metrics_horizon_value`` follows the replacement
  when the evaluation config sets ``metrics_horizon`` to ``"configured"``
  (``EvaluationContext.metrics_horizon_value`` is derived from ``horizon``),
  so under that mode the read is *measured* at the campaign's own horizon;
  under the default ``"shortest"`` the metrics keep the shortest-covered
  policy exactly as before;
* a campaign is admitted as a financial world only through
  :func:`admit_financial_worlds` -- the shared admission helper -- which,
  beside the standing VOID filter, excludes a campaign whose recorded
  ``grid_last_date`` falls on or after the first out-of-sample date and a
  campaign that records none at all (unknown is not admitted), whenever the
  scoring context carries an OOS grid.

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

import dataclasses
import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Any

import discovery
from artifacts import ArtifactStore
from policy_runtime import POLICY_MODULE_NAME, episode_commit, guard_policy
from replay import TerminalPick, committed_pick, run_replay

from ._bootstrap_eval import _load_select
from ._context import EvaluationContext
from ._evaluate import evaluate_on_dates
from ._live_tree import live_question
from ._targets import snapshot_forward_returns

__all__ = [
    "EXCLUDED_AS_UNKNOWN",
    "EXCLUDED_FOR_OVERLAP",
    "FINANCIAL_ADMISSION_CODE",
    "FinancialEvalContext",
    "FinancialWorldAdmission",
    "FinancialWorldExclusion",
    "admit_financial_worlds",
    "score_on_financial_world",
]

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


# -- The shared financial-world admission --------------------------------------
#
# One helper, two callers: the dreaming cycle's own admission
# (``orchestrator.dream._admitted_financial_campaigns``) and the M3 verdict's
# (``orchestrator.m3_verdict._verify_financial_pool``) -- the verdict's
# admission mirrors the cycle's, so the two must be one code path and not two
# readings of the same law that could drift apart.


#: The greppable word every exclusion :func:`admit_financial_worlds` reports
#: opens with -- an excluded campaign is reported with an error message of
#: this module's own, naming the ``grid_last_date`` that excluded it, so an
#: operator reading a cycle's summary (or a verdict's refusal) can grep one
#: token and find this law.
FINANCIAL_ADMISSION_CODE = "financial_world_admission"

#: The reason a campaign was excluded because its in-sample grid reached
#: into the out-of-sample window: ``grid_last_date`` on or after the first
#: OOS date.
EXCLUDED_FOR_OVERLAP = "overlap"

#: The reason a campaign was excluded because no ``grid_last_date`` is
#: recorded at all: whether its grid precedes the OOS window is unknown, and
#: unknown is not admitted.
EXCLUDED_AS_UNKNOWN = "unknown"


@dataclass(frozen=True)
class FinancialWorldExclusion:
    """One campaign the admission refused, and why.

    Carries the ``grid_last_date`` that decided the refusal (``None`` for the
    unknown case -- the absent value *is* the reason) beside the full
    :attr:`message`, because the counts a summary displays say *how many*
    and this row is the *which one* an operator repairs next.
    """

    #: The excluded campaign's own id.
    campaign_id: str
    #: :data:`EXCLUDED_FOR_OVERLAP` or :data:`EXCLUDED_AS_UNKNOWN`.
    reason: str
    #: The campaign row's ``grid_last_date`` (ISO text), or ``None`` when the
    #: row records none -- the one fact the refusal turned on.
    grid_last_date: str | None
    #: The full error message, opening with :data:`FINANCIAL_ADMISSION_CODE`
    #: and naming the ``grid_last_date`` -- reported verbatim by the dream
    #: summary and by the verdict's thin-pool refusal.
    message: str


@dataclass(frozen=True)
class FinancialWorldAdmission:
    """What :func:`admit_financial_worlds` decided: the admitted ids, the refusals.

    ``campaign_ids`` is the admitted pool in the manifest store's own stable
    order; ``exclusions`` carries every refused campaign with its reason and
    message.  The count views (:meth:`counts`, :meth:`summary`) are the
    figures the dream summary displays -- admitted, excluded for overlap,
    excluded as unknown -- never re-derived from the tuples by a caller.
    """

    #: The campaigns admitted as financial worlds, in
    #: :meth:`discovery.CampaignManifests.completed`'s own id order.
    campaign_ids: tuple[str, ...]
    #: Every refused campaign, in the same order, empty when all were
    #: admitted.
    exclusions: tuple[FinancialWorldExclusion, ...]

    @property
    def excluded_overlap(self) -> tuple[str, ...]:
        """The ids refused for an in-sample grid reaching into the OOS window."""
        return tuple(
            exclusion.campaign_id
            for exclusion in self.exclusions
            if exclusion.reason == EXCLUDED_FOR_OVERLAP
        )

    @property
    def excluded_unknown(self) -> tuple[str, ...]:
        """The ids refused for carrying no recorded ``grid_last_date``."""
        return tuple(
            exclusion.campaign_id
            for exclusion in self.exclusions
            if exclusion.reason == EXCLUDED_AS_UNKNOWN
        )

    def counts(self) -> dict[str, int]:
        """The three counts a refusal or a summary reports."""
        return {
            "admitted": len(self.campaign_ids),
            "excluded_overlap": len(self.excluded_overlap),
            "excluded_unknown": len(self.excluded_unknown),
        }

    def summary(self) -> dict[str, Any]:
        """:meth:`counts`, with each excluded campaign's own error message.

        The shape the dream cycle's summary carries as its
        ``financial_admission`` figure: the three counts beside
        ``{campaign_id: message}`` for every refused campaign, so the line an
        operator reads states not only *how many* were excluded but *which*
        and *why* -- the message names the ``grid_last_date``.
        """
        payload = self.counts()
        payload["excluded"] = {
            exclusion.campaign_id: exclusion.message
            for exclusion in self.exclusions
        }
        return payload


def _overlap_message(
    campaign_id: str, grid_last_date: str, oos_first_date: dt.date
) -> str:
    """The error message for a grid that reached into the OOS window."""
    return (
        f"{FINANCIAL_ADMISSION_CODE}: campaign {campaign_id!r} is excluded as "
        f"a financial world: its in-sample grid ended {grid_last_date} "
        f"(grid_last_date), on or after the first out-of-sample date "
        f"{oos_first_date.isoformat()} the picks would be scored over, so a "
        "pick judged on that window would be judged on bars the campaign's "
        "own in-sample evaluation already saw"
    )


def _unknown_message(campaign_id: str, oos_first_date: dt.date) -> str:
    """The error message for a campaign whose grid's end is not recorded."""
    return (
        f"{FINANCIAL_ADMISSION_CODE}: campaign {campaign_id!r} is excluded as "
        f"a financial world: its campaign row records no grid_last_date "
        f"(NULL), so whether its in-sample grid ended before the first "
        f"out-of-sample date {oos_first_date.isoformat()} is unknown -- and "
        "unknown is not admitted"
    )


def admit_financial_worlds(
    database_url: str, *, oos_first_date: dt.date | None = None
) -> FinancialWorldAdmission:
    """Admit the completed campaigns that may serve as financial worlds.

    The standing VOID filter first, exactly as
    ``orchestrator.dream._admitted_financial_campaigns`` always applied it:
    every manifest :class:`discovery.CampaignManifests` holds, one at a time
    through :func:`discovery.admit_completed_campaigns` -- a single-manifest
    call per campaign (the same shape :func:`orchestrator.closeout.close_out`
    uses for its own M2 commit), because the function's own batch form
    refuses the *whole* batch the moment one campaign is ``VOID`` (docs
    §7.4), and a caller's job here is to admit every campaign it can rather
    than refuse the lot over one voided one.

    Then, **only when ``oos_first_date`` is given** -- the first date of the
    out-of-sample grid the scoring context carries -- the clean-grid rule
    ``additions_spec_engine_edge_recovery.xml`` feature 5 states, read off
    each campaign's own row (:meth:`discovery.CampaignRecords.get`, whose
    five grid columns ``0120_campaign_evaluation_grid.py`` added):

    * a campaign whose ``grid_last_date`` is **on or after**
      ``oos_first_date`` is excluded (:data:`EXCLUDED_FOR_OVERLAP`) -- its
      in-sample evaluation already saw bars the out-of-sample read would
      judge it on, which is the leak the M3 RESULT's erratum records (17 of
      103 admitted worlds were not out of sample for the picks scored on
      them);
    * a campaign that records **no** ``grid_last_date`` is excluded
      (:data:`EXCLUDED_AS_UNKNOWN`) -- whether its grid precedes the OOS
      window is unknown, and unknown is not admitted.

    ``oos_first_date=None`` -- a context with no out-of-sample grid, and the
    M3 verdict, which holds an evaluation configuration only by its digest --
    leaves admission exactly as it was before this helper existed: the VOID
    filter alone, no grid column ever read.  A campaign row that is missing
    entirely (a manifest without its campaign row) is read as the unknown
    case, never silently admitted.

    Answers the whole decision -- admitted ids, and every exclusion with its
    own error message naming the ``grid_last_date`` -- so each caller reports
    the counts it measured rather than re-deriving them.
    """
    manifests = discovery.CampaignManifests(database_url).completed()
    records = discovery.CampaignRecords(database_url)
    admitted: list[str] = []
    exclusions: list[FinancialWorldExclusion] = []
    for manifest in manifests:
        try:
            discovery.admit_completed_campaigns([manifest])
        except discovery.VoidCampaignError:
            continue
        if oos_first_date is None:
            admitted.append(manifest.campaign_id)
            continue
        record = records.get(manifest.campaign_id)
        grid_last_date = None if record is None else record.grid_last_date
        if grid_last_date is None:
            exclusions.append(
                FinancialWorldExclusion(
                    campaign_id=manifest.campaign_id,
                    reason=EXCLUDED_AS_UNKNOWN,
                    grid_last_date=None,
                    message=_unknown_message(manifest.campaign_id, oos_first_date),
                )
            )
        elif dt.date.fromisoformat(grid_last_date) >= oos_first_date:
            exclusions.append(
                FinancialWorldExclusion(
                    campaign_id=manifest.campaign_id,
                    reason=EXCLUDED_FOR_OVERLAP,
                    grid_last_date=grid_last_date,
                    message=_overlap_message(
                        manifest.campaign_id, grid_last_date, oos_first_date
                    ),
                )
            )
        else:
            admitted.append(manifest.campaign_id)
    return FinancialWorldAdmission(
        campaign_ids=tuple(admitted), exclusions=tuple(exclusions)
    )


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
    #: The per-run cache, keyed by ``(node_id, oos_dates, horizon)`` -- a
    #: committed pick's out-of-sample cost-adjusted IR, the quantity this
    #: module's scorer answers.  The horizon is part of the key because it is
    #: part of the measurement: one node scored at two horizons is two
    #: different readings, and a cache that keyed on the node and the grid
    #: alone would hand the second horizon the first one's figure.  Private
    #: to this dataclass: a caller reads and writes it only through
    #: :func:`score_on_financial_world`, never directly.
    _cache: dict[tuple[str, tuple[Any, ...], int], float] = field(default_factory=dict)


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
    answers through.  ``abstain`` is the record's other way through that same
    door: a candidate that declares it commits nothing leaves ``record.pick``
    ``None`` exactly as a fall-off would, so :func:`replay.committed_pick`
    reads it as the identical miss -- :data:`replay.NON_COMMITTING_SCORE`,
    no pick.
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

    def abstain(self) -> None:
        return self._commit.abstain()

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
    cached) through ``context`` -- at the campaign row's own ``horizon``
    when it records one (see :func:`_oos_ir`), at ``context``'s otherwise.

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
    """The committed node's out-of-sample cost-adjusted IR -- cached by ``(node_id, oos_dates, horizon)``.

    The one expensive act this module performs: reads the node's stored
    ``code.py`` artifact back and runs it through
    :func:`orchestrator._evaluate.evaluate_on_dates` over
    ``context.evaluation.oos_dates``.  A second call naming a node this
    run has already scored answers the cached figure without touching the
    artifact store or the sandbox again.

    **The node is scored at its own campaign's horizon.**  Before anything
    else, the ``campaign`` row's ``horizon`` is read
    (:func:`_campaign_horizon`) and, when it carries one, the evaluation runs
    under ``dataclasses.replace(context.evaluation, horizon=that)`` -- the
    horizon the pick was *selected for* is the horizon it is judged on, never
    the dreaming context's own.  :func:`_dream_oracle` serves the requested
    horizon out of the same snapshot's real forward returns, so the read stays
    one oracle over one grid.  Since bug_spec_metrics_horizon.xml bug 2, the
    replacement reaches the *metrics* too: the re-horizoned context's
    ``metrics_horizon_value`` resolves to the campaign's horizon when the
    evaluation config sets ``metrics_horizon`` to ``"configured"``
    (:class:`orchestrator._context.EvaluationContext` derives the value from
    ``horizon``, so the ``replace`` re-resolves it), and under the default
    ``"shortest"`` the metrics keep the shortest-covered policy exactly as
    they always were -- the pre-fix state, where this replacement moved only
    the cache key.  A campaign row with no ``horizon`` (or no row
    at all) scores at ``context.evaluation.horizon`` exactly as before this
    law existed.  The horizon is part of the cache key because it is part of
    the measurement: the same node scored under two horizons is two figures.
    """
    evaluation = context.evaluation
    horizon = _campaign_horizon(evaluation.database_url, campaign_id)
    if horizon is not None:
        evaluation = dataclasses.replace(evaluation, horizon=horizon)
    key = (node_id, tuple(evaluation.oos_dates), evaluation.horizon)
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


def _campaign_horizon(database_url: str, campaign_id: str) -> int | None:
    """The campaign row's own ``horizon``, or ``None`` when it records none.

    Read once per out-of-sample score (:func:`_oos_ir`) so a pick is judged at
    the horizon its own campaign selected under -- ``0120_campaign_evaluation_grid``
    column, present only on campaigns recorded since that migration, so a
    missing row, a ``NULL`` column or a database whose chain has not reached
    ``0120`` (:meth:`discovery.CampaignRecords._grid_select_list` substitutes
    a literal ``NULL`` for the column) answers ``None``, and the caller scores
    at the context's horizon, exactly as the pre-grid campaigns always were.

    A database with no ``campaign`` table at all -- the pre-``0111`` shape --
    answers ``None`` too, and only that: the refusal is caught by its own
    text, so an unreachable or corrupt store still raises rather than being
    mistaken for a campaign that merely records no horizon.
    """
    try:
        record = discovery.CampaignRecords(database_url).get(campaign_id)
    except sqlite3.OperationalError as error:
        if "no such table" not in str(error):
            raise
        return None
    if record is None:
        return None
    return record.horizon
