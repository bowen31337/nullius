"""Feature 364: the end-to-end journey — a random signal returns an information
coefficient indistinguishable from zero across the sealed snapshot.

app_spec.xml, "End-to-End Verification", feature 364: *"System passes an
end-to-end test where a random signal returns an information coefficient
indistinguishable from zero across the sealed snapshot."*  The sentence is one
of the repository's M0 exit criteria, spelled twice more in the same words —
docs/alpha-engine-prd.md:570 (*"evaluator reproduces known results … a random
signal shows IC indistinguishable from zero"*) and
docs/nullius-tech-architecture.md:991 — and it is the negative control the whole
evaluation story rests on: if a signal carrying no information still came back
with a distinguishable coefficient, nothing the evaluator reports about a
signal that does carry information could be believed.  Everything else in the
pipeline would reproduce perfectly and the system would still be broken.

The journey is feature 363's journey run backwards — the same pipeline, driven
by a signal with nothing in it — and it names four clauses, each staged through
the shipped system's own public seams and none of it staged by hand:

**A random signal.**  LLM-authored-shaped source, handed to the *real*
:class:`~evaluator.SignalSandbox`: a genuine ``python -c`` child of the same
interpreter, under POSIX rlimits and a wall-clock watchdog, over the payload
channel (feature 73, §5.2).  Not a stub, and not a skip marker — the sandbox
spawns once per rebalance date and every envelope is checked clean, because a
journey that asserted a coefficient over a signal the sandbox refused to run
would be asserting a number about nothing.  Inside the sandbox the signal draws
from :class:`random.Random` seeded from its own required ``seed`` argument
(feature 11: the seed is required precisely so a signal never samples randomness
by default) *and* from the decision instant the window carries, so the
cross-section is a fresh draw on every date — the shape a genuinely random
signal has, rather than the same arbitrary vector re-issued twenty-four times.
It reads the sealed bars for their row count, so the window it was handed is
observably real to it and observably excluded from what it returns.

**Returns an information coefficient.**  The five steps between the signal and
the number are the shipped pipeline's own verbs, in §6.1's order: feature 72's
:func:`~evaluator.resolve_window` slices a *sealed* mount to the decision time
and resolves the point-in-time universe; feature 74's
:func:`~evaluator.normalize_scores` ranks and z-scores each date's raw vector
(so the coefficient measures the *ordering* the signal expressed, not the scale
it chose); feature 75's :func:`~evaluator.align_targets` aligns post-rebalance
forward returns; feature 76's :func:`~evaluator.gate_targets` asks an oracle
whose answer is the alignment's own series for the real branch — the
real-branch seam the evaluator's own member suite supplies the same way, since
*which* branch the oracle resolves belongs to feature 366's journey and the
labels live behind §4.2's barrier, not here; feature 77's
:func:`~evaluator.apply_costs` nets the returns through the shared §6.2 fee
library, priced from the cost model document's own resolved ``FeeSchedule``
(``binance_spot/2026.09.1``, 10 bps both sides) rather than a second fee
arithmetic — feature 69 refuses a second fee implementation, so the schedule
here is a *transport* of the library's own fraction and computes nothing; and
feature 80's :func:`~evaluator.compute_node_metrics` reduces the per-date
Spearman coefficients to ``ic_mean``, ``ic_se`` and ``ic_tstat`` — the
coefficient the sentence names, in the spelling the system reports it in.

**Indistinguishable from zero.**  This is the clause with no number in it, and
the journey is careful about what it can honestly assert.  The spec names no
threshold for *nullity* — prd §10 and architecture §6.3 give a t-statistic bar
for *promotion*, not for *nullity* — and, more importantly, ``ic_tstat`` is
itself a random variable: under the null it is asymptotically standard normal *by
construction*, so "``|t| < 1.96``" is a statement a *correct* pipeline makes only
about 95% of the time and a *broken* pipeline makes just as often.  One draw at
one seed therefore cannot distinguish a working system from a broken one, and
this module does not pretend otherwise.  It asserts the property in the forms
that are falsifiable:

* **the zero is inside the error bar**: for the main run, ``ic_mean`` sits
  within 1.96 standard errors of zero and ``ic_tstat`` inside the conventional
  two-sided 5% bar — the coefficient is not merely small, it is indistinguishable
  from zero *at the precision the same pipeline reports for it*, at the bar the
  promotion path reads against;
* **the coefficient is a measurement, not a fabricated zero**: the per-date
  series is not constant (a constant series makes the standard error zero, which
  the shipped metrics *refuses* rather than reporting a small number for —
  asserted in the controls below) and its coefficients span a wide band, so the
  mean that landed near zero landed there by cancellation rather than by
  construction;
* **the coefficients behave like draws**: over a twelve-seed ladder of the same
  signal on the same sealed world, the signs are mixed, the draws' mean sits
  inside its own error, and — the assertion a bare ``|ic_mean| < ε`` check cannot
  make — the *observed* dispersion of the twelve coefficients matches the
  standard error the pipeline reported for each draw.  A pipeline whose error bar
  was wrong by a factor of two, or a magnitude that happened to be small, would
  pass a threshold check and fail this one.  The ladder also asserts what
  distinguishes a correct pipeline from a broken one at six standard deviations:
  no draw lands at or beyond ``|t| = 3``.  That the ladder *does* show one draw
  in the conventional 5% band is recorded rather than hidden — see
  :data:`LADDER_CROSSING_BAR` — because suppressing it would require choosing
  seeds after seeing them, which is the selection effect the reproduction
  contract (§12) exists to forbid;
* **the bar is not vacuous**: a signal *plugged into the labels* — same window,
  same sandbox, same sample size, same fee schedule, same metrics — is
  distinguishable well beyond the bar, and a signal plugged in *exactly* is
  refused outright by the shipped metrics as a zero standard error.  Together
  these say the pipeline that reports "zero" for a random signal is one that
  reports "not zero" for a signal that is not, at the same n.

**Across the sealed snapshot.**  The window is sliced from a *real* sealed
snapshot: ingest writes §4.2's partition layout into the lake's staging area,
:meth:`snapshot.SnapshotService.seal` publishes it immutably (files ``0444``,
directories ``0555``), and the evaluator reaches it only through
:meth:`snapshot.SnapshotService.mount`'s read-only handle — the same handle §4.2
requires (*"the evaluator can only open sealed snapshots.  Staging is not on its
mount path at all"*).  The journey asserts the sealedness rather than assuming
it: every staged byte is re-hashed and compared against the manifest the seal
published, this lake reports no corruption across that manifest, ``resolve_window``
refuses a raw path and a bare name, and the mount's root refuses every write mode
it offers.  The bars the window carries are the sealed bytes, read back through
the mount's own ``select`` and read-only paths — the production lake reader
feature 73's ``materialize`` seam exists to be injected with — and the snapshot
name and hash the metrics were stamped with are the sealed directory's own.  So
"across the sealed snapshot" is measured, not claimed: the coefficient is stamped
with the identity of the world it was measured in.

**What this journey checks rather than assumes.**  The bars it seals are
generated from a pinned pseudo-random walk, so the *content* is the journey's
own; the seal, the mount, the immutability, the manifest, the window resolution,
the point-in-time universe, the sandbox, the normalization, the alignment, the
gate, the fee library, the metrics and the node-metrics store are all the shipped
system's.  The one seam this journey supplies beside the market data is the
oracle's real-branch answer, because the labels that decide the branch live
behind the barrier and feature 366's journey owns that half; the gate's own
support check certifies the supplied series either way.

**One module, one journey, run once.**  The journey runs its acts once in a
module-scoped fixture over its own lake, its own SQLite store and its own
composed application, and the facet tests below read the sealed snapshot, the
resolved window, the score panel, the four numbers, the twelve-seed ladder and
the control plug-ins out of that one run.  The member suites pin each verb's own
law — the window resolution (packages/evaluator/tests/test_window.py), the
sandbox protocol (test_sandbox.py), the alignment's refusal taxonomy
(test_align.py), the gate's support rule (test_gate.py), the fee library
(packages/cost-model/tests/test_fees.py), the metrics' closed forms
(test_metrics.py), the store's read-back checks (test_metrics_store.py) — and
this module does not re-test them; it asserts the one thing only the composition
can: that a signal with nothing in it, scored through the assembled system over
a sealed world, comes back with a coefficient indistinguishable from zero.
"""

