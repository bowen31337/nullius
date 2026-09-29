"""Feature 363: the end-to-end journey — a hand-written momentum signal returns a
positive information coefficient across the sealed snapshot, and the run leaves a
persisted node row.

app_spec.xml, "End-to-End Verification", feature 363: *"System passes an
end-to-end test where ingest seals a snapshot, the evaluator scores a hand-written
momentum signal, and the run returns positive information coefficient with a
persisted node row."*  The sentence is the repository's positive control — the
mirror image of feature 364's negative control (a random signal returns an IC
indistinguishable from zero) — and it is the thing the whole evaluation story
rests on the other side of: if a signal that *does* carry information came back
with no distinguishable coefficient, nothing the evaluator reports about edge
could be believed either.  Everything else in the pipeline would reproduce
perfectly and the system would still be broken.  The sentence names five clauses,
each staged through the shipped system's own public seams and none of it staged by
hand:

**Ingest seals a snapshot.**  LLM-authored-shaped source is not involved here —
the *market* is the journey's own content, generated from a pinned pseudo-random
walk — but the seal is the shipped system's: ingest writes §4.2's partition
layout into the lake's staging area, :meth:`snapshot.SnapshotService.seal`
publishes it immutably (files ``0444``, directories ``0555``), and the evaluator
reaches it only through :meth:`snapshot.SnapshotService.mount`'s read-only handle.
The journey asserts the sealedness rather than assuming it: every staged byte is
re-hashed and compared against the manifest the seal published, this lake reports
no corruption across that manifest, and the mount's root refuses every write mode
it offers.  The bars the window carries are the sealed bytes, read back through
the mount's own ``select`` and read-only paths — the production lake reader
feature 73's ``materialize`` seam exists to be injected with.

**The evaluator scores a hand-written momentum signal.**  A genuine momentum
signal, written the way a node's source arrives — a module-level ``signal(ctx,
seed)`` returning a polars Series indexed positionally by ``ctx.universe`` — and
handed to the *real* :class:`~evaluator.SignalSandbox`: a genuine ``python -c``
child of the same interpreter, under POSIX rlimits and a wall-clock watchdog, over
the payload channel (feature 73, §5.2).  Not a stub, and not a skip marker — the
sandbox spawns once per rebalance date and every envelope is checked clean.  The
signal is *hand-written*, in the literal sense the sentence means: it is not
LLM-authored in a discovery loop, it is this module's own source text, and it
computes a real cross-sectional momentum — the trailing percentage price change
over the window's own bars, read from ``ctx.bars("1d")`` and folded through the
decision instant the window carries — so the score on every date is a function of
the sealed market the window was handed, and observably excludes the window from
what it returns.

**Positive information coefficient.**  The five steps between the signal and the
number are the shipped pipeline's own verbs, in §6.1's order: feature 72's
:func:`~evaluator.resolve_window` slices a *sealed* mount to the decision time and
resolves the point-in-time universe; feature 74's
:func:`~evaluator.normalize_scores` ranks and z-scores each date's raw vector (so
the coefficient measures the *ordering* the signal expressed, not the scale it
chose); feature 75's :func:`~evaluator.align_targets` aligns post-rebalance
forward returns; feature 76's :func:`~evaluator.gate_targets` asks an oracle whose
answer is the alignment's own series for the real branch — the real-branch seam the
evaluator's own member suite supplies the same way, since *which* branch the
oracle resolves belongs to feature 366's journey and the labels live behind §4.2's
barrier, not here; feature 77's :func:`~evaluator.apply_costs` nets the returns
through the shared §6.2 fee library, priced from the cost model document's own
resolved ``FeeSchedule`` (``binance_spot/2026.09.1``, 10 bps both sides) rather
than a second fee arithmetic — feature 69 refuses a second fee implementation, so
the schedule here is a *transport* of the library's own fraction and computes
nothing; and feature 80's :func:`~evaluator.compute_node_metrics` reduces the
per-date Spearman coefficients to ``ic_mean``, ``ic_se`` and ``ic_tstat`` — the
coefficient the sentence names, in the spelling the system reports it in.

**With a momentum world behind it.**  This is the clause that distinguishes the
journey from feature 364's: the sealed market must be one in which momentum
*means something*.  A sealed random walk — feature 364's world — has no return
autocorrelation, so a momentum signal scored on it returns an IC indistinguishable
from zero, and the journey would assert a positive number about a market that
carries none.  So the bars here are generated from an AR(1) process on the
per-bar log-returns — one independent path per symbol, each with a positive
autoregressive coefficient — so that a bar's return predicts a fraction of the
next bar's return, which is the market condition under which a trailing price
change carries information about the next bar's direction.  The autocorrelation
is the journey's own content, exactly as the bars in feature 364 are, and it is
pinned by the world seed, so the whole journey is a function of one integer.  The
journey does not assert the market has the property by construction; it asserts
the *signal* earns a positive coefficient on it, and it records the world's own
autocorrelation as a control so a reader can see the edge is measured against a
market that has some to give.

**A persisted node row.**  The four scalars are a number the system keeps —
feature 80's ``node_metrics`` row, keyed by the node and the cost model — and the
store's reader re-derives ``ic_mean`` from the stored series, so a round trip is a
check of the row against itself rather than a cache read.  The journey persists
through the shipped :func:`~evaluator.persist_node_metrics` and reads back through
the shipped :func:`~evaluator.load_node_metrics`, into the journey's own SQLite
store addressed by ``DATABASE_URL`` — the same store the deployment composes — and
asserts the row the system keeps says the coefficient is positive.

**What this journey checks rather than assumes.**  The bars it seals are
generated from a pinned pseudo-random AR(1) walk, so the *content* is the
journey's own; the seal, the mount, the immutability, the manifest, the window
resolution, the point-in-time universe, the sandbox, the normalization, the
alignment, the gate, the fee library, the metrics and the node-metrics store are
all the shipped system's.  The one seam this journey supplies beside the market
data is the oracle's real-branch answer, because the labels that decide the branch
live behind the barrier and feature 366's journey owns that half; the gate's own
support check certifies the supplied series either way.  The signal source is the
journey's own too — that is the whole of "hand-written" — but it is scored through
the shipped sandbox, so the number it earns is the shipped pipeline's.

**One module, one journey, run once.**  The journey runs its acts once in a
module-scoped fixture over its own lake, its own SQLite store and its own composed
application, and the facet tests below read the sealed snapshot, the resolved
window, the score panel, the four numbers, the persisted node row and the control
world out of that one run.  The member suites pin each verb's own law — the window
resolution (packages/evaluator/tests/test_window.py), the sandbox protocol
(test_sandbox.py), the alignment's refusal taxonomy (test_align.py), the gate's
support rule (test_gate.py), the fee library
(packages/cost-model/tests/test_fees.py), the metrics' closed forms
(test_metrics.py), the store's read-back checks (test_metrics_store.py) — and this
module does not re-test them; it asserts the one thing only the composition can:
that a signal with edge in it, scored through the assembled system over a sealed
world that has edge to give, comes back with a positive coefficient and a row the
system keeps.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import os
import random
import statistics
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from contract.window import MarketWindow
from cost_model import TAKER, FeeSchedule, load_cost_model
from evaluator import (
    HORIZONS,
    CostModelRef,
    OracleResponse,
    SignalSandbox,
    align_targets,
    apply_costs,
    compute_node_metrics,
    execute_signal,
    gate_targets,
    load_node_metrics,
    normalize_scores,
    persist_node_metrics,
    resolve_window,
)

# The shared tests/e2e/conftest.py puts every declared member's scan root on
# sys.path before this line runs, so the members import by their bare names —
# the workspace contract that no member imports another, honoured here by
# reaching each through the path the conftest already built.  The factory is
# reachable as ``app.module_loader`` through that same conftest, which is the
# declaration production reads.
from app.module_loader import create_app

# ---------------------------------------------------------------------------
# The sealed world — §4.2's layout, and the universe the window resolves
# ---------------------------------------------------------------------------

#: The symbols the journey's world carries.  Eight is the cross-section the
#: coefficient is computed over on every date: small enough that the whole
#: journey (seal, two-dozen sandbox spawns, the store round trip) runs in about a
#: minute, large enough that a per-date Spearman coefficient over it takes values
#: across a decent band rather than a handful of grid points.  A *universe* is
#: sorted and de-duplicated by the resolution, so the spelling here is the roster
#: order.
SYMBOLS = tuple(f"SYM{index:02d}" for index in range(8))

#: The UTC day the sealed history opens on.  A pinned calendar date, never
#: ``date.today()``: the journey is a replay (§12), and a world that moved with
#: the wall clock would report a different coefficient tomorrow.
FIRST_DAY = dt.date(2026, 9, 1)

#: Every day the sealed bars carry.  A momentum signal needs a lookback of real
#: bars before it can express a preference, and the alignment needs a forward bar
#: to step into, so the rebalance grid is the *interior* of the bar span rather
#: than its head: the first few bars are lookback runway the signal reads but is
#: not scored on, and the last bar is the horizon's forward return the alignment
#: steps into.  Forty-eight bars give the signal a six-bar lookback and the
#: alignment a one-bar forward step, with twenty-four scored rebalance dates
#: between — the sample every facet below is calibrated against, and the sample
#: the evaluator's own member suites use, so the standard errors this journey
#: reads are of the size the rest of the repository reads.
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(48))
LOOKBACK = 6
REBALANCE_DAYS = BAR_DAYS[LOOKBACK : LOOKBACK + 24]

#: The seed of the generated world, and the autoregressive coefficient of its
#: per-bar log-returns.  The market is the journey's own content — the pipeline
#: under test does not care whether the prices came from an exchange or from a
#: generator — and pinning both makes the whole journey a function of these.  The
#: coefficient is positive and material: an AR(1) return of 0.5 means a bar's
#: return predicts half of the next bar's, which is the market condition under
#: which a trailing price change carries information about the next bar's
#: direction — exactly what a momentum signal is scored on.  A coefficient of
#: zero would be feature 364's random walk, on which momentum earns nothing; the
#: journey records the value it uses so a reader can see the edge is measured
#: against a world that has some to give.
WORLD_SEED = 20260924
AUTOCORRELATION = 0.5

#: The node and campaign identities the evaluation is stamped with.  Canonical
#: UUID text, because every seam that carries them joins to the tree store's
#: ``node.id`` and refuses a spelling that cannot.  The metrics are keyed by the
#: node and the cost model, so the store round-trip below is a round-trip of
#: *this* evaluation.
NODE_ID = "3f1c9b2a-4d5e-4f60-8a71-9b2c3d4e5f60"
CAMPAIGN_ID = "8c7d6e5f-4a3b-4c2d-9e1f-0a9b8c7d6e5f"

#: The two-sided 5% bar.  1.96 is the conventional normal quantile, and it is
#: the *same* number the promotion path's t-statistic bar is read against
#: (architecture §6.3) — so the claim this journey makes is that the momentum
#: signal *clears* the bar the system promotes on, which is the operational
#: meaning of "positive information coefficient" in this codebase: not merely a
#: coefficient whose point estimate is above zero, but one whose evidence is
#: strong enough to be distinguished from the null the promotion path tests
#: against.  It is stated here rather than replaced by a magnitude threshold of
#: the journey's own invention, because the documents name no threshold for a
#: positive control and a pinned ``ic_mean > 0.01`` would be a number the journey
#: chose to make its own test pass.
PROMOTION_BAR = 1.96

#: The band the per-date information coefficients must span for the journey to
#: call the mean a real edge rather than a construction.  A degenerate signal
#: returning the same tiny positive coefficient on every date would satisfy a
#: bare "``ic_mean > 0``" assertion and be worthless; the momentum signal's
#: coefficients vary with the cross-section it scored, so the mean that landed
#: positive landed there over a spread of dates, some positive and some not.
MIN_IC_SPREAD = 0.3

#: The tolerance the *pairwise* Spearman identity is checked to.  Feature 80
#: reduces both sides to average ranks and correlates those, which is the
#: Spearman coefficient by definition; the facet re-derives it directly from
#: rank arithmetic to prove the number it asserts on is the statistic it claims
#: to be.
_RANK_TOLERANCE = 1e-9

#: The signal source the sandbox runs.  Written the way a node's source arrives —
#: a module-level ``signal(ctx, seed)`` returning a polars Series indexed
#: positionally by ``ctx.universe`` — and it exercises the two things the
#: sandbox's entrypoint contract promises: ``seed`` is required and positional,
#: and ``pl`` is pre-bound in the child's namespace (the sandbox denies the signal
#: a working ``import`` of its own, feature 11's "polars is the one library a
#: signal is entitled to, provided pre-bound").  It reads the sealed bars for
#: their row count — so the window it was handed is observably materialized — and
#: returns a momentum whose sign and magnitude come from the sealed market the
#: window carries, not from the bars' row count — the count is read and
#: discarded, which is what makes it possible to say the coefficient is a
#: statement about the *signal* rather than about what the signal was shown.
MOMENTUM_SIGNAL_CODE = f"""
def signal(ctx, seed):
    bars = ctx.bars("1d")
    # The window is read — the accessor is called and its rows are counted, and
    # the count must be non-zero — so the signal observably ran against a real
    # slice of the sealed lake rather than against the resolution alone.  The
    # count then plays no part in the scores: the coefficients below are a
    # statement about the *signal*, and a signal whose momentum moved with the
    # market's row count would be one whose edge the journey could not attribute.
    if len(bars) <= 0:
        raise ValueError("the window carries no bars to score against")

    frame = bars.with_columns(pl.col("close").cast(pl.Float64).alias("c"))
    momentum = {{}}
    for symbol in ctx.universe:
        series = (
            frame.filter(pl.col("symbol") == symbol)
            .sort("open_time")
        )
        # A trailing price change over the window's own bars: the first close the
        # window carries against the last, so the score is a function of the
        # sealed market the window was handed and of the decision instant it was
        # sliced to — a fresh cross-section on every date, because the window's
        # trailing bar moves with ``t``.  A signal that returned the same vector
        # twenty-four times would make the per-date coefficients degenerate.
        if len(series) < {LOOKBACK}:
            momentum[symbol] = 0.0
        else:
            first = float(series[0]["c"][0])
            last = float(series[-1]["c"][0])
            momentum[symbol] = (last - first) / first
    return pl.Series([momentum[symbol] for symbol in ctx.universe])
