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

**``ir_tstat`` is the post-cost IR t-statistic, computed once beside
``cost_adjusted_ir``.**  additions_spec_cost_aware_selection.xml, "Cost-Aware
Selection", feature 1: ``ir_standalone · √dates`` — the same standardization
``ic_tstat`` already applies to ``ic_mean``, taken over the node's own
post-cost book instead of the per-date IC series.  Computed from exactly the
``metrics`` this module already measured (never a second pass over the
panel), carried on :class:`NodeEvaluation.score` and the node row beside
``ic_tstat`` (:mod:`orchestrator._tree_writer` upgrades a pre-existing
``node`` table with the column by probe-then-``ALTER``, since ``0114``
shipped before this feature existed), and left ``None`` on every failure
path the same way every other metric is — never written, because
:func:`_persist` is never reached before ``metrics`` exists.

**The configured book construction is what both ``compute_node_metrics``
calls measure against.**  additions_spec_research_book_v2.xml feature 2:
when ``context.book.beta_neutral`` is set, :func:`orchestrator._context.compute_betas`
answers this evaluation's point-in-time per-date betas from
``context.closes`` — never a row after the date being scored — and both
``evaluate_node`` and ``evaluate_on_dates`` hand them to every
``compute_node_metrics`` call they make, the net figure and
:func:`_gross_ir_tstat`'s gross diagnostic alike, so neither figure is
silently measured against a different book from the other.  ``None`` when
the block is absent or ``beta_neutral`` is false, which reproduces every
figure exactly as this module measured them before the book carried an
opinion.  The same holds for the book's *weighting*: when
``context.book.weighting`` is ``"inverse_vol"``,
:func:`orchestrator._context.compute_vols` answers this evaluation's
point-in-time per-date realised volatilities from the same ``closes``, and
both chains hand them to the same two calls as ``vols=`` — one key in the
evaluation config switches the whole engine to volatility-scaled books.
With ``"z"`` (the default, key absent or spelled ``"z"``) ``vols`` stays
``None`` and every figure is unchanged.

A third spelling, ``"tail_decile"``, needs no side panel at all: the book
is a function of each date's scores alone, so ``vols`` stays ``None`` (the
same ``INVERSE_VOL_WEIGHTING`` branch guarding it), and every call below
hands ``weighting=context.book.weighting`` through unchanged.  The fourth
spelling, ``"short_tail"`` (additions_spec_short_tail_book.xml), is guarded
the same way: no side panel, no ``vols``, the string passed straight
through.  The
weighting is carried on the call rather than folded into the panel, so the
net figure, :func:`_gross_ir_tstat`'s gross diagnostic and the out-of-sample
chain (``evaluate_on_dates``) all measure the *same* book the config named —
a weighting applied to only one of the three would report a fee, an IC or an
OOS t-statistic for a portfolio the campaign never configured.  ``betas``
still composes afterwards, inside
:func:`evaluator.book_weights`, so a tail-decile or short-tail book can be
beta-neutral too: the two knobs are independent, exactly as ``beta_neutral``
and ``weighting`` already are for the other two weightings.

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
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
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
    RawScoreVector,
    SignalExecution,
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
    INVERSE_VOL_WEIGHTING,
    PERP_INSTRUMENT,
    Z_WEIGHTING,
    EvaluationContext,
    compute_betas,
    compute_vols,
    signal_sandbox,
)
from ._tree_writer import NodeMetricsWriter
from ._tripwire_step import NOT_MEASURED, PROBE_NAMES, TripwireOutcome, run_tripwires