from __future__ import annotations

import datetime as dt
import hashlib
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
    CostQuote,
    NodeMetrics,
    NodeMetricsStore,
    OracleResponse,
    SignalSandbox,
    align_targets,
    apply_costs,
    compute_node_metrics,
    execute_signal,
    gate_targets,
    normalize_scores,
    resolve_window,
)

# The shared tests/e2e/conftest.py puts every declared member's scan root on
# sys.path before this line runs, so the members import by their bare names —
# the workspace contract that no member imports another member, honoured here by
# reaching each through the path the conftest already built.  The factory is
# reachable as ``app.module_loader`` through that same conftest, which is the
# declaration production reads.
from app.module_loader import create_app
from app.modules.evaluator import evaluator_component
from app.modules.snapshot import snapshot_component

# ---------------------------------------------------------------------------
# The sealed world — §4.2's layout, and the universe the window resolves
# ---------------------------------------------------------------------------

#: The symbols the journey's world carries.  Eight is the cross-section the
#: coefficient is computed over on every date: small enough that the whole
#: journey (seal, three-dozen sandbox spawns, a twelve-seed ladder, the store
#: round trip) runs in about a minute and a half, large enough that a per-date
#: Spearman coefficient over it takes values across a decent band rather than a
#: handful of grid points.  A *universe* is sorted and de-duplicated by the
#: resolution, so the spelling here is the roster order.
SYMBOLS = tuple(f"SYM{index:02d}" for index in range(8))

#: The UTC day the sealed history opens on.  A pinned calendar date, never
#: ``date.today()``: the journey is a replay (§12), and a world that moved with
#: the wall clock would report a different coefficient tomorrow.
FIRST_DAY = dt.date(2026, 9, 1)

#: Every day the sealed bars carry, and the trailing span of it the journey
#: rebalances on.  The two are deliberately different lengths: the alignment
#: steps forward *in bars* (feature 75), so a grid that reached the last bar
#: would have no forward return to align at any horizon and the journey would be
#: measuring an empty panel.  Twenty-four rebalance dates with twenty-four days
#: of runway is the sample every facet below is calibrated against, and it is
#: the sample the evaluator's own member suites use — the same n, so the
#: standard errors this journey reads are of the size the rest of the repository
#: reads.
BAR_DAYS = tuple(FIRST_DAY + dt.timedelta(days=offset) for offset in range(48))
REBALANCE_DAYS = BAR_DAYS[:24]

#: The seed of the generated world.  The market is the journey's own content —
#: the pipeline under test does not care whether the prices came from an
#: exchange or from a generator — and pinning the generator makes the whole
#: journey a function of this one integer.
PRICE_SEED = 20260924

#: The seed the main random signal runs under.  It is the *first* of the ladder
#: seeds, chosen before any measurement was taken and not selected for the size
#: of the coefficient it produced: a seed picked because it came out nearest zero
#: would make the headline assertion a statement about the selection rather than
#: about the pipeline, which is exactly the failure mode §12's reproducibility
#: contract forbids.  Its measured figures are recorded in the facets below so a
#: drift in any step surfaces as a changed number rather than a silently
#: different world.
MAIN_SEED = 1

