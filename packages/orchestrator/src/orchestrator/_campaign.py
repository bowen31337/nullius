"""The campaign driver — plant, seal, evaluate the roots, then loop.

additions_spec_campaign_driver.xml, "Campaign Loop" category, feature 6:
*System runs one campaign with orchestrator._campaign.run_campaign(*,
campaign_type, workspaces, rounds, width, allowance, author, evaluator,
policy, context, sidecar_selection, emit), and it creates a
CampaignResult(campaign_id, roots, nodes, rounds_run, stop_reason,
manifest).*  Every collaborator this spec names already exists — feature 1's
``author_root``, feature 2's :func:`~orchestrator._roots.plant_root`,
feature 4's exploration policy, feature 5's
:class:`~orchestrator._worker.NodeWorker`, and discovery's campaign,
batching and retry seams — so this module is the one place that calls them
in the order the spec fixes: plant every root, seal the campaign's Type-R
draw, evaluate every root, then loop the round until one of four conditions
stops it.

**A root's proposal is persisted exactly once, beside its final score.**
:class:`signal_agent.ProposalHistoryStore` refuses a second ``persist`` for
one node whose score differs from the first (feature 207's own law: *"a
different score for the same document"* is a re-measurement and is refused,
never overwritten).  A root is planted before it is evaluated — the two
happen in separate passes over the roots, with the Type-R seal between them
— so persisting the proposal at planting time, unscored, would make the
*second*, scored call (once ``evaluator.evaluate`` has actually measured
something) a conflict rather than a record.  This module therefore persists
a root's proposal only after it is evaluated, with the measured score
already in hand — the same single-call shape
:class:`~orchestrator._worker.NodeWorker` already uses for every other node,
and the reading of "proposal persistence" and "persist each root's score"
that keeps both halves of the feature's sentence one call rather than two
that would fight.

**The round loop's batch dispatch must be unpacked before it is retried.**
``discovery.retry_interrupted`` refuses outright any result that is not
itself an interruption (a completed run, or an evaluation failure, is
refused with :class:`~discovery.errors.BatchDispatchError` — *"filter the
stream with is_interruption() before retrying"*, its own docstring says).
So *"run_batch(...) wrapped in retry_interrupted(retries=2)"* is not one
pipe: this module drains ``run_batch``'s stream in full, splits it with
``discovery.is_interruption``, and retries only the interrupted half,
folding each retried job's standing result back in with the results that
never needed a retry.

**The two budgets are different resources, checked in different places.**
The *statistical* budget (``allowance``, read through
``policy_runtime.budget_account`` off this campaign's own ledger rows) is
checked once at the top of every round, before a batch is even selected —
an exhausted account stops the campaign before spending anything further.
The *token* budget (``providers.BudgetExhaustedError``, the pin's own
per-call ceiling) is a fact a worker's authoring call can raise mid-batch;
``discovery.run_batch`` captures it on the result rather than letting it
escape the dispatch, so this module reads it back off the batch's results
once the round has run, rather than catching it directly.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import uuid
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlparse

import discovery
import ledger
import providers
import signal_agent
from artifacts import ArtifactStore, executed_source
from policy_runtime import budget_account, prefix_view

from ._live_tree import live_question
from ._roots import plant_root
from ._worker import NodeWorker

# ``resume_campaign`` and ``CampaignResumeError`` are deliberately absent
# from ``__all__``: this module's own test suite (test_campaign.py, outside
# this feature's footprint) pins ``__all__`` to exactly run_campaign's four
# stop reasons and its result — a set this feature must not disturb.  Both
# names are still a public, importable surface; ``__all__`` only governs
# ``from orchestrator._campaign import *``.
__all__ = [
    "STOP_BUDGET_EXHAUSTED",
    "STOP_NO_BATCH",
    "STOP_ROUND_CAP",
    "STOP_TOKEN_BUDGET",
    "CampaignResult",
    "run_campaign",
]

#: The round loop's four stop conditions, spelled as the feature's own words
#: — a caller greps one of these on ``CampaignResult.stop_reason`` rather
#: than re-deriving which of the four fired.
STOP_NO_BATCH = "no_batch"
STOP_BUDGET_EXHAUSTED = "budget_exhausted"
STOP_TOKEN_BUDGET = "token_budget"
STOP_ROUND_CAP = "round_cap"

#: How many re-runs :func:`discovery.retry_interrupted` grants an
#: interrupted job, per round — the spec's own literal
#: ``retry_interrupted(retries=2)``, and not a parameter: a campaign's
#: tolerance for a reclaimed spot instance is this module's own policy, the
#: same way ``discovery.workers.run_batch`` takes no default ``width``.
_RETRIES = 2


@dataclass(frozen=True)
class CampaignResult:
    """One campaign's whole run — the feature's own six fields.

    ``roots`` is every planted root's node id, in planting order.  ``nodes``
    is every node the round loop actually produced a
    :class:`~orchestrator._worker.ChildOutcome` for — success, evaluation
    failure or authoring refusal alike — and deliberately excludes a root
    (``roots`` already names those) and a job that never produced an
    outcome at all (an interrupted job whose retries were exhausted still
    interrupted).  ``manifest`` is :func:`discovery.finish_campaign`'s own
    answer, read back from the table it wrote.
    """

    campaign_id: str
    roots: tuple[str, ...]
    nodes: tuple[str, ...]
    rounds_run: int
    stop_reason: str
    manifest: discovery.CampaignManifest


# -- Rendering an emitted event's value as JSON-ready ---------------------------


def _json_score(score: Any) -> Any:
    """``score``, as something :func:`json.dumps` can carry.

    A real :class:`signal_agent.ScoreRecord` renders through its own
    ``to_json()``; a plain dataclass a caller handed through
    :mod:`dataclasses`; anything else (a test's bare string or ``None``) is
    trusted to already be JSON-ready, which is the duck-typed contract every
    collaborator in this module is read through.
    """
    if score is None:
        return None
    to_json = getattr(score, "to_json", None)
    if callable(to_json):
        return json.loads(to_json())
    if dataclasses.is_dataclass(score) and not isinstance(score, type):
        return dataclasses.asdict(score)
    return score


def _evaluated_event(
    campaign_id: str,
    node_id: str,
    depth: int,
    *,
    fail_class: str | None,
    score: Any,
    charges_budget: bool,
    fail_detail: str | None = None,
) -> dict[str, Any]:
    return {
        "event": "node_evaluated",
        "campaign_id": campaign_id,
        "node_id": node_id,
        "depth": depth,
        "fail_class": fail_class,
        "fail_detail": fail_detail,
        "charges_budget": charges_budget,
        "score": _json_score(score),
    }


# -- Planting: a theme per root, cycling the deployment's legal set -------------


def _themes_for(workspaces: int) -> tuple[str, ...]:
    """One legal theme per root, cycling the deployment's configured set.

    ``run_campaign`` names no per-root theme of its own — the feature's
    sentence is ``assign_theme`` called once per root, not a theme supplied
    by the caller — so this module reads the deployment's legal set once
    (:func:`discovery.legal_themes_from_env`, the same two-step
    :func:`discovery.create_campaign` takes for ``DATABASE_URL``) and walks
    it in its own canonical order, wrapping around when there are more
    roots than configured themes.  A deployment configured with no legal
    theme at all can plant no root, and that refusal is
    :func:`discovery.assign_theme`'s own to raise.
    """
    legal = discovery.legal_themes_from_env()
    if not legal.themes:
        # Let the real refusal name the empty set rather than this module
        # raising a bespoke one in front of it.
        return tuple(discovery.assign_theme(f"root-{i}", legal=legal) for i in range(workspaces))
    return tuple(
        discovery.assign_theme(legal.themes[i % len(legal.themes)], legal=legal)
        for i in range(workspaces)
    )


# -- The round loop's two readings: the ledger, and the batch -------------------


def _campaign_ledger_rows(context: Any, campaign_id: str) -> tuple[Any, ...]:
    """This campaign's own trial-ledger rows — the account's own read.

    ``ledger.TrialLedger.rows()`` answers the whole table; a round's
    ``budget_account`` reads only this campaign's directives, so the filter
    lives here rather than asking the ledger member to grow a scoped read it
    does not otherwise need.
    """
    trial_ledger = ledger.TrialLedger(context.database_url)
    return tuple(row for row in trial_ledger.rows() if row.campaign_id == campaign_id)


def _dispatch_round(
    worker: NodeWorker, batch: list[str], *, width: int
) -> list[discovery.WorkerResult]:
    """Run one round's batch, retry every interruption, answer the standing results.

    ``discovery.retry_interrupted`` refuses a result that is not itself an
    interruption (see the module docstring), so the stream is drained and
    split with :func:`discovery.is_interruption` first: the interrupted half
    goes through the retry, the rest stands as :func:`discovery.run_batch`
    answered it, and the two are folded back into one list in no particular
    order — a caller that cares sorts by ``job``, the pool's own discipline.
    """
    results = list(discovery.run_batch(worker, batch, width=width))
    interrupted = [result for result in results if discovery.is_interruption(result)]
    settled = [result for result in results if not discovery.is_interruption(result)]
    retried = discovery.retry_interrupted(worker, interrupted, retries=_RETRIES, width=width)
    return settled + [retry.result for retry in retried]


def _is_token_budget_error(error: BaseException | None) -> bool:
    return isinstance(error, providers.BudgetExhaustedError)


# -- Resuming: reading what a campaign already has -------------------------------

#: The code word every :class:`CampaignResumeError` message opens with —
#: ``plant_root``'s and every sibling error class's own convention
#: (:data:`~orchestrator._roots.ROOT_PLANT_CODE`), spelled once so the raise
#: sites and an operator's grep agree on one token.
CAMPAIGN_RESUME_CODE: Final[str] = "campaign_resume"

#: The table resume reads — feature 97's, the same one :mod:`orchestrator._roots`
#: plants into and :mod:`discovery.manifest` censuses.
_NODE_TABLE: Final[str] = "node"

_NODE_TABLE_EXISTS_SQL = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"

#: One representative metric column.  A real evaluation's success path
#: writes all seven metric columns through one call
#: (:meth:`orchestrator._tree_writer.NodeMetricsWriter.write_node`), so a
#: ``NULL`` here is a ``NULL`` across the other six as well — reading one is
#: reading the fact.
_METRIC_PROBE_COLUMN: Final[str] = "ic_mean"

#: :data:`discovery.persist.FAIL_CLASS_COLUMN`, restated rather than
#: imported (the workspace convention every sibling module in this tree
#: already follows for a column it only reads).  Added lazily by
#: :class:`discovery.AttemptLog` the first time any attempt is recorded, so
#: a campaign resumed before its first round-loop expansion may have a
#: ``node`` table that does not carry this column at all.
_FAIL_CLASS_COLUMN: Final[str] = "fail_class"


class CampaignResumeError(Exception):
    """Raised by :func:`resume_campaign` when it cannot continue a campaign.

    The one named refusal: a ``campaign_id`` whose ``node`` table holds no
    row at all.  Resume continues work that was already started — it does
    not plant one — so an id naming no existing node is not a campaign to
    resume, and the reason it is not resumable is the one fact this class
    exists to report.  Every message opens with
    :data:`CAMPAIGN_RESUME_CODE`, the same convention
    :class:`~orchestrator._roots.RootPlantError` states for its own code
    word.
    """


def _resume_sqlite_path(database_url: str) -> Path:
    """Translate ``context.database_url`` into the node table's file.

    The same ``sqlite:///`` grammar every store in this workspace restates
    (:mod:`orchestrator._roots` states it for :func:`plant_root`): a
    non-SQLite scheme, a host, or a pathless (``:memory:``) URL are refused
    by name under :class:`CampaignResumeError`, because the rows a resume
    reads were committed by an earlier, separate process.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CampaignResumeError(
            f"{CAMPAIGN_RESUME_CODE}: unsupported database_url scheme "
            f"{parsed.scheme!r}: resume_campaign speaks sqlite:/// only "
            "(the spec's single-machine dev allowance)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CampaignResumeError(
            f"{CAMPAIGN_RESUME_CODE}: sqlite database_url must not carry a "
            f"host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CampaignResumeError(
            f"{CAMPAIGN_RESUME_CODE}: sqlite database_url carries no "
            "database path: an in-memory database cannot hold a campaign "
            "for a later process to resume"
        )
    return Path(path)


@dataclass(frozen=True)
class _ExistingNode:
    """One row resume reads off the tree — only the three facts it needs."""

    node_id: str
    is_root: bool
    evaluated: bool


def _existing_nodes(database_url: str, campaign_id: str) -> tuple[_ExistingNode, ...]:
    """Every node row this campaign already holds, oldest first.

    An absent ``node`` table reads as no rows at all, the same answer an
    unplanted campaign gives — :func:`resume_campaign` turns either into
    the same :class:`CampaignResumeError`, because both are "there is
    nothing here to resume". ``fail_class`` is read only when the table
    actually carries it (:class:`discovery.AttemptLog` adds the column
    lazily, on its own first write): a database resumed before any
    round-loop expansion ever ran may not have it yet, and probing first —
    the same :func:`PRAGMA table_info` idiom :mod:`discovery.persist` and
    :mod:`orchestrator._tree_writer` both use — is what keeps that an
    ordinary "not evaluated" reading rather than an ``OperationalError``.
    """
    path = _resume_sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute(_NODE_TABLE_EXISTS_SQL, (_NODE_TABLE,)).fetchone() is None:
            return ()
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_NODE_TABLE})")}
        select = ["id", "parent_id"]
        for optional in (_METRIC_PROBE_COLUMN, _FAIL_CLASS_COLUMN):
            if optional in columns:
                select.append(optional)
        rows = connection.execute(
            f"SELECT {', '.join(select)} FROM {_NODE_TABLE} WHERE campaign_id = ? "
            "ORDER BY rowid",
            (campaign_id,),
        ).fetchall()
    nodes = []
    for row in rows:
        values = dict(zip(select, row))
        evaluated = (
            values.get(_METRIC_PROBE_COLUMN) is not None
            or values.get(_FAIL_CLASS_COLUMN) is not None
        )
        nodes.append(
            _ExistingNode(
                node_id=values["id"],
                is_root=values["parent_id"] is None,
                evaluated=evaluated,
            )
        )
    return tuple(nodes)


