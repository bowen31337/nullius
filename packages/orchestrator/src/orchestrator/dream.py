"""The dreaming-cycle CLI -- ``python -m orchestrator.dream``.

``additions_spec_operator_surfaces.xml``, "Middle Loop Operation" category,
feature 11: *System runs one dreaming cycle over the stored world pool from*
``python -m orchestrator.dream --incumbent PATH [--iteration-id ID] [--beta
0.5] [--seed S] [--round-cap 30]``. *It prints the selected policy revision
and its train-vs-holdout gap, so the M3 gate's inputs can be produced by an
operator.* The library already builds every piece of docs §C5's loop --
feature 270's pool freeze, feature 271's revision sweep, feature 273's
incumbent inclusion, feature 278's train/holdout split, feature 279's
holdout rotation, feature 272's sweep and feature 274's argmax selection,
feature 347's meta-overfit gap -- but nothing an operator can run joins
them into one outer iteration. This module is that join.

**Order of checks, each before any write** (mirroring
``bootstrap.fill``'s and ``orchestrator.closeout``'s own convention): a
``--reviser llm`` is refused before anything else is read, because no
store access is needed to know that no OS sandbox exists yet for
LLM-authored policy code (CLAUDE.md, SEC-1); then ``DATABASE_URL``; then
the canary's ``require_dreaming_allowed`` (feature 143's halt); then the
pool's size against the ladder floor (feature 275's ``rejects_thin_pool``,
through feature 186's ``world_census``); then the incumbent's own
admission (feature 230's ``screen_policy``).

**Financial worlds are a second arm, admitted and swept beside the
bootstrap pool.** ``additions_spec_m2_baseline_financial_worlds.xml``
feature 3: the completed, non-``VOID`` campaigns
(:func:`discovery.admit_completed_campaigns` over every manifest
:class:`discovery.CampaignManifests` holds) are this cycle's financial
worlds, and ``n_financial`` is now their count -- not the worlds
``world_census`` counts in ``replay_score`` that the bootstrap pool does
not hold, which was always a byproduct reading of a prior cycle's own
writes rather than the admitted pool itself. The bootstrap sweep is
unchanged: ``score_on_world`` (feature 4, :mod:`orchestrator._bootstrap_eval`)
still drives every bootstrap world's own question object, and the
bootstrap pool's world list is still :meth:`bootstrap.BootstrapPool.worlds`.
Beside it, every widened candidate is replayed over every admitted
financial world through :func:`orchestrator._financial_eval.
score_on_financial_world` (feature 245's stored-tree transition, feature
249's committed pick -- no node is generated), each committed pick scored
by its out-of-sample IR and persisted with ``policy_version
f"{candidate.module_id}#financial"``, and the cycle's own winner is
compared against the ``"m2-fixed"`` baseline (:data:`orchestrator.closeout.
M2_FIXED_POLICY_VERSION`) with :func:`dreaming.paired_pool_difference` --
reported as its own ``financial_arm`` figure, separate from the bootstrap
``train_mean``/``holdout_mean``/``gap``. With fewer than
:data:`DREAMING_MIN_FINANCIAL_WORLDS` admitted, or with no out-of-sample
grid configured for this process (``NULLIUS_EVALUATION_CONFIG`` unset, or
set with no ``oos_dates``), the financial arm is reported ``"thin"``
rather than computed -- the bootstrap arm runs exactly as before either
way.

**Selection is a two-phase sweep, not one.** ``dreaming.commit_selection``
reads every one of a candidate's ``replay_score`` rows at the episode's
beta and refuses a row whose world no named stratum covers (feature 274's
own "a dropped world silently changes which tournament the argmax is
taken over"). A ``strata={"train": train_worlds}`` call can therefore only
ever see a candidate's *train* rows -- so this module sweeps the full
widened candidate set (the incumbent plus the ``M`` revisions) over the
train worlds only, selects the argmax over that stratum, and *then*
sweeps the one winner over the holdout worlds. That is exactly feature
278's own discipline, applied to what the evaluator can be asked for:
every candidate contends on train, and only the winner's generalisation
is measured on holdout -- "select on train, report on holdout"
(docs §10.3.1) is a statement about which worlds decide, not a claim that
every losing candidate must be replayed on both halves.

**A rerun at the same iteration id and seed is a no-op, not a crash.**
``revise_policy``'s candidates are deterministic in ``(incumbent, count,
seed)``, so a second run at the same inputs produces the identical widened
set and the identical winner -- and ``policy_revision.policy_version`` is
``UNIQUE``, so ``commit_selection``'s own insert refuses the second write.
This module treats that one failure specially: when the store already
holds a ``selected`` row whose ``code_hash`` is one of this run's
candidates, that row *is* the rerun's answer, read back rather than
re-written -- the same "a re-run is a refresh, not a re-draw" stance
``bootstrap.BootstrapPool.persist_worlds`` takes for its own upsert. Any
other store refusal propagates and exits 1.

**Exit codes**, the workspace's own convention (CLAUDE.md's five operator
verbs): 0 once the cycle's summary line is printed; 1 when a collaborator
refuses -- the canary's halt, a pool below the ladder floor, the
incumbent's own admission, ``--reviser llm``, or any other refusal -- each
printed with the refusing collaborator's own code word (or this module's
own, where the library's message carries none); 2 for a missing
``DATABASE_URL``, naming it.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

import bootstrap
import discovery
import dreaming
import policy_runtime
from canary import CanaryDeterminismBrokenError, require_dreaming_allowed
from ops import MetaOverfitGaps

from ._bootstrap_eval import score_on_world
from ._context import EvaluationConfigError, EvaluationContext, load_evaluation_context
from ._financial_eval import FinancialEvalContext, score_on_financial_world
from .closeout import M2_FIXED_POLICY_VERSION

__all__ = [
    "DREAMING_MIN_FINANCIAL_WORLDS",
    "DREAM_CODE",
    "EXIT_CONFIG",
    "EXIT_OK",
    "EXIT_REFUSED",
    "FINANCIAL_SUFFIX",
    "POLICY_ISOLATION_CODE",
    "POLICY_SCREENING_CODE",
    "main",
    "run_cycle",
]

#: The greppable word this module's own refusals open with -- never a
#: collaborator's, which already opens with its own (``pool_too_thin``,
#: ``determinism_broken``, or the canary's bare message, handled below).
DREAM_CODE = "orchestrator_dream"

#: The code word ``--reviser llm`` is refused with. LLM-authored policy
#: code must not execute in the host process until policies have an OS
#: sandbox (CLAUDE.md, SEC-1) -- ``policy_runtime.guard_policy`` is
#: defence-in-depth, not the boundary, so this CLI refuses the reviser
#: choice outright rather than running it unisolated.
POLICY_ISOLATION_CODE = "policy_isolation_required"

#: The code word this module's own screening refusal opens with, naming
#: the incumbent's admission reason (feature 230's ``screen_policy``).
POLICY_SCREENING_CODE = "policy_screening_refused"

#: Done -- the cycle committed and its summary line was printed.
EXIT_OK = 0
#: A collaborator refused: the canary's halt, a thin pool, a screening
#: refusal, ``--reviser llm``, or any other refusal of the cycle.
EXIT_REFUSED = 1
#: Missing configuration: no ``DATABASE_URL``.
EXIT_CONFIG = 2

#: The two reviser choices this CLI accepts. ``jitter`` is the default,
#: structure-preserving reviser (feature 271's own); ``llm`` names the
#: isolation gap and is always refused.
_REVISERS = ("jitter", "llm")

#: The floor below which the financial arm is reported ``"thin"`` rather
#: than computed -- additions_spec_m2_baseline_financial_worlds.xml feature
#: 3's own documented constant. Two is also :func:`dreaming.paired_ir_difference`'s
#: own minimum (a single paired world has no spread to measure), so a pool
#: that clears this floor is one the paired statistic can actually take.
DREAMING_MIN_FINANCIAL_WORLDS = 2

#: The suffix a financial-world row's ``policy_version`` carries, so a
#: candidate's bootstrap-pool row and its financial-world row never share
#: one version -- their quantities differ (a bootstrap world's ``r2_holdout``
#: against a financial world's out-of-sample IR), and the paired statistic
#: compares ``f"{module_id}{FINANCIAL_SUFFIX}"`` against
#: :data:`orchestrator.closeout.M2_FIXED_POLICY_VERSION` on this suffix's own
#: rows alone.
FINANCIAL_SUFFIX = "#financial"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator.dream",
        description=(
            "Run one dreaming cycle over the stored world pool: hold the "
            "pool fixed, revise the incumbent policy M times, sweep every "
            "candidate over the train worlds, select the argmax, sweep the "
            "winner over the holdout worlds, and print the selected "
            "revision's train-versus-holdout gap as one JSON line."
        ),
    )
    parser.add_argument(
        "--incumbent",
        required=True,
        metavar="PATH",
        help="path to the incumbent exploration policy's source",
    )
    parser.add_argument(
        "--iteration-id",
        dest="iteration_id",
        default=None,
        metavar="ID",
        help="names this cycle (default: a fresh id)",
    )
    parser.add_argument(
        "--beta",
        type=float,
        default=0.5,
        metavar="BETA",
        help="the explore/exploit scalar scores are measured at (default 0.5)",
    )
    parser.add_argument(
        "--seed",
        default=None,
        metavar="S",
        help="the revision sweep's seed (default: the iteration id)",
    )
    parser.add_argument(
        "--round-cap",
        dest="round_cap",
        type=int,
        default=30,
        metavar="N",
        help="selection rounds score_on_world allows per world (default 30)",
    )
    parser.add_argument(
        "--reviser",
        choices=_REVISERS,
        default="jitter",
        help="the policy-development strategy (default jitter; llm is refused)",
    )
    parser.add_argument(
        "--write-selected",
        dest="write_selected",
        default=None,
        metavar="PATH",
        help="write the selected candidate's source to PATH (refuses to overwrite)",
    )
    return parser


def _missing_component_line(name: str) -> str:
    """The one stderr line a missing composed component prints."""
    return (
        f"{DREAM_CODE}: create_app() answers no {name!r} component; a "
        "dreaming cycle cannot persist a single replay_score row without "
        "it -- configure the deployment and run again"
    )


def _existing_winner(database_url: str, widened: Sequence[Any]) -> Any | None:
    """The candidate already marked ``selected`` for this run, or ``None``.

    A rerun at the same ``(incumbent, count, seed)`` produces the identical
    widened candidate set -- ``revise_policy``'s own determinism -- and
    ``commit_selection``'s insert then refuses the second write because
    ``policy_revision.policy_version`` is ``UNIQUE``. Reads the table
    directly for a ``selected`` row whose ``code_hash`` is one of this
    run's own candidates and answers the matching candidate, so a rerun's
    "winner" is read back rather than re-decided. ``None`` when no such row
    exists -- the caller's failure was a real refusal, not a rerun.
    """
    by_hash = {candidate.code_hash: candidate for candidate in widened}
    path = dreaming.sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT code_hash FROM policy_revision WHERE selected = 1"
        ).fetchall()
    for (code_hash,) in rows:
        candidate = by_hash.get(code_hash)
        if candidate is not None:
            return candidate
    return None


def _admitted_financial_campaigns(database_url: str) -> tuple[str, ...]:
    """The completed, non-``VOID`` campaigns admitted as financial worlds.

    Every manifest :class:`discovery.CampaignManifests` holds, filtered one
    at a time through :func:`discovery.admit_completed_campaigns` -- a
    single-manifest call per campaign (the same shape
    :func:`orchestrator.closeout.close_out` already uses for its own M2
    commit), because the function's own batch form refuses the *whole*
    batch the moment one campaign is ``VOID`` (docs §7.4), and this cycle's
    job is to admit every campaign it can rather than refuse the lot over
    one voided one. :meth:`~discovery.CampaignManifests.completed` creates
    its own table on first read, so a database this cycle's own migrations
    never touched (no completed campaign has ever been persisted here)
    answers an empty tuple rather than raising.
    """
    manifests = discovery.CampaignManifests(database_url).completed()
    admitted: list[str] = []
    for manifest in manifests:
        try:
            discovery.admit_completed_campaigns([manifest])
        except discovery.VoidCampaignError:
            continue
        admitted.append(manifest.campaign_id)
    return tuple(admitted)


def _financial_arm(
    widened: Any,
    winner: Any,
    *,
    database_url: str,
    beta: float,
    evaluation_context: EvaluationContext | None,
    replay_component: Any,
) -> tuple[int, object]:
    """Score every widened candidate on every admitted financial world.

    Answers ``(n_financial, financial_arm)``: the admitted campaign count,
    always honestly reported, and either the string ``"thin"`` (fewer than
    :data:`DREAMING_MIN_FINANCIAL_WORLDS` admitted, or no out-of-sample grid
    configured for this process) or the paired statistic comparing the
    cycle's own winner against :data:`orchestrator.closeout.
    M2_FIXED_POLICY_VERSION` on the admitted worlds (every one of them
    treated as held out -- there is no train/holdout split for financial
    worlds, every candidate already contended for the win on the bootstrap
    pool's own split).

    Every widened candidate -- not only the winner -- is swept, through one
    shared :class:`orchestrator._financial_eval.FinancialEvalContext`, so two
    candidates committing the same node of one campaign's tree share one
    out-of-sample read (the feature's own per-run cache).
    """
    campaigns = _admitted_financial_campaigns(database_url)
    n_financial = len(campaigns)
    if (
        n_financial < DREAMING_MIN_FINANCIAL_WORLDS
        or evaluation_context is None
        or not evaluation_context.oos_dates
    ):
        return n_financial, "thin"

    financial_context = FinancialEvalContext(evaluation=evaluation_context)
    for candidate in widened:
        version = f"{candidate.module_id}{FINANCIAL_SUFFIX}"
        for campaign_id in campaigns:
            pick = score_on_financial_world(
                candidate.source, campaign_id, context=financial_context
            )
            replay_component.persist_replay_score(
                pick,
                version,
                campaign_id,
                beta,
                is_holdout=True,
                database_url=database_url,
            )

    try:
        comparison = dreaming.paired_pool_difference(
            f"{winner.module_id}{FINANCIAL_SUFFIX}",
            M2_FIXED_POLICY_VERSION,
            database_url=database_url,
        )
    except dreaming.PairedComparisonError:
        return n_financial, "thin"
    return n_financial, {
        "paired_worlds": comparison.paired_worlds,
        "candidate_mean": comparison.candidate_mean,
        "baseline_mean": comparison.baseline_mean,
        "mean_difference": comparison.mean_difference,
        "p_value": comparison.p_value,
    }


def run_cycle(
    *,
    incumbent_source: str,
    database_url: str,
    iteration_id: str,
    beta: float,
    seed: Any,
    round_cap: int,
    replay_component: Any,
    census: Any,
    pool: Any,
    evaluation_context: EvaluationContext | None = None,
) -> dict[str, object]:
    """Run one dreaming cycle and answer the summary payload -- the join.

    Takes the incumbent's already-admitted source and every input the CLI's
    flags name, and performs §C5's whole outer iteration: the revision
    cap (feature 277), the pool freeze (feature 270) around the revision
    sweep (feature 271) and the incumbent's inclusion (feature 273), the
    train/holdout split and its holdout record (features 278-279), the
    two-phase sweep and selection the module docstring argues for (features
    272 and 274), and the meta-overfit gap (feature 347). The caller
    (:func:`main`) has already run every precondition this function does
    not re-check: the canary's halt, the pool's floor, and the incumbent's
    own admission.

    ``evaluation_context``, when given, is what lets this cycle also score
    the financial arm (see :func:`_financial_arm`) -- ``None`` (the default,
    and what every caller that never configured ``NULLIUS_EVALUATION_CONFIG``
    gets from :func:`main`) reports the financial arm ``"thin"`` regardless
    of how many campaigns are admitted, because there is no out-of-sample
    grid to score a committed pick over.
    """
    cap_record = dreaming.record_cycle_cap(
        iteration_id, census.total, database_url=database_url
    )
    revision_cap = cap_record.revision_cap

    freeze = dreaming.CycleFreeze(database_url)
    hold = freeze.open(iteration_id)
    try:
        candidates = dreaming.revise_policy(
            incumbent_source, revision_cap, seed=seed
        )
        # The incumbent's module_id is cycle-scoped rather than the include
        # helper's content-derived default. An unchanged incumbent (the
        # ordinary case when it wins and the operator has not yet pointed
        # --incumbent at a new winner) would otherwise carry the identical
        # module_id into every cycle, and a second cycle's commit_selection
        # would then read the *first* cycle's leftover replay_score rows
        # back for it -- rows filed under the first cycle's rotation, which
        # the second cycle's train-only strata does not cover, refusing the
        # whole selection as "uncovered". Every produced revision already
        # gets a fresh, cycle-derived identity through the seed; this gives
        # the one candidate the reviser does not jitter the same property.
        widened = dreaming.include_incumbent(
            candidates, incumbent_source, version=f"incumbent-{iteration_id}"
        )
    finally:
        freeze.release(hold)

    world_by_id = {record.world_id: pool.world(record.world_id) for record in pool.worlds()}

    # dreaming.split_replay_pool's own pool_worlds() reads bootstrap_world
    # UNIONed with every world replay_score already names -- which, the
    # moment a single campaign has been closed out (its own "m2-fixed" row)
    # or this feature's own financial arm has written a "#financial" row in
    # an earlier cycle, folds financial worlds into the same digest rank the
    # bootstrap worlds are split by. That does not just mis-tag a few rows:
    # it changes the pool size the 70/30 arithmetic is taken over and so the
    # *count* of bootstrap worlds assigned to each half, and it can move a
    # bootstrap world across the train/holdout line depending on how a
    # financial world's id happens to rank beside it -- the whole bootstrap
    # arm's split becomes a function of which financial worlds this database
    # happens to hold, not of the bootstrap pool and the rotation alone.
    # dreaming.split_pool is the pure half of feature 278's judgment -- the
    # world ids and a rotation in, the two halves out, with no database read
    # of its own -- so calling it directly over the bootstrap pool's own
    # worlds keeps the bootstrap arm's split exactly what it was before
    # financial worlds existed, independent of anything replay_score holds.
    split = dreaming.split_pool(tuple(world_by_id), rotation=iteration_id)
    dreaming.record_cycle_holdout(iteration_id, database_url=database_url)

    def evaluator(candidate: Any, world_id: str) -> Any:
        return score_on_world(candidate.source, world_by_id[world_id], round_cap=round_cap)

    train_worlds = list(split.train)
    holdout_worlds = list(split.holdout)

    train_report = dreaming.sweep_candidates(
        widened,
        evaluator=evaluator,
        beta=beta,
        worlds=train_worlds,
        split=split,
        database_url=database_url,
        replay=replay_component,
    )

    strata = {"train": tuple(train_worlds)}
    try:
        winner = dreaming.commit_selection(
            widened,
            strata=strata,
            beta=beta,
            iteration_id=iteration_id,
            database_url=database_url,
        )
    except dreaming.SelectionStoreError:
        rerun_winner = _existing_winner(database_url, widened)
        if rerun_winner is None:
            raise
        winner = rerun_winner

    holdout_report = dreaming.sweep_candidates(
        [winner],
        evaluator=evaluator,
        beta=beta,
        worlds=holdout_worlds,
        split=split,
        database_url=database_url,
        replay=replay_component,
    )

    path = dreaming.sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT score, is_holdout FROM replay_score "
            "WHERE policy_version = ? AND beta = ?",
            (winner.module_id, beta),
        ).fetchall()
    train_scores = [score for score, is_holdout in rows if not is_holdout]
    holdout_scores = [score for score, is_holdout in rows if is_holdout]
    train_mean = sum(train_scores) / len(train_scores)
    holdout_mean = sum(holdout_scores) / len(holdout_scores)

    gap_record = MetaOverfitGaps(database_url).record(
        iteration_id,
        train_mean=train_mean,
        holdout_mean=holdout_mean,
        train_worlds=len(train_worlds),
        holdout_worlds=len(holdout_worlds),
    )

    n_financial, financial_arm = _financial_arm(
        widened,
        winner,
        database_url=database_url,
        beta=beta,
        evaluation_context=evaluation_context,
        replay_component=replay_component,
    )

    return {
        "iteration_id": iteration_id,
        "n_bootstrap": census.n_bootstrap,
        "n_financial": n_financial,
        "revision_cap": revision_cap,
        "module_id": winner.module_id,
        "code_hash": winner.code_hash,
        "train_mean": gap_record.train_mean,
        "holdout_mean": gap_record.holdout_mean,
        "gap": gap_record.gap,
        "financial_arm": financial_arm,
        "replay_score_rows": train_report.pair_count + holdout_report.pair_count,
        "_winner_source": winner.source,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    emit: Callable[[str], object] = print,
    app: Any = None,
) -> int:
    """``python -m orchestrator.dream --incumbent PATH [...]``.

    ``env`` and ``emit`` are this command's seams, taken exactly as the
    other operator CLIs in this workspace take them (``bootstrap.fill``,
    ``orchestrator.closeout``): ``env`` is where ``DATABASE_URL`` is read
    from, ``emit`` is what the one JSON summary line is printed with, and
    ``app`` is the composed application the ``replay`` component is read
    from (a real :func:`~app.module_loader.create_app` when ``None``) --
    so the suite drives this command in-process, with no subprocess and no
    real environment.

    ``env`` is also where ``NULLIUS_EVALUATION_CONFIG`` is read from, the
    same variable ``./run.sh campaign`` configures
    (:func:`orchestrator._context.load_evaluation_context`) -- optional for
    this CLI, unlike ``campaign``'s own required reading of it: unset, this
    cycle still runs, with the financial arm reported ``"thin"`` (see
    :func:`run_cycle`); set but malformed, this command refuses the same way
    ``campaign`` would, naming the broken key.
    """
    parser = _build_parser()
    arguments = parser.parse_args(argv)

    if arguments.reviser == "llm":
        print(
            f"{POLICY_ISOLATION_CODE}: --reviser llm is refused; "
            "LLM-authored policy code must not execute in the host process "
            "until policies have an OS sandbox (CLAUDE.md, SEC-1) -- "
            "policy_runtime.guard_policy is defence-in-depth, not the "
            "boundary. Use --reviser jitter, the default no-network reviser",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    source = os.environ if env is None else env
    database_url = source.get(dreaming.DATABASE_URL_ENV, "").strip()
    if not database_url:
        print(
            f"{DREAM_CODE}: {dreaming.DATABASE_URL_ENV} must name the "
            "database the replay pool lives in",
            file=sys.stderr,
        )
        return EXIT_CONFIG

    write_selected = arguments.write_selected
    if write_selected is not None and Path(write_selected).exists():
        print(
            f"{DREAM_CODE}: --write-selected {write_selected!r} already "
            "exists; refusing to overwrite it",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        incumbent_source = Path(arguments.incumbent).read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"{DREAM_CODE}: --incumbent {arguments.incumbent!r} cannot be "
            f"read: {exc}",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        require_dreaming_allowed(database_url=database_url)
    except CanaryDeterminismBrokenError as exc:
        print(f"determinism_broken: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    pool = bootstrap.BootstrapPool(database_url)
    try:
        census = bootstrap.world_census(pool)
    except bootstrap.BootstrapError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    try:
        dreaming.rejects_thin_pool(census.total)
    except dreaming.PoolTooThinError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    decision = policy_runtime.screen_policy(incumbent_source)
    if not decision.adopted:
        print(
            f"{POLICY_SCREENING_CODE}: --incumbent {arguments.incumbent!r} "
            f"was refused admission ({decision.reason.value}): "
            f"{decision.detail}",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    try:
        evaluation_context = load_evaluation_context(env=source)
    except EvaluationConfigError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    composed = app if app is not None else _create_app()
    replay_component = composed.get("replay")
    if replay_component is None:
        print(_missing_component_line("replay"), file=sys.stderr)
        return EXIT_REFUSED

    iteration_id = arguments.iteration_id or f"dream-{uuid.uuid4().hex}"
    seed = arguments.seed if arguments.seed is not None else iteration_id

    try:
        summary = run_cycle(
            incumbent_source=incumbent_source,
            database_url=database_url,
            iteration_id=iteration_id,
            beta=arguments.beta,
            seed=seed,
            round_cap=arguments.round_cap,
            replay_component=replay_component,
            census=census,
            pool=pool,
            evaluation_context=evaluation_context,
        )
    except dreaming.DreamingError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_REFUSED

    winner_source = summary.pop("_winner_source")
    if write_selected is not None:
        try:
            with open(write_selected, "x", encoding="utf-8") as handle:
                handle.write(winner_source)
        except OSError as exc:
            print(
                f"{DREAM_CODE}: --write-selected {write_selected!r} could "
                f"not be written: {exc}",
                file=sys.stderr,
            )
            return EXIT_REFUSED

    emit(json.dumps(summary))
    return EXIT_OK


def _create_app() -> Any:
    """``create_app()``, imported at call time.

    Deferred so a caller that supplies its own ``app`` -- every test -- pays
    nothing for the composition scan, the same lazy import
    ``orchestrator.campaign`` performs for the identical reason.
    """
    from app.module_loader import create_app

    return create_app()


if __name__ == "__main__":  # pragma: no cover - the module's own door
    raise SystemExit(main())