#: The seeds the draw-ladder re-runs the same signal at.  The first twelve, for
#: the same reason.
LADDER_SEEDS = tuple(range(1, 13))

#: How many standard normals the signal accumulates per symbol per date.  Twelve
#: is enough that the resulting score is a draw from an approximately normal law
#: rather than dominated by one variate, and small enough that the sandbox's CPU
#: budget is never in question.  The signal is *inside* the sandbox's
#: payload-only channel, so this is the whole of the work the child does beyond
#: serializing its own output.
DRAWS_PER_SYMBOL = 12

#: The node and campaign identities the evaluation is stamped with.  Canonical
#: UUID text, because every seam that carries them joins to the tree store's
#: ``node.id`` and refuses a spelling that cannot.  Nothing in this journey reads
#: them back from a tree — feature 363's journey owns the persisted node row —
#: but the metrics are keyed by the pair, so the store round-trip below is a
#: round-trip of *this* evaluation.
NODE_ID = "3f1c9b2a-4d5e-4f60-8a71-9b2c3d4e5f60"
CAMPAIGN_ID = "8c7d6e5f-4a3b-4c2d-9e1f-0a9b8c7d6e5f"

#: The two-sided 5% bar.  1.96 is the conventional normal quantile, and it is
#: the *same* number the promotion path's t-statistic bar is read against
#: (architecture §6.3) — so the claim this journey makes is that the random
#: signal would not clear the bar the system promotes on, which is the
#: operational meaning of "indistinguishable from zero" in this codebase.  It is
#: stated here rather than replaced by a magnitude threshold of the journey's own
#: invention, because the documents name no threshold for nullity and a pinned
#: ``|ic_mean| < 0.01`` would be a number the journey chose to make its own test
#: pass.
NULLITY_BAR = 1.96

#: The bar the *ladder* is held to, and the reason it is not :data:`NULLITY_BAR`.
#: Under the null ``ic_tstat`` is asymptotically standard normal, so about one
#: draw in twenty clears 1.96 *whether or not the pipeline is correct* — a ladder
#: asserting "no draw clears 1.96" would fail for a working system 46% of the
#: time over twelve seeds, and passing it would say nothing.  Three is a
#: different claim: ``P(|Z| >= 3) ~ 0.0027``, so a ladder of twelve draws landing
#: entirely inside it is evidence at the 97th percentile that the coefficients are
#: drawn from a mean-zero law rather than merely small.  Measured over these
#: seeds, one draw (seed 7) sits at ``|t| = 2.273`` — inside the conventional 5%
#: band, which is what a correct pipeline looks like, and recorded rather than
#: hidden because hiding it would require choosing seeds after seeing them.
LADDER_CROSSING_BAR = 3.0

#: How far outside the ladder's own reported precision the ladder's *mean* may
#: land, in standard errors of that mean.  Three is the same multiple
#: :data:`LADDER_CROSSING_BAR` applies to a single draw, applied to a mean of
#: draws.
LADDER_MEAN_BAND = 3.0

#: The band the ladder's observed dispersion and its reported standard errors
#: must agree within.  Measured at these seeds the ratio is 0.879; the band is
#: wide because a ratio is itself a sample statistic over twelve draws, and
#: narrow because the claim it carries is real — a pipeline whose error bars were
#: off by a factor of two, which a magnitude threshold would never notice, falls
#: outside it.
LADDER_PRECISION_BAND = (0.5, 1.6)
#: The band the per-date information coefficients must span for the journey to
#: call the mean a cancellation rather than a construction.  Measured on the main
#: run: a span of about 1.38 (from -0.68 to +0.70 across the 24 dates, 10 positive
#: and 14 negative).  A degenerate pipeline returning the same tiny coefficient on
#: every date would satisfy every "near zero" magnitude assertion and fail this
#: one.
MIN_IC_SPREAD = 0.5

#: The fraction of the label the non-degenerate control signal is plugged into,
#: the scale of the pinned-noise perturbation beside it, and the seed that
#: perturbation is drawn under.  The control scores ``alpha * label +
#: (1 - alpha) * noise``: the label's *ordering* carries most of the score, with
#: a perturbation that keeps the per-date coefficients from collapsing to one
#: value.  The perturbation is what makes the control scorable at all — a *pure*
#: plug-in returns the same coefficient on every date and is refused by the
#: shipped metrics for a zero standard error, which is itself one of the facets
#: below, and is why the control comes in two strengths rather than one.
#: Measured at these constants: ``ic_mean = +0.4762``, ``|t| = +7.90``, with 18
#: distinct per-date coefficients across the 24 dates.
CONTROL_LABEL_WEIGHT = 0.25
CONTROL_NOISE_SD = 0.01
CONTROL_SEED = 90

#: The tolerance the *pairwise* Spearman identity is checked to.  Feature 80
#: reduces both sides to average ranks and correlates those, which is the
#: Spearman coefficient by definition; the facet re-derives it directly from
#: rank arithmetic to prove the number it asserts on is the statistic it claims
#: to be.
_RANK_TOLERANCE = 1e-9

