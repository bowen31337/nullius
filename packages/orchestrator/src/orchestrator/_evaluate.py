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

import bisect
import datetime as dt
import json
import logging
import math
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import unquote, urlparse

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
from tripwires import (
    LABEL_PERMUTE_NAME,
    LOOKBACK_AXIS,
    SUBSAMPLE_AXIS,
    TIME_SHUFFLE_NAME,
    WINDOW_AXIS,
    poison_node,
    record_stability,
)

from ._artifact_writer import ArtifactStoreWriter
from ._charge import charge_failed_node, charge_node
from ._context import (
    BARS_STREAM,
    DEFAULT_MAX_HISTORY_DAYS,
    EvaluationContext,
    signal_sandbox,
)
from ._tree_writer import NodeMetricsWriter
from ._tripwire_step import NOT_MEASURED, PROBE_NAMES, TripwireOutcome, run_tripwires

__all__ = [
    "MIN_SCORED_DATES",
    "TRIPWIRES_GATE_DISCOVERY",
    "TRIPWIRE_VERDICT_TABLE",
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
#: empty-book stand-in), tripwires (10, :mod:`orchestrator._tripwire_step`'s
#: six-probe sweep) and debit_ledger (11).  Step 12 (the full feature-85
#: persist) is not reached by this spec.
_STEPS_COMPLETED: tuple[int, ...] = (7, 8, 9, 10, 11)

#: The three perturbation axes whose verdicts the tripwires member's own
#: :func:`tripwires.stability.record_stability` accepts — :data:`WINDOW_AXIS`,
#: :data:`SUBSAMPLE_AXIS` and :data:`LOOKBACK_AXIS` share the ``stability``/
#: ``stability_threshold`` field names that store checks structurally.  The
#: seed axis is deliberately absent: its verdict carries ``degradation``/
#: ``degradation_threshold`` instead (the tripwires member's own
#: one-provenance argument — see :mod:`orchestrator._tripwire_step`'s module
#: docstring), and ``record_stability`` refuses it by name.
_STABILITY_AXES: tuple[str, ...] = (WINDOW_AXIS, SUBSAMPLE_AXIS, LOOKBACK_AXIS)

#: The two probes whose verdict shape :func:`tripwires.poison.poison_node`
#: accepts — the ten-field ``surviving_sharpe``/``threshold`` shape
#: :class:`~tripwires.time_shuffle.TimeShuffleVerdict` and
#: :class:`~tripwires.label_permute.LabelPermuteVerdict` share.  The four
#: perturbation axes reject on a different comparison (``degradation`` or
#: ``stability`` against their own configured bar) and cannot be poisoned
#: through this seam — see :mod:`orchestrator._tripwire_step`'s module
#: docstring for why that is the tripwires member's own design rather than a
#: gap.
_POISONABLE_PROBES: tuple[str, ...] = (TIME_SHUFFLE_NAME, LABEL_PERMUTE_NAME)

#: Whether a step-10 rejection hard-fails a node — ``fail_class
#: "tripwire_fail"`` and feature 131's poisoning — rather than being merely
#: recorded and flagged.  ``False`` by default: bug_spec_tripwires_hard_fail
#: measured that the live pipeline's structural window clipping already
#: makes the lookahead the probes assume impossible for agent-authored code,
#: and that on real data an honest, persistent signal (20-day trailing
#: volatility) is rejected by five of the six probes — a hard fail at that
#: rate would cost real discoveries for little protection.  Every probe's
#: verdict is still persisted (:data:`TRIPWIRE_VERDICT_TABLE`) and the
#: rejecting ones are still named on :attr:`NodeEvaluation.tripwires_failed`
#: and logged, win or lose, so a rejection is never silent — only never, by
#: itself, a node failure.  A deployment that wants the old behaviour back
#: sets this ``True``.
TRIPWIRES_GATE_DISCOVERY: Final[bool] = False

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

    ``metrics`` and ``persistence`` are ``None`` on every failure path *but
    one* (the import screen's refusal, or anything the pipeline's own
    ``try`` caught): a node that was not measured has no metrics to carry
    and nothing was written for it.  The one exception is step 10's
    tripwire sweep (:mod:`orchestrator._tripwire_step`): under
    :data:`TRIPWIRES_GATE_DISCOVERY`'s default ``False`` a rejection there
    is recorded and flagged, never a node failure, so ``fail_class`` stays
    ``None`` and ``metrics``/``persistence`` are simply the measured,
    written values like any other success.  A deployment that sets
    :data:`TRIPWIRES_GATE_DISCOVERY` restores the old hard fail: a
    rejection happens *after* the metrics were measured, so ``fail_class``
    is ``"tripwire_fail"`` while ``metrics`` and ``persistence`` are still
    the real, written values — the evidence the spec's own sentence says
    must survive a leaking node.  ``score`` is always present — a
    :class:`signal_agent.ScoreRecord` whose six scalars are the measured
    values and whose ``fail_class`` is ``None`` on success, or whose six
    scalars are the absent measurement ``None`` and whose ``fail_class``
    names the failure (a gated tripwire_fail excepted, which carries the
    six measured scalars beside its own ``fail_class``).  ``debit`` is
    always present too: every evaluated node, failed ones included, is
    charged exactly once.
    """

    #: The node this answer is for.
    node_id: str
    #: Feature 80's four scalars plus the horizon and the per-date IC
    #: series, ``None`` on any failure before the metrics were measured —
    #: present on a gated ``tripwire_fail`` node too, since step 10 runs
    #: after step 8.
    metrics: NodeMetrics | None
    #: The score, in the shape a replay history reads (§14.1's ``score.json``).
    score: ScoreRecord
    #: The oracle's own bit — ``True`` until the oracle has answered (the
    #: conservative default), exactly what it answered afterward, win or fail.
    charges_budget: bool
    #: The failure's class name, the spec's own code word
    #: (``disallowed_import``) for a refused import screen, ``"tripwire_fail"``
    #: when step 10 rejected the node *and* :data:`TRIPWIRES_GATE_DISCOVERY`
    #: is set, or ``None`` on success — which, at the default ``False``, is
    #: what a step-10 rejection leaves this too (see :attr:`tripwires_failed`
    #: for what step 10 actually found).
    fail_class: str | None
    #: What was written for this node — ``None`` on any failure before the
    #: metrics were measured, present (row and artifacts both) on a gated
    #: ``tripwire_fail`` node.
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
    #: The probes, among :mod:`orchestrator._tripwire_step`'s
    #: ``PROBE_NAMES``, that rejected this node — in that fixed order,
    #: empty when none did and empty on every failure path the pipeline
    #: never reached step 10 on.  Every probe's own verdict is persisted
    #: too (:data:`TRIPWIRE_VERDICT_TABLE`); this is the subset step 10
    #: actually flagged.  Non-empty while ``fail_class`` is still ``None``
    #: is the common case at :data:`TRIPWIRES_GATE_DISCOVERY`'s default —
    #: a rejection recorded and flagged, not a node failure.
    tripwires_failed: tuple[str, ...] = ()


# -- The materialize seam: reading the sealed mount for execute_signal ----------


#: One bars panel per (mount, symbol, admitted set), shared by every node and
#: every rebalance date of a process. The window used to be rebuilt per date
#: by looping over every partition of every symbol and concatenating one-row
#: tables: about 37M Python iterations per node on the 2019-2026 archive
#: (about 50 min per node, GIL-bound, so threads did not help). A panel now
#: grows only up to the decision date being materialized: each partition is
#: read once, never ahead of the day it serves (the no-look-ahead read
#: invariant), and each date takes a bisect slice of one contiguous table.
#: The entry holds the mount itself, so a recycled id() can never serve
#: another mount's rows.
_PANELS: dict[tuple[int, str, int, str], dict[str, Any]] = {}
_PANELS_LOCK = threading.Lock()


def _symbol_panel(
    mount: Any, resolution: Any, symbol: str, decision_date: dt.date
) -> tuple[list[dt.date], Any]:
    """``(row dates, table)`` for one symbol's bars, read up to ``decision_date``.

    Covers every partition ``resolution`` admits for the symbol that is dated
    at or before ``decision_date``, oldest first. The table is ``None`` when
    none is. Partitions are read on demand, so a later date extends the panel
    rather than rereading it.
    """
    admitted = tuple(resolution.dates(BARS_STREAM, symbol))
    # The admitted set is part of the key: a resolution at a later decision
    # time admits more partitions and must not reuse a shorter panel.
    key = (id(mount), symbol, len(admitted), max(admitted) if admitted else "")
    with _PANELS_LOCK:
        entry = _PANELS.get(key)
        if entry is None or entry["mount"] is not mount:
            entry = {
                "mount": mount,
                "pending": sorted(admitted),
                "days": [],
                "table": None,
            }
            _PANELS[key] = entry
        pending: list[str] = entry["pending"]
        due = 0
        while due < len(pending) and dt.date.fromisoformat(pending[due]) <= decision_date:
            due += 1
        if due:
            import pyarrow as pa
            import pyarrow.parquet as pq

            fresh: list[Any] = []
            for iso in pending[:due]:
                paths = list(mount.select(BARS_STREAM, symbol, iso))
                if not paths:
                    continue
                table = pq.read_table(str(paths[0]))
                if table.num_rows == 0:
                    continue
                entry["days"].extend([dt.date.fromisoformat(iso)] * table.num_rows)
                fresh.append(table)
            del pending[:due]
            if fresh:
                parts = ([entry["table"]] if entry["table"] is not None else []) + fresh
                # One contiguous chunk per symbol: each partition is a
                # one-row table, and a panel left as ~1,600 chunks made every
                # later compute call pay per-chunk overhead (0.79 s for one
                # 22k-row filter).
                entry["table"] = pa.concat_tables(parts).combine_chunks()
        return entry["days"], entry["table"]


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
    drift apart.  Only the partitions that per-date universe names, dated
    in ``(decision_date - context.max_history_days, decision_date]``, are
    read through the mount's own ``select`` — bug_spec_evaluation_throughput.xml's
    own bound on a window's depth, applied after the point-in-time universe
    rule rather than in place of it, so a 2026 date on a multi-year archive
    pays for :attr:`~orchestrator._context.EvaluationContext.max_history_days`
    trailing days per symbol rather than the snapshot's entire history, and
    an early date whose own history is shorter than that still carries
    everything it has.  The same read-only handle and the same sealedness
    back every score this evaluation computes, and a symbol not yet listed
    (or already delisted, or truncated out of range) on a given date is
    never read for it.  A small per-partition cache keeps one evaluation
    from re-reading the same compressed bytes twice across rebalance dates.
    """
    mount = context.snapshot
    # getattr, not context.max_history_days: a few tests hand this function a
    # bare duck-typed context carrying only ``snapshot`` (the production
    # EvaluationContext always has the field, defaulted), and those callers
    # mean "no cap beyond this suite's own tiny history", which the default
    # depth already is for them.
    max_history_days = getattr(context, "max_history_days", DEFAULT_MAX_HISTORY_DAYS)

    def materialize(resolution: Any, decision_time: dt.datetime) -> Any:
        import pyarrow as pa
        import pyarrow.compute as pc
        from contract.bars import bars_frame_name
        from contract.window import MarketWindow

        decision_date = decision_time.date()
        earliest_date = decision_date - dt.timedelta(days=max_history_days)
        universe = pit_universe(resolution, decision_date)
        tables: list[Any] = []
        for symbol in universe:
            days, table = _symbol_panel(mount, resolution, symbol, decision_date)
            if table is None:
                continue
            # Rows dated in (earliest_date, decision_date], the same
            # partitions the per-partition loop used to select.
            lo = bisect.bisect_right(days, earliest_date)
            hi = bisect.bisect_right(days, decision_date)
            if hi > lo:
                tables.append(table.slice(lo, hi - lo))
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
    """The mean post-cost edge of the node's own dollar-neutral book.

    The same figure :mod:`evaluator._persist_store` assembles onto a node
    row: the mean of :attr:`NodeMetrics.book_returns`, the per-date
    signal-weighted (``w_i = z_i / Σ|z_j|``) book returns ``ir_standalone``
    reduces from. It is restated here because that module's helper is private
    and this spec writes the row directly rather than through
    ``evaluator.persist_node``. It is never the panel's equal-weight mean,
    which is the market every node on one snapshot shares. ``returns`` is
    kept for the call shape. ``metrics`` is the record ``compute_node_metrics``
    just measured, so its book is never empty.
    """
    book = metrics.book_returns
    if not book:
        raise RuntimeError(
            "compute_node_metrics measured a metrics record with no per-date "
            "book returns; a fresh measurement always carries them, so "
            "finding none here is an invariant this module relies on having "
            "broken"
        )
    return math.fsum(book.values()) / len(book)


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
    perturb_stability: float | None = None,
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

    ``perturb_stability`` is the lookback-jitter tripwire's own figure
    (:mod:`orchestrator._tripwire_step`), or ``None`` when step 10's
    rejection gated the node into a tripwire failure
    (:data:`TRIPWIRES_GATE_DISCOVERY`) or that axis could not measure; it is
    handed straight to
    :class:`_TreeNodeRow`, whose writer already knows a ``None`` there
    means *not measured by this step* and leaves the column untouched
    (see :mod:`orchestrator._tree_writer`).
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
            perturb_stability=perturb_stability,
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


# -- Step 10: the tripwire sweep's own figures, and feature 131's poisoning -----


def _tripwire_figure(outcome: TripwireOutcome, name: str) -> float | None:
    """One probe's own figure, for naming in a tripwire failure's detail.

    The two independent probes (time-shuffle, label-permute) report their
    surviving Sharpe; the four perturbation axes report
    :attr:`TripwireOutcome.axis_figures`' own entry.  ``None`` when the named
    probe could not measure.
    """
    if name in (TIME_SHUFFLE_NAME, LABEL_PERMUTE_NAME):
        verdict = outcome.verdicts[name]
        return None if verdict is NOT_MEASURED else verdict.surviving_sharpe
    return outcome.axis_figures[name]


def _tripwire_fail_detail(outcome: TripwireOutcome) -> str:
    """``fail_detail``'s text for a tripwire rejection — the failing probes
    and their figures, in :attr:`TripwireOutcome.failed`'s own fixed order.
    """
    named = ", ".join(
        f"{name}={_tripwire_figure(outcome, name)!r}" for name in outcome.failed
    )
    return f"tripwire_fail: {named}"


def _poison_tripwire_failure(outcome: TripwireOutcome, *, database_url: str) -> None:
    """Poison the node and its subtree for a step-10 rejection — feature 131.

    :func:`tripwires.poison.poison_node` only accepts the time-shuffle or
    label-permute verdict shape (see :mod:`orchestrator._tripwire_step`'s
    module docstring for why the four perturbation axes cannot be poisoned
    through this seam); this poisons on whichever of those two rejected,
    preferring time-shuffle when both did.  Logs a warning, rather than
    poisoning nothing silently, for the residual case where only a
    perturbation axis rejected and neither poisonable probe did.
    """
    for name in _POISONABLE_PROBES:
        if name in outcome.failed:
            poison_node(outcome.verdicts[name], database_url=database_url)
            return
    _logger.warning(
        "tripwire_fail with no poisonable probe among %s; feature 131's "
        "poisoning needs a time-shuffle or label-permute rejection and "
        "neither fired",
        outcome.failed,
    )


#: The table step 10's six-probe sweep persists one row to per probe, per
#: node — created if absent and refreshed (never duplicated) on a
#: re-evaluation, keyed by ``(node_id, probe)``.  Written identically for a
#: null node and a real one: neither this module nor
#: :func:`orchestrator._tripwire_step.run_tripwires` reads any null status.
TRIPWIRE_VERDICT_TABLE: Final[str] = "tripwire_verdict"

_TRIPWIRE_VERDICT_SCHEMA = (
    f"CREATE TABLE IF NOT EXISTS {TRIPWIRE_VERDICT_TABLE} ("
    "node_id TEXT NOT NULL, "
    "probe TEXT NOT NULL, "
    "rejected INTEGER NOT NULL, "
    "figure REAL, "
    "measured INTEGER NOT NULL, "
    "recorded_at TEXT NOT NULL, "
    "PRIMARY KEY (node_id, probe)"
    ")"
)


def _tripwire_sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The same translation every store in this workspace restates rather than
    imports (:mod:`orchestrator.closeout`'s own ``_sqlite_path`` states the
    identical grammar for the identical reason) — this is the one table this
    module writes to directly, beside the injected writers it uses for
    everything else.
    """
    parsed = urlparse(database_url)
    return Path(unquote(parsed.path).removeprefix("/"))


def _persist_tripwire_verdicts(
    outcome: TripwireOutcome, *, node_id: str, database_url: str
) -> None:
    """Persist every one of step 10's six probe outcomes for ``node_id``.

    One row per probe (:data:`TRIPWIRE_VERDICT_TABLE`, created if absent),
    upserted on ``(node_id, probe)`` so a re-evaluation refreshes rather
    than accumulates a second row.  A probe that could not measure is
    recorded with ``measured=0`` and ``rejected=0`` rather than being left
    out, so the row set always names all six probes
    (:data:`orchestrator._tripwire_step.PROBE_NAMES`).  Runs after every
    evaluation step 10 reaches, whether or not :data:`TRIPWIRES_GATE_DISCOVERY`
    goes on to turn a rejection into a node failure — the record is the same
    either way.
    """
    recorded_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    rows = []
    for name in PROBE_NAMES:
        verdict = outcome.verdicts[name]
        measured = verdict is not NOT_MEASURED
        rejected = bool(measured and verdict.rejected)
        rows.append(
            (
                node_id,
                name,
                int(rejected),
                _tripwire_figure(outcome, name),
                int(measured),
                recorded_at,
            )
        )
    path = _tripwire_sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute(_TRIPWIRE_VERDICT_SCHEMA)
        connection.executemany(
            f"INSERT INTO {TRIPWIRE_VERDICT_TABLE} "
            "(node_id, probe, rejected, figure, measured, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(node_id, probe) DO UPDATE SET "
            "rejected = excluded.rejected, "
            "figure = excluded.figure, "
            "measured = excluded.measured, "
            "recorded_at = excluded.recorded_at",
            rows,
        )


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

    Once the metrics are measured, :func:`orchestrator._tripwire_step.run_tripwires`
    runs step 10's six leakage probes over the same normalized scores and the
    post-cost target bundle at the metrics horizon — the exact panel a null
    node and a real node are scored on alike.  Every probe's own verdict is
    persisted, one row per probe, in :data:`TRIPWIRE_VERDICT_TABLE` — created
    if absent and refreshed on a re-evaluation, identically for a null node
    and a real one — and the probes that rejected are named, in their fixed
    order, on the answered ``NodeEvaluation.tripwires_failed``.  A probe that
    could not measure (too thin a panel, a statistic with zero dispersion)
    is recorded as such and never counted among the rejections.  When any
    probe rejected, one ``WARNING`` line is logged naming them.

    What a rejection does to the node depends on :data:`TRIPWIRES_GATE_DISCOVERY`,
    ``False`` by default (see that constant's own docstring for the
    false-positive rate on real data that made it so).  At the default, a
    rejection changes nothing else: the node's row and artifacts are
    written, ``fail_class`` stays ``None``, and the node is charged
    ``outcome="ok"`` — the rejection is recorded and flagged, not a node
    failure. With the constant set, the old hard fail applies: the node's
    row and artifacts are still written (the evidence survives), feature
    131's poisoning is applied to the node and its subtree through
    whichever of the time-shuffle or label-permute verdicts itself
    rejected, and the node is charged ``outcome="tripwire_fail"`` rather
    than failed — step 10 ran to completion and the caller holds its
    answer, which :func:`orchestrator._charge.charge_node`'s own docstring
    states is exactly when the outcome is *stated*, not classified.
    Either way, when the node is not gated into a tripwire failure, the
    lookback-jitter axis' figure is written onto the node's row as
    ``perturb_stability`` and the window, universe-subsample and
    lookback-jitter axes' figures are persisted through
    :func:`tripwires.stability.record_stability` (the seed axis is not: see
    :mod:`orchestrator._tripwire_step`'s module docstring for why that is
    the tripwires member's own design).

    On success, the node's row is written and its artifacts staged and
    flushed (see :func:`_persist`), the node is charged with
    :func:`orchestrator._charge.charge_node` under outcome ``"ok"`` (or
    ``"tripwire_fail"``, per the paragraph above), and the answer carries
    the measured metrics, the score, the oracle's own ``charges_budget``
    bit, ``fail_class`` (``None`` or ``"tripwire_fail"``), the persistence
    and the debit.

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
        tripwire_outcome = run_tripwires(
            scores,
            {metrics.horizon: priced.series[metrics.horizon].values},
            node_id=node_id,
        )
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

    _persist_tripwire_verdicts(
        tripwire_outcome, node_id=node_id, database_url=context.database_url
    )
    if tripwire_outcome.failed:
        _logger.warning(
            "node %s flagged by step 10's tripwires: %s",
            node_id,
            ", ".join(tripwire_outcome.failed),
        )

    gated_tripwire_fail = TRIPWIRES_GATE_DISCOVERY and bool(tripwire_outcome.failed)
    if gated_tripwire_fail:
        fail_class: str | None = "tripwire_fail"
        fail_detail: str | None = _tripwire_fail_detail(tripwire_outcome)[
            :_FAIL_DETAIL_LIMIT
        ]
        perturb_stability = None
    else:
        fail_class = None
        fail_detail = None
        perturb_stability = tripwire_outcome.perturb_stability
        for axis in _STABILITY_AXES:
            verdict = tripwire_outcome.verdicts[axis]
            if verdict is not NOT_MEASURED:
                record_stability(verdict, database_url=context.database_url)

    persistence = _persist(
        node_id=node_id,
        campaign_id=campaign_id,
        code=code,
        context=context,
        returns=priced,
        metrics=metrics,
        ir_marginal=ir_marginal,
        cost_adjusted_ir=cost_adjusted_ir,
        perturb_stability=perturb_stability,
    )

    if gated_tripwire_fail:
        _poison_tripwire_failure(tripwire_outcome, database_url=context.database_url)

    debited = charge_node(
        node_id,
        campaign_id,
        outcome="tripwire_fail" if gated_tripwire_fail else "ok",
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
        perturb_stability=perturb_stability,
        fail_class=fail_class,
    )
    return NodeEvaluation(
        node_id=node_id,
        metrics=metrics,
        score=score,
        charges_budget=charges_budget,
        fail_class=fail_class,
        persistence=persistence,
        debit=debited,
        fail_detail=fail_detail,
        flat_dates=flat_dates,
        tripwires_failed=tripwire_outcome.failed,
    )