# -- Root evaluation, the round loop and the finish: one helper, shared whole ----


def _continue_campaign(
    campaign_id: str,
    roots: tuple[str, ...],
    unevaluated_roots: list[tuple[str, str, str | None]],
    *,
    rounds: int,
    width: int,
    allowance: Any,
    author: Any,
    evaluator: Any,
    policy: Any,
    context: Any,
    history_store: Any,
    artifact_store: Any,
    emit: Callable[[dict[str, Any]], None],
) -> CampaignResult:
    """Evaluate what is left of the roots, run the round loop, finish, answer.

    The one private helper :func:`run_campaign` and :func:`resume_campaign`
    both call for everything that happens once a campaign's roots already
    exist in the tree — the two entry points differ only in how they got
    there (planting a fresh set versus reading an existing one) and in what
    they hand this call as ``unevaluated_roots``.

    **The roots.**  Every ``(node_id, code, proposal)`` in
    ``unevaluated_roots`` is evaluated, in order, before the round loop: a
    freshly planted root hands over the author's own text as ``proposal``,
    while a root resumed before it was ever evaluated hands over ``None`` —
    the model's original natural-language answer lived only in the
    interrupted process's memory, and nothing the tree persists
    (``code_hash``, ``stated_mechanism``) can reconstruct it byte for byte.
    ``history_store.persist`` therefore runs only when there is a document
    to persist; a root resumed with none is still evaluated and still emits
    its ``node_evaluated`` event — it simply leaves that one node's §14.1
    proposal-history pair unwritten, rather than fabricating a document the
    model never answered.

    **The loop and the finish.**  A fresh :class:`~orchestrator._worker.NodeWorker`
    over this campaign's author, evaluator and stores, up to ``rounds``
    rounds — each building a fresh :func:`~orchestrator._live_tree.live_question`
    over the campaign's current ledger charges, asking ``policy.select`` for
    a batch, and running it through :func:`discovery.run_batch` and
    :func:`discovery.retry_interrupted` — until one of the four stop
    reasons fires (see :func:`run_campaign`'s docstring for which, and why).
    Finishes with :func:`discovery.finish_campaign` regardless of which one
    fired, measures the depth tier's cache rate only when the loop produced
    at least one depth-role authoring record, and answers the
    :class:`CampaignResult` both entry points hand back.
    """
    for node_id, code, proposal in unevaluated_roots:
        evaluation = evaluator.evaluate(node_id, campaign_id, 0, code)
        if proposal is not None:
            history_store.persist(node_id, proposal, score=evaluation.score)
        emit(
            _evaluated_event(
                campaign_id,
                node_id,
                0,
                fail_class=evaluation.fail_class,
                score=evaluation.score,
                charges_budget=evaluation.charges_budget,
                # getattr, not .fail_detail: a duck-typed evaluator (this
                # module's own test doubles included) may answer an object
                # that predates the field.
                fail_detail=getattr(evaluation, "fail_detail", None),
            )
        )

    worker = NodeWorker(
        author,
        evaluator,
        context=context,
        artifact_directory=artifact_store,
        history_store=history_store,
    )
    evaluation_periods = len(context.evaluation_dates)

    nodes: list[str] = []
    records: list[Any] = []
    rounds_run = 0
    stop_reason: str = STOP_ROUND_CAP

    for round_index in range(1, rounds + 1):
        account = budget_account(allowance, _campaign_ledger_rows(context, campaign_id))
        if account.exhausted:
            stop_reason = STOP_BUDGET_EXHAUSTED
            emit(
                {
                    "event": "round",
                    "campaign_id": campaign_id,
                    "round": round_index,
                    "batch_size": 0,
                    "stop_reason": stop_reason,
                }
            )
            break

        question = live_question(
            campaign_id,
            database_url=context.database_url,
            evaluation_periods=evaluation_periods,
            budget=account,
        )
        batch = policy.select(prefix_view(question))[:width]

        if not batch:
            stop_reason = STOP_NO_BATCH
            emit(
                {
                    "event": "round",
                    "campaign_id": campaign_id,
                    "round": round_index,
                    "batch_size": 0,
                    "stop_reason": stop_reason,
                }
            )
            break

        final_results = _dispatch_round(worker, batch, width=width)

        token_budget_hit = False
        for result in final_results:
            if result.error is not None:
                if _is_token_budget_error(result.error):
                    token_budget_hit = True
                continue
            outcome = result.value
            nodes.append(outcome.node_id)
            if outcome.record is not None:
                records.append(outcome.record)
            emit(
                _evaluated_event(
                    campaign_id,
                    outcome.node_id,
                    outcome.depth,
                    fail_class=outcome.fail_class,
                    score=outcome.score,
                    charges_budget=outcome.charges_budget,
                    # ChildOutcome (orchestrator._worker, outside this bug's
                    # footprint) carries no fail_detail field yet, so this
                    # degrades to None for every round-loop child rather than
                    # raising on a frozen dataclass's missing attribute.
                    fail_detail=getattr(outcome, "fail_detail", None),
                )
            )

        rounds_run += 1
        emit(
            {
                "event": "round",
                "campaign_id": campaign_id,
                "round": round_index,
                "batch_size": len(batch),
                "stop_reason": STOP_TOKEN_BUDGET if token_budget_hit else None,
            }
        )
        if token_budget_hit:
            stop_reason = STOP_TOKEN_BUDGET
            break
    else:
        stop_reason = STOP_ROUND_CAP

    manifest = discovery.finish_campaign(campaign_id, database_url=context.database_url)
    if records:
        providers.record_campaign_cache_rate(campaign_id, records, database_url=context.database_url)

    result = CampaignResult(
        campaign_id=campaign_id,
        roots=tuple(roots),
        nodes=tuple(nodes),
        rounds_run=rounds_run,
        stop_reason=stop_reason,
        manifest=manifest,
    )
    emit(
        {
            "event": "summary",
            "campaign_id": campaign_id,
            "roots": list(result.roots),
            "nodes": list(result.nodes),
            "rounds_run": result.rounds_run,
            "stop_reason": result.stop_reason,
            "manifest": dataclasses.asdict(manifest),
        }
    )
    return result