#: The signal source the sandbox runs.  Written the way a node's source arrives
#: — a module-level ``signal(window, seed)`` returning a polars Series indexed
#: positionally by ``window.universe`` — and it exercises the two things the
#: sandbox's entrypoint contract promises: ``seed`` is required and positional,
#: and ``pl`` is pre-bound in the child's namespace (the sandbox denies the
#: signal a working ``import`` of its own, feature 11's "polars is the one library
#: a signal is entitled to, provided pre-bound").  It reads the sealed bars for
#: their row count — so the window it was handed is observably materialized — and
#: returns a draw whose randomness comes from the seed and the instant, not from
#: the bars — the row count is read and discarded, which is what makes it
#: possible to say the coefficient is a statement about the *signal* rather than
#: about what the signal was shown.
RANDOM_SIGNAL_CODE = f'''
def signal(ctx, seed):
    import random as _random

    window = ctx.bars("1d")
    # A fresh stream per decision instant: the seed is required by the
    # entrypoint (feature 11), and folding the window's own ``t`` into it is
    # what makes the cross-section a draw on *every* date rather than one
    # arbitrary vector re-issued across the whole grid.  A signal that returned
    # the same vector twenty-four times would make the per-date coefficients
    # degenerate — and this is exactly the shape a genuinely random signal has.
    rng = _random.Random("{{}}:{{}}".format(seed, ctx.t.isoformat()))

    # The window is read — the accessor is called and its rows are counted, and
    # the count must be non-zero — so the signal observably ran against a real
    # slice of the sealed lake rather than against the resolution alone.  The
    # count then plays no part in the scores: the coefficients below are a
    # statement about the *signal*, and a signal whose draws moved with the
    # market's row count would be one whose randomness the journey could not
    # attribute.
    if len(window) <= 0:
        raise ValueError("the window carries no bars to score against")

    scores = []
    for symbol in ctx.universe:
        total = 0.0
        for _ in range({DRAWS_PER_SYMBOL}):
            total += rng.gauss(0.0, 1.0)
        scores.append(total)
    return pl.Series(scores)
'''


# ---------------------------------------------------------------------------
# The sealed lake — ingest's own layout, sealed by the service's own verb
# ---------------------------------------------------------------------------


def _seal_the_world(workdir: Path) -> tuple[Any, Any, dict[str, dict[dt.date, float]], dict[str, str]]:
    """Generate the market, stage it in §4.2's layout, and seal it.

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

    generator = random.Random(PRICE_SEED)
    closes: dict[str, dict[dt.date, float]] = {}
    for symbol in SYMBOLS:
        # A pinned pseudo-random walk: one independent path per symbol, so the
        # cross-section has a real dispersion to rank.  The 2% per-bar step is
        # small enough that a 48-bar path stays away from the clamp and large
        # enough that the forward returns the alignment computes are of the
        # order an exchange bar's are — which matters, because the fee the cost
        # model charges is a fixed 10 bps against them, so a panel whose returns
        # were much smaller than its fee would measure mostly the fee.
        price = 100.0 + generator.uniform(-20.0, 20.0)
        path: dict[dt.date, float] = {}
        for day in BAR_DAYS:
            price = max(1.0, price * (1.0 + generator.gauss(0.0, 0.02)))
            path[day] = round(price, 2)
        closes[symbol] = path

    staged: dict[str, str] = {}
    for symbol in SYMBOLS:
        for day in BAR_DAYS:
            partition = staging / "bars" / f"symbol={symbol}" / f"date={day.isoformat()}"
            partition.mkdir(parents=True)
            part = partition / "part-0.parquet"
            pq.write_table(
                pa.table(
                    {
                        "symbol": [symbol],
                        "open_time": [
                            dt.datetime.combine(
                                day, dt.time(0), tzinfo=dt.UTC
                            )
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
    service = snapshot_component(application)
    sealed = service.seal(sealed_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC))
    return service, sealed, closes, staged


def _materialize_from_the_mount(mount: Any) -> Any:
    """Feature 73's ``materialize`` seam, reading the sealed lake.

    ``_materialize_default`` in the evaluator member builds *empty* frames from
    the resolution alone, and its own docstring says why: "the production reader
    (over a real ``SnapshotMount``) is injected by the feature that owns the lake
    read."  This is that reader, in the only form a test can honestly supply it —
    the mount's own ``select`` for the resolution's surviving partitions, read
    back through the mount's read-only paths and truncated at the decision time
    by the contract's own comparison.

    It reads *only* the partitions feature 72's resolution already named as
    surviving at or before the decision date, and it never constructs a path of
    its own: every byte comes through ``mount.select(stream, symbol, date)``,
    which is the mount's pruned query, so the same read-only handle and the same
    sealedness back the sandbox payload as back everything else.  The truncation
    runs on the assembled frame rather than in the reader because the frame is
    assembled per-date; a row past ``t`` cannot exist inside the partitions the
    slice kept, and filtering on ``open_time`` is what makes the reader's own
    guarantee checked rather than intended.

    A tiny per-partition cache keeps the twelve-seed ladder from re-reading the
    same compressed bytes hundreds of times per run; the cache holds *sealed*
    tables and is keyed by ``(symbol, ISO date)``, so it can never serve a
    partition the resolution excluded.
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
                    cache[key] = pa.Table.from_batches(
                        [
                            pq.read_table(str(path)).to_batches()[0]
                            for path in mount.select("bars", symbol, iso)
                        ]
                    )
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

    def charges(request: Any) -> CostQuote:
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
    366's.  Nothing about a random signal's coefficient depends on which branch
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
    metrics: NodeMetrics


