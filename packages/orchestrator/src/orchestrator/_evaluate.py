"""The one-call evaluation — a live node, scored and persisted.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 7:
*System evaluates one live node with
orchestrator._evaluate.evaluate_node(node_id, campaign_id, depth, code, *,
context, oracle, ledger), and it answers a NodeEvaluation with node_id,
metrics, score (a signal_agent.ScoreRecord), charges_budget, fail_class,
persistence and debit.*  Every other feature this member added (the oracle
adapter, the two writers, the context loader, the charge caller) is a seam
with one job; this module is where they are driven in the order
``tests/e2e/test_momentum_signal_positive_ic.py``'s own ``_run_pipeline``
already proved — resolve_window, execute_signal, normalize_scores,
align_targets, gate_targets, apply_costs, compute_node_metrics — plus the
two steps a live run needs beyond that journey: the import screen that
comes before any of it, and the charge and the persisted row that come
after.

**The import screen is the first thing that runs, and the code is never
executed if it refuses.**  §5.2's posture — "LLM-authored code is untrusted
code. Treat it that way." — is a law feature 167 holds in the sandbox
member, not a second copy of it here: ``sandbox.sandbox_imports()`` compiles
the committed allowlist fresh on every call (the same never-cached posture
``_context``'s own ``runsc`` lookup takes), and ``evaluate_node`` asks it
before ``resolve_window`` ever touches the sealed snapshot.  A refusal is
charged immediately, with ``fail_class`` the spec's own code word
(``disallowed_import``) rather than an exception's class name — the one
deliberate exception to the rule the rest of this module follows for
failures.

**Every other failure is charged under the class of what was raised.**
"When the signal raises, or the sandbox or the execution fails ... NodeEvaluation
then carries fail_class (the failure's class name)."  So the whole pipeline
chain from ``resolve_window`` through ``compute_node_metrics`` runs inside
one ``try``, and whatever escapes it — ``EvaluatorWindowError``,
``EvaluatorSignalError``, ``OracleTargetError``, a bare ``ValueError`` from a
malformed signal — is charged with :func:`orchestrator._charge.charge_failed_node`
and its class name is ``fail_class``, both on the ledger row and on the
answered :class:`NodeEvaluation`.  A day whose score vector the sandbox did
not return conforming (a timeout, an oom, a crash, a contract violation) is
not silently treated as "scored nothing" — it is raised here, as
:class:`SandboxExecutionError`, specifically so it takes the same path as
every other pipeline failure and is never scored past.

**``execute_signal`` always runs under the orchestrator's own executor, and
the generic ``SandboxExecutionError`` name is narrowed where the executor
said more.**  additions_spec_gvisor_executor.xml, "Executor Selection",
feature 7, adds the one call that chooses it:
:func:`orchestrator._context.signal_sandbox` reads ``context.sandbox_runtime``
and answers a :class:`~orchestrator._gvisor.GVisorSandbox` or a
:class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox` — never
the evaluator's own unconfined default — and this module hands its answer to
every ``execute_signal`` call.  :class:`~evaluator.RawScoreVector` has no
``fail_class`` or ``detail`` field at all, so the executor's own last
:class:`~evaluator.SandboxResult` (remembered on ``last_result``, the one
attribute :func:`~orchestrator._context.signal_sandbox` always attaches) is
the only place either value survives past ``execute_signal`` returning.
:func:`_fail_class` reads it: a specific reported class (``"timeout"``,
``"oom"``, ``"violation"``, ``"payload"``, ``"empty"``, gVisor's own
``"sandbox_escape"``) replaces the generic ``SandboxExecutionError`` name on
``NodeEvaluation.fail_class``; the one fail_class the executor itself
defines as a catch-all (``"crash"`` — "the signal raised or the child died
to a limit") stays mapped to ``SandboxExecutionError``, which is already
what a signal that merely raises would be named by this module's own rule.

**``compute_marginal_ir`` runs against an empty book, by the spec's own
words, and the evaluator's own refusal says what to do about it.**  There is
no resident book in spec A — the campaign loop that would hold one is spec
B's ``additions_spec_campaign_driver.xml`` — so the call the spec names is
``compute_marginal_ir(priced, {})``, which :mod:`evaluator._marginal`
refuses unconditionally (*"a book of zero signals has no information ratio
to increment from — that question is the candidate's standalone IR"*).  That
refusal is caught here, narrowly, around this one call: an empty book is
not a pipeline failure, it is the honest fact that nothing exists yet to be
marginal against, and the evaluator's own message names the number that
answers it.  ``ir_marginal`` is therefore ``metrics.ir_standalone`` whenever
the book is empty, and the real ``compute_marginal_ir`` once a book exists
is spec B's to call.

**Persistence writes through the two injected seams directly, not through
``evaluator.persist_node``.**  Feature 85's orchestration
(:func:`evaluator.persist_node`) reads back a decay profile and a capacity
estimate that were persisted earlier in the same node's pipeline — and
computing either needs inputs (dollar volumes, regime labels) that nothing
in this spec's :class:`~orchestrator._context.EvaluationContext` carries.
Spec A measures four things: the metrics (feature 80), the marginal IR
(feature 83, or its empty-book stand-in), the priced panel (feature 79) and
the charge (feature 84) — so this module copies those directly onto the
node row through the injected ``NodeMetricsWriter`` and writes the
artifacts the records support (the priced panel, the IC series, the
turnover series, the run's exec trace, and the signal source) through the
injected ``ArtifactStoreWriter``, built fresh from the context's own
``database_url`` and ``artifact_dir`` — construction of both is I/O-free,
so building them per call costs nothing a live run was not already paying.
Decay and capacity stay unwritten in spec A; a later spec that measures them
calls ``evaluator.persist_node`` once those inputs exist.

**``charges_budget`` is the oracle's bit, nothing else, and it defaults
conservatively until the oracle has spoken.**  Before ``gate_targets`` asks
the oracle, a failure (a bad import screen, a broken window, a crashed
signal) is charged with ``charges_budget=True`` — the same conservative
statement :mod:`orchestrator._charge` documents for a failure before the
gate answered, because understating ``K`` is the one error direction that
lets a false discovery through.  Once the oracle answers, every later charge
— success or failure — carries exactly the bit ``GatedTargets.charges_budget``
named.  This module never reads a node's null status, the sidecar key or
any ``is_null`` value; the only route a bit can reach a charge through is
the oracle's own response.

**Idempotency is inherited, not implemented twice.**  A second
``evaluate_node`` for the same node re-derives the same metrics from the
same sealed snapshot (§12's replay contract): ``NodeMetricsWriter.write_node``
answers ``written=False`` for identical values rather than conflicting,
``ArtifactStoreWriter.flush`` republishes identical bytes, and
``charge_node``/``charge_failed_node`` are answered by the ledger's own
idempotent-by-node debit.  Nothing in this module remembers a prior call.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Any, Final

import sandbox
from artifacts import (
    IC_SERIES_FILENAME,
    SIGNAL_RETURNS_FILENAME,
    TURNOVER_SERIES_FILENAME,
    ArtifactStore,
)
from evaluator import (
    HORIZONS,
    ArtifactPayload,
    EvaluatorMarginalError,
    EvaluatorNormalizeError,
    NodeMetrics,
    Oracle,
    PostCostReturns,
    align_targets,
    apply_costs,
    compute_marginal_ir,
    compute_node_metrics,
    execute_signal,
    gate_targets,
    normalize_scores,
    render_exec_trace,
    resolve_window,
)
from evaluator._execute import pit_universe
from signal_agent import ScoreRecord

from ._artifact_writer import ArtifactStoreWriter
from ._charge import charge_failed_node, charge_node
from ._context import BARS_STREAM, EvaluationContext, signal_sandbox
from ._tree_writer import NodeMetricsWriter

__all__ = [
    "MIN_SCORED_DATES",
    "NodeEvaluation",
    "NodePersistence",
    "SandboxExecutionError",
    "evaluate_node",
]

_logger = logging.getLogger(__name__)

#: The floor on how many rebalance dates must express a preference (survive
#: normalization) before a node is allowed to pass at all.  A date is absent
#: — not scored — when its point-in-time universe holds fewer than two
#: symbols or when every raw score on it is identical (normalize_scores' own
#: no-preference refusal, see :func:`_score_rebalance_dates`); without a
#: floor a signal could pass by expressing a view on a handful of
#: cherry-picked days while sitting out everything else.
MIN_SCORED_DATES: Final[int] = 20

#: The length a failure's message is truncated to before it is carried on
#: :attr:`NodeEvaluation.fail_detail` — long enough for a pipeline error's
#: own context (symbols, dates), short enough that a pathological message
#: cannot bloat the node row or the emitted event.
_FAIL_DETAIL_LIMIT: Final[int] = 2_000

#: The pipeline steps this spec's evaluation reaches, in the numbering
#: :mod:`evaluator._artifact`'s ``render_exec_trace`` and
#: :mod:`evaluator._persist_store``'s own default share: apply_costs (7),
#: compute_metrics (8, the IC/IR/turnover half feature 80 owns — the decay
#: and capacity halves are unmeasured in spec A), marginal_ir (9, or its
#: empty-book stand-in) and debit_ledger (11).  Step 10 (tripwires) and step
#: 12 (the full feature-85 persist) are not reached by this spec.
_STEPS_COMPLETED: tuple[int, ...] = (7, 8, 9, 11)

#: The decision instant a live evaluation resolves its window at: the last
#: rebalance date of the grid, at the end of its day — the same instant the
#: momentum e2e journey resolves at, and the honest "as of everything this
#: evaluation was configured to score" reading of a date grid.
_END_OF_DAY = dt.time(23, 59, tzinfo=dt.UTC)


class SandboxExecutionError(Exception):
    """A rebalance date's score vector did not come back conforming.

    Raised when the sandbox recorded a failure (a timeout, an oom, a crash,
    a channel failure) or the signal's return failed the contract — any day
    for which :attr:`~evaluator.RawScoreVector.conforming` is false.  Caught
    nowhere specially: it takes the same path as every other pipeline
    failure, charged with :func:`orchestrator._charge.charge_failed_node`
    and named on the answered :class:`NodeEvaluation` as ``fail_class``,
    which for this class is the literal string ``"SandboxExecutionError"`` —
    the spec's "the failure's class name", read off ``type(exc).__name__``
    the same way every other pipeline exception is.
    """


@dataclass(frozen=True)
class NodePersistence:
    """What this spec's write left for one node — the tree row and the files.

    Not :class:`evaluator.NodePersistence`: that record is feature 85's
    answer for the full twelve-step write (decay profile, capacity, regime
    attribution included), and spec A measures a narrower set.  This is the
    smaller, honest answer for what actually landed: whether the tree row
    changed (``False`` on an idempotent re-evaluation whose values agree
    with what already stood) and whether the artifact directory was
    committed.
    """

    #: The node this write was for.
    node_id: str
    #: Whether this call changed the node's tree row — ``False`` when the
    #: row already held exactly these values (an idempotent re-evaluation).
    tree_written: bool
    #: Whether the artifact directory was committed by this call.
    artifact_written: bool


@dataclass(frozen=True)
class NodeEvaluation:
    """``evaluate_node``'s whole answer — the spec's own six fields, plus the node.

    ``metrics`` and ``persistence`` are ``None`` on every failure path (the
    import screen's refusal, or anything the pipeline's own ``try`` caught):
    a node that was not measured has no metrics to carry and nothing was
    written for it.  ``score`` is always present — a
    :class:`signal_agent.ScoreRecord` whose six scalars are the measured
    values and whose ``fail_class`` is ``None`` on success, or whose six
    scalars are the absent measurement ``None`` and whose ``fail_class``
    names the failure.  ``debit`` is always present too: every evaluated
    node, failed ones included, is charged exactly once.
    """

    #: The node this answer is for.
    node_id: str
    #: Feature 80's four scalars plus the horizon and the per-date IC
    #: series, or ``None`` on any failure.
    metrics: NodeMetrics | None
    #: The score, in the shape a replay history reads (§14.1's ``score.json``).
    score: ScoreRecord
    #: The oracle's own bit — ``True`` until the oracle has answered (the
    #: conservative default), exactly what it answered afterward, win or fail.
    charges_budget: bool
    #: The failure's class name, the spec's own code word
    #: (``disallowed_import``) for a refused import screen, or ``None`` on
    #: success.
    fail_class: str | None
    #: What was written for this node, or ``None`` on any failure.
    persistence: NodePersistence | None
    #: The ledger's answer to this node's charge — the landed row, its
    #: sequence, and whether this call wrote it.
    debit: Any
    #: The failure's own message, ``str(exc)`` truncated to
    #: :data:`_FAIL_DETAIL_LIMIT` characters, or ``None`` on success.  Pipeline
    #: messages name symbols and dates, never a node's null status or any
    #: sidecar content, so two nodes failing the same way differ in this text
    #: only where their own identifiers (a node id, say) do.  ``fail_class``
    #: is unchanged — this only carries the reason beside the class.
    fail_detail: str | None = None
    #: How many of this node's rebalance dates were absent — no score,
    #: never a fabricated zero — because their point-in-time universe held
    #: fewer than two symbols or because every raw score on them was
    #: identical (normalize_scores' own no-preference refusal).  ``0`` on
    #: every failure path, since no date was scored past the point of
    #: failure.
    flat_dates: int = 0


# -- The materialize seam: reading the sealed mount for execute_signal ----------


def _materialize_from_context(context: EvaluationContext) -> Any:
    """The production lake reader, over this evaluation's sealed mount.

    The seam :func:`evaluator.execute_signal` takes to turn a
    ``(resolution, decision_time)`` into a materialized window — the same
    reader ``tests/e2e/test_momentum_signal_positive_ic.py`` injects for the
    same reason: the evaluator's own default builds empty frames, and a live
    run needs the sealed bytes.  The window's ``universe`` is
    :func:`evaluator._execute.pit_universe`'s per-date answer — feature 72's
    admission rule applied at *this* rebalance date, not the resolution's own
    decision date — so a symbol listed or delisted partway through the
    evaluation grid is admitted only on the dates its sealed bars actually
    carry a partition, the same rule :func:`evaluator._execute._materialize_default`
    applies from the one shared helper, so the two materializers cannot
    drift apart.  Only the partitions that per-date universe names, at or
    before the decision date, are read through the mount's own ``select``,
    so the same read-only handle and the same sealedness back every score
    this evaluation computes, and a symbol not yet listed (or already
    delisted) on a given date is never read for it.  A small per-partition
    cache keeps one evaluation from re-reading the same compressed bytes
    twice across rebalance dates.
    """
    mount = context.snapshot
    cache: dict[tuple[str, str], Any] = {}

    def materialize(resolution: Any, decision_time: dt.datetime) -> Any:
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        from contract.bars import bars_frame_name
        from contract.window import MarketWindow

        universe = pit_universe(resolution, decision_time.date())
        tables: list[Any] = []
        for symbol in universe:
            for iso in resolution.dates(BARS_STREAM, symbol):
                if dt.date.fromisoformat(iso) > decision_time.date():
                    continue
                key = (symbol, iso)
                if key not in cache:
                    paths = list(mount.select(BARS_STREAM, symbol, iso))
                    cache[key] = (
                        pq.read_table(str(paths[0])) if paths else pa.table({})
                    )
                tables.append(cache[key])
        frame = pa.concat_tables(tables) if tables else pa.table({})
        if frame.num_rows:
            frame = frame.filter(
                pc.less_equal(
                    frame["open_time"],
                    pa.scalar(decision_time, type=pa.timestamp("us", tz="UTC")),
                )
            )
        return MarketWindow(
            decision_time,
            universe=universe,
            frames={bars_frame_name("1d"): frame},
        )

    return materialize


# -- The cost seam: the context's own schedule, transported not re-implemented --


def _cost_schedule_from_context(context: EvaluationContext) -> Any:
    """The injected ``CostSchedule`` :func:`evaluator.apply_costs` charges through.

    The context already resolved the venue's :class:`~cost_model.FeeSchedule`
    (feature 5); this closure quotes its taker rate on exactly the support
    ``apply_costs`` asks about, the same transport
    ``tests/e2e/test_momentum_signal_positive_ic.py`` builds over the shared
    library and for the same reason feature 69 forbids a second one: the fee
    arithmetic is the library's, never re-implemented here.

    Quoted *per date*, off that date's own ``request.gross_returns[day]`` —
    never off ``request.symbols`` (the request's whole-horizon union)
    applied uniformly — because a point-in-time universe lets one
    rebalance date's cross-section be a strict subset of another's (a
    listing or a delisting inside the horizon's span), and a quote naming a
    symbol a date never scored is exactly what
    :func:`evaluator._costs._check_charge_support` refuses.
    """
    from cost_model import TAKER
    from evaluator import CostQuote

    fee = context.cost_schedule.fee_fraction(TAKER)

    def charges(request: Any) -> Any:
        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: dict.fromkeys(row, fee)
                for day, row in request.gross_returns.items()
            },
        )

    return charges


# -- The cost-adjusted axis: the panel's own mean, restated from the horizon ----


def _cost_adjusted_ir(returns: PostCostReturns, metrics: NodeMetrics) -> float:
    """The mean post-cost edge of the equal-weight book, at the metrics horizon.

    The same figure :mod:`evaluator._persist_store` assembles onto a node
    row — the panel's per-date equal-weight mean, averaged over the dates
    ``compute_node_metrics`` measured — restated here because that module's
    helper is private and this spec writes the row directly rather than
    through ``evaluator.persist_node``.  The horizon and its dates are
    exactly the ones ``metrics.ic_mean`` already reduced over, so this can
    never find no dates to average: a metrics record that exists is a
    metrics record whose horizon had at least one priced, non-empty date.
    """
    series = returns.series[metrics.horizon]
    per_date_means = [
        sum(series.at(day).values()) / len(series.at(day))
        for day in sorted(series.dates())
        if series.at(day)
    ]
    if not per_date_means:
        raise RuntimeError(
            "compute_node_metrics measured a metrics record over this very "
            "horizon, so the priced panel must carry at least one non-empty "
            "date at it; finding none here is an invariant this module "
            "relies on having broken"
        )
    return sum(per_date_means) / len(per_date_means)


# -- The write: the tree row and the artifact set this spec measures -----------


@dataclass(frozen=True)
class _TreeNodeRow:
    """The duck-typed row :class:`~orchestrator._tree_writer.NodeMetricsWriter`
    wants — exactly the identity and the seven metric columns it reads by
    attribute, and nothing of :class:`evaluator.NodeRow`'s wider shape (the
    tree writer never reads ``campaign_id``, ``snapshot_name``,
    ``evaluator_hash`` or ``cost_model`` — those are the tree member's own
    columns, already on the row the discovery loop or the root planter
    wrote first).
    """

    node_id: str
    ic_mean: float
    ic_tstat: float
    ir_standalone: float
    ir_marginal: float
    turnover: float
    cost_adjusted_ir: float
    perturb_stability: float | None = None


def _persist(
    *,
    node_id: str,
    campaign_id: str,
    code: str,
    context: EvaluationContext,
    returns: PostCostReturns,
    metrics: NodeMetrics,
    ir_marginal: float,
    cost_adjusted_ir: float,
) -> NodePersistence:
    """Write the node row and this spec's artifact set — the two injected seams.

    Builds both writers fresh from the context's own ``database_url`` and
    ``artifact_dir``: construction of a
    :class:`~orchestrator._tree_writer.NodeMetricsWriter`, an
    :class:`artifacts.ArtifactStore` and an
    :class:`~orchestrator._artifact_writer.ArtifactStoreWriter` performs no
    I/O, so paying for them once per evaluated node costs nothing a live run
    was not already going to pay for the write itself.  Writes the row
    first (the measured scalars), then stages and flushes the artifacts the
    records this spec computed actually support: the priced panel, the IC
    series, the turnover series, the run's exec trace, and the signal
    source.  Decay and capacity are not in this spec's scope (see the
    module docstring) and are not written here.
    """
    tree_writer = NodeMetricsWriter(context.database_url)
    node_id_written, tree_written = tree_writer.write_node(
        _TreeNodeRow(
            node_id=node_id,
            ic_mean=metrics.ic_mean,
            ic_tstat=metrics.ic_tstat,
            ir_standalone=metrics.ir_standalone,
            ir_marginal=ir_marginal,
            turnover=metrics.turnover,
            cost_adjusted_ir=cost_adjusted_ir,
            perturb_stability=None,
        )
    )
    if node_id_written != node_id:
        raise RuntimeError(
            f"the tree writer answered a write for node {node_id_written!r} "
            f"but this evaluation is for node {node_id!r}; a row for one "
            "node cannot be written under another's identity"
        )

    artifact_writer = ArtifactStoreWriter(ArtifactStore(context.artifact_dir))
    artifact_writer.write_artifact(
        node_id,
        campaign_id,
        SIGNAL_RETURNS_FILENAME,
        ArtifactPayload(
            filename=SIGNAL_RETURNS_FILENAME, kind="parquet", source=returns
        ),
    )
    artifact_writer.write_artifact(
        node_id,
        campaign_id,
        IC_SERIES_FILENAME,
        ArtifactPayload(filename=IC_SERIES_FILENAME, kind="parquet", source=metrics),
    )
    artifact_writer.write_artifact(
        node_id,
        campaign_id,
        TURNOVER_SERIES_FILENAME,
        ArtifactPayload(
            filename=TURNOVER_SERIES_FILENAME,
            kind="parquet",
            source=(returns, metrics),
        ),
    )
    trace = render_exec_trace(
        node_id=node_id,
        campaign_id=campaign_id,
        snapshot_name=returns.snapshot_name,
        evaluator_hash=context.evaluator_hash,
        cost_model=returns.cost_model,
        horizons=HORIZONS,
        charges_budget=returns.charges_budget,
        steps_completed=_STEPS_COMPLETED,
    )
    artifact_writer.write_artifact(
        node_id,
        campaign_id,
        "exec_trace.json",
        ArtifactPayload(
            filename="exec_trace.json", kind="json", json_text=json.dumps(trace)
        ),
    )
    artifact_writer.write_artifact(
        node_id,
        campaign_id,
        "code.py",
        ArtifactPayload(filename="code.py", kind="code", code_text=code),
    )
    artifact_writer.flush(node_id)

    return NodePersistence(
        node_id=node_id, tree_written=tree_written, artifact_written=True
    )


# -- The executor's own failure, read past what RawScoreVector drops -----------

#: The one sandbox ``fail_class`` that maps back to this module's own
#: generic ``SandboxExecutionError`` rather than surfacing verbatim.  The
#: evaluator's own vocabulary defines ``"crash"`` as "the signal raised or
#: the child died to a limit" (:class:`evaluator.SandboxResult`'s own
#: docstring) — exactly the shape "the failure's class name" already covers
#: for every other pipeline exception, so collapsing it here keeps that one
#: rule rather than adding a second vocabulary beside it for the single
#: fail_class that is itself already a catch-all.
_GENERIC_SANDBOX_FAIL_CLASS = "crash"


def _executor_failure(executor: object) -> str:
    """The executor's own last reported shape, for a richer refusal message.

    :class:`~evaluator.RawScoreVector` drops ``fail_class`` and ``detail``
    entirely, so this is where they are read back — off the ``last_result``
    attribute :func:`orchestrator._context.signal_sandbox` always attaches
    to the executor it hands back (see that function's own docstring).
    Answers the old placeholder text when the executor never ran, or ran
    and recorded no failure — both are "there is nothing more specific to
    say" states.
    """
    last = getattr(executor, "last_result", None)
    if last is not None and last.fail_class is not None:
        return f"{last.fail_class}: {last.detail}"
    return "no scores (a resource or channel failure)"


def _fail_class(exc: Exception, executor: object) -> str:
    """``type(exc).__name__`` — or the executor's own reported ``fail_class``
    when ``exc`` is a :class:`SandboxExecutionError` and that fail_class is
    more specific than the generic catch-all (see
    :data:`_GENERIC_SANDBOX_FAIL_CLASS`).

    Feature 7's own rule: *"The fail_class and detail that the executor
    reports are carried into NodeEvaluation.fail_class ... evaluate_node
    reads them from the executor's last result."*  Every other pipeline
    exception (a window, a cost, a metrics failure) is still named by its
    own class, unchanged — this only narrows the one generic bucket
    ``SandboxExecutionError`` already was.
    """
    if isinstance(exc, SandboxExecutionError):
        last = getattr(executor, "last_result", None)
        if (
            last is not None
            and last.fail_class is not None
            and last.fail_class != _GENERIC_SANDBOX_FAIL_CLASS
        ):
            return last.fail_class
    return type(exc).__name__


# -- Per-date scoring: a flat or thin date is absent, never a node failure -----


def _all_scores_identical(scores: Any) -> bool:
    """True exactly when :func:`evaluator.normalize_scores` would refuse
    ``scores`` as no-preference — ``std_rank == 0`` restated without calling
    it, so the only route to that specific refusal is a direct, narrow
    check rather than a catch of its exception class.

    Checked against the same three preconditions ``normalize_scores`` checks
    first (a Polars ``Series``, floating point, every value finite): any
    vector failing one of those is not "no preference", it is malformed in a
    way this function answers ``False`` for and leaves for
    ``normalize_scores`` itself to refuse, unabsorbed — the genuine
    malformation :func:`_score_rebalance_dates` must still let fail the
    whole node.
    """
    try:
        import polars as pl
    except ModuleNotFoundError:  # pragma: no cover - dependency is declared
        return False
    if not isinstance(scores, pl.Series) or not scores.dtype.is_float():
        return False
    if not scores.is_finite().all():
        return False
    return scores.n_unique() <= 1


def _score_rebalance_dates(
    execution: Any, node_id: str
) -> tuple[dict[dt.date, dict[str, float]], int]:
    """Normalize every rebalance date's raw scores; a date with no view is absent.

    Two conditions make a date unmeasurable rather than merely uninteresting,
    and both are treated the same way — ``scores[day] = {}``, never a
    fabricated zero — so the node is still evaluated over the dates that
    remain: a point-in-time universe holding fewer than two symbols (one
    symbol is not a cross-section), and every raw score on the date being
    identical (:func:`_all_scores_identical`, restating
    :func:`evaluator.normalize_scores`' own no-preference refusal — a
    warm-up day before a lookback fills, or a genuinely flat market day).
    Checked *before* calling ``normalize_scores`` rather than by catching its
    :class:`~evaluator.EvaluatorNormalizeError`, so a vector that is not a
    conforming Series of finite floats at all (which should never reach here
    — ``execute_signal`` already raised :class:`SandboxExecutionError` for
    any non-``conforming`` vector — but is not this function's invariant to
    trust blindly) still refuses the whole node through ``normalize_scores``'s
    own, unabsorbed exception rather than being silently treated as a flat
    date.

    Refuses with :class:`~evaluator.EvaluatorNormalizeError` — the same
    class, so the caller's pipeline ``try`` charges it like any other
    pipeline failure — when fewer than :data:`MIN_SCORED_DATES` dates end up
    scored *and at least one date was absent for the no-preference reason
    this function adds*: a signal that expresses a preference on a handful
    of cherry-picked days is not a measurable signal. The floor is scoped to
    that one new reason rather than to every thin date too, because a thin
    point-in-time universe is bug_spec_pit_universe.xml's own, already-settled
    territory (``test_pit_universe_per_date.py`` pins a node scored over as
    few as two non-thin dates succeeding), and widening its floor is not this
    bug's defect to fix.

    Answers ``(scores, flat_dates)`` — the per-date normalized scores and
    the total count of dates that ended up absent (thin or no-preference
    alike), the figure :attr:`NodeEvaluation.flat_dates` carries forward.
    """
    scores: dict[dt.date, dict[str, float]] = {}
    thin_dates = 0
    no_preference_dates = 0
    for day in execution.dates():
        vector = execution.vector(day)
        if len(vector.universe) < 2:
            scores[day] = {}
            thin_dates += 1
            continue
        if _all_scores_identical(vector.scores):
            scores[day] = {}
            no_preference_dates += 1
            continue
        normalized = normalize_scores(vector.scores).to_list()
        scores[day] = dict(zip(vector.universe, normalized))

    if no_preference_dates:
        total_dates = len(execution.dates())
        scored_dates = total_dates - thin_dates - no_preference_dates
        if scored_dates < MIN_SCORED_DATES:
            raise EvaluatorNormalizeError(
                f"cannot normalize node {node_id!r}: only {scored_dates} of "
                f"{total_dates} rebalance dates expressed a preference, "
                f"fewer than MIN_SCORED_DATES ({MIN_SCORED_DATES}); every "
                "raw score was identical, or the cross-section held fewer "
                "than two symbols, on the rest — the signal expressed no "
                "preference on enough dates to measure"
            )
    return scores, thin_dates + no_preference_dates


# -- The one call ---------------------------------------------------------------


def evaluate_node(
    node_id: str,
    campaign_id: str,
    depth: int,
    code: str,
    *,
    context: EvaluationContext,
    oracle: Oracle,
    ledger: object,
) -> NodeEvaluation:
    """Evaluate one live node end to end — feature 7's single call.

    Screens ``code``'s imports against the sandbox member's committed
    allowlist before anything else runs; a refusal is charged with
    ``fail_class="disallowed_import"`` and the code is never executed. Logs
    one ``WARNING`` line naming the node when ``context.sandbox_runtime`` is
    ``"unisolated"`` — the operator's own acknowledgement that model code
    runs on the host, restated at every evaluation rather than only at load.

    Then runs the evaluator chain :mod:`tests.e2e.test_momentum_signal_positive_ic`
    already proved, in its own order — ``resolve_window``, ``execute_signal``,
    ``normalize_scores``, ``align_targets``, ``gate_targets`` (with the
    caller's ``oracle``, an :class:`~orchestrator._oracle.SubtreeOracle` in
    production), ``apply_costs``, ``compute_node_metrics`` — and
    ``compute_marginal_ir`` against an empty book, which the evaluator
    refuses unconditionally; that refusal is caught narrowly and
    ``ir_marginal`` falls back to ``metrics.ir_standalone``, the number the
    evaluator's own refusal message names for "nothing to be marginal
    against yet" (see the module docstring). ``execute_signal`` is always
    handed :func:`orchestrator._context.signal_sandbox(context)
    <orchestrator._context.signal_sandbox>` as its ``sandbox`` — a
    :class:`~orchestrator._gvisor.GVisorSandbox` or a
    :class:`~orchestrator._hardened_sandbox.HardenedSubprocessSandbox`,
    never the evaluator's own unconfined default (additions_spec_gvisor_executor.xml,
    "Executor Selection", feature 7).

    Any exception the chain raises — the window, the signal, the oracle,
    the cost schedule, the metrics — is charged with
    :func:`orchestrator._charge.charge_failed_node` and named as
    ``fail_class`` by its class, and the node's metrics and persistence are
    both ``None``. Nothing is retried. The one exception to "named by its
    class": when a rebalance date's score vector is not conforming and the
    executor's own last :class:`~evaluator.SandboxResult` names a specific
    ``fail_class`` (``"timeout"``, ``"oom"``, ``"violation"``, ``"payload"``,
    ``"empty"``, or gVisor's own ``"sandbox_escape"``) rather than the
    generic ``"crash"``, that fail_class is what lands on ``NodeEvaluation``
    — read off the executor after the fact, because
    :class:`~evaluator.RawScoreVector` drops both ``fail_class`` and
    ``detail`` (see :func:`_fail_class`).

    On success, the node's row is written and its artifacts staged and
    flushed (see :func:`_persist`), the node is charged with
    :func:`orchestrator._charge.charge_node` under outcome ``"ok"``, and the
    answer carries the measured metrics, the score, the oracle's own
    ``charges_budget`` bit, ``fail_class=None``, the persistence and the
    debit.

    This function reads no node's null status, the sidecar key or any
    ``is_null`` value anywhere in its body; ``charges_budget`` on every
    returned :class:`NodeEvaluation` is either the conservative ``True`` a
    pre-oracle failure charges, or exactly the bit ``gate_targets``'s oracle
    answered.
    """
    if context.sandbox_runtime == "unisolated":
        _logger.warning("unisolated sandbox: evaluating node %s", node_id)

    decision = sandbox.sandbox_imports().screen(code)
    if not decision.admitted:
        failure = sandbox.DisallowedImportError(decision.detail)
        debited = charge_failed_node(
            node_id,
            campaign_id,
            failure,
            charges_budget=True,
            epoch_id=context.epoch_id,
            evaluator_hash=context.evaluator_hash,
            snapshot_hash=context.snapshot_hash,
            cost_model_hash=context.cost_model_hash,
            ledger=ledger,
        )
        return NodeEvaluation(
            node_id=node_id,
            metrics=None,
            score=ScoreRecord(fail_class=sandbox.DISALLOWED_IMPORT_CODE),
            charges_budget=True,
            fail_class=sandbox.DISALLOWED_IMPORT_CODE,
            persistence=None,
            debit=debited,
            fail_detail=str(failure)[:_FAIL_DETAIL_LIMIT],
        )

    executor = signal_sandbox(context)
    charges_budget = True
    try:
        decision_time = dt.datetime.combine(
            context.evaluation_dates[-1], _END_OF_DAY
        )
        resolution = resolve_window(context.snapshot, decision_time)
        execution = execute_signal(
            resolution,
            code,
            seed=context.seed,
            rebalance_dates=context.evaluation_dates,
            sandbox=executor,
            materialize=_materialize_from_context(context),
        )
        for day in execution.dates():
            vector = execution.vector(day)
            if not vector.conforming:
                raise SandboxExecutionError(
                    f"the sandbox did not return a conforming score vector "
                    f"for node {node_id!r} at {day.isoformat()}: "
                    f"{vector.problems or _executor_failure(executor)}"
                )

        scores, flat_dates = _score_rebalance_dates(execution, node_id)
        alignment = align_targets(execution, context.closes)
        gated = gate_targets(
            alignment, oracle, node_id=node_id, campaign_id=campaign_id, depth=depth
        )
        charges_budget = gated.charges_budget
        priced = apply_costs(
            gated,
            _cost_schedule_from_context(context),
            node_id=node_id,
            cost_model=context.cost_model,
        )
        metrics = compute_node_metrics(priced, scores)
        try:
            marginal = compute_marginal_ir(priced, {})
        except EvaluatorMarginalError:
            # Spec A has no resident book (spec B's campaign loop is what
            # builds one); the evaluator's own refusal names the honest
            # stand-in for "nothing to be marginal against yet".
            ir_marginal = metrics.ir_standalone
        else:  # pragma: no cover - unreachable while the book stays empty
            ir_marginal = marginal.ir_marginal
    except Exception as exc:  # noqa: BLE001 - every pipeline failure is charged, by name
        fail_class = _fail_class(exc, executor)
        fail_detail = str(exc)[:_FAIL_DETAIL_LIMIT]
        _logger.warning(
            "node %s failed (%s): %s", node_id, fail_class, fail_detail
        )
        debited = charge_failed_node(
            node_id,
            campaign_id,
            exc,
            charges_budget=charges_budget,
            epoch_id=context.epoch_id,
            evaluator_hash=context.evaluator_hash,
            snapshot_hash=context.snapshot_hash,
            cost_model_hash=context.cost_model_hash,
            ledger=ledger,
        )
        return NodeEvaluation(
            node_id=node_id,
            metrics=None,
            score=ScoreRecord(fail_class=fail_class),
            charges_budget=charges_budget,
            fail_class=fail_class,
            persistence=None,
            debit=debited,
            fail_detail=fail_detail,
        )

    cost_adjusted_ir = _cost_adjusted_ir(priced, metrics)
    persistence = _persist(
        node_id=node_id,
        campaign_id=campaign_id,
        code=code,
        context=context,
        returns=priced,
        metrics=metrics,
        ir_marginal=ir_marginal,
        cost_adjusted_ir=cost_adjusted_ir,
    )
    debited = charge_node(
        node_id,
        campaign_id,
        outcome="ok",
        charges_budget=charges_budget,
        epoch_id=context.epoch_id,
        evaluator_hash=context.evaluator_hash,
        snapshot_hash=context.snapshot_hash,
        cost_model_hash=context.cost_model_hash,
        ledger=ledger,
    )
    score = ScoreRecord(
        ic_mean=metrics.ic_mean,
        ic_tstat=metrics.ic_tstat,
        ir_standalone=metrics.ir_standalone,
        ir_marginal=ir_marginal,
        turnover=metrics.turnover,
        cost_adjusted_ir=cost_adjusted_ir,
        perturb_stability=None,
        fail_class=None,
    )
    return NodeEvaluation(
        node_id=node_id,
        metrics=metrics,
        score=score,
        charges_budget=charges_budget,
        fail_class=None,
        persistence=persistence,
        debit=debited,
        flat_dates=flat_dates,
    )