# -- The one call ---------------------------------------------------------------


def run_campaign(
    *,
    campaign_type: str,
    workspaces: int,
    rounds: int,
    width: int,
    allowance: Any,
    author: Any,
    evaluator: Any,
    policy: Any,
    context: Any,
    sidecar_selection: Any,
    emit: Callable[[dict[str, Any]], None],
) -> CampaignResult:
    """Run one campaign end to end — feature 6's whole sentence, as one call.

    Plants ``workspaces`` roots (:func:`discovery.assign_theme`,
    ``author.author_root``, :func:`~orchestrator._roots.plant_root`,
    :func:`providers.record_authoring`, one ``emit`` per root), seals the
    campaign's Type-R draw with ``sidecar_selection.persist(campaign_id)``,
    evaluates every root and persists its proposal beside the measured
    score (see the module docstring for why that persist is the one and
    only call), then loops up to ``rounds`` rounds — each building a fresh
    :func:`~orchestrator._live_tree.live_question` over this campaign's
    current ledger charges, asking ``policy.select`` for a batch, and
    running it through :func:`discovery.run_batch` and
    :func:`discovery.retry_interrupted`.

    Stops on the first of: the policy answering an empty batch
    (:data:`STOP_NO_BATCH`), the statistical budget already exhausted
    before a batch was even built (:data:`STOP_BUDGET_EXHAUSTED`), a
    ``providers.BudgetExhaustedError`` on any of a round's results
    (:data:`STOP_TOKEN_BUDGET`), or the round cap
    (:data:`STOP_ROUND_CAP`, the ``for`` loop's own ``else``).  Finishes
    with :func:`discovery.finish_campaign` regardless of which one fired,
    and measures the depth tier's cache rate
    (:func:`providers.record_campaign_cache_rate`) only when the round loop
    produced at least one depth-role authoring record — a campaign that
    stopped at the roots has none, and that store refuses a measurement of
    no calls.

    Reads no node's null status, the sidecar key or an ``is_null`` value
    anywhere in its body: the only thing this function does with
    ``sidecar_selection`` is call ``.persist(campaign_id)`` on it, once.
    """
    record = discovery.create_campaign(campaign_type, workspaces, database_url=context.database_url)
    campaign_id = record.campaign_id

    artifact_store = ArtifactStore(context.artifact_dir)
    history_store = signal_agent.ProposalHistoryStore(
        signal_agent.ProposalStore(context.database_url)
    )

    themes = _themes_for(workspaces)
    roots: list[str] = []
    planted: list[tuple[str, Any]] = []
    for theme_root in themes:
        root_id = str(uuid.uuid4())
        authored = author.author_root(campaign_id, theme_root, root_id=root_id)
        node_id = plant_root(
            campaign_id, theme_root, authored, context=context, artifact_store=artifact_store
        )
        providers.record_authoring(authored.record, database_url=context.database_url)
        roots.append(node_id)
        planted.append((node_id, authored))
        emit(
            {
                "event": "root_planted",
                "campaign_id": campaign_id,
                "node_id": node_id,
                "theme_root": theme_root,
                "depth": 0,
            }
        )

    sidecar_selection.persist(campaign_id)

    return _continue_campaign(
        campaign_id,
        tuple(roots),
        [(node_id, authored.code, authored.proposal) for node_id, authored in planted],
        rounds=rounds,
        width=width,
        allowance=allowance,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        history_store=history_store,
        artifact_store=artifact_store,
        emit=emit,
    )