def _run_pipeline(
    resolution: Any,
    closes: Mapping[str, Mapping[dt.date, float]],
    config: Any,
    schedule: FeeSchedule,
    code: str,
    seed: int,
    materialize: Any,
) -> Panel:
    """Drive one signal source through steps 2 through 8 of §6.1.

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
        code,
        seed=seed,
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

    The sealed identity, the resolved window, the main panel's four numbers and
    per-date series, the twelve-seed ladder, the two control plug-ins' verdicts,
    the store round-trip and the determinism re-run — every fact the facets below
    assert on, captured once so no facet re-runs the pipeline.
    """

    sealed_name: str
    sealed_hash: str
    sealed_path: Path
    staged_files: Mapping[str, str]
    manifest_files: Mapping[str, str]
    corruption_alerts: tuple[Any, ...]
    universe: tuple[str, ...]
    resolution: Any
    main: Panel
    ladder: tuple[tuple[int, float, float, float], ...]
    control_metrics: NodeMetrics
    control_refusal: str
    stored: Any
    rerun_scores: Mapping[dt.date, Mapping[str, float]]
    rerun_code_hash: str
    database_url: str
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
    workdir = tmp_path_factory.mktemp("random-signal-zero-ic")
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

        # Act 3 — the pipeline runs over the same sealed world fourteen times: the
        # random signal at its pinned main seed, then at the twelve ladder seeds,
        # each a fresh sandbox spawn reading the same sealed bytes.
        materialize = _materialize_from_the_mount(mount)
        config, schedule = _shared_fee_schedule()

        main = _run_pipeline(
            resolution,
            closes,
            config,
            schedule,
            RANDOM_SIGNAL_CODE,
            MAIN_SEED,
            materialize,
        )

        # The determinism re-run (§12): the same source at the same seed over the
        # same resolution must reproduce the identical score panel — the sandbox
        # is a fresh child each time, so this is a real re-execution rather than a
        # cached value.
        rerun = _run_pipeline(
            resolution,
            closes,
            config,
            schedule,
            RANDOM_SIGNAL_CODE,
            MAIN_SEED,
            materialize,
        )

        ladder: list[tuple[int, float, float, float]] = []
        for seed in LADDER_SEEDS:
            panel = _run_pipeline(
                resolution,
                closes,
                config,
                schedule,
                RANDOM_SIGNAL_CODE,
                seed,
                materialize,
            )
            ladder.append(
                (
                    seed,
                    panel.metrics.ic_mean,
                    panel.metrics.ic_se,
                    panel.metrics.ic_tstat,
                )
            )

        # Act 4 — the controls, which say the zero means something.  Both are
        # `compute_node_metrics` over the *same* priced panel the random signal
        # was measured on, so the sample size, the horizon, the fee schedule and
        # the reduction are held fixed and only the scores move.
        horizon = main.metrics.horizon
        labels = main.priced.returns(horizon)

        # The exact plug-in: the label itself as the score.  A signal whose score
        # is that perfectly ranked returns the same coefficient on every date — a
        # zero standard error, over which the t-statistic is undefined — and the
        # shipped metrics must refuse it rather than report a number.  Refusing
        # the signal with *maximal* information, rather than scoring it as
        # neutral, is the clearest statement the system makes that it does not
        # manufacture small numbers.
        control_refusal = ""
        try:
            compute_node_metrics(
                main.priced, {day: dict(labels[day]) for day in main.scores}
            )
        except Exception as exc:  # noqa: BLE001 - the refusal *is* the assertion
            control_refusal = f"{type(exc).__name__}: {exc}"

        # And the plug-in taken to a strength that *is* scorable: the label's
        # ordering carries the score, with pinned-noise perturbation keeping the
        # per-date coefficients from collapsing.  Its mean coefficient is
        # therefore a function of the sealed world and of the fee schedule, and
        # of nothing this journey chose after seeing a number.
        perturbation = random.Random(CONTROL_SEED)
        control_scores = {
            day: {
                symbol: CONTROL_LABEL_WEIGHT * labels[day][symbol]
                + (1.0 - CONTROL_LABEL_WEIGHT)
                * perturbation.gauss(0.0, CONTROL_NOISE_SD)
                for symbol in main.scores[day]
            }
            for day in main.scores
        }
        control_metrics = compute_node_metrics(main.priced, control_scores)

        # Act 5 — the four scalars are persisted and read back through the
        # shipped store, so the journey's number is a number the system keeps
        # rather than one it printed once.
        NodeMetricsStore(database_url).persist(main.metrics)
        stored = NodeMetricsStore(database_url).load(NODE_ID, config)

        yield Journey(
            sealed_name=sealed.name,
            sealed_hash=service.read_manifest(sealed.name).snapshot_hash,
            sealed_path=Path(str(sealed.path)),
            staged_files=staged,
            manifest_files=dict(mount.files()),
            corruption_alerts=service.verify_all(),
            universe=resolution.universe,
            resolution=resolution,
            main=main,
            ladder=tuple(ladder),
            control_metrics=control_metrics,
            control_refusal=control_refusal,
            stored=stored,
            rerun_scores=rerun.scores,
            rerun_code_hash=rerun.execution.code_hash,
            database_url=database_url,
            app_evaluator=evaluator_component(create_app()),
            app_snapshot=snapshot_component(create_app()),
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


class TestTheRandomSignalRunsOverTheSealedSnapshot:
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
        modes = {
            path.stat().st_mode & 0o777
            for path in journey.sealed_path.rglob("*")
        }
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
        assert len(journey.main.execution.dates()) == len(REBALANCE_DAYS)
        assert (
            sum(
                1
                for day in journey.main.execution.dates()
                if journey.main.execution.vector(day).conforming
            )
            == len(REBALANCE_DAYS)
        )
        for day in journey.main.execution.dates():
            vector = journey.main.execution.vector(day)
            assert vector.seed == MAIN_SEED
            assert vector.contract_version

    def test_the_signal_identity_is_the_source_hash_and_the_seed(
        self, journey: Journey
    ) -> None:
        # Feature 73 stamps the execution with ``sha256(code)`` and the seed.
        # The hash is asserted against independent recomputation rather than
        # against itself, so a drifted identity surfaces.
        assert journey.rerun_code_hash == hashlib.sha256(
            RANDOM_SIGNAL_CODE.encode("utf-8")
        ).hexdigest()
        assert journey.main.execution.seed == MAIN_SEED

    def test_the_scores_are_a_fresh_cross_section_on_every_date(
        self, journey: Journey
    ) -> None:
        # The signal folds the decision instant into its stream, so each date is a
        # fresh draw rather than one vector re-issued twenty-four times — which is
        # the shape a genuinely random signal has, and the reason the per-date
        # coefficients vary at all (a signal that returned the same vector every
        # date would produce the same coefficient every date, which the metrics
        # refuse rather than report; the control facet below proves it).
        #
        # The assertion is on the *raw* vectors, because those are what the signal
        # drew.  The normalized panel is those vectors reduced to ranks, and two
        # draws can share a rank ordering by coincidence — with eight symbols there
        # are 8! = 40320 orderings, so twenty-four draws collide about once in
        # every 140 runs.  Measured at the main seed all 24 raw vectors are
        # distinct, and two of the 24 rank orderings coincide; asserting on the
        # orderings would make this journey fail on a birthday coincidence rather
        # than on a defect, so it is deliberately not asserted here.
        draws = [
            tuple(journey.main.execution.vector(day).scores.to_list())
            for day in journey.main.execution.dates()
        ]
        assert len(set(draws)) == len(draws)
        # And the panel really is many cross-sections rather than one: 24 distinct
        # draws over 24 dates is the whole grid.
        assert len(draws) == len(REBALANCE_DAYS)

    def test_the_normalized_cross_section_is_centred_by_construction(
        self, journey: Journey
    ) -> None:
        # Feature 74's z-scoring makes each date's normalized vector sum to zero —
        # so the *coefficient* near zero is not a consequence of a centred score
        # (a constant signal is refused, not centred), it is a consequence of the
        # ordering being unrelated to the returns.
        for day, cross_section in journey.main.scores.items():
            assert all(isinstance(value, float) for value in cross_section.values()), day
            assert abs(sum(cross_section.values())) < 1e-9


# ---------------------------------------------------------------------------
# Facet: the coefficient is indistinguishable from zero
# ---------------------------------------------------------------------------


class TestTheCoefficientIsIndistinguishableFromZero:
    """The middle clause: the number itself, and what it is a number *of*.

    Every assertion here is a statement about the coefficient the shipped metrics
    returned for the random signal.  None of them pins a magnitude to a figure the
    documents do not contain: "indistinguishable from zero" is asserted as the
    zero falling inside the error bar the same pipeline reported, at the bar the
    promotion path reads against.
    """

    def test_the_metrics_are_step_eights_four_scalars(self, journey: Journey) -> None:
        # Step 8's record, whole: the four scalars over the shortest horizon the
        # priced panel covers, stamped with the node, the sealed world and the
        # cost model that priced them.  The identity is the point — the same
        # numbers under a different fee schedule are different numbers.
        metrics = journey.main.metrics
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
        metrics = journey.main.metrics
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
        horizon = journey.main.metrics.horizon
        for day, coefficient in journey.main.metrics.ic_series.items():
            scores = journey.main.scores[day]
            forwards = journey.main.priced.returns(horizon)[day]
            symbols = sorted(scores)
            ranks = _average_ranks([scores[symbol] for symbol in symbols])
            targets = _average_ranks([forwards[symbol] for symbol in symbols])
            count = len(symbols)
            mean = (count + 1) / 2.0
            covariance = sum(
                (ranks[index] - mean) * (targets[index] - mean)
                for index in range(count)
            )
            spread = (
                statistics.pstdev(ranks) * statistics.pstdev(targets) * count
            )
            assert coefficient == pytest.approx(
                covariance / spread, abs=_RANK_TOLERANCE
            ), day

    def test_the_zero_lies_inside_the_error_bar_the_pipeline_reported(
        self, journey: Journey
    ) -> None:
        # The first half of "indistinguishable": for this run the coefficient *and*
        # its t-statistic are inside the two-sided 5% bar, so the zero is not
        # merely close to ``ic_mean`` — it is inside the interval the system itself
        # would report for this measurement, and the random signal would not have
        # cleared the bar the promotion path reads against.
        #
        # This is one draw, and a single draw cannot by itself distinguish a
        # correct pipeline from a broken one — under the null a *correct* pipeline
        # produces ``|t| >= 1.96`` about one time in twenty.  What makes the reading
        # evidence is the ladder in the next facet, which measures the distribution
        # rather than one point of it.
        metrics = journey.main.metrics
        assert abs(metrics.ic_mean) < NULLITY_BAR * metrics.ic_se
        assert abs(metrics.ic_tstat) < NULLITY_BAR

    def test_the_coefficient_is_a_measurement_and_not_a_fabricated_zero(
        self, journey: Journey
    ) -> None:
        # The second half, and the one a bare magnitude threshold would miss: a
        # pipeline that returned a tiny constant would pass every "near zero" check
        # in the world.  The per-date coefficients must instead show real
        # dispersion — so the mean landed near zero by *cancellation* across dates,
        # which is what an informationless signal does, and not by construction.
        series = journey.main.metrics.ic_series
        assert len(set(series.values())) > 1
        assert max(series.values()) - min(series.values()) >= MIN_IC_SPREAD
        assert any(value > 0.0 for value in series.values())
        assert any(value < 0.0 for value in series.values())

    def test_the_mean_coefficient_is_not_the_fee_and_not_the_market(
        self, journey: Journey
    ) -> None:
        # The panel's own scale, stated so the zero is read against it.  The
        # post-cost returns the coefficient is measured against have real
        # dispersion (the priced panel is not a flat line the fee schedule
        # annihilated), and the per-date coefficients are bounded by one as rank
        # correlations must be.  A coefficient near zero against a *constant*
        # return panel would mean the fee had eaten the whole panel rather than
        # that the signal had no information.
        horizon = journey.main.metrics.horizon
        day = next(iter(journey.main.metrics.ic_series))
        priced = journey.main.priced.returns(horizon)[day]
        assert statistics.pstdev(list(priced.values())) > 0.0
        assert all(abs(value) <= 1.0 for value in journey.main.metrics.ic_series.values())


# ---------------------------------------------------------------------------
# Facet: the coefficients are draws, and the error bar is honest
# ---------------------------------------------------------------------------


class TestTheCoefficientsAreDrawsAndTheErrorBarIsHonest:
    """The same signal, the same world, twelve seeds.

    One seed landing near zero is weak evidence on its own — an arbitrary vector
    might do it.  What makes the reading strong is that the coefficients behave
    the way draws from a mean-zero law behave: mixed signs, a mean of their own
    inside its own error, and — the assertion a bare magnitude check cannot make —
    a dispersion matching the standard error the pipeline reported for each draw.
    """

    def test_the_ladder_is_the_same_signal_over_the_same_sealed_world(
        self, journey: Journey
    ) -> None:
        # The ladder differs from the main run in exactly one term, the seed — and
        # the main run *is* one of the ladder draws, so the headline number is not
        # a special case carved out of the ladder.
        assert [seed for seed, *_ in journey.ladder] == list(LADDER_SEEDS)
        index = LADDER_SEEDS.index(MAIN_SEED)
        assert journey.ladder[index][1] == pytest.approx(journey.main.metrics.ic_mean)
        assert journey.ladder[index][2] == pytest.approx(journey.main.metrics.ic_se)

    def test_the_signs_are_mixed(self, journey: Journey) -> None:
        # A signal with an edge would lean one way; a signal with none splits.
        # This is the cheapest falsification available and it is stated first.
        means = [mean for _seed, mean, _se, _t in journey.ladder]
        assert any(mean > 0.0 for mean in means)
        assert any(mean < 0.0 for mean in means)

    def test_the_t_statistics_carry_no_systematic_direction(
        self, journey: Journey
    ) -> None:
        # The same fact one scale up, where the sample size is already divided
        # out: the twelve t-statistics must not lean.  A pipeline with a small
        # positive bias somewhere — a sign convention, a fee applied to one side,
        # an alignment off by a bar — would push these all one way while still
        # leaving each individual draw inside the bar, so this is the assertion
        # that catches a bias a per-draw threshold cannot.
        statistics_ = [value for _seed, _mean, _se, value in journey.ladder]
        positive = sum(1 for value in statistics_ if value > 0.0)
        assert 0 < positive < len(statistics_), statistics_

    def test_the_ladder_is_centred_on_zero(self, journey: Journey) -> None:
        # The mean of twelve draws must sit inside the precision of a mean of
        # twelve draws — the ladder's own standard error, computed from the
        # ladder's *observed* dispersion rather than from the pipeline's reported
        # one, so this assertion does not depend on the pipeline being right.
        means = [mean for _seed, mean, _se, _t in journey.ladder]
        observed = statistics.pstdev(means)
        standard_error = observed / len(means) ** 0.5
        assert abs(statistics.mean(means)) <= LADDER_MEAN_BAND * standard_error

    def test_the_reported_standard_error_matches_the_observed_dispersion(
        self, journey: Journey
    ) -> None:
        # The assertion that gives "indistinguishable" its teeth.  Each draw's
        # ``ic_se`` is the pipeline's claim about how much its own ``ic_mean``
        # would move from sample to sample; re-running the sample twelve times
        # measures that movement directly, so the two must agree.  A pipeline whose
        # error bar was wrong by a factor of two — which a "``|ic_mean| < ε``"
        # check would never notice — fails right here.
        means = [mean for _seed, mean, _se, _t in journey.ladder]
        reported = [se for _seed, _mean, se, _t in journey.ladder]
        ratio = statistics.pstdev(means) / statistics.mean(reported)
        low, high = LADDER_PRECISION_BAND
        assert low <= ratio <= high, (
            f"the ladder's observed dispersion over its reported standard errors "
            f"is {ratio:.3f}, outside [{low}, {high}]: the pipeline's error bar is "
            "not the error its own draws show"
        )

    def test_no_draw_lands_beyond_three_standard_errors(
        self, journey: Journey
    ) -> None:
        # The falsifiable form of "the ladder is centred", and the reason this
        # facet does *not* assert that every draw is inside :data:`NULLITY_BAR`.
        # Under the null ``ic_tstat`` is asymptotically standard normal, so about
        # one draw in twenty clears 1.96 *whether or not the pipeline is correct*:
        # a twelve-seed ladder asserting "no draw clears 1.96" would fail for a
        # working system nearly half the time, and passing it would therefore say
        # nothing.  Three is a claim with content — ``P(|Z| >= 3) ≈ 0.27%`` — so
        # twelve draws all inside it is evidence that the coefficients come from a
        # mean-zero law rather than merely that they are small.
        #
        # Measured at these seeds, seed 7 sits at |t| = 2.273: inside the
        # conventional 5% band, which is exactly what a correct pipeline looks
        # like.  It is recorded rather than removed, because removing it would mean
        # choosing seeds after seeing their coefficients.
        crossers = [
            (seed, value)
            for seed, _mean, _se, value in journey.ladder
            if abs(value) >= LADDER_CROSSING_BAR
        ]
        assert crossers == [], (
            f"{crossers} in a twelve-seed ladder is not a draw from a mean-zero "
            "law: a random signal at any seed beyond three standard errors means "
            "the pipeline is finding information that is not there"
        )

    def test_the_ladder_spans_the_bar_on_both_sides_of_zero(
        self, journey: Journey
    ) -> None:
        # The operational reading, stated at the object level: the twelve draws
        # mostly sit inside the promotion bar, and they straddle it — the
        # coefficients alternate across zero rather than piling on one side.  The
        # number of draws outside the bar is asserted as a small count rather than
        # zero, for the reason the facet above gives.
        inside = [
            1 for _seed, _mean, _se, value in journey.ladder if abs(value) < NULLITY_BAR
        ]
        assert len(inside) >= len(LADDER_SEEDS) - 2
        means = [mean for _seed, mean, _se, _t in journey.ladder]
        assert min(means) < 0.0 < max(means)


# ---------------------------------------------------------------------------
# Facet: the bar is not vacuous
# ---------------------------------------------------------------------------


class TestTheBarIsNotVacuous:
    """The controls that say the zero means something.

    A pipeline that returned "zero" for everything would satisfy every facet
    above and be worthless.  These plug a signal *into* the labels — same window,
    same sandbox, same sample size, same fee schedule, same metrics, same
    reduction — and require the system to say so at both strengths.
    """

    def test_a_signal_plugged_into_the_labels_is_distinguishable(
        self, journey: Journey
    ) -> None:
        # The control's score is the label's own ordering carrying most of its
        # weight, so the whole of its information is the label's.  Same n, same
        # horizon, same priced panel as the random signal, so "the bar is not
        # vacuous" is a statement about the bar rather than about the sample: the
        # metric that reads ≈ 0 for the random signal reads unmistakably non-zero
        # here.
        metrics = journey.control_metrics
        assert metrics.dates == journey.main.metrics.dates
        assert metrics.horizon == journey.main.metrics.horizon
        assert metrics.ic_mean > 0.0
        assert abs(metrics.ic_tstat) >= NULLITY_BAR
        # And by a wide margin, not merely over the line by a hair: the control's
        # evidence is of a different order from the random signal's.
        assert abs(metrics.ic_tstat) > 3.0

    def test_the_control_does_not_owe_its_verdict_to_the_fee_schedule(
        self, journey: Journey
    ) -> None:
        # The control's coefficients are computed against the *priced* panel, so a
        # fee schedule that had annihilated the labels would make the control's
        # verdict vacuous in a different way.  The per-date coefficients vary
        # (the perturbation is doing its job) and the mean is positive on the
        # dates the panel covers.
        series = journey.control_metrics.ic_series
        assert len(set(series.values())) > 1
        assert len(series) == journey.main.metrics.dates

    def test_a_perfectly_plugged_signal_is_refused_rather_than_reported(
        self, journey: Journey
    ) -> None:
        # Taken to its limit, the plug-in makes every date's coefficient identical
        # — a zero standard error, over which the t-statistic is undefined — and
        # the shipped metrics refuse it by name.  That refusal is the clearest
        # possible statement that this system does not manufacture small numbers:
        # the signal carrying *maximal* information is the one it will not score,
        # rather than the one it scores as neutral.
        assert journey.control_refusal
        assert "EvaluatorMetricsError" in journey.control_refusal
        assert "standard error" in journey.control_refusal

    def test_the_random_signal_and_the_control_differ_only_in_their_scores(
        self, journey: Journey
    ) -> None:
        # The premise the whole facet rests on, and the one thing a hand-built
        # control panel could get wrong: both coefficients are reduced from the
        # *same* ``PostCostReturns`` object over the same dates, so the contrast
        # is attributable to the scores and to nothing else.  If the control had
        # been measured on a differently priced panel, the comparison would be
        # between two things.
        assert journey.control_metrics.node_id == journey.main.metrics.node_id
        assert journey.control_metrics.snapshot_name == journey.main.metrics.snapshot_name
        assert (
            journey.control_metrics.cost_model.reference
            == journey.main.metrics.cost_model.reference
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
        assert journey.stored is not None
        assert journey.stored == journey.main.metrics
        assert journey.stored.ic_mean == pytest.approx(journey.main.metrics.ic_mean)
        assert journey.stored.ic_tstat == pytest.approx(journey.main.metrics.ic_tstat)
        assert dict(journey.stored.ic_series) == dict(journey.main.metrics.ic_series)

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
            f"{journey.main.metrics.cost_model.venue}/"
            f"{journey.main.metrics.cost_model.version}"
        )
        assert stored.cost_model.reference == CostModelRef(
            venue="binance_spot", version="2026.09.1"
        ).reference
        miss = NodeMetricsStore(journey.database_url).load(
            NODE_ID, CostModelRef(venue="binance_spot", version="2026.08.4")
        )
        assert miss is None

    def test_a_node_the_store_never_measured_reads_back_as_nothing(
        self, journey: Journey
    ) -> None:
        # The other half of the key: the same schedule under a node the journey
        # never scored.  Absence is ``None``, never a zero-filled record — the same
        # stance every store in this workspace takes, so a reader can tell "never
        # measured" from "measured zero".
        miss = NodeMetricsStore(journey.database_url).load(
            "00000000-0000-4000-8000-000000000000", journey.main.metrics.cost_model
        )
        assert miss is None

    def test_the_composed_application_serves_the_components_this_journey_used(
        self, journey: Journey
    ) -> None:
        # The assembled system, not an import: the snapshot service the seal went
        # through and the evaluator service the deployment composes are reachable
        # through the app namespace's own seats, and both are the loader's scanned
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
        assert journey.rerun_scores == journey.main.scores