__all__ = [
    "MIN_SCORED_DATES",
    "TRIPWIRES_GATE_DISCOVERY",
    "TRIPWIRE_VERDICT_TABLE",
    "NodeEvaluation",
    "NodeIdentityError",
    "NodePersistence",
    "SandboxExecutionError",
    "evaluate_node",
    "evaluate_on_dates",
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


class NodeIdentityError(Exception):
    """A stored node's own ``campaign_id`` and ``depth`` could not be read.

    :func:`evaluate_on_dates` asks the same oracle an in-sample evaluation
    asked, and :func:`evaluator.gate_targets` builds that ask from the
    node's own campaign and depth — the identity a Type-D oracle resolves
    its flip on, and the campaign the sidecar's sealed assignment is scoped
    to.  Unlike :func:`evaluate_node`, ``evaluate_on_dates`` is handed only
    a node id: an out-of-sample evaluation runs over a node that is already
    stored, so its row is where both facts are read from, never supplied by
    the caller.  Raised when the tree holds no such row.
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
    #: Diagnostic only, never persisted: ir_tstat recomputed with
    #: cost_per_unit_traded=0.0 over the same priced panel and scores --
    #: what score's own ir_tstat would have read before the venue fee was
    #: wired into the book.  None on every failure path, since there is no
    #: panel to recompute a gross figure from.
    ir_tstat_gross: float | None = None
    #: How many ``(date, symbol)`` pairs :func:`_drop_unpriced_symbols`
    #: dropped from the score vector before alignment, because the symbol
    #: had no perp close at that date — ``context.instrument == "perp"``
    #: only; always ``0`` for the spot default and on every failure path.
    #: A fail_detail-free diagnostic, the same shape :attr:`flat_dates`
    #: already takes: dropped, never zero-filled, and never itself a node
    #: failure.
    dropped_perp_symbols: int = 0


# -- The materialize seam: reading the sealed mount for execute_signal ----------


#: The three derivative streams sliced beside bars (:data:`evaluator.SLICED_STREAMS`),
#: named locally because this is the one module that reads each by name to
#: build its own feature frame — not a shared constant another member needs.
FUNDING_STREAM: Final[str] = "funding"
FUTBARS_STREAM: Final[str] = "futbars"
METRICS_STREAM: Final[str] = "metrics"

#: ``feature:funding_1d:v1``'s own columns beyond ``symbol``/``open_time``,
#: in the order :mod:`nullius_ingest.derivs_backfill` writes them to the
#: ``funding`` stream — the order the spec's own sentence names them in.
_FUNDING_FIELDS: Final[tuple[str, ...]] = (
    "funding_rate_sum",
    "funding_rate_last",
    "n_settlements",
)

#: ``feature:metrics_1d:v1``'s own columns beyond ``symbol``/``open_time``,
#: in the order :mod:`nullius_ingest.derivs_backfill` writes them to the
#: ``metrics`` stream — every one a verbatim string, like every other
#: observed-stream column this evaluator serves.
_METRICS_FIELDS: Final[tuple[str, ...]] = (
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
)


def _day_part_paths(
    mount: Any, stream: str, symbols: Sequence[str], day: dt.date
) -> tuple[list[str], list[str]]:
    """One day's part paths for ``symbols``, as ``(paths, symbols present)``.

    One partition lookup per (symbol, day) — the two lists stay parallel, so
    the *n*-th path is the *n*-th present symbol.  Where the mount offers
    :meth:`~snapshot.SnapshotMount.part_path` — the path-only accessor added
    beside ``select`` — that is what is called: the lake writes exactly one
    ``part-0.parquet`` per symbol-day (``nullius_ingest.bars_backfill``) at
    the Hive path the mount already knows, so the day's part is *derived*
    from the ``(stream, symbol, date)`` triple instead of read off the
    directory, which is three ``is_dir`` probes rather than a ``scandir``
    plus a sort for every symbol-day.  On the wide snapshot that listing was
    1.8 s of a 14 s date.  A mount without the accessor (the PIT suite's own
    counting proxy, a hand-rolled mount in a test) keeps the previous
    ``select`` read — the same answer, just listed.

    A symbol with no partition that day contributes no path, exactly as the
    per-partition loop skipped it.  The first part of the day's directory is
    the one taken, matching the per-partition loop this replaces, which read
    ``paths[0]``; should a day ever carry several, the previous path's own
    choice is kept rather than a new union of files the frames have never
    seen.
    """
    part_path = getattr(mount, "part_path", None)
    iso = day.isoformat()
    paths: list[str] = []
    present: list[str] = []
    for symbol in symbols:
        parts = (
            part_path(stream, symbol, iso)
            if part_path is not None
            else mount.select(stream, symbol, iso)
        )
        if parts:
            paths.append(str(parts[0]))
            present.append(symbol)
    return paths, present


def _read_day_parts(
    paths: Sequence[str], symbols: Sequence[str]
) -> dict[str, Any]:
    """One day's parts for many symbols, read in a single pyarrow call.

    Answers ``{symbol: one table}`` — each symbol's own rows, in ``paths``
    order, carrying the columns and dtypes of the file it came from.  This
    is the batching half of the fix: the previous path made one
    ``read_table`` per (date, symbol, day) — 1,385,448 of them on the
    239-symbol wide snapshot — and the forward-growing cache that replaced
    it still made one per (stream, symbol) per date, 629 of the 14 s a date
    cost.  A whole day's parts for every symbol of the universe go to one
    :func:`pyarrow.parquet.read_table`.

    pyarrow answers a multi-path read with one chunk per file (verified:
    each file contributes exactly one chunk, an empty file contributing a
    zero-length one), so chunk *i* is the rows of ``paths[i]`` and a
    per-symbol table is the slice covering that chunk.  A file carrying
    several row groups would break that one-chunk-per-file correspondence,
    so the chunk count is checked and a mismatch falls back to reading the
    parts one at a time — the old behaviour, kept as the correctness floor
    rather than assumed away.

    ``partitioning=None`` is load-bearing.  The lake's paths are Hive-shaped
    (``symbol=…/date=…/part-0.parquet``), so pyarrow's dataset inference
    reads the directory names as partition keys — and the file already
    carries its own ``symbol`` column, so the inferred dictionary-typed
    partition column collides with the file's string column and the read
    fails with *"Unable to merge: Field symbol has incompatible types"*.
    Disabling inference makes the call a plain concatenation of the named
    files: the file's own columns, nothing synthesised from the path.
    """
    import pyarrow.parquet as pq

    if not paths:
        return {}

    table = pq.read_table(list(paths), partitioning=None)
    chunks = table.column(0).num_chunks if table.num_columns else 0
    if chunks != len(paths):
        # Not one chunk per file (a part with several row groups), so the
        # chunk boundary no longer names a file.  Read each part on its
        # own — the previous path — so each symbol's rows stay exact.
        return {
            symbol: pq.read_table(path, partitioning=None)
            for path, symbol in zip(paths, symbols)
        }

    out: dict[str, Any] = {}
    start = 0
    for chunk, symbol in zip(table.column(0).chunks, symbols):
        length = len(chunk)
        out[symbol] = table.slice(start, length)
        start += length
    return out


class _PanelCache:
    """One process's per-(stream, symbol) partition tables, grown forward.

    ``execute_signal`` calls ``materialize`` once per rebalance date and each
    call asks for every symbol's trailing window under every sealed stream.
    Adjacent dates share almost all of those files, so a per-date read is the
    same bytes paid for again: on the 239-symbol wide snapshot one 60-date
    out-of-sample evaluation made 1,385,448 ``read_table`` calls and took
    3.5-27 minutes, essentially all of it outside the sandbox.

    This cache keeps one table per ``(stream, symbol)`` and **grows it
    forward only**: materializing day ``D`` reads the partitions the
    resolution admits for that symbol whose own ``date=`` is at or before
    ``D`` and that have not been read yet, and appends them to the symbol's
    table; the day's window is then a bisect slice of the grown table.  Each
    date's window is exactly the slice the per-partition loop used to
    assemble, so the row order, columns, dtypes, truncation and renaming that
    reach the sandbox are byte-identical to the previous path.

    **Growing forward is what keeps the read point-in-time, and it is why
    this cache cannot read a symbol's whole partition table on first
    access.**  A one-pass read of the symbol's table reads partitions dated
    *after* the day being materialized, which is future data crossing into an
    evaluation that must not see it — and it needs the symbol's whole
    partition listing to do it.  Reading only the partitions due for the day
    in hand, through the same per-partition path lookups the pre-cache path
    made (never ``mount.partitions()``/``mount.dates()``), keeps every read
    dated at or before the day it serves.  Because ``execute_signal`` walks a
    rebalance grid in increasing order, each partition is read at most once —
    the ``_read`` set below is what enforces that, and the window's own lower
    bound is what keeps the reads to the partitions a window needs rather
    than a symbol's whole history.

    **One day's reads are batched, and each symbol's table is kept in one
    chunk.**  The forward-growing path this replaces still made one
    ``read_table`` per (stream, symbol) per date — 629 of them, 1.0 s, on the
    wide snapshot, on top of 1.8 s of ``mount.select`` directory listings.
    Here a date's whole due set for a stream is resolved to part paths
    through :func:`_day_part_paths` (three ``is_dir`` probes per symbol-day,
    no listing) and read in one :func:`_read_day_parts` call.  Each symbol's
    table is then ``concat_tables([prior, new]).combine_chunks()``: pyarrow
    charges per *chunk* on every later ``filter``/``sort_by``, so a table
    left as one chunk per appended day (631 of them after a 400-day window)
    made the day's frame building the single largest host cost — 5.1 s of a
    14 s date, in ``_truncate`` alone.  Re-combining the symbol's whole table
    on append is a rewrite of that symbol's history, but it is a rewrite of
    *one symbol* (0.008 ms for 400 rows) against a filter that is otherwise
    paid per chunk, per symbol, per date, per stream.

    The cache is **process-lifetime**, not call-lifetime, because the cost
    the fix is for is a campaign node, and a worker process evaluates many
    nodes over the same sealed snapshot.  It lives in the module-level
    registry :data:`_PANELS` — bounded to a handful of snapshots, with a
    snapshot-less (rootless) context keyed on the mount object's identity —
    and is cleared by :func:`reset_panel_caches` between tests.  Sharing
    tables across calls is safe because a cached table is only ever an
    *exact* earlier call's read, and every call slices to its own
    ``decision_date``:

    * the tables never grow past the latest day any call in this process has
      materialized — ``grow_day`` reads only days ``<= decision_date`` — and
      once this process has materialized day ``D`` the tables hold the bytes
      every call for a day ``<= D`` is entitled to; a later call for an
      *earlier* day still slices at its own ``decision_date`` and so sees no
      row dated after its day;
    * a cached table is not a read.  The point-in-time rule the tests hold is
      about what a given ``materialize`` call reads off the sealed mount, and
      a table a previous call already read is not re-read — the same
      per-(stream, symbol) sharing the call-lifetime cache already did
      between two dates of one grid, extended across the calls of one
      process;
    * a snapshot is sealed and read-only, so the bytes under a
      ``snapshot_hash`` never change; two contexts over the same hash would
      share identical tables, and this cache is only ever fed by the mount
      that built it.

    ``resolution`` is the resolution the evaluation resolved once; the
    admitted dates it names are the panel's own dates, so the no-look-ahead
    invariant is unchanged — the panel holds partitions dated at or before
    the day being materialized, and every per-date slice is cut at that
    date's own ``earliest_date``/``decision_date`` boundary.
    """

    __slots__ = ("_days", "_lock", "_mount", "_read", "_resolution", "_tables")

    def __init__(self, mount: Any, resolution: Any) -> None:
        self._mount = mount
        self._resolution = resolution
        self._tables: dict[tuple[str, str], Any] = {}
        self._days: dict[tuple[str, str], list[dt.date]] = {}
        #: The days already read for each (stream, symbol) — the same set the
        #: pre-cache ``_symbol_panel`` kept as its ``pending`` list, so a
        #: partition is never read twice and never read ahead of its day.
        self._read: dict[tuple[str, str], frozenset[dt.date]] = {}
        #: One cache is shared by every evaluation this process runs over the
        #: snapshot (:data:`_PANELS`), and ``evaluation_mode: "thread"`` — and
        #: ``_evaluate_roots_concurrently``'s own thread pool — runs several
        #: of them at once.  "Has this day been read yet?" is a check-then-act:
        #: without this lock two threads both see a day unread, both read it
        #: (a partition read twice) and both append it (its rows duplicated
        #: in the frame), which is exactly what the PIT and byte-identical
        #: assertions forbid.  Holding it across the whole grow serializes
        #: the reads — the point of the cache is that a day is read once per
        #: process, and a second thread arriving at the same day should wait
        #: for that read rather than repeat it.
        self._lock = threading.Lock()

    def grow_day(
        self,
        stream: str,
        symbols: Sequence[str],
        earliest_date: dt.date,
        decision_date: dt.date,
    ) -> None:
        """Read ``symbols``' owed days for this window, one batched call per day.

        The days due are every admitted day of ``(earliest_date,
        decision_date]`` any of ``symbols`` has not read yet — ``earliest_date``
        is the window's own lower bound, so a first date reaching back
        ``max_history_days`` reads that many trailing days, never the symbol's
        whole history before it, and a gap in a grid costs nothing between
        the two dates that straddle it.  On any date but a grid's first, the
        only day still unread in that span is the day in hand, so this is one
        :func:`_read_day_parts` call per stream for the whole universe; on the
        first it is one per stream per trailing day.

        Every read is dated at or before ``decision_date`` — nothing ahead of
        its day — and a day already in a symbol's ``_read`` set is skipped, so
        nothing is read twice.  The resolution's own admitted dates are the
        only day source, never a ``mount.dates()`` listing.

        The whole read-and-append runs under :attr:`_lock`, because the
        registry hands this one cache to every evaluation the process runs
        and ``evaluation_mode: "thread"`` runs several at once (see
        :attr:`_lock`): the "not yet read" test and the read it guards have to
        be one step, or two threads both read a day and both append it.
        """
        with self._lock:
            # Inside the lock, like the swap that replaces it (:func:`_panel_cache`):
            # the admitted set is read off the resolution a sibling evaluation
            # may be widening, and a half-adopted view of it would drop days.
            admitted = {
                symbol: {
                    dt.date.fromisoformat(iso)
                    for iso in self._resolution.dates(stream, symbol)
                }
                for symbol in symbols
            }
            already = {
                symbol: self._read.get((stream, symbol), frozenset())
                for symbol in symbols
            }
            due: set[dt.date] = set()
            for symbol in symbols:
                due.update(
                    day
                    for day in admitted[symbol]
                    if earliest_date < day <= decision_date
                    and day not in already[symbol]
                )
            for day in sorted(due):
                pending = [
                    symbol
                    for symbol in symbols
                    if day in admitted[symbol] and day not in already[symbol]
                ]
                if not pending:
                    continue
                for symbol in pending:
                    self._read[(stream, symbol)] = self._read.get(
                        (stream, symbol), frozenset()
                    ) | {day}
                paths, present = _day_part_paths(self._mount, stream, pending, day)
                tables = _read_day_parts(paths, present)
                for symbol in present:
                    table = tables[symbol]
                    if table.num_rows == 0:
                        continue
                    self._append((stream, symbol), table, [day] * table.num_rows)

    def window(
        self, stream: str, symbol: str, earliest_date: dt.date, decision_date: dt.date
    ) -> Any:
        """One symbol's window under ``stream``, sliced from the grown table.

        Covers the panel rows dated in ``(earliest_date, decision_date]`` —
        the identical range, in the identical order, the per-partition loop
        selected.  ``None`` when the panel is absent or the slice is empty.

        The slice is taken first and filtered not at all: the bisect bounds
        are ``decision_date`` itself, so no row past it can be in the slice.
        The caller owns the frame builder's own ``_truncate`` for the rows
        between the day and the decision *instant*.

        The table and its day list are read as one pair under :attr:`_lock`:
        they are two dicts, and a concurrent :meth:`grow_day` appends to both,
        so reading them separately could take a table from one batch with the
        day list of the next — and slice it at indices that name no boundary.
        In ``evaluation_mode: "process"`` (the default) exactly one evaluation
        runs per process and the lock is uncontended.
        """
        key = (stream, symbol)
        with self._lock:
            table = self._tables.get(key)
            if table is None:
                return None
            days = self._days[key]
            lo = bisect.bisect_right(days, earliest_date)
            hi = bisect.bisect_right(days, decision_date)
            if hi <= lo:
                return None
            return table.slice(lo, hi - lo)

    def _append(
        self, key: tuple[str, str], table: Any, days: Sequence[dt.date]
    ) -> None:
        """Append one batch of rows to a symbol's table, days kept ascending.

        The forward case — every new day at or after the table's last — is a
        plain concatenation, which is every append a grid walked in
        increasing order makes (the whole of a normal evaluation).  A later
        call for an *earlier* day, or a grid gap a *later* window reaches
        back across, puts a batch in the middle of the table instead.  The
        row-day list is the bisect key, so it must stay sorted whichever
        order the batches arrive in: the two sorted sequences are merged and
        the table rebuilt in that order with one ``take``.

        The table is re-combined into a single chunk because pyarrow charges
        per chunk on every later ``filter``/``sort_by`` (see the class
        docstring), and the merge's ``take`` yields one chunk anyway.
        """
        import pyarrow as pa

        prior = self._tables.get(key)
        if prior is None:
            self._tables[key] = table
            self._days[key] = [*days]
            return
        prior_days = self._days[key]
        if days and days[0] >= prior_days[-1]:
            self._tables[key] = pa.concat_tables([prior, table]).combine_chunks()
            self._days[key] = [*prior_days, *days]
            return
        # Merge the two ascending day runs, remembering which side each row
        # comes from so the table can be reordered to match.
        order: list[tuple[int, int]] = []
        i = 0
        j = 0
        while i < len(prior_days) and j < len(days):
            if prior_days[i] <= days[j]:
                order.append((0, i))
                i += 1
            else:
                order.append((1, j))
                j += 1
        order.extend((0, k) for k in range(i, len(prior_days)))
        order.extend((1, k) for k in range(j, len(days)))
        merged = pa.concat_tables([prior, table])
        offsets = [0, prior.num_rows]
        indices = pa.array([offsets[side] + k for side, k in order])
        self._tables[key] = merged.take(indices)
        self._days[key] = sorted([*prior_days, *days])


#: The process-lifetime panel caches, one per ``snapshot_hash`` (plus one for
#: a context that carries none, keyed on the mount object's identity so two
#: different mounts never share a table).  A worker process that evaluates
#: many nodes of one campaign pays the initial windows and each day's read
#: once per process rather than once per node, which is where the campaign's
#: 183-dates-a-node cost lives.  The registry is small by construction — a
#: campaign evaluates against one snapshot — and is cleared between tests by
#: :func:`reset_panel_caches`.
_PANELS: dict[Any, _PanelCache] = {}
_PANELS_LOCK = threading.Lock()


def _resolution_reach(resolution: Any) -> str:
    """The latest ISO partition date ``resolution`` admits, ``""`` for none.

    The resolution resolved at a later decision time admits every partition
    an earlier one did plus the ones in between — ``resolve_window`` slices
    at or before its own instant — so this single value orders two
    resolutions of one snapshot by ``⊆``: the greater reach is the superset.
    """
    reach = ""
    for per_symbol in resolution.slices.values():
        for dates in per_symbol.values():
            if dates and dates[-1] > reach:
                reach = dates[-1]
    return reach


def _panel_cache(mount: Any, resolution: Any, cache_key: Any) -> _PanelCache:
    """The registry's cache for ``cache_key``, built over ``mount`` on first use.

    Keyed on the snapshot's identity by the caller (:data:`_PANELS`), so the
    tables a sealed, read-only snapshot answers are shared across the nodes
    of one process and never across two snapshots.  A later call whose
    resolution reaches further than the cache's own adopts it: the admitted
    set is what :meth:`_PanelCache.grow_day` reads days from, so a narrower
    resolution left in place would make a later, wider call silently skip the
    dates only it admits.  A narrower call never shrinks the stored
    resolution — and cannot read ahead of its own day regardless, because
    :meth:`_PanelCache.grow_day` bounds every read by the day being
    materialized.

    The swap is made under the *cache's own* lock, not just this registry's:
    in ``evaluation_mode: "thread"`` a sibling evaluation may be inside
    :meth:`_PanelCache.grow_day` reading the admitted set off that same
    attribute, and ``grow_day`` takes that lock — so taking the registry lock
    and then the cache lock, never the reverse, is what keeps a resolution
    change from landing mid-grow.
    """
    with _PANELS_LOCK:
        panels = _PANELS.get(cache_key)
        if panels is None or panels._mount is not mount:
            panels = _PanelCache(mount, resolution)
            _PANELS[cache_key] = panels
        elif _resolution_reach(resolution) > _resolution_reach(panels._resolution):
            with panels._lock:
                panels._resolution = resolution
    return panels


def reset_panel_caches() -> None:
    """Drop every process-lifetime panel cache.

    The one hook a test needs to stop an earlier evaluation in the same
    process from answering a later one's reads: ``_PANELS`` is deliberately
    shared across calls, so a test that counts reads must start from cold.
    Also the honest thing for a caller that has swapped the mount under a
    live key.
    """
    with _PANELS_LOCK:
        _PANELS.clear()


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
    read through the mount's own per-partition lookup — bug_spec_evaluation_throughput.xml's
    own bound on a window's depth, applied after the point-in-time universe
    rule rather than in place of it, so a 2026 date on a multi-year archive
    pays for :attr:`~orchestrator._context.EvaluationContext.max_history_days`
    trailing days per symbol rather than the snapshot's entire history, and
    an early date whose own history is shorter than that still carries
    everything it has.  The same read-only handle and the same sealedness
    back every score this evaluation computes, and a symbol not yet listed
    (or already delisted, or truncated out of range) on a given date is
    never read for it.  A process-lifetime per-partition cache
    (:data:`_PANELS`) keeps a worker from re-reading the same compressed
    bytes for every node of the campaign it evaluates, not merely across the
    rebalance dates of one.

    **Beside bars, the derivative streams become four feature frames**
    (additions_spec_derivatives_inputs.xml, "Snapshot and Window" feature
    3): ``feature:funding_1d:v1``, ``feature:basis_1d:v1`` (perp close over
    spot close minus one, computed host-side as a string, present only on a
    day both closes exist), ``feature:taker_flow_1d:v1`` (the day's
    taker-buy share of futures volume) and ``feature:metrics_1d:v1`` (the
    open-interest and long/short columns, opt-in at backfill time) — read
    through the identical per-(stream, symbol) panel and point-in-time
    cutoff as bars, so a signal reaching them through
    ``ctx.feature(name, version)`` gets the same no-look-ahead guarantee.
    Each is built only when its own stream is sealed at all — read off
    ``resolution.slices`` (the resolution already answered that question
    once, host-side; bug_spec_evaluation_throughput.xml's own "never asks
    the mount for a fresh partition listing" bar applies here exactly as it
    does to bars) — and only from universe symbols that actually carry a
    row under it: a symbol with no perpetual contributes none, never a
    zero-filled one.
    """
    mount = context.snapshot
    # getattr, not context.max_history_days: a few tests hand this function a
    # bare duck-typed context carrying only ``snapshot`` (the production
    # EvaluationContext always has the field, defaulted), and those callers
    # mean "no cap beyond this suite's own tiny history", which the default
    # depth already is for them.
    max_history_days = getattr(context, "max_history_days", DEFAULT_MAX_HISTORY_DAYS)
    # The panel cache is shared across this process's evaluations of the same
    # sealed snapshot (see :data:`_PANELS`), keyed by the snapshot's identity
    # so two snapshots never share a table.  A context without a hash (a
    # duck-typed test context) is keyed on the mount *object* itself — never
    # its ``id``, which is a recycled ``int`` the moment the mount is
    # collected and would let a later mount inherit a dead one's tables.
    cache_key = getattr(context, "snapshot_hash", None)
    if cache_key is None:
        cache_key = mount

    def materialize(resolution: Any, decision_time: dt.datetime) -> Any:
        import pyarrow as pa
        import pyarrow.compute as pc
        from contract.bars import bars_frame_name
        from contract.features import feature_frame_name
        from contract.window import MarketWindow

        decision_date = decision_time.date()
        earliest_date = decision_date - dt.timedelta(days=max_history_days)
        universe = pit_universe(resolution, decision_date)
        decision_scalar = pa.scalar(decision_time, type=pa.timestamp("us", tz="UTC"))
        panels = _panel_cache(mount, resolution, cache_key)
        # Every stream the resolution carries, read for the whole universe in
        # one batched pass *before* any frame is built: the days this window
        # owes (the day in hand, and on a grid's first date its trailing
        # window) go to one ``read_table`` per stream per day rather than one
        # per symbol — the batching half of the fix.
        for stream in (BARS_STREAM, FUNDING_STREAM, FUTBARS_STREAM, METRICS_STREAM):
            if stream in resolution.slices:
                panels.grow_day(stream, universe, earliest_date, decision_date)

        def _window_slice(stream: str, symbol: str) -> Any:
            # One cached table per (stream, symbol) for the whole process,
            # grown forward only: each date reads just the partitions it owes
            # whose date is at or before the day being materialized, appends
            # them to the symbol's table and takes a slice — exactly what the
            # per-partition loop used to assemble, with a partition never
            # read twice or ahead of its day.
            return panels.window(stream, symbol, earliest_date, decision_date)

        def _truncate(table: Any) -> Any:
            if table.num_rows == 0:
                return table
            # The bisect slice above already cut at ``decision_date``, so the
            # filter only has to drop rows stamped *inside* the day that fall
            # past the decision instant.  One ``pc.max`` over the day column
            # answers whether any such row exists; on the ingest layout every
            # row is stamped ``D`` 00:00 UTC (``bars_backfill._row_table``)
            # and the instant is ``D`` 23:59, so it never does and the slice
            # is returned untouched.  That check is what turns this call from
            # a per-(stream, symbol, date) filter into one scan of a single
            # column, and the frames stay byte-identical because a filter
            # that removes nothing is the identity.
            if pc.max(table["open_time"]).as_py() <= decision_scalar.as_py():
                return table
            return table.filter(pc.less_equal(table["open_time"], decision_scalar))

        bars_by_symbol: dict[str, Any] = {}
        for symbol in universe:
            sliced = _window_slice(BARS_STREAM, symbol)
            if sliced is not None:
                bars_by_symbol[symbol] = _truncate(sliced)
        bars_frame = (
            pa.concat_tables(list(bars_by_symbol.values()))
            if bars_by_symbol
            else pa.table({})
        )
        frames: dict[str, Any] = {bars_frame_name("1d"): bars_frame}

        def _renamed(table: Any) -> Any:
            # The sealed derivative streams stamp their day as ``date``
            # (ingest.derivs_backfill's own column, matching bars'
            # partitioning); a served feature frame names it ``open_time``,
            # the spelling every accessor and every other frame shares.
            names = [
                "open_time" if name == "date" else name for name in table.column_names
            ]
            return table.rename_columns(names)

        def _empty_feature_table(
            fields: tuple[str, ...], *, int_fields: tuple[str, ...] = ()
        ) -> Any:
            columns: dict[str, Any] = {
                "symbol": pa.array([], type=pa.string()),
                "open_time": pa.array([], type=pa.timestamp("us", tz="UTC")),
            }
            for field in fields:
                columns[field] = pa.array(
                    [], type=pa.int64() if field in int_fields else pa.string()
                )
            return pa.table(columns)

        def _sorted_feature_table(table: Any) -> Any:
            return table.sort_by([("symbol", "ascending"), ("open_time", "ascending")])

        if FUNDING_STREAM in resolution.slices:
            funding_tables = []
            for symbol in universe:
                sliced = _window_slice(FUNDING_STREAM, symbol)
                if sliced is not None:
                    funding_tables.append(_truncate(_renamed(sliced)))
            funding_frame = (
                pa.concat_tables(funding_tables)
                if funding_tables
                else _empty_feature_table(_FUNDING_FIELDS, int_fields=("n_settlements",))
            )
            frames[feature_frame_name("funding_1d", "v1")] = _sorted_feature_table(
                funding_frame
            )

        if FUTBARS_STREAM in resolution.slices:
            spot_closes_by_symbol = {
                symbol: {row["open_time"]: row["close"] for row in table.to_pylist()}
                for symbol, table in bars_by_symbol.items()
            }
            taker_symbols: list[str] = []
            taker_times: list[Any] = []
            taker_ratios: list[str] = []
            basis_symbols: list[str] = []
            basis_times: list[Any] = []
            basis_values: list[str] = []
            for symbol in universe:
                sliced = _window_slice(FUTBARS_STREAM, symbol)
                if sliced is None:
                    continue
                fut_table = _truncate(_renamed(sliced))
                spot_closes = spot_closes_by_symbol.get(symbol, {})
                for row in fut_table.to_pylist():
                    open_time = row["open_time"]
                    try:
                        ratio = Decimal(row["taker_buy_volume"]) / Decimal(
                            row["fut_volume"]
                        )
                    except (InvalidOperation, ZeroDivisionError):
                        pass
                    else:
                        taker_symbols.append(symbol)
                        taker_times.append(open_time)
                        taker_ratios.append(format(ratio, "f"))

                    spot_close = spot_closes.get(open_time)
                    if spot_close is None:
                        continue
                    try:
                        basis = Decimal(row["fut_close"]) / Decimal(spot_close) - Decimal(1)
                    except (InvalidOperation, ZeroDivisionError):
                        continue
                    basis_symbols.append(symbol)
                    basis_times.append(open_time)
                    basis_values.append(format(basis, "f"))

            taker_frame = (
                pa.table(
                    {
                        "symbol": taker_symbols,
                        "open_time": pa.array(
                            taker_times, type=pa.timestamp("us", tz="UTC")
                        ),
                        "taker_buy_ratio": taker_ratios,
                    }
                )
                if taker_symbols
                else _empty_feature_table(("taker_buy_ratio",))
            )
            frames[feature_frame_name("taker_flow_1d", "v1")] = _sorted_feature_table(
                taker_frame
            )

            basis_frame = (
                pa.table(
                    {
                        "symbol": basis_symbols,
                        "open_time": pa.array(
                            basis_times, type=pa.timestamp("us", tz="UTC")
                        ),
                        "basis": basis_values,
                    }
                )
                if basis_symbols
                else _empty_feature_table(("basis",))
            )
            frames[feature_frame_name("basis_1d", "v1")] = _sorted_feature_table(
                basis_frame
            )

        if METRICS_STREAM in resolution.slices:
            metrics_tables = []
            for symbol in universe:
                sliced = _window_slice(METRICS_STREAM, symbol)
                if sliced is not None:
                    metrics_tables.append(_truncate(_renamed(sliced)))
            metrics_frame = (
                pa.concat_tables(metrics_tables)
                if metrics_tables
                else _empty_feature_table(_METRICS_FIELDS)
            )
            frames[feature_frame_name("metrics_1d", "v1")] = _sorted_feature_table(
                metrics_frame
            )

        return MarketWindow(decision_time, universe=universe, frames=frames)

    return materialize


# -- The cost seam: the context's own schedule, transported not re-implemented --


def _fee_per_unit_traded(context: EvaluationContext) -> float:
    """The fee this evaluation charges per unit of notional turned over.

    ``context.execution`` picks the side, quoted off the context's own
    resolved :class:`~cost_model.FeeSchedule` — never re-derived — so this
    is the one place either of the two cost seams below (and the two
    orchestrator call sites that hand it to ``compute_node_metrics``)
    reads the fee a signal was actually priced at.

    :data:`cost_model.TAKER` (the default) quotes the schedule's taker
    rate alone — unchanged from every evaluation run before this key
    existed. :data:`cost_model.MAKER` quotes the maker rate *plus* the
    schedule's :attr:`~cost_model.FeeSchedule.passive_penalty_fraction`
    (cost_model feature 64's queue-position penalty), so a signal priced
    as executed passively pays what a resting fill actually costs: the fee
    it would be charged, and the adverse-selection cost it would not avoid
    by resting instead of crossing.  ``load_evaluation_context`` refuses a
    ``"maker"`` configuration whose cost model resolves no passive penalty
    before a context is ever built, so a context reaching this function
    with ``execution == MAKER`` always carries a non-``None`` penalty.

    Read with ``getattr``/default taker, the same courtesy the context's
    other optional attributes (``instrument``, ``max_history_days``) extend
    to a bare duck-typed test context that carries only ``cost_schedule``.
    """
    from cost_model import MAKER, TAKER

    schedule = context.cost_schedule
    if getattr(context, "execution", TAKER) == MAKER:
        return schedule.fee_fraction(MAKER) + schedule.passive_penalty_fraction
    return schedule.fee_fraction(TAKER)


def _cost_schedule_from_context(context: EvaluationContext) -> Any:
    """The injected ``CostSchedule`` :func:`evaluator.apply_costs` charges through.

    The context already resolved the venue's :class:`~cost_model.FeeSchedule`
    (feature 5); this closure quotes :func:`_fee_per_unit_traded`'s rate on
    exactly the support ``apply_costs`` asks about, the same transport
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

    This uniform per-symbol charge cancels in the node's own dollar-neutral
    book (bug_spec_turnover_cost_charge, bug 1): the book weights sum to
    zero, so ``Σ w_i f = f Σ w_i = 0`` regardless of ``f``. It is kept
    anyway because :func:`evaluator.apply_costs` still prices the resident
    book this node's own book is measured *marginal to*, where it is not
    centered. The charge that actually prices this node's own book is the
    turnover charge :func:`_turnover_fee_from_context` hands
    ``compute_node_metrics`` at both call sites below.

    **Quotes the uniform fee alone — on every instrument, including perp.**
    additions_spec_research_book_v2.xml's perp instrument feature once added
    a funding carry here, beside the fee, keyed by the request's own
    ``(date, symbol)``. bug_spec_null_carry_leak found that seam downstream
    of the null oracle's permutation: a planted null permutes the *target*
    series (:func:`orchestrator._targets.snapshot_forward_returns`, read
    through :class:`nulloracle.TargetEndpoint`) but this schedule quoted the
    carry straight off the request's own symbol, so a null's permuted price
    return still carried its own symbol's real funding — the one component
    of the post-cost return no derangement ever touched, biasing every
    funding- or basis-driven signal's null distribution upward. The carry
    now lives in the target seam instead: ``snapshot_forward_returns`` sums
    it into the served forward return, under ``context.instrument ==
    "perp"``, before either branch (real or permuted) is built, so a null's
    derangement carries the carry along with the price return it is paired
    with. :func:`_funding_carry` keeps its one definition and its signature;
    only its caller moved.
    """
    from evaluator import CostQuote

    fee = _fee_per_unit_traded(context)

    def charges(request: Any) -> Any:
        costs = {
            day: dict.fromkeys(row, fee) for day, row in request.gross_returns.items()
        }
        return CostQuote(venue=request.venue, version=request.version, costs=costs)

    return charges


def _funding_carry(
    context: EvaluationContext, symbol: str, day: dt.date, horizon: int
) -> float:
    """The funding settled over one holding window — ``D+1`` through ``D+h``.

    additions_spec_research_book_v2.xml, the perp instrument feature: under
    the ingest day rule (:mod:`nullius_ingest.derivs_backfill`), the
    settlement at ``D+1`` 00:00 belongs to row ``D`` — the row a position
    entered at the ``D``-close is already past the instant it was entered,
    not after it — so the window that starts strictly after the entry
    begins at row ``D+1``, not row ``D``. A missing funding row anywhere in
    the window (no settlement sealed for that symbol on that day) counts
    zero rather than refusing or shrinking the window — the same absence
    convention :attr:`EvaluationContext.funding`'s own docstring states.
    """
    funding = getattr(context, "funding", None)
    symbol_funding = funding.get(symbol, {}) if funding else {}
    return math.fsum(
        symbol_funding.get(day + dt.timedelta(days=offset), 0.0)
        for offset in range(1, horizon + 1)
    )


def _turnover_fee_from_context(context: EvaluationContext) -> float:
    """The fee charged on this node's own book's traded notional.

    The same rate :func:`_cost_schedule_from_context` quotes to
    ``apply_costs`` per symbol — :func:`_fee_per_unit_traded`, read off the
    context's own resolved :class:`~cost_model.FeeSchedule` rather than
    re-derived, so the two seams can never quote two different numbers for
    the one fee the configured execution mode charges — but handed to
    :func:`evaluator.compute_node_metrics` instead, as
    ``cost_per_unit_traded``: that is the charge which actually prices a
    dollar-neutral book, where the per-symbol charge above cancels.
    """
    return _fee_per_unit_traded(context)


def _gross_ir_tstat(
    priced: PostCostReturns,
    scores: Mapping[Any, Any],
    *,
    betas: Mapping[dt.date, Mapping[str, float]] | None = None,
    vols: Mapping[dt.date, Mapping[str, float]] | None = None,
    weighting: str = Z_WEIGHTING,
    horizon: int | None = None,
) -> float:
    """``ir_tstat`` recomputed over the same panel with no turnover charge.

    The diagnostic bug_spec_turnover_cost_charge's bug 2 asks for beside
    every net figure: the same ``compute_node_metrics`` call the net figure
    came from, with ``cost_per_unit_traded=0.0`` — the pre-fix reading —
    so a caller comparing the two sees exactly what the venue fee cost this
    node's own book.  ``betas`` (additions_spec_research_book_v2.xml feature
    2) is handed through unchanged, so the gross diagnostic is measured
    over the same beta-neutral book as the net figure — never the plain
    dollar-neutral one the net figure no longer is.  ``vols`` is handed
    through unchanged for the same reason: the gross figure is measured
    over the same inverse-volatility (or z-weighted) book as the net one,
    never a different weighting the config did not name.  ``weighting`` is
    handed through unchanged for that same reason and is what makes it true
    of the tail-decile and short-tail books too: ``vols`` alone cannot say
    it, because ``"tail_decile"`` and ``"short_tail"`` carry no side panel,
    so a gross diagnostic that
    only forwarded the panel would silently measure a z-weighted book
    against a tail-decile or short-tail net figure.  ``horizon``
    (bug_spec_metrics_horizon.xml bug 2) is handed through for the same
    reason again: the gross figure is measured over the same horizon's
    series as the net one, never the shortest covered one the config did
    not name.
    """
    gross = compute_node_metrics(
        priced,
        scores,
        cost_per_unit_traded=0.0,
        betas=betas,
        vols=vols,
        weighting=weighting,
        horizon=horizon,
    )
    return gross.ir_standalone * math.sqrt(gross.dates)


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
    wants — exactly the identity and the eight metric columns it reads by
    attribute, and nothing of :class:`evaluator.NodeRow`'s wider shape (the
    tree writer never reads ``campaign_id``, ``snapshot_name``,
    ``evaluator_hash`` or ``cost_model`` — those are the tree member's own
    columns, already on the row the discovery loop or the root planter
    wrote first).  ``ir_tstat`` (additions_spec_cost_aware_selection.xml,
    feature 1) is the post-cost IR t-statistic — never ``None`` here, since
    this row is only ever built once :func:`evaluate_node` has already
    measured it from the same metrics as every other field.
    """

    node_id: str
    ic_mean: float
    ic_tstat: float
    ir_tstat: float
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
    ir_tstat: float,
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
            ir_tstat=ir_tstat,
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


# -- The perp scoring universe: a no-perp-close symbol is dropped, not refused -


def _drop_unpriced_symbols(
    execution: SignalExecution, context: EvaluationContext
) -> tuple[SignalExecution, int]:
    """Drop, per rebalance date, any scored symbol with no perp close at it.

    additions_spec_research_book_v2.xml, the perp instrument feature:
    *"on each date, a scored symbol with no perp close at D is dropped
    from the score vector before alignment ... This replaces _align's
    refusal for that case only."*  With the spot default,
    ``context.instrument != "perp"`` and this is the identity transform —
    feature 72's universe rule already guarantees every symbol
    ``execute_signal`` scored has a bars close on its own rebalance date, so
    there is nothing to drop and :func:`evaluator.align_targets` keeps its
    existing refusal for every case it already covered.

    With the perp instrument, not every symbol the bars-derived universe
    scored has a perpetual contract (or has one sealed on this particular
    date), so this is where that gap is resolved — *before*
    ``normalize_scores`` or ``align_targets`` ever see the symbol, by
    removing it from the raw execution's own universe and (positionally)
    its scores.  The containment check (``day in context.closes.get(symbol,
    {})``) reads only the lazy directory listing :class:`_LazySymbolCloses`
    already cached for that symbol, never a partition's content — so
    deciding to drop costs nothing beyond what :attr:`EvaluationContext.closes`
    was going to pay anyway, and a genuinely poisoned (as opposed to absent)
    perp close is still read and still refused, at :func:`evaluator.align_targets`'s
    own entry-close lookup, exactly as a poisoned bars close already is.

    Answers the filtered execution (unchanged, by identity, when nothing
    was dropped) and the total count of ``(date, symbol)`` drops — the
    evaluation's own fail_detail-free diagnostic
    (:attr:`NodeEvaluation.dropped_perp_symbols`), never a zero-filled
    target.
    """
    if context.instrument != PERP_INSTRUMENT:
        return execution, 0

    import polars as pl

    dropped = 0
    changed = False
    vectors: dict[dt.date, RawScoreVector] = {}
    for day, vector in execution.vectors.items():
        keep_mask = [
            day in context.closes.get(symbol, {}) for symbol in vector.universe
        ]
        if all(keep_mask):
            vectors[day] = vector
            continue
        changed = True
        dropped += keep_mask.count(False)
        kept_universe = tuple(
            symbol for symbol, keep in zip(vector.universe, keep_mask) if keep
        )
        kept_scores = vector.scores.filter(pl.Series(keep_mask, dtype=pl.Boolean))
        vectors[day] = replace(vector, universe=kept_universe, scores=kept_scores)

    if not changed:
        return execution, 0
    return (
        SignalExecution(
            snapshot_name=execution.snapshot_name,
            code_hash=execution.code_hash,
            seed=execution.seed,
            vectors=vectors,
        ),
        dropped,
    )


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
    # bug_spec_metrics_horizon.xml bug 2: the evaluation line names the book's
    # weighting and the horizon the metrics are measured at, so a "horizon 5"
    # campaign's log carries the mode its numbers were actually reduced under.
    _logger.info(
        "evaluating node %s: book weighting %r, metrics_horizon %r (measuring %s)",
        node_id,
        context.book.weighting,
        context.metrics_horizon,
        "the shortest covered horizon"
        if context.metrics_horizon_value is None
        else f"horizon {context.metrics_horizon_value}",
    )

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

        execution, dropped_perp_symbols = _drop_unpriced_symbols(execution, context)
        scores, flat_dates = _score_rebalance_dates(execution, node_id)
        betas = compute_betas(context, scores) if context.book.beta_neutral else None
        vols = (
            compute_vols(context, scores)
            if context.book.weighting == INVERSE_VOL_WEIGHTING
            else None
        )
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
        metrics = compute_node_metrics(
            priced,
            scores,
            cost_per_unit_traded=_turnover_fee_from_context(context),
            betas=betas,
            vols=vols,
            weighting=context.book.weighting,
            horizon=context.metrics_horizon_value,
        )
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
    ir_tstat = metrics.ir_standalone * math.sqrt(metrics.dates)
    ir_tstat_gross = _gross_ir_tstat(
        priced,
        scores,
        betas=betas,
        vols=vols,
        weighting=context.book.weighting,
        horizon=context.metrics_horizon_value,
    )

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
        ir_tstat=ir_tstat,
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
        ir_tstat=ir_tstat,
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
        ir_tstat_gross=ir_tstat_gross,
        dropped_perp_symbols=dropped_perp_symbols,
    )


# -- The out-of-sample call: the same chain, over a different grid, nothing written --

#: The node table's own identity columns, read (never written) for
#: :func:`evaluate_on_dates` — the same table
#: :mod:`orchestrator._tree_writer` updates and :mod:`orchestrator._oracle`
#: walks, named locally rather than imported because this is the one place
#: in this module that reads identity off it rather than a metric.
_NODE_IDENTITY_TABLE: Final[str] = "node"


def _node_identity(database_url: str, node_id: str) -> tuple[str, int]:
    """One stored node's own ``(campaign_id, depth)`` — read, never written.

    :func:`evaluator.gate_targets` builds its ask from the node identity
    (``campaign_id`` and ``depth``) the caller supplies; ``evaluate_node``
    gets both from its own caller, but ``evaluate_on_dates`` is handed only
    a node id — the node it evaluates is already stored, so its existing row
    is where both facts come from, read fresh on every call rather than
    threaded in by a caller that may not hold them.

    Raises :class:`NodeIdentityError` when the tree holds no such row.
    """
    path = _tripwire_sqlite_path(database_url)
    with closing(sqlite3.connect(path)) as connection:
        row = connection.execute(
            f"SELECT campaign_id, depth FROM {_NODE_IDENTITY_TABLE} WHERE id = ?",
            (node_id,),
        ).fetchone()
    if row is None:
        raise NodeIdentityError(
            f"the tree holds no node {node_id!r} to read a campaign and "
            "depth from; evaluate_on_dates evaluates a node that is already "
            "stored, and a node the tree does not hold has neither an "
            "identity to ask the oracle with nor a signal to evaluate "
            "out of sample"
        )
    campaign_id, depth = row
    return campaign_id, depth


class _OutOfSampleEvaluation(tuple):
    """``(metrics, cost_adjusted_ir)``, with ``ir_tstat_gross`` riding along.

    :func:`closeout.commit_oos` and :func:`_financial_eval`'s dream reader
    both destructure this function's answer as
    ``metrics, cost_adjusted_ir = evaluate_on_dates(...)`` — a contract this
    class keeps by being, at heart, a plain two-element tuple (``__new__``
    stores only ``metrics`` and ``cost_adjusted_ir`` as its two items, so
    unpacking and ``len()`` see exactly two). ``ir_tstat_gross`` is an
    instance attribute beside that tuple, never a third item, for a caller
    that wants the diagnostic without either of those two files widening
    what they unpack. (``tuple`` itself allows no non-empty ``__slots__``
    on a subclass, so this one carries the ordinary instance ``__dict__``
    a bare ``class Foo(tuple): pass`` already would.)
    """

    def __new__(
        cls, metrics: NodeMetrics, cost_adjusted_ir: float, ir_tstat_gross: float
    ) -> "_OutOfSampleEvaluation":
        self = super().__new__(cls, (metrics, cost_adjusted_ir))
        self.ir_tstat_gross = ir_tstat_gross
        return self


def evaluate_on_dates(
    node_id: str,
    code: str,
    *,
    context: EvaluationContext,
    oracle: Oracle,
    dates: Sequence[dt.date],
) -> tuple[NodeMetrics, float]:
    """Score a stored node's signal over ``dates`` — the same chain, nothing written.

    additions_spec_m2_baseline_financial_worlds.xml, "Out-of-Sample
    Evaluation", feature 1: the pipeline ``evaluate_node`` already proved —
    ``execute_signal``, the per-date normalization, ``align_targets``,
    ``gate_targets`` (through the caller's own ``oracle``, so a null node
    gets permuted targets out of sample exactly as it does in sample),
    ``apply_costs``, ``compute_node_metrics`` — run again over ``dates``
    instead of ``context.evaluation_dates``.  The window is resolved at the
    end of ``dates``' own last day (the same no-look-ahead reading
    ``evaluate_node`` gives its own grid), and ``execute_signal`` is handed
    the same :func:`orchestrator._context.signal_sandbox` executor
    ``evaluate_node`` always uses — never the evaluator's own unconfined
    default.

    Three things this call does *not* do, which is the whole of what makes
    it an out-of-sample read rather than a second evaluation of the node:
    it never screens ``code``'s imports (the node is already stored, which
    means its code already cleared that screen the one time it had to); it
    never runs step 10's tripwire sweep or the empty-book marginal-IR
    stand-in (neither is part of the chain this feature names, and neither
    is in its return value); and it books no ledger debit, writes no node
    row, no artifact, no tripwire verdict and no stability record — an
    out-of-sample read measures a node, it does not re-evaluate one.  The
    node's own ``campaign_id`` and ``depth`` — what ``gate_targets`` needs
    to ask the oracle the same question an in-sample evaluation would —
    are read off its existing row (see :func:`_node_identity`), since this
    function is handed only the node id.

    Answers ``(metrics, cost_adjusted_ir)`` — the measured
    :class:`~evaluator.NodeMetrics`, net of the venue's turnover charge, and
    the same cost-adjusted axis :func:`_cost_adjusted_ir` restates onto a
    live node's row, computed here and handed back rather than written
    anywhere. The answer also carries ``ir_tstat_gross`` (see
    :class:`_OutOfSampleEvaluation`) — the same figure with no turnover
    charge, for a caller that wants to see what the fee cost this read.

    Every exception the chain raises — a window, a non-conforming score
    vector (:class:`SandboxExecutionError`), a gate or cost or metrics
    failure — propagates unchanged: this function charges nothing, so there
    is no failure path to charge it under, and a caller sees exactly the
    pipeline's own error.  :class:`NodeIdentityError` is raised first, before
    any sandbox spawns, when the tree holds no row for ``node_id``.
    """
    campaign_id, depth = _node_identity(context.database_url, node_id)
    grid = tuple(dates)
    executor = signal_sandbox(context)

    decision_time = dt.datetime.combine(grid[-1], _END_OF_DAY)
    resolution = resolve_window(context.snapshot, decision_time)
    execution = execute_signal(
        resolution,
        code,
        seed=context.seed,
        rebalance_dates=grid,
        sandbox=executor,
        materialize=_materialize_from_context(context),
    )
    for day in execution.dates():
        vector = execution.vector(day)
        if not vector.conforming:
            raise SandboxExecutionError(
                f"the sandbox did not return a conforming score vector for "
                f"node {node_id!r} at {day.isoformat()} (out of sample): "
                f"{vector.problems or _executor_failure(executor)}"
            )

    execution, _dropped_perp_symbols = _drop_unpriced_symbols(execution, context)
    scores, _flat_dates = _score_rebalance_dates(execution, node_id)
    betas = compute_betas(context, scores) if context.book.beta_neutral else None
    vols = (
        compute_vols(context, scores)
        if context.book.weighting == INVERSE_VOL_WEIGHTING
        else None
    )
    alignment = align_targets(execution, context.closes)
    gated = gate_targets(
        alignment, oracle, node_id=node_id, campaign_id=campaign_id, depth=depth
    )
    priced = apply_costs(
        gated,
        _cost_schedule_from_context(context),
        node_id=node_id,
        cost_model=context.cost_model,
    )
    metrics = compute_node_metrics(
        priced,
        scores,
        cost_per_unit_traded=_turnover_fee_from_context(context),
        betas=betas,
        vols=vols,
        weighting=context.book.weighting,
        horizon=context.metrics_horizon_value,
    )
    return _OutOfSampleEvaluation(
        metrics,
        _cost_adjusted_ir(priced, metrics),
        _gross_ir_tstat(
            priced,
            scores,
            betas=betas,
            vols=vols,
            weighting=context.book.weighting,
            horizon=context.metrics_horizon_value,
        ),
    )
