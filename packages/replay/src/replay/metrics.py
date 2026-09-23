"""Feature 254 — replay latency at p50 and p99, into the observability metrics store.

app_spec.xml, "Replay Engine", feature 254: *System persists replay latency at
p50 and p99 into the observability metrics store.*  It declares
``depends_on=252`` — the measured duration — and it is the *reporting* half of
the cost argument the category is made of.  The parent (252) measures one
replay's duration and carries it on a per-replay record; the sibling (253)
compares *one* duration against the broken-cost-model point and alerts; this
feature aggregates a **population** of measured durations into the two
percentiles docs/nullius-tech-architecture.md §16 names among the research
metrics — *"replay latency p50/p99"* — and writes them into the store an
operator reads them from.  Feature 252's module docstring named this module's
arrival: *"There is no observability member in this workspace yet — feature
254 would be the first to write one"* — and this module is that writer: the
first table in the workspace whose reason for existing is §16.

**What "the observability metrics store" is, spelled once.**  §16 states the
stack choice as a sentence with a number on it:

    Stack: Prometheus + Grafana, or a single Postgres metrics table with a
    Streamlit dashboard if you would rather not run infrastructure. At this
    scale the simpler option is defensible.

The workspace's spelling of the simpler option is the one relational store
every member store already addresses by ``DATABASE_URL`` — the cost-model
member's identity and latency tables, the evaluator's metric tables,
discovery's campaign records — ``sqlite:///`` on a single machine, Postgres
when a deployment grows into one.  So the observability metrics store this
feature persists into is a metrics table in that store, owned by this member,
created idempotently on connect (``CREATE TABLE IF NOT EXISTS``, the contract
every store in this workspace states) so no migration step is needed and no
shared schema file is touched.  The in-repo precedent is the cost-model
member's feature 67 — *System persists an empirical p50, p95 and p99 latency
distribution measured from shadow runs rather than an assumed constant* — the
same sentence shape on the fill-latency side; this module is the replay-side
echo, with the two percentiles *this* feature's sentence names where 67's
named three.

**The row is the sample, not a summary of it.**  The natural shape for a
persisted latency report would be two columns — ``p50`` and ``p99`` — and
nothing else, since those are the numbers the feature names.  But a report
persisted as a summary cannot be read back as the thing it was: the reader
would get two numbers and lose the population they were measured from, so a
later reader could not recompute a percentile the writer did not store, could
not say *how many replays* the p99 was estimated from (a p99 over four
replays is a number to distrust, and a p99 over four thousand is a fact about
the tail), and could not check the stored summary against the data it
summarises.  So the measured durations land as a JSON array — the source of
truth — and the ``p50``/``p99`` columns are a *derived*, denormalised view
over them: an index for a reader (a dashboard, an operator's query) that only
wants the two numbers, never the source.  Reading a report back rebuilds it
from the samples, so the persisted row round-trips to the report that was
written — the law feature 67's store states, restated for this one.

**One row per measured instant.**  The primary key is ``measured_at`` — the
instant the population was summarised — because a deployment's replay latency
is re-measured every dreaming cycle (§10.3's 200 worlds × 40 policy versions
is ~8000 replays per cycle, each leaving a duration), and each cycle's
percentiles are a distinct snapshot of the replay path *at that point in its
life*.  The table is therefore a time-ordered history of latency snapshots,
not one row: a re-measurement at a later instant adds a row, and a
re-measurement at the *same* instant upserts onto the one row, which is the
honest answer for the same snapshot written twice.  The instant is ISO 8601
UTC at second resolution, so the string order ``ORDER BY measured_at DESC``
answers newest-first — the same key shape feature 67's store carries minus
the ``(venue, version)`` half, which is the cost model's identity and has no
replay-side counterpart: there is one replay path in a deployment, and its
latency is what the row is about.

**The population arrives duck-typed, because a member never imports another
member — not even its own past.**  The durations this module aggregates are
feature 252's :class:`~replay.ReplayDuration` records, but the seam does not
``isinstance`` them: the module loader imports a member under a synthetic
name and re-executes it, so the record a *composed* application's path
produced can be a second class object of the same name, and an ``isinstance``
would refuse the very record the deployment measured.  The seam reads what a
duration *is*: each carrier's ``duration_seconds``, validated as it is read —
a real, finite, non-negative number, the same three facts 252's constructor
defends, restated here because a duck-typed carrier owes the proof a
constructor no longer stands behind.  A bare float is refused — a number
names no ``(policy, world)`` replay, and 252's record, not the number, is the
unit this feature aggregates — and an empty population is refused, because
p50/p99 over zero replays is not a latency, it is the absence of one: a
fabricated figure nothing measured, exactly the assumed constant feature 67's
sentence refuses to fall back to and this one inherits the refusal of.

**The percentile convention: linear, spelled in pure Python.**  The rank of
the p-th percentile is ``p/100 * (n - 1)`` in the sorted sample, and a rank
that falls between two order statistics is interpolated linearly —
``numpy.percentile``'s default method, the convention the cost-model member
spells as its :data:`QUANTILE_METHOD` and the one this module restates as
:data:`REPLAY_LATENCY_METHOD`.  Restated, not imported, for two reasons a
member in this workspace always has: a member never imports another member
(:mod:`cost_model.latency` is the sibling's spelling of the same three
interpolations), and the replay path may not grow a numerical stack (§12's
determinism contract, §11.2's materialization row) — so the arithmetic is
three interpolations of pure Python and nothing here can pull a numpy in
behind it.  Two percentiles, not three, because the feature's sentence names
two: p50 is the centre a deployment's replays cluster at, and p99 is the tail
§16's pairing exists to watch — the slow-but-present replays a plain average
would bury and a maximum would over-read.

**Persists, never censors.**  A population's slow tail is persisted as it
was measured: a 300 ms replay's duration sits in the samples and lifts the
p99 above it, and no population is refused, clipped or re-centred for
containing one.  That is 252's law — *measures and persists; never refuses a
slow replay* — carried into the store, and it is load-bearing here for the
same reason it was there: the sibling (253) alerts on the tail this module
reports, and an observability store that quietly dropped the tail it existed
to watch would defeat the alert beside it.  The refusals this module *does*
raise are about the report's own contract — a population that is not one, a
store that cannot take the write — in :class:`~replay.ReplayMetricsError`,
argued in :mod:`replay.errors`.

**The clock split, and it is a split.**  This module reads a wall clock —
:func:`datetime.datetime.now`, UTC — for exactly one purpose: the row's key,
*when this snapshot was taken*.  That is a label, not a measurement, and it
is the same split feature 67's store makes (``measured_at`` defaulted to now,
overridable by a caller that measured at a known instant).  The only clock a
*duration* is ever read from remains 252's :func:`time.perf_counter`, and
nothing in this module subtracts two wall-clock readings or compares a
duration against one — a snapshot stamped by NTP is a mis-keyed row, while a
duration measured on a clock that can jump backwards is not a measurement at
all, and only the second one is this feature's parent's law.

**What this module deliberately does not do.**  It does not *alert* — the
``recomputation_suspected`` emission past 200 ms is feature 253's, reading a
flag 252 derives; this module is the report the alert is read against, not a
second place the threshold could live.  It does not *grade* the report
against the target — no ``within_target`` reading is derived here, because
252's module spells the 50 ms target and the 200 ms threshold once and a
second derived flag on the report would be a second spelling of the same
comparison; an operator (or 253) comparing p99 to 0.05 quotes the constants
the record already quotes.  It does not *register a component* — a store
addressed by ``DATABASE_URL`` is never composed, the stance every store in
this workspace takes, so the member's one ``@register`` contribution stays
feature 245's stateless facade and no builder here can spend I/O inside
``create_app()``.  It does not *widen* ``replay_score`` (feature 255's
table, a separate lineage) — the report is this module's own row, exactly as
252's record was 252's own.  And it does not *store milliseconds* — the
second is the unit 252 pinned its record in, so the second is the unit the
sample, the percentiles and the columns carry; §10.4's "50 ms" and "~200 ms"
are the reader's arithmetic (× 1000), performed in one place, the repr.

Stdlib only — :mod:`datetime` for the row's key, :mod:`json` for the sample
array, :mod:`math` for the finite check, :mod:`os` for the one ambient the
workspace's stores share (``DATABASE_URL``), :mod:`sqlite3` for the store
itself, :mod:`contextlib` and :mod:`pathlib` and :mod:`urllib.parse` for the
connection's plumbing, :mod:`typing` for the seam — no numerics, no Polars,
no PyArrow, so importing this member on every factory scan still costs
composition nothing, per §12's rule that the replay path may not grow a
numerical stack.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import ReplayMetricsError

__all__ = [
    "DATABASE_URL_ENV",
    "REPLAY_LATENCY_METHOD",
    "REPLAY_LATENCY_QUANTILES",
    "REPLAY_LATENCY_TABLE",
    "ReplayLatency",
    "load_latest_replay_latency",
    "load_replay_latency",
    "persist_replay_latency",
    "quantile",
    "replay_latency",
]

#: The environment variable naming the relational store — the one spelling
#: every member store in this workspace already uses (the cost-model identity
#: and latency stores, the evaluator's metric stores, discovery's campaign
#: records), restated here so this module states its own contract and imports
#: no sibling's.  The observability metrics store is that store: §16's "single
#: Postgres metrics table", ``sqlite:///`` on a single machine.
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the replay latency metrics live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named
#: for what it holds (the metrics of replay latency) the way the cost-model
#: member's ``cost_model_latency`` is, so a reader of the store can tell whose
#: observability row it is holding.
REPLAY_LATENCY_TABLE = "replay_latency_metrics"

#: The two percentile ranks the feature's sentence names — p50 and p99, as
#: percentile ranks.  Spelled once so the report, its persistence and any
#: caller that reads the latency share one tuple rather than each inventing
#: ``(50.0, 99.0)``.  Two, not the cost-model member's three, because this
#: feature's sentence names two: the centre and the tail, §16's own pairing.
REPLAY_LATENCY_QUANTILES = (50.0, 99.0)

#: The quantile-definition convention — ``"linear"``, numpy's default (the
#: interpolation method ``numpy.percentile`` uses): the rank of the p-th
#: percentile is ``p/100 * (n - 1)`` over the sorted sample, and a rank that
#: falls between two order statistics is interpolated linearly.  Named here
#: rather than assumed — the same stance the cost-model member's
#: ``QUANTILE_METHOD`` takes — so the convention a persisted p99 was computed
#: under is a visible constant and not a buried arithmetic choice, and a
#: reader comparing this table's p99 against a recompute knows which method
#: to recompute with.
REPLAY_LATENCY_METHOD = "linear"

_SCHEMA = f"""
-- Feature 254: replay latency at p50 and p99, in the observability metrics
-- store (docs §16's research metrics: "replay latency p50/p99").
--
-- The primary key is `measured_at` — the instant the population was
-- summarised.  A deployment's replay latency is re-measured every dreaming
-- cycle, so the table is a time-ordered history of latency snapshots, not one
-- row; a re-measurement at a later instant adds a row, and the same instant
-- upserts onto the one row (the same snapshot written twice).
--
-- `samples` is the source of truth: the measured durations as a JSON array
-- (seconds, the unit feature 252 pinned its record in).  `p50`/`p99` are a
-- denormalised view over those samples — an index for a reader that only
-- wants the two numbers, not the report itself.  A report is always rebuilt
-- from `samples` on read, so the row round-trips losslessly, and `n` is the
-- count a reader distrusts a small-sample p99 against.
CREATE TABLE IF NOT EXISTS {REPLAY_LATENCY_TABLE} (
    measured_at TEXT NOT NULL,  -- ISO 8601 UTC: when the population was summarised
    source      TEXT,           -- where the durations came from (provenance)
    n           INTEGER NOT NULL,  -- number of replay durations summarised
    samples     TEXT NOT NULL,  -- the measured durations in seconds, JSON array
    p50         REAL NOT NULL,  -- derived: 50th percentile of samples (linear)
    p99         REAL NOT NULL,  -- derived: 99th percentile of samples (linear)
    PRIMARY KEY (measured_at)
);
"""


# -- the report ---------------------------------------------------------------------------


class ReplayLatency:
    """One population's replay latency at p50 and p99 — feature 254's value.

    What :func:`replay_latency` answers and :func:`persist_replay_latency`
    writes: the two percentiles the feature's sentence names, over the
    measured durations of a population of replays, plus the one provenance
    figure a percentile is meaningless without — :attr:`n`, how many replays
    the numbers were measured from (a p99 estimated from four replays is a
    number to distrust; the count is what lets a reader distrust it).

    The two numbers are **derived from the population, never stored beside
    it**: :func:`replay_latency` computes them by one method
    (:data:`REPLAY_LATENCY_METHOD`) over the one sorted sample, and this
    class merely carries the result — so a report cannot hold a p50 its own
    population does not support, the same reason a
    :class:`~replay.duration.ReplayDuration` derives its two readings from
    the one measured duration instead of storing them.  The constructor is
    the seam's own spelling, for a caller that already holds computed
    percentiles (the reader, rebuilding from persisted samples) — exactly as
    :class:`~replay.ReplayReturns` trusts a hold the free function has
    already validated — and it defends the same arithmetic's invariants: the
    count is a positive integer, each percentile a finite non-negative real,
    and p50 at or under p99 (the linear method is monotone in the rank, so a
    report claiming the reverse is not a summary of any one sample).

    Frozen — ``__slots__`` and no setter expose the values; the only writable
    path is the constructor — because a report is a *measurement of a
    population*, and a measurement that could be reassigned after the fact
    would be a latency no dashboard and no alert could rely on, the same
    reason 252's record is frozen on the duration it started from.

    Not a component and not ``@register``-ed: it is the *report* one caller
    computed over one population, per-report state in the stance this member
    takes for the transition, the read and the duration — a second population
    is summarised into its own report.
    """

    __slots__ = ("_n", "_p50_seconds", "_p99_seconds")

    def __init__(
        self,
        n: int,
        p50_seconds: float,
        p99_seconds: float,
    ) -> None:
        # The constructor trusts that the percentiles were computed (the free
        # function computed them, or the reader rebuilt them from persisted
        # samples) but defends the arithmetic's own invariants: a count that
        # is not a positive integer names no population, a percentile that is
        # not a finite non-negative real is not an order statistic of measured
        # durations (252's constructor refuses those, so a summary containing
        # one is not a summary of any population this member can aggregate),
        # and a p50 above the p99 is not a summary any one sample yields — the
        # linear method interpolates a monotone rank over a sorted sample, so
        # the median of a population cannot exceed its 99th percentile.  All
        # refused in this member's vocabulary, naming the report.
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ReplayMetricsError(
                f"a replay latency report summarises a population of at least "
                f"one measured duration — got a count of {n!r} "
                f"({type(n).__name__}). A report's count is the figure a "
                "reader distrusts a small-sample p99 against (feature 254), "
                "so a count that is not a positive integer names no population "
                "the percentiles could have been measured from"
            )
        self._n = n
        self._p50_seconds = _percentile_value("p50", p50_seconds)
        self._p99_seconds = _percentile_value("p99", p99_seconds)
        if self._p50_seconds > self._p99_seconds:
            raise ReplayMetricsError(
                f"a replay latency report's p50 ({self._p50_seconds!r} s) sits "
                f"above its p99 ({self._p99_seconds!r} s). Both are order "
                "statistics of one population under the linear method "
                f"(feature 254's {REPLAY_LATENCY_METHOD!r}: the rank "
                "p/100 * (n - 1) is interpolated over a sorted sample, which "
                "is monotone in the rank), so the median of a population "
                "cannot exceed its 99th percentile — a report claiming the "
                "reverse is not a summary of any one sample and no dashboard "
                "or alert could rely on either number"
            )

    @property
    def n(self) -> int:
        """How many replays the two percentiles were measured from.

        The provenance figure a percentile is meaningless without: a p99 over
        four replays is a number to distrust, and the count is what lets a
        reader distrust it.  Persisted beside the samples so a stored report
        still answers the question.
        """
        return self._n

    @property
    def p50_seconds(self) -> float:
        """The median replay latency of the population, in seconds.

        The centre §16's p50/p99 pairing watches: where a deployment's
        replays cluster.  Derived from the population under
        :data:`REPLAY_LATENCY_METHOD`, carried in the unit feature 252 pinned
        its record in — the second; §10.4's "50 ms" target is this number
        × 1000.
        """
        return self._p50_seconds

    @property
    def p99_seconds(self) -> float:
        """The 99th-percentile replay latency of the population, in seconds.

        The tail the pairing exists to watch: the slow-but-present replays a
        plain average would bury and a maximum would over-read, and the
        number an operator holds against docs §10.4's *"if a replay exceeds
        ~200 ms ... the cost model of the architecture has broken"* — a p99
        under 0.2 s is a deployment whose slowest percentile of replays still
        reads rather than recomputes.
        """
        return self._p99_seconds

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Deliberately reads the stored fields and derives nothing that could
        # fail: a repr is a debugging aid, and one that raised while an
        # operator was already looking at the latency would be a second
        # refusal at the worst moment.  Spells the two numbers in ms — the
        # unit §10.4 states the target in — as 252's repr does.
        return (
            f"ReplayLatency(n={self._n}, "
            f"p50={self._p50_seconds * 1000:.3f} ms, "
            f"p99={self._p99_seconds * 1000:.3f} ms)"
        )


# -- the percentiles ----------------------------------------------------------------------


def quantile(sorted_samples: Any, p: float) -> float:
    """Return the ``p``-th percentile of ``sorted_samples`` (linear method).

    The pure arithmetic of the percentile and nothing else:
    ``sorted_samples`` must already be in non-decreasing order and contain at
    least one value — :func:`replay_latency` sorts and guards before calling
    — and the rank of the p-th percentile is ``p/100 * (n - 1)`` over the
    sorted sample (:data:`REPLAY_LATENCY_METHOD`, numpy's default).  A rank
    that lands on an order statistic returns that statistic; a rank between
    two statistics is interpolated linearly between them.  Reproduced in pure
    Python — the same three interpolations the cost-model member spells for
    its fill-latency distribution — because a member never imports another
    member and the replay path may not grow a numerical stack (§12), so
    nothing here can pull a numpy in behind it.

    A percentile outside ``[0, 100]`` is refused: a p101 would read one past
    the last order statistic and a negative percentile has no meaning, and a
    latency quantile built on a silently clamped rank would be a tail the
    numbers do not support.
    """
    if not (0.0 <= p <= 100.0):
        raise ReplayMetricsError(
            f"a percentile rank is within [0, 100] — got {p!r}. The linear "
            f"method (feature 254's {REPLAY_LATENCY_METHOD!r}) places the "
            "p-th percentile at rank p/100 * (n - 1) over the sorted sample, "
            "and a rank outside [0, 100] names no order statistic a measured "
            "population could answer"
        )
    ordered = tuple(sorted_samples)
    count = len(ordered)
    if count == 1:
        # A single observation has no spread to interpolate over: every
        # quantile is that one value.  The honest answer for a one-replay
        # population, and numpy agrees.
        return float(ordered[0])
    rank = (p / 100.0) * (count - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[int(rank)])
    fraction = rank - lower
    return float(
        ordered[lower]
        + fraction * (ordered[upper] - ordered[lower])
    )


def replay_latency(durations: Any) -> ReplayLatency:
    """Summarise a population of measured replay durations at p50 and p99.

    Feature 254's computation half: read the population of
    :class:`~replay.duration.ReplayDuration` records a caller holds (a
    dreaming cycle's replays, a benchmark run's, a test's), take each one's
    measured ``duration_seconds``, and answer the two percentiles the
    feature's sentence names plus the count they were measured from — one
    sort, one method, one report.  The persistence half is
    :func:`persist_replay_latency`; this verb is the same summary without the
    write, for a caller that wants the number (a log line, a benchmark
    assertion) rather than the row.

    **The population is read duck-typed and validated as it is read.**  Each
    carrier must *be* a measured duration — a ``duration_seconds`` that is a
    real, finite, non-negative number, the three facts 252's constructor
    defends — because the module loader imports a member under a synthetic
    name and re-executes it, so a record the composed application's path
    produced is a second class object of the same name and an ``isinstance``
    would refuse the very duration the deployment measured.  A bare number is
    refused (it names no ``(policy, world)`` replay; 252's record is the unit
    this feature aggregates), an empty population is refused (p50/p99 over
    zero replays is not a latency, it is the absence of one — the fabricated
    figure feature 67's sentence refuses to fall back to), and a carrier
    whose duration cannot be read is refused naming it.  All in
    :class:`~replay.ReplayMetricsError`, this member's vocabulary, so a
    caller's single ``except ReplayError`` catches every way a report can
    fail to be one.

    **The slow tail is summarised, never censored.**  A population containing
    a 300 ms replay keeps it: the samples are read as measured, the p99
    carries the tail, and nothing here refuses, clips or re-centres a slow
    replay — 252's law (*measures and persists; never refuses*), carried into
    the summary.  The alert on the tail is feature 253's.
    """
    report, _ = _summarise(durations)
    return report


def _summarise(durations: Any) -> tuple[ReplayLatency, list[float]]:
    """The one spelling of the summary — the report and the sample it is.

    Read the population once, sort it once, compute both percentiles through
    the one :func:`quantile` seam: every caller (:func:`replay_latency`,
    :func:`persist_replay_latency`) answers the same report from the same
    read, so the duck-typed population is walked exactly once per summary —
    a second walk could read a second population, and a caller would persist
    samples its report did not summarise.
    """
    samples = _samples_of(durations)
    ordered = sorted(samples)
    report = ReplayLatency(
        len(ordered),
        quantile(ordered, REPLAY_LATENCY_QUANTILES[0]),
        quantile(ordered, REPLAY_LATENCY_QUANTILES[1]),
    )
    return report, ordered


# -- the store ---------------------------------------------------------------------------


def persist_replay_latency(
    durations: Any,
    *,
    measured_at: str | None = None,
    source: str | None = None,
    database_url: str | None = None,
) -> ReplayLatency:
    """Persist a population's replay latency at p50 and p99; return the report.

    Feature 254's sentence, made concrete: the measured durations land as the
    source of truth (a JSON array of seconds, sorted), the p50 and p99 as the
    derived view over them, and the count beside both — one row in the
    observability metrics store, keyed by the instant the population was
    summarised.  A re-measurement at a later instant adds a row, so the table
    accumulates the history of how the replay path's latency evolved as
    dreaming cycles piled up; a re-measurement at the *same* instant upserts
    onto the one row, which is the honest answer for the same snapshot
    written twice.

    **The population is validated before the store is touched.**  The
    ordering is the member's law (245's refusal before the tree is read,
    251's before the arena is touched, 252's before the clock is read): a
    malformed ask is the caller's to repair, and the store should never see
    it — so :func:`replay_latency` runs first, and a broken population is
    refused without opening so much as a connection.

    Args:
        durations: The population of measured durations to summarise —
            feature 252's records, read duck-typed (see :func:`replay_latency`).
        measured_at: The instant the population was summarised, an ISO 8601
            UTC string (second resolution keeps the key comparable with
            :meth:`~datetime.datetime.isoformat`'s default spelling and the
            string order chronological).  Defaults to *now*; a caller that
            summarised at a known instant (a dreaming cycle, a test) passes
            it so the row's key matches the summary, not the write.
        source: Where the durations came from — a dreaming cycle's id, a
            benchmark run, a test.  Provenance, deliberately outside the key:
            the same population measured from two sources at the same instant
            is one snapshot.
        database_url: The observability metrics store to write to; defaults
            to ``DATABASE_URL``.

    Any failure of the write — an unconfigured store, an unsupported URL
    scheme, a locked or unwritable database — surfaces as
    :class:`~replay.ReplayMetricsError`, chained to the original.  It is
    deliberately *not* swallowed: a latency that measured but never landed is
    the state the feature exists to rule out, exactly as a cost model that
    resolved but never persisted is feature 59's and a latency distribution
    that measured but never landed is feature 67's.

    Returns:
        The :class:`ReplayLatency` report that was written — the same object
        :func:`replay_latency` would have answered, so a caller that persists
        gets the summary it stored without computing it twice.
    """
    # The ask first, the store second: the summary is computed (and the
    # population refused, if it is not one) before a connection is opened, so
    # a broken population never reaches the store and the ordering of the
    # member's other refusals holds here too.
    report, ordered = _summarise(durations)
    instant = _instant_of(measured_at)
    try:
        samples_json = json.dumps(ordered)
    except (TypeError, ValueError) as exc:  # the samples are validated reals,
        # so this is unreachable in practice — but a serialisation failure is
        # still a write that did not land, and it surfaces in the store's
        # vocabulary rather than as a bare json error a caller cannot catch.
        raise ReplayMetricsError(
            f"could not serialise the replay latency samples measured at "
            f"{instant!r}: {exc!r}"
        ) from exc
    try:
        with closing(_open_store(database_url)) as connection, connection:
            connection.execute(
                f"""
                INSERT INTO {REPLAY_LATENCY_TABLE} (
                    measured_at, source, n, samples, p50, p99
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(measured_at) DO UPDATE SET
                    source  = excluded.source,
                    n       = excluded.n,
                    samples = excluded.samples,
                    p50     = excluded.p50,
                    p99     = excluded.p99
                """,
                (
                    instant,
                    source,
                    report.n,
                    samples_json,
                    report.p50_seconds,
                    report.p99_seconds,
                ),
            )
    except ReplayMetricsError:
        raise
    except (sqlite3.Error, OSError) as exc:
        # The store's own failure, translated: a caller catching this
        # member's base class must catch a report that measured but never
        # landed, and the original is chained so the operator still sees the
        # database's own words.
        raise ReplayMetricsError(
            f"could not persist the replay latency measured at {instant!r} "
            f"into the observability metrics store: {exc!r}. A report that "
            "measured but never landed is the state feature 254 exists to "
            "rule out — the deployment's p50/p99 are how the 50 ms target of "
            "docs §10.4 is supervised — so the failure is surfaced, never "
            "swallowed; the repair is the store's (the original refusal is "
            "chained), never a re-run over a population that already measured"
        ) from exc
    return report


def load_replay_latency(
    database_url: str | None = None,
) -> list[tuple[str, ReplayLatency, str | None]]:
    """Read every persisted latency snapshot, newest first.

    Returns ``(measured_at, report, source)`` triples ordered by
    ``measured_at`` descending — the ISO 8601 UTC key's string order is
    chronological, so newest-first is the table's own order.  The table is a
    *history*: each dreaming cycle's summary is a row, and a reader that
    wanted only the latest would be asking a history question and getting a
    single answer (:func:`load_latest_replay_latency` is that spelling).  An
    empty list is the honest answer for a deployment that has never
    summarised a population: a discoverable state, not an exception, on the
    same stance the cost-model member's readers take.

    Each report is rebuilt **from the samples** — the source of truth — never
    from the denormalised ``p50``/``p99`` columns, so the report a caller
    reads is the summary of the population that was written and cannot drift
    from it.  The reader selects ``measured_at, source, n, samples, p50,
    p99``, so ``samples`` is index 3; positional, matching the store
    conventions of this workspace (the connections set no row factory, and
    the column order is the SELECT's contract).  A row whose samples cannot
    be read back as measured durations is refused by name — a corrupt row is
    a report no operator could rely on, and refusing it is how the rest of
    the history stays trustworthy.
    """
    try:
        with closing(_open_store(database_url)) as connection:
            rows = connection.execute(
                f"""
                SELECT measured_at, source, n, samples, p50, p99
                FROM {REPLAY_LATENCY_TABLE}
                ORDER BY measured_at DESC
                """
            ).fetchall()
    except ReplayMetricsError:
        raise
    except (sqlite3.Error, OSError) as exc:
        raise ReplayMetricsError(
            f"could not read the replay latency history from the "
            f"observability metrics store: {exc!r}. The history is how a "
            "deployment supervises its replay latency against the 50 ms "
            "target of docs §10.4 (feature 254), so a store that cannot be "
            "asked is surfaced rather than answered around; the repair is "
            "the store's (the original refusal is chained)"
        ) from exc
    return [(_row_to_report(row)) for row in rows]


def load_latest_replay_latency(
    database_url: str | None = None,
) -> ReplayLatency | None:
    """Read the most recently persisted latency report, or ``None``.

    The reader a dashboard or an operator resolves against: the newest
    snapshot in the history, or ``None`` — the honest answer for a deployment
    that has never summarised a population.  ``None`` is a signal the caller
    must handle rather than a default to paper over: a deployment whose
    replay latency has never been persisted is a deployment whose supervision
    of docs §10.4's target has not started, and reporting a zero in place of
    the absence would be the fabricated figure the feature refuses to
    produce.
    """
    history = load_replay_latency(database_url)
    if not history:
        return None
    _, report, _ = history[0]
    return report


# -- the reads the seam performs ----------------------------------------------------------


def _samples_of(durations: Any) -> list[float]:
    """The population's measured durations — validated as they are read.

    The one place the population is touched: each carrier's
    ``duration_seconds`` is looked up and read, and what it answered is
    defended as a measured duration — a real, finite, non-negative number,
    the three facts 252's constructor defends, restated because a duck-typed
    carrier owes the proof a constructor no longer stands behind.  A bare
    number is refused (it names no replay), an empty population is refused
    (p50/p99 over zero replays is the absence of a latency, not one), and a
    carrier that cannot be read is refused naming it — all before the caller
    (the summary, the write) touches anything else.
    """
    if durations is None or isinstance(durations, (str, bytes, bool, int, float)):
        raise ReplayMetricsError(
            f"a replay latency report summarises a population of measured "
            f"durations — got {durations!r} ({type(durations).__name__}), "
            "which is no population. Feature 254 aggregates feature 252's "
            "per-replay records — a population a dreaming cycle or a "
            "benchmark run holds — into p50 and p99, and a value that is not "
            "a population of them names no replays to summarise"
        )
    try:
        carried = list(durations)
    except TypeError as exc:
        raise ReplayMetricsError(
            f"a replay latency report summarises a population of measured "
            f"durations — got {durations!r} ({type(durations).__name__}), "
            "which is not iterable. Feature 254 aggregates feature 252's "
            "per-replay records into p50 and p99, and a carrier that cannot "
            "be walked names no population to summarise"
        ) from exc
    if not carried:
        raise ReplayMetricsError(
            "a replay latency report summarises a population of at least one "
            "measured duration — got an empty population. p50 and p99 over "
            "zero replays is not a latency, it is the absence of one, and "
            "persisting such a figure would be the fabricated latency "
            "feature 67's sentence refuses to fall back to and feature 254 "
            "inherits the refusal of"
        )
    samples: list[float] = []
    for position, carrier in enumerate(carried):
        samples.append(_duration_of(carrier, position))
    return samples


def _duration_of(carrier: Any, position: int) -> float:
    """One carrier's measured duration — read duck-typed, or refused.

    A duration is read by what it *is* — a ``duration_seconds`` answering a
    real, finite, non-negative number — never by ``isinstance``, because the
    module loader imports a member under a synthetic name and re-executes it,
    so the record a composed application's path produced is a second class
    object of the same name and a class check would refuse the very duration
    the deployment measured.  A bare number is refused here too: it names no
    ``(policy, world)`` replay, and 252's record — the measurement *and* the
    identity it was measured for — is the unit this feature aggregates.
    """
    duration = getattr(carrier, "duration_seconds", None)
    if (
        duration is None
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
    ):
        raise ReplayMetricsError(
            f"the duration at position {position} of the population — "
            f"{carrier!r} ({type(carrier).__name__}) — is not a measured "
            "replay duration. Feature 254 summarises feature 252's records, "
            "each carrying the one measured ``duration_seconds`` of one "
            "(policy, world) replay, and a carrier that does not answer one "
            "names no replay this population could be summarised over; a "
            "bare number is refused for the same reason — it names no "
            "replay, and the identity is half of what the record persists"
        )
    value = float(duration)
    if not math.isfinite(value):  # NaN or either infinity: not an order
        # statistic of measured durations — a NaN compares false against
        # everything and would drop out of a percentile, reading as "no
        # replay", and an infinity is a ruler with no end (the same two
        # refusals 252's constructor makes, restated for the duck-typed read).
        raise ReplayMetricsError(
            f"the duration at position {position} of the population is "
            f"{value!r}. A replay's duration is a finite, real interval on a "
            "single core (feature 252), and a value that is not finite is "
            "not one — it would compare false against a rank or drop out of "
            "the p99, so a non-finite duration is a measurement no "
            "percentile can aggregate"
        )
    if value < 0.0:
        raise ReplayMetricsError(
            f"the duration at position {position} of the population is "
            f"negative ({value!r}). A replay's duration is measured on a "
            "monotonic clock read once at each end (feature 252), so the "
            "difference cannot be negative — a negative duration is a clock "
            "read in the wrong order, and a percentile built on it would be "
            "measuring against a ruler that runs backwards"
        )
    return value


def _percentile_value(name: str, value: Any) -> float:
    """A percentile as the report carries it — a real, finite, non-negative.

    The constructor's own read of a handed-in p50/p99: the free function
    computed them from a validated population, and the reader rebuilt them
    from persisted samples, but the constructor is also this seam's own
    spelling (a caller that holds computed percentiles), so the two numbers
    are defended here — the same defence the population's durations get, for
    the same reason: a percentile that is not a finite non-negative real is
    not an order statistic of any population this member can aggregate.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ReplayMetricsError(
            f"a replay latency report's {name} is a real number — got "
            f"{value!r} ({type(value).__name__}). The two percentiles are "
            "order statistics of a population of measured durations (feature "
            "254), and a value that is not a number is not one"
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ReplayMetricsError(
            f"a replay latency report's {name} is a finite, non-negative "
            f"real — got {number!r}. The two percentiles are order "
            "statistics of a population of measured durations (feature 254), "
            "and a value that is not a finite non-negative real is not one — "
            "a NaN would compare false against every rank and an infinity is "
            "a tail no population measured"
        )
    return number


def _instant_of(measured_at: str | None) -> str:
    """The snapshot's instant — the caller's, or the wall clock's now.

    ``measured_at`` defaults to *now* (UTC, second resolution — the spelling
    :meth:`~datetime.datetime.isoformat` produces and the one the table's
    ``ORDER BY`` stays chronological under), because a caller that summarised
    a population at a known instant passes it so the row's key matches the
    summary rather than the write.  An explicit instant must be a non-empty
    string — it is the row's *key*, and a key that is not a nameable instant
    would upsert onto nothing nameable.  The wall clock read here is a label,
    never a measurement: the only clock a duration is read from remains
    feature 252's :func:`time.perf_counter`.
    """
    if measured_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(measured_at, str) or not measured_at.strip():
        raise ReplayMetricsError(
            f"a latency snapshot's instant is an ISO 8601 UTC string — got "
            f"{measured_at!r} ({type(measured_at).__name__}). The instant is "
            "the row's key in the observability metrics store (feature 254), "
            "and a value that is not a nameable instant would upsert onto "
            "nothing nameable; pass the instant the population was "
            "summarised at, or nothing and let the write stamp its own"
        )
    return measured_at


def _row_to_report(row: Any) -> tuple[str, ReplayLatency, str | None]:
    """Rebuild a report from a persisted row — from the samples.

    The samples are the source of truth, so the report is reconstructed from
    them (recomputed under :data:`REPLAY_LATENCY_METHOD`, through the same
    :func:`quantile` the write used), never from the denormalised
    ``p50``/``p99`` columns: those are an index for a reader that only wants
    the two numbers, and rebuilding from them would let the report and the
    population it summarises drift.  Reading from the samples is what makes
    the round trip lossless — the same law the cost-model member's latency
    store states for its own rows.

    The reader selects ``measured_at, source, n, samples, p50, p99``, so the
    columns are read positionally: the contract the store conventions of
    this workspace spell (no row factory; the SELECT's order is the
    contract).  A samples column that does not read back as a population of
    measured durations is refused by name, so a corrupt row fails loudly
    rather than quietly answering a fabricated percentile.
    """
    measured_at, source, count, samples_json = row[0], row[1], row[2], row[3]
    try:
        raw = json.loads(samples_json)
    except (TypeError, ValueError) as exc:
        raise ReplayMetricsError(
            f"the replay latency snapshot at {measured_at!r} carries samples "
            f"that do not read back as a JSON array: {exc!r}. The samples are "
            "the source of truth of a persisted report (feature 254), and a "
            "row whose truth cannot be read is a report no operator could "
            "rely on — the repair is the store's, never a re-summarise over "
            "a population that already measured"
        ) from exc
    if (
        not isinstance(raw, list)
        or not raw
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0.0
            for value in raw
        )
    ):
        raise ReplayMetricsError(
            f"the replay latency snapshot at {measured_at!r} carries samples "
            f"that are not a population of measured durations — got "
            f"{raw!r}. The samples are the source of truth of a persisted "
            "report (feature 254), and a row whose samples are not the "
            "measured durations of real replays (each a finite, non-negative "
            "real number of seconds, feature 252's unit) is a report no "
            "operator could rely on"
        )
    ordered = sorted(float(value) for value in raw)
    report = ReplayLatency(
        len(ordered),
        quantile(ordered, REPLAY_LATENCY_QUANTILES[0]),
        quantile(ordered, REPLAY_LATENCY_QUANTILES[1]),
    )
    if isinstance(count, int) and count != report.n:
        # The count is the one figure the samples already determine, so a
        # stored count that disagrees with them is a row that disagrees with
        # its own truth — refused by name rather than read, the tamper check
        # that keeps the history trustworthy.
        raise ReplayMetricsError(
            f"the replay latency snapshot at {measured_at!r} claims a count "
            f"of {count} but carries {report.n} samples. The count is the "
            "figure a reader distrusts a small-sample p99 against (feature "
            "254), and a row whose count disagrees with its own samples is a "
            "report no operator could rely on"
        )
    return (measured_at, report, source if isinstance(source, str) else None)


def _open_store(database_url: str | None) -> sqlite3.Connection:
    """Open the observability metrics store ``DATABASE_URL`` names.

    The member's own spelling of the open every store in this workspace
    performs: the URL comes from the argument or the one ambient the
    workspace's stores share (``DATABASE_URL``), a missing one is refused by
    name rather than by a bare error, and only ``sqlite:///`` speaks — the
    spec's single-machine allowance — with any other scheme refused loudly
    rather than silently mis-parsed, so a misrouted Postgres URL cannot hide
    behind a mysterious file.  The schema is created idempotently on connect
    (``CREATE TABLE IF NOT EXISTS``, the contract every store here states),
    so a fresh database and an existing one take one path and no migration
    step is needed for this member.  The caller owns the connection; use it
    as a context manager to commit.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url:
        raise ReplayMetricsError(
            f"no observability metrics store configured: pass a database URL "
            f"or set {DATABASE_URL_ENV} to one (sqlite:///path/to/store.db "
            "on a single machine — docs §16's 'single Postgres metrics "
            "table', the simpler option the section defends at this scale)"
        )
    parsed = urlparse(url)
    if parsed.scheme != "sqlite":
        raise ReplayMetricsError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "observability metrics store speaks sqlite:/// (the spec's "
            "single-machine allowance), the same refusal every store in this "
            "workspace documents — a Postgres metrics table arrives with the "
            "versioned migration member, and pretending to speak it here "
            "would hide a misrouted URL behind a mysterious file"
        )
    if parsed.netloc not in ("", "localhost"):
        raise ReplayMetricsError(
            f"the observability metrics store's sqlite {DATABASE_URL_ENV} "
            f"must not carry a host, got {parsed.netloc!r}"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise ReplayMetricsError(
            f"the observability metrics store's sqlite {DATABASE_URL_ENV} "
            "carries no database path"
        )
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    with connection:
        connection.executescript(_SCHEMA)
    return connection