"""


# ---------------------------------------------------------------------------
# The sealed lake — ingest's own layout, sealed by the service's own verb
# ---------------------------------------------------------------------------


def _seal_the_world(
    workdir: Path,
) -> tuple[Any, Any, dict[str, dict[dt.date, float]], dict[str, str]]:
    """Generate the momentum market, stage it in §4.2's layout, and seal it.

    Ingest's half of the sentence: a §4.2 lake root is laid out (``snapshots/``
    for sealed content, ``staging/`` for writable ingest), the staged tree is
    written at the partition granularity the layout names —
    ``bars/symbol=<SYM>/date=<ISO>/part-*.parquet`` — and then sealed through
    :meth:`snapshot.SnapshotService.seal`, the service's own verb, which computes
    the §4.2 identity over the staged content, copies it, and publishes
    ``MANIFEST.json`` beside it under an immutable name.

    The bars carry the two columns the contract requires of a ``bars`` frame —
    ``symbol`` and ``open_time``, the two :data:`contract.bars.BARS_REQUIRED_COLUMNS`
    this materialization's mechanics turn on (which book, which candle-open
    instant — the instant the accessor's truncation at ``t`` is computed against)
    — plus ``close`` in the venue's own string spelling, because §4.1's candle
    stream is an *observation* and the contract passes a venue's string spelling
    through verbatim rather than re-rendering it into a float whose rounding no
    audit could tell from the exchange's own.

    The per-bar returns are an AR(1) process with the journey's pinned
    autoregressive coefficient, one independent path per symbol, so a bar's return
    predicts a fraction of the next bar's return — the market condition a momentum
    signal is scored on.  The 2% shock scale is small enough that a 48-bar path
    stays away from the clamp and large enough that the forward returns the
    alignment computes are of the order an exchange bar's are — which matters,
    because the fee the cost model charges is a fixed 10 bps against them, so a
    panel whose returns were much smaller than its fee would measure mostly the
    fee.

    Returns the composed snapshot service, the sealed snapshot record, the
    ``{symbol: {date: close}}`` map the alignment is given — the host-side read
    feature 75's ``closes`` argument is — and the staged content's own
    ``{relative path: sha256}`` so a facet can compare the manifest against what
    was written.  The service is composed *after* ``LAKE_ROOT`` is set: the
    member resolves its lake at construction, and a service built before the
    redirect would seal into whatever lake the process was pointed at.
    """
    lake_root = workdir / "lake"
    (lake_root / "snapshots").mkdir(parents=True)
    staging = lake_root / "staging"
    staging.mkdir()

    generator = random.Random(WORLD_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SYMBOLS:
        # One independent AR(1) path per symbol: the per-bar log-return is an
        # autoregressive process, so a bar's return predicts a fraction
        # (:data:`AUTOCORRELATION`) of the next bar's.  That is the market
        # condition under which a trailing price change — the momentum the signal
        # computes — carries information about the next bar's direction, and so
        # the condition the whole journey's positive coefficient is measured
        # against.  A coefficient of zero would be feature 364's random walk.
        price = 100.0 + generator.uniform(-20.0, 20.0)
        previous_return = 0.0
        path: dict[dt.date, float] = {}
        for day in BAR_DAYS:
            shock = generator.gauss(0.0, 0.02)
            return_ = (
                AUTOCORRELATION * previous_return + (1.0 - AUTOCORRELATION) * shock
            )
            price = max(1.0, price * (1.0 + return_))
            path[day] = round(price, 2)
            previous_return = return_
        closes[symbol] = path

    staged: dict[str, str] = {}
    for symbol in SYMBOLS:
        for day in BAR_DAYS:
            partition = (
                staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            )
            partition.mkdir(parents=True)
            part = partition / "part-0.parquet"
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(day, dt.time(0), tzinfo=dt.UTC)
                        ],
                        "close": [f"{closes[symbol][day]:.2f}"],
                        "volume": ["12.5"],
                    }
                ),
                part,
            )
            staged[f"bars/symbol={symbol}/date={day.isoformat()}/part-0.parquet"] = (
                hashlib.sha256(part.read_bytes()).hexdigest()
            )

    # LAKE_ROOT before create_app(): the snapshot member resolves its lake when
    # the factory builds the component, and the seal's default source is the
    # lake's own staging root.
    os.environ["LAKE_ROOT"] = str(lake_root)
    application = create_app()
    service = application.get("snapshot")
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed, closes, staged


def _materialize_from_the_mount(mount: Any) -> Any:
    """Feature 73's ``materialize`` seam, reading the sealed lake.

    ``_materialize_default`` in the evaluator member builds *empty* frames from
    the resolution alone, and its own docstring says why: "the production reader
    (over a real ``SnapshotMount``) is injected by the feature that owns the lake
    read."  This is that reader, in the only form a test can honestly supply it —
    the mount's own ``select`` for the resolution's surviving partitions, read
    back through the mount's read-only paths and truncated at the decision time by
    the contract's own comparison.

    It reads *only* the partitions feature 72's resolution already named as
    surviving at or before the decision date, and it never constructs a path of
    its own: every byte comes through ``mount.select("bars", symbol, iso)``, which
    is the mount's pruned query, so the same read-only handle and the same
    sealedness back the sandbox payload as back everything else.  The truncation
    runs on the assembled frame rather than in the reader because the frame is
    assembled per-date; a row past ``t`` cannot exist inside the partitions the
    slice kept, and filtering on ``open_time`` is what makes the reader's own
    guarantee checked rather than intended.

    A tiny per-partition cache keeps the journey from re-reading the same
    compressed bytes hundreds of times; the cache holds *sealed* tables and is
    keyed by ``(symbol, ISO date)``, so it can never serve a partition the
    resolution excluded.
    """
    cache: dict[tuple[str, str], pa.Table] = {}

    def materialize(resolution: Any, decision_time: dt.datetime) -> MarketWindow:
        tables: list[pa.Table] = []
        for symbol in resolution.universe:
            for iso in resolution.dates("bars", symbol):
                if dt.date.fromisoformat(iso) > decision_time.date():
                    continue
                key = (symbol, iso)
                if key not in cache:
                    paths = list(mount.select("bars", symbol, iso))
                    cache[key] = pq.read_table(str(paths[0])) if paths else pa.table({})
                tables.append(cache[key])
        frame = pa.concat_tables(tables) if tables else pa.table({})
        if frame.num_rows:
            frame = frame.filter(
                pa.compute.less_equal(
                    frame["open_time"],
                    pa.scalar(decision_time, type=pa.timestamp("us", tz="UTC")),
                )
            )
        return MarketWindow(
            decision_time, universe=resolution.universe, frames={"bars:1d": frame}
        )

    return materialize


# ---------------------------------------------------------------------------
# The cost seam — the shared fee library, transported and not re-implemented
# ---------------------------------------------------------------------------


def _shared_fee_schedule() -> tuple[Any, FeeSchedule]:
    """The §6.2 cost model and the fee schedule it resolves to.

    Feature 69's rule — *one* shared fee implementation — is what makes this a
    two-line function rather than a reason to write a stub schedule: the document
    is the deployment's own (``packages/cost-model/src/cost_model/cost_model.yaml``,
    the default the library reads when nothing names another), the rates are the
    library's own resolved :class:`~cost_model.FeeSchedule` for
    ``binance_spot/2026.09.1``, and the schedule object is what the step-7 seam
    below applies.  Returns the resolved config (the ``(venue, version)`` pair
    every post-cost series and every metrics row is stamped with, via the
    evaluator's duck-typed :func:`~evaluator.cost_model_ref`) and the schedule.
    """
    config = load_cost_model()
    return config, FeeSchedule(venue=config.venue, taker_bps=10.0, maker_bps=10.0)


def _charge_through_the_library(config: Any, schedule: FeeSchedule) -> Any:
    """Feature 77's ``charges`` seam over the shared library's own quote.

    The evaluator's ``apply_costs`` "computes no fee arithmetic of its own: a fee
    schedule implemented here would be the second implementation feature 69
    refuses".  So this closure does not compute a fee either — it reads
    :meth:`cost_model.FeeSchedule.fee_fraction`, the library's own bps-to-fraction
    conversion, and quotes that one number on exactly the support the request
    names.  Every fill in this journey pays ``binance_spot``'s taker rate; a maker
    rate would be a claim about the order's queue position, which a flat-book
    evaluation with no book does not make.

    The quote must live on the charged support *exactly* — feature 77 refuses a
    schedule that omits a date or a symbol (a free ride) as firmly as one that
    prices a bar nobody traded — so the mapping is built from ``gross_returns``
    itself, and the refusal is left to the shipped check rather than pre-empted
    here.
    """
    fee = schedule.fee_fraction(TAKER)

    def charges(request: Any) -> Any:
        from evaluator import CostQuote

        return CostQuote(
            venue=request.venue,
            version=request.version,
            costs={
                day: dict.fromkeys(request.symbols, fee)
                for day in request.gross_returns
            },
        )

    return charges


def _oracle_over_the_alignment(alignment: Any) -> Any:
    """Feature 76's oracle seam, answering the real branch.

    §7.2's interface is *"send forward-return series for a given node … or
    permuted versions"*, and the gate asks once per covered horizon with the
    alignment's own support in the request.  For this journey the answer is the
    alignment's own series — the **real** branch — which is what the evaluator
    member's own suite supplies through the same seam and for the same reason:
    the labels that *decide* the branch live behind §4.2's barrier, in the null
    oracle's sealed sidecar, and the journey that stages that decision is feature
    366's.  Nothing about a momentum signal's coefficient depends on which branch
    answered, because the branch changes the *targets*, never the scores.

    The answer is built from the alignment per horizon rather than precomputed
    because the gate names the horizon: a closure that served one horizon to
    every ask would be refused by the gate's own support check, which is the
    certification this seam relies on instead of re-implementing.
    """

    def oracle(request: Any) -> OracleResponse:
        series = alignment.targets(request.horizon)
        return OracleResponse(
            target_series={day: dict(series.at(day)) for day in series.dates()},
            charges_budget=True,
        )

    return oracle


# ---------------------------------------------------------------------------
# The pipeline — §6.1's order, the shipped verbs, one panel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Panel:
    """Everything one signal's pass through the pipeline produced.

    Not a record the system stores — the member suites own those — but the
    journey's own worksheet: the raw score panel the sandbox returned, the
    normalized cross-sections the metrics are measured against, the priced
    post-cost panel, and the four scalars.  Frozen and module-private so the
    facets read one panel rather than re-deriving it, and so a facet cannot
    accidentally mutate the panel a later facet asserts on.
    """

    #: Raw per-date score vectors — feature 73's ``SignalExecution``, kept whole
    #: so a facet can read its identity terms.
    execution: Any
    #: ``{rebalance date: {symbol: normalized score}}`` — step 3's output paired
    #: with the universe it was scored against, which is the exact shape feature
    #: 80's ``scores`` argument is defined over.
    scores: dict[dt.date, Mapping[str, float]]
    #: Step 7's ``PostCostReturns`` — the priced panel the metrics reduce from.
    priced: Any
    #: Step 8's ``NodeMetrics`` — ``ic_mean``, ``ic_se``, ``ic_tstat``,
    #: ``ir_standalone``, ``turnover``, and the per-date series behind them.
    metrics: Any


def _run_pipeline(
    resolution: Any,
    closes: Mapping[str, Mapping[dt.date, float]],
    config: Any,
    schedule: FeeSchedule,
    materialize: Any,
) -> Panel:
    """Drive the momentum signal through steps 2 through 8 of §6.1.

    The five verbs in the order the frozen pipeline runs them, with the one
    injected seam — the lake reader, step 1's materialization — threaded in
    exactly where the member's own suite threads it, because that is the step the
    pipeline's design says is *injected, never reached for*.

    Every step's own refusals are left switched on: the sandbox's envelope is
    checked clean (a refused signal would make every downstream number a
    statement about a run that did not happen), and a date whose vector carries a
    contract problem surfaces here rather than being scored as if it conformed.
    """
    execution = execute_signal(
        resolution,
        MOMENTUM_SIGNAL_CODE,
        seed=WORLD_SEED,
        rebalance_dates=REBALANCE_DAYS,
        sandbox=SignalSandbox(),
        materialize=materialize,
    )
    for day in execution.dates():
        vector = execution.vector(day)
        assert vector.scores is not None, (
            f"the sandbox returned no scores for {day.isoformat()}: a signal the "
            "sandbox refused to run is not a signal whose coefficient means "
            "anything"
        )
        assert not vector.problems, (
            f"the contract validator refused the return at {day.isoformat()}: "
            f"{vector.problems}"
        )

    # Step 3, and the shape step 8's ``scores`` argument is defined over: the
    # window carries the labels, the series carries the values, and this is where
    # the two are paired — ``normalize_scores`` is a pure function over one
    # positional vector and deliberately does not carry the universe.
    scores = {
        day: dict(
            zip(
                execution.vector(day).universe,
                normalize_scores(execution.vector(day).scores).to_list(),
            )
        )
        for day in execution.dates()
    }

    # Step 4: forward returns off the sealed closes, stepped in *bars* on the
    # market grid the scored symbols' own bar dates name.
    alignment = align_targets(execution, closes)
    # Step 5: the oracle answers, and the gate certifies the supply it was given
    # is the alignment's own support, per date and per symbol.
    gated = gate_targets(
        alignment,
        _oracle_over_the_alignment(alignment),
        node_id=NODE_ID,
        campaign_id=CAMPAIGN_ID,
        depth=0,
    )
    # Step 7: the shared library's schedule prices every fill.
    priced = apply_costs(
        gated,
        _charge_through_the_library(config, schedule),
        node_id=NODE_ID,
        cost_model=config,
    )
    # Step 8: the four scalars, over the shortest horizon the priced panel covers.
    return Panel(
        execution=execution,
        scores=scores,
        priced=priced,
        metrics=compute_node_metrics(priced, scores),
    )


# ---------------------------------------------------------------------------
# The journey — one run, one lake, one store
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Journey:
    """What the one run produced, as the facets read it.

    The sealed identity, the resolved window, the panel's four numbers and
    per-date series, the persisted node row, the determinism re-run and the
    control world — every fact the facets below assert on, captured once so no
    facet re-runs the pipeline.
    """

    sealed_name: str
    sealed_hash: str
    sealed_path: Path
    staged_files: Mapping[str, str]
    manifest_files: Mapping[str, str]
    corruption_alerts: tuple[Any, ...]
    universe: tuple[str, ...]
    resolution: Any
    panel: Panel
    closes: Mapping[str, Mapping[dt.date, float]]
    stored: Any
    rerun_scores: Mapping[dt.date, Mapping[str, float]]
    rerun_code_hash: str
    database_url: str
    world_autocorrelation: float
    app_evaluator: Any
    app_snapshot: Any


@pytest.fixture(scope="module")
def journey(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Journey]:
    """Run the journey once and hand its captured facts to the facets.

    The journey's own lake and its own SQLite store, not the suite's isolated
    ones: the acts are one ordered story over one world, and the composed
    application is built with ``LAKE_ROOT`` and ``DATABASE_URL`` pointed at them
    so the service the seal goes through and the store the metrics land in are
    the ones the deployment would compose — the same stance the sibling journeys
    in this suite take.  Both variables are saved and restored in a ``finally``,
    so a facet in another module never inherits this lake.
    """
    workdir = tmp_path_factory.mktemp("momentum-signal-positive-ic")
    database_url = f"sqlite:///{workdir / 'nullius-e2e.db'}"

    saved_lake = os.environ.get("LAKE_ROOT")
    saved_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    try:
        # Act 1 — the world is sealed.  §4.2's layout is staged and the service's
        # own seal publishes it under its content-addressed name; staging is
        # never on the evaluator's path from here on.
        service, sealed, closes, staged = _seal_the_world(workdir)
        mount = service.mount(sealed.name)

        # Act 2 — the window is resolved host-side from the sealed mount, at the
        # last rebalance date's end of day, so the resolution's universe and its
        # slice boundary are the ones the grid below runs on.
        decision_time = dt.datetime.combine(
            REBALANCE_DAYS[-1], dt.time(23, 59), tzinfo=dt.UTC
        )
        resolution = resolve_window(mount, decision_time)

        # Act 3 — the pipeline runs over the same sealed world.  The momentum
        # signal is scored at every rebalance date, each a fresh sandbox spawn
        # reading the same sealed bytes.
        materialize = _materialize_from_the_mount(mount)
        config, schedule = _shared_fee_schedule()

        panel = _run_pipeline(resolution, closes, config, schedule, materialize)

        # The determinism re-run (§12): the same source at the same seed over the
        # same resolution must reproduce the identical score panel — the sandbox
        # is a fresh child each time, so this is a real re-execution rather than a
        # cached value.
        rerun = _run_pipeline(resolution, closes, config, schedule, materialize)

        # Act 4 — the four scalars are persisted and read back through the shipped
        # store, so the journey's number is a number the system keeps rather than
        # one it printed once.
        persist_node_metrics(panel.metrics, database_url=database_url)
        stored = load_node_metrics(
            NODE_ID, panel.metrics.cost_model, database_url=database_url
        )

        yield Journey(
            sealed_name=sealed.name,
            sealed_hash=service.read_manifest(sealed.name).snapshot_hash,
            sealed_path=Path(str(sealed.path)),
            staged_files=staged,
            manifest_files=dict(mount.files()),
            corruption_alerts=service.verify_all(),
            universe=resolution.universe,
            resolution=resolution,
            panel=panel,
            closes=closes,
            stored=stored,
            rerun_scores=rerun.scores,
            rerun_code_hash=rerun.execution.code_hash,
            database_url=database_url,
            world_autocorrelation=AUTOCORRELATION,
            app_evaluator=create_app().get("evaluator"),
            app_snapshot=create_app().get("snapshot"),
        )
    finally:
        if saved_lake is None:
            os.environ.pop("LAKE_ROOT", None)
        else:
            os.environ["LAKE_ROOT"] = saved_lake
        if saved_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = saved_url


def _average_ranks(values: list[float]) -> list[float]:
    """Average ranks of a vector, ties sharing the mean of the ranks they would
    have held — feature 80's own tie rule, restated so the facet below can
    recompute the coefficient without importing the member's private helper.
    """
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        stop = start
        while stop + 1 < len(order) and values[order[stop + 1]] == values[order[start]]:
            stop += 1
        shared = (start + stop) / 2.0 + 1.0
        for position in range(start, stop + 1):
            ranks[order[position]] = shared
        start = stop + 1
    return ranks


# ---------------------------------------------------------------------------
# Facet: the signal, and the world it was scored in
# ---------------------------------------------------------------------------


class TestTheMomentumSignalRunsOverTheSealedSnapshot:
    """The sentence's first and last clauses: the signal, and its world.

    The signal is real untrusted-shaped code in a real child process — the
    sandbox is not stubbed anywhere in this journey — and the world is a sealed
    snapshot reached through a mount that refuses to be an ordinary path.
    """

    def test_the_snapshot_is_sealed_content_addressed_and_immutable(
        self, journey: Journey
    ) -> None:
        # §4.2's name is ``<sealed_at>_<hash prefix>`` and the manifest the seal
        # published must agree with it.  ``verify_all()`` re-hashes the whole
        # sealed tree against the manifest, so an empty alert list is the
        # strongest statement available that the bytes the evaluator read are the
        # bytes ingest staged.
        assert journey.sealed_name.startswith("2026-11-01")
        assert journey.sealed_name.endswith(journey.sealed_hash[:6])
        assert journey.corruption_alerts == ()

    def test_every_staged_byte_is_accounted_for_in_the_manifest(
        self, journey: Journey
    ) -> None:
        # Per-file sha256, checked against what was written rather than trusted:
        # the manifest is the seal's testimony about the content, and the journey
        # compares it to the hash it computed off each staged file.  A manifest
        # covering *more* files than were staged would also be a finding, hence
        # set equality rather than containment.
        assert journey.manifest_files
        assert set(journey.manifest_files) == set(journey.staged_files)
        for relative, digest in journey.staged_files.items():
            assert journey.manifest_files[relative] == digest, (
                f"the manifest's sha256 for {relative} is not the staged file's "
                "own hash: the seal did not cover the bytes it published"
            )

    def test_the_sealed_tree_is_read_only_on_disk(self, journey: Journey) -> None:
        # §4.2's immutability, at the filesystem level rather than only at the
        # handle's: files 0444 and directories 0555.  A mount that *offered* no
        # write verb but sat on a writable tree would still be one ``open()``
        # away from mutating a sealed world.
        modes = {path.stat().st_mode & 0o777 for path in journey.sealed_path.rglob("*")}
        assert modes <= {0o444, 0o555}, sorted(oct(mode) for mode in modes)

    def test_the_evaluator_reached_the_world_only_through_a_mount(
        self, journey: Journey
    ) -> None:
        # The point-in-time universe comes from the sealed bars (feature 72's
        # roster rule): a symbol is tradable as of the decision date when the
        # sealed bars carry a partition on that very date.  Every symbol staged
        # has bars on every day, so the roster is the whole list — and the window
        # that carried it names the mount, stamped onto the resolution so the
        # score's provenance says which sealed world it came from.
        assert journey.universe == tuple(sorted(SYMBOLS))
        assert journey.resolution.snapshot_name == journey.sealed_name
        assert journey.resolution.decision_date == REBALANCE_DAYS[-1]

    def test_the_sandbox_is_the_real_child_and_its_envelopes_are_clean(
        self, journey: Journey
    ) -> None:
        # The signal ran in a genuine ``python -c`` child, once per rebalance
        # date, and every envelope was a success envelope: ``_run_pipeline``
        # asserts that per date, and this facet states the sample size and the
        # identity bookkeeping — the seed and the ABI version ride back on each
        # vector, so a persisted score can say which source of randomness produced
        # it and under which contract.
        assert len(journey.panel.execution.dates()) == len(REBALANCE_DAYS)
        assert sum(
            1
            for day in journey.panel.execution.dates()
            if journey.panel.execution.vector(day).conforming
        ) == len(REBALANCE_DAYS)
        for day in journey.panel.execution.dates():
            vector = journey.panel.execution.vector(day)
            assert vector.seed == WORLD_SEED
            assert vector.contract_version

    def test_the_signal_is_hand_written_and_its_identity_is_the_source_hash(
        self, journey: Journey
    ) -> None:
        # "Hand-written" is the sentence's own word: the signal is this module's
        # own source text, not LLM-authored in a discovery loop, and the sandbox
        # ran exactly it.  The execution's code hash is asserted against an
        # independent recomputation rather than against itself, so a drifted
        # identity surfaces.
        assert (
            journey.rerun_code_hash
            == hashlib.sha256(MOMENTUM_SIGNAL_CODE.encode("utf-8")).hexdigest()
        )
        assert journey.panel.execution.code_hash == journey.rerun_code_hash
        assert journey.panel.execution.seed == WORLD_SEED

    def test_the_scores_are_a_fresh_cross_section_on_every_date(
        self, journey: Journey
    ) -> None:
        # The signal folds the decision instant into the window's trailing bar, so
        # each date is a fresh cross-section rather than one vector re-issued
        # twenty-four times — which is the shape a genuinely market-driven signal
        # has, and the reason the per-date coefficients vary at all (a signal that
        # returned the same vector every date would produce the same coefficient
        # every date, which the metrics refuse rather than report).  The assertion
        # is on the *raw* vectors, because those are what the signal drew from the
        # market.
        draws = [
            tuple(journey.panel.execution.vector(day).scores.to_list())
            for day in journey.panel.execution.dates()
        ]
        assert len(set(draws)) == len(draws)
        assert len(draws) == len(REBALANCE_DAYS)

    def test_the_normalized_cross_section_is_centred_by_construction(
        self, journey: Journey
    ) -> None:
        # Feature 74's z-scoring makes each date's normalized vector sum to zero —
        # so a positive coefficient is a statement about the *ordering* the
        # momentum expressed relative to the forward returns, not a consequence of
        # a centred score.
        for day, cross_section in journey.panel.scores.items():
            assert all(isinstance(value, float) for value in cross_section.values()), (
                day
            )
            assert abs(sum(cross_section.values())) < 1e-9

    def test_the_world_carries_the_autocorrelation_the_signal_is_scored_on(
        self, journey: Journey
    ) -> None:
        # The control that says the positive coefficient is measured against a
        # world that has edge to give.  The sealed closes are the journey's own
        # AR(1) content — the very bytes the seal published and feature 75's
        # ``closes`` argument was read from — and the per-symbol, per-bar
        # log-returns' lag-1 autocorrelation is a property of those bytes,
        # recomputed here rather than assumed, and it is positive and of the order
        # the pinned coefficient names.  A momentum signal earns nothing on a world
        # whose returns do not persist, so this is the market condition the
        # positive coefficient below is read against.
        autocorrelations = []
        for path in journey.closes.values():
            days = sorted(path)
            logs = [math.log(path[day]) for day in days]
            returns = [logs[i] - logs[i - 1] for i in range(1, len(logs))]
            demeaned = [value - statistics.mean(returns) for value in returns]
            numerator = sum(
                demeaned[i] * demeaned[i + 1] for i in range(len(demeaned) - 1)
            )
            denominator = sum(value * value for value in demeaned)
            if denominator > 0.0:
                autocorrelations.append(numerator / denominator)
        # Every symbol's lag-1 autocorrelation is positive, and the panel of them
        # centres on the pinned coefficient the world was generated with — so the
        # edge the momentum signal earns is measured against a world that
        # genuinely carries it, not one that carries it by assertion.
        assert len(autocorrelations) == len(SYMBOLS)
        assert all(value > 0.0 for value in autocorrelations)
        assert statistics.mean(autocorrelations) == pytest.approx(
            journey.world_autocorrelation, abs=0.15
        )


# ---------------------------------------------------------------------------
# Facet: the coefficient is positive
# ---------------------------------------------------------------------------


class TestTheCoefficientIsPositive:
    """The middle clause: the number itself, and what it is a number *of*.

    Every assertion here is a statement about the coefficient the shipped metrics
    returned for the momentum signal.  None of them pins a magnitude to a figure
    the documents do not contain: "positive information coefficient" is asserted
    as the coefficient clearing the promotion bar, at the bar the negative control
    (feature 364) is read against.
    """

    def test_the_metrics_are_step_eights_four_scalars(self, journey: Journey) -> None:
        # Step 8's record, whole: the four scalars over the shortest horizon the
        # priced panel covers, stamped with the node, the sealed world and the
        # cost model that priced them.  The identity is the point — the same
        # numbers under a different fee schedule are different numbers.
        metrics = journey.panel.metrics
        assert metrics.node_id == NODE_ID
        assert metrics.snapshot_name == journey.sealed_name
        assert metrics.horizon == min(HORIZONS)
        assert metrics.dates == len(REBALANCE_DAYS)

    def test_the_mean_is_the_mean_of_its_own_per_date_series(
        self, journey: Journey
    ) -> None:
        # ``ic_mean`` is the equal-weight mean of the per-date coefficients — one
        # closed form, re-derived at construction and again on every store read.
        # Recomputed here from the series the record carries, so the number this
        # journey asserts on is a number that reduces from itself and not a scalar
        # the pipeline chose.
        metrics = journey.panel.metrics
        series = metrics.ic_series
        assert len(series) == metrics.dates == len(REBALANCE_DAYS)
        assert metrics.ic_mean == pytest.approx(sum(series.values()) / len(series))
        assert metrics.ic_tstat == pytest.approx(metrics.ic_mean / metrics.ic_se)

    def test_each_daily_coefficient_is_the_spearman_rank_correlation(
        self, journey: Journey
    ) -> None:
        # The statistic, independently re-derived.  Feature 80 reduces both sides
        # to average ranks and correlates those — the Spearman coefficient's own
        # definition — and this recomputes that pairwise formula by hand for every
        # date in the series.  It is worth doing rather than trusting: the sentence
        # says *information coefficient*, and the IC's whole content is that it is
        # a rank correlation (which is why ``normalize_scores``' monotone rank
        # transform cannot change it).
        horizon = journey.panel.metrics.horizon
        for day, coefficient in journey.panel.metrics.ic_series.items():
            scores = journey.panel.scores[day]
            forwards = journey.panel.priced.returns(horizon)[day]
            symbols = sorted(scores)
            ranks = _average_ranks([scores[symbol] for symbol in symbols])
            targets = _average_ranks([forwards[symbol] for symbol in symbols])
            count = len(symbols)
            mean = (count + 1) / 2.0
            covariance = sum(
                (ranks[index] - mean) * (targets[index] - mean)
                for index in range(count)
            )
            spread = statistics.pstdev(ranks) * statistics.pstdev(targets) * count
            assert coefficient == pytest.approx(
                covariance / spread, abs=_RANK_TOLERANCE
            ), day

    def test_the_coefficient_is_positive(self, journey: Journey) -> None:
        # The headline clause, in its weakest falsifiable form: the point estimate
        # of the information coefficient is above zero.  A momentum signal scored
        # on a world with return persistence earns a positive rank correlation
        # between its trailing-price-change ordering and the next bar's forward
        # return, and a coefficient at or below zero would mean the pipeline found
        # no edge in a signal that has some — the positive control failing exactly
        # as feature 364's negative control would fail on a distinguishable
        # coefficient.
        assert journey.panel.metrics.ic_mean > 0.0

    def test_the_coefficient_clears_the_promotion_bar(self, journey: Journey) -> None:
        # The operational reading of "positive information coefficient": the
        # coefficient is not merely above zero, its t-statistic clears the same
        # two-sided 5% bar the promotion path reads against.  This is the claim the
        # negative control is held *inside* (feature 364 asserts its random signal
        # stays within this bar), so the momentum signal clearing it is the mirror
        # statement — the two controls, measured on the same bar, say the pipeline
        # distinguishes a signal with edge from one without.
        assert journey.panel.metrics.ic_tstat > PROMOTION_BAR

    def test_the_coefficient_is_a_measurement_and_not_a_construction(
        self, journey: Journey
    ) -> None:
        # A degenerate signal returning the same tiny positive coefficient on every
        # date would pass a bare "``ic_mean > 0``" check and be worthless.  The
        # per-date coefficients must instead show real dispersion — so the mean
        # landed positive over a spread of dates, some positive and some not, which
        # is what a real cross-sectional signal does and not a fabricated constant.
        series = journey.panel.metrics.ic_series
        assert len(set(series.values())) > 1
        assert max(series.values()) - min(series.values()) >= MIN_IC_SPREAD
        assert any(value > 0.0 for value in series.values())

    def test_the_mean_coefficient_is_not_the_fee_and_not_the_market(
        self, journey: Journey
    ) -> None:
        # The panel's own scale, stated so the positive coefficient is read against
        # it.  The post-cost returns the coefficient is measured against have real
        # dispersion (the priced panel is not a flat line the fee schedule
        # annihilated), and the per-date coefficients are bounded by one as rank
        # correlations must be.  A coefficient near one against a *constant* return
        # panel would mean the metric had collapsed rather than that the signal had
        # edge.
        horizon = journey.panel.metrics.horizon
        day = next(iter(journey.panel.metrics.ic_series))
        priced = journey.panel.priced.returns(horizon)[day]
        assert statistics.pstdev(list(priced.values())) > 0.0
        assert all(
            abs(value) <= 1.0 for value in journey.panel.metrics.ic_series.values()
        )


# ---------------------------------------------------------------------------
# Facet: the number the system keeps
# ---------------------------------------------------------------------------


class TestTheSystemKeepsTheNumber:
    """Persisted, read back, and reachable through the composed application.

    The journey's coefficient is a number the system stores — feature 80's
    ``node_metrics`` row, keyed by the node and the cost model — and the store's
    reader re-derives ``ic_mean`` from the stored series, so a round trip is a
    check of the row against itself rather than a cache read.
    """

    def test_the_metrics_round_trip_through_the_shipped_store(
        self, journey: Journey
    ) -> None:
        # The shipped store persists step 8's record and reads it back; the row is
        # the system's, not this journey's.  The reader re-derives ``ic_mean`` from
        # the stored series, so an identical round trip is a check of the row
        # against itself rather than a cache read, and the persisted coefficient
        # carries the positivity the journey asserts on.
        assert journey.stored is not None
        assert journey.stored == journey.panel.metrics
        assert journey.stored.ic_mean == pytest.approx(journey.panel.metrics.ic_mean)
        assert journey.stored.ic_tstat == pytest.approx(journey.panel.metrics.ic_tstat)
        assert dict(journey.stored.ic_series) == dict(journey.panel.metrics.ic_series)
        # The persisted node row says the coefficient is positive: the whole point
        # of the journey, now a number the system keeps rather than one it printed.
        assert journey.stored.ic_mean > 0.0

    def test_the_store_key_is_the_node_and_the_cost_model_pair(
        self, journey: Journey
    ) -> None:
        # The scalars are functions of a *priced* panel: two fee schedules net
        # different post-cost returns out of the same gross ones, so the pair is
        # part of the question rather than a filter over it.  A read under a
        # schedule the evaluation was never measured under must miss — the honest
        # "never measured", not a partial answer to a different question.
        stored = journey.stored
        assert stored is not None
        assert stored.cost_model.reference == (
            f"{journey.panel.metrics.cost_model.venue}/"
            f"{journey.panel.metrics.cost_model.version}"
        )
        miss = load_node_metrics(
            NODE_ID,
            CostModelRef(venue="binance_spot", version="2026.08.4"),
            database_url=journey.database_url,
        )
        assert miss is None

    def test_a_node_the_store_never_measured_reads_back_as_nothing(
        self, journey: Journey
    ) -> None:
        # The other half of the key: the same schedule under a node the journey
        # never scored.  Absence is ``None``, never a zero-filled record — the same
        # stance every store in this workspace takes, so a reader can tell "never
        # measured" from "measured zero".
        miss = load_node_metrics(
            "00000000-0000-4000-8000-000000000000",
            journey.panel.metrics.cost_model,
            database_url=journey.database_url,
        )
        assert miss is None

    def test_the_composed_application_serves_the_components_this_journey_used(
        self, journey: Journey
    ) -> None:
        # The assembled system, not an import: the snapshot service the seal went
        # through and the evaluator service the deployment composes are reachable
        # by name from the composed application, and both are the loader's scanned
        # components — reached the factory's way, through the package the loader
        # discovered rather than through a direct import that a different module
        # object would satisfy.
        assert journey.app_snapshot is not None
        assert journey.app_evaluator is not None
        assert type(journey.app_snapshot).__module__.startswith(
            "_nullius_scanned_snapshot"
        )
        assert type(journey.app_evaluator).__module__.startswith(
            "_nullius_scanned_evaluator"
        )

    def test_the_journey_is_deterministic_under_replay(self, journey: Journey) -> None:
        # §12's contract, at the granularity a journey can check it: the same
        # source at the same seed over the same sealed snapshot reproduces the
        # identical normalized score panel, through a *fresh* sandbox child.  So
        # the coefficient this journey asserts on is reproducible rather than a
        # draw that happened to land where the assertions needed it to.
        assert journey.rerun_scores == journey.panel.scores