# -- Resuming an interrupted campaign --------------------------------------------


def resume_campaign(
    campaign_id: str,
    *,
    rounds: int,
    width: int,
    allowance: Any,
    author: Any,
    evaluator: Any,
    policy: Any,
    context: Any,
    emit: Callable[[dict[str, Any]], None],
) -> CampaignResult:
    """Resume ``campaign_id`` — the same :class:`CampaignResult` run_campaign answers.

    Reads the campaign's existing ``node`` rows off ``context.database_url``
    rather than calling :func:`discovery.create_campaign`: the roots are
    whatever depth-0 rows the tree already holds, planted by an earlier,
    interrupted call to :func:`run_campaign`. A ``campaign_id`` with no node
    rows at all — unplanted, or a typo — raises :class:`CampaignResumeError`
    naming the id: this function continues work, it does not start it.

    Never plants a root and never calls ``sidecar_selection.persist`` —
    there is no ``sidecar_selection`` parameter at all, because Type-R's
    null draw is sealed exactly once, at planting time, and a campaign this
    function finds already has that seal or it would have no node rows to
    resume. Any already-planted root that has not yet been evaluated (its
    row carries no metric and no ``fail_class`` — see
    :func:`_existing_nodes`) is evaluated before the round loop, and the
    round loop and the finish that follow are unchanged from
    ``run_campaign``'s own — the same ``budget_account``, the same
    ``policy.select``, the same :class:`~orchestrator._worker.NodeWorker`
    batch with ``retry_interrupted``, the same four stop reasons. All of
    that — the root evaluation, the loop and the finish — is
    :func:`_continue_campaign`, the one private helper this function and
    :func:`run_campaign` both call once their roots already exist in the
    tree. Because a child's id is ``uuid5`` of its parent and the ledger
    and every store this loop writes through are idempotent, a node
    already expanded and evaluated in an earlier run is not repeated.

    ``emit`` receives the same per-node and per-round events
    :func:`run_campaign` sends, plus one opening ``campaign_resumed`` event
    naming ``campaign_id`` and the count of node rows already present —
    before anything else runs, so even a resume that goes on to raise
    nothing further at least recorded that an attempt was made.
    """
    existing = _existing_nodes(context.database_url, campaign_id)
    if not existing:
        raise CampaignResumeError(
            f"{CAMPAIGN_RESUME_CODE}: campaign {campaign_id!r} has no node "
            "rows to resume; resume_campaign continues an existing "
            "campaign's work and does not start one — plant its roots with "
            "run_campaign first"
        )

    emit(
        {
            "event": "campaign_resumed",
            "campaign_id": campaign_id,
            "nodes_present": len(existing),
        }
    )

    roots = tuple(node.node_id for node in existing if node.is_root)
    artifact_store = ArtifactStore(context.artifact_dir)
    history_store = signal_agent.ProposalHistoryStore(
        signal_agent.ProposalStore(context.database_url)
    )

    unevaluated_roots = [
        (node.node_id, executed_source(artifact_store, campaign_id, node.node_id), None)
        for node in existing
        if node.is_root and not node.evaluated
    ]

    return _continue_campaign(
        campaign_id,
        roots,
        unevaluated_roots,
        rounds=rounds,
        width=width,
        allowance=allowance,
        author=author,
        evaluator=evaluator,
        policy=policy,
        context=context,
        history_store=history_store,
        artifact_store=artifact_store,
        emit=emit,
    )
