"""Persistence for the empirical latency distribution (feature 67).

app_spec.xml, "Cost Model & Fill Simulation", feature 67: *System persists
an empirical p50, p95 and p99 latency distribution measured from shadow
runs rather than an assumed constant.*  Feature 59 persisted the resolved
cost model *identity* (:mod:`cost_model.store`: one row per ``(venue,
version)``); this module persists the *latency distribution* that identity
is priced with.  The two are related and deliberately not the same table:
feature 59's row says *which* cost model this is, and this module says
*how long its shadow runs took* — a cost model's identity is stable and
one-per-venue, but its latency distribution is measured repeatedly as more
shadow runs accumulate, so the distribution is a history the identity is
not.

**The row is the sample, not a summary of it.**  The natural shape for a
persisted distribution would be three columns — ``p50``, ``p95``,
``p99`` — and nothing else, since those are the numbers the feature names.
But a distribution persisted as a summary cannot be read back as the thing
it was: the reader would get three numbers and lose the sample they came
from, so a re-measurement could not append and a later feature could not
recompute a quantile the writer did not think to store.  The distribution
(:class:`cost_model.latency.EmpiricalLatencyDistribution`) keeps the whole
sample for exactly this reason, and persistence mirrors that: the samples
are stored as a JSON array, and the p50/p95/p99 columns are a *derived*,
denormalised view over them — an index for a reader that only wants the
tail, not the source of truth.  The samples are the source of truth, and
reading a distribution back rebuilds it from the samples, so the persisted
row round-trips to the distribution that was written.

**One row per ``(venue, version, measured_at)``.**  The pair is the cost
model identity (feature 59); the instant is *when the latency was
measured*.  A cost model's latency is re-measured as shadow runs
accumulate, and each measurement is a distinct snapshot of the tape at that
time — so the primary key carries the instant, and the table is a
time-ordered history of latency snapshots, one per cost model per moment.
That is the shape "measured from shadow runs" demands: latency is not a
static property of a cost model, it is a property of a cost model *at a
point in its shadow execution*, and collapsing the history to one row per
cost model would lose the very thing being tracked.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as :mod:`cost_model.store` and the universe and snapshot members
are — ``sqlite:///`` on a single machine, Postgres in production.  The
schema is created idempotently on connect, so no migration step is needed
for this member; a URL whose scheme is not ``sqlite`` is refused by name,
the same refusal the identity store documents.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Optional

from .errors import CostModelStoreError
from .latency import DEFAULT_QUANTILES, EmpiricalLatencyDistribution
from .store import connect

__all__ = [
    "LATENCY_TABLE",
    "load_latency_distributions",
    "load_latest_latency_distribution",
    "persist_latency_distribution",
]

#: The table the empirical latency distributions live in.
LATENCY_TABLE = "cost_model_latency"

_SCHEMA = f"""
-- Feature 67: the empirical latency distribution measured from shadow runs.
--
-- The primary key is (venue, version, measured_at): a cost model's identity
-- is the (venue, version) pair feature 59 persists, but its latency is
-- re-measured as shadow runs accumulate, so each measurement is a distinct
-- snapshot keyed by when it was measured.  The table is therefore a history
-- of latency snapshots, not one row per cost model.
--
-- `samples` is the source of truth: the observed latencies as a JSON array.
-- `p50`/`p95`/`p99` are a denormalised view over those samples — an index
-- for a reader that only wants the tail, not the distribution itself.  A
-- distribution is always rebuilt from `samples` on read, so the row
-- round-trips losslessly.
CREATE TABLE IF NOT EXISTS {LATENCY_TABLE} (
    venue       TEXT NOT NULL,  -- the cost model's venue (feature 59's pair)
    version     TEXT NOT NULL,  -- the cost model's version string
    measured_at TEXT NOT NULL,  -- ISO 8601 UTC: when the latency was measured
    source      TEXT,           -- where the samples came from (provenance)
    n           INTEGER NOT NULL,  -- number of shadow-run samples
    samples     TEXT NOT NULL,  -- the observed latencies, JSON array
    p50         REAL NOT NULL,  -- derived: 50th percentile of samples
    p95         REAL NOT NULL,  -- derived: 95th percentile of samples
    p99         REAL NOT NULL,  -- derived: 99th percentile of samples
    PRIMARY KEY (venue, version, measured_at)
);
"""


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the latency table if absent, on the caller's connection.

    Split from :func:`store.connect` on purpose: the identity store owns
    opening a connection and creating *its* schema, and this module creates
    *its own* table on a connection it is handed — so a caller that already
    holds a connection (a batch that persists identity and latency together)
    does not open a second one, and the two tables are created by the
    modules responsible for them.  Idempotent, so calling it on every write
    and read is safe.
    """
    with connection:
        connection.executescript(_SCHEMA)


def persist_latency_distribution(
    distribution: EmpiricalLatencyDistribution,
    venue: str,
    version: str,
    *,
    measured_at: Optional[str] = None,
    source: Optional[str] = None,
    database_url: Optional[str] = None,
) -> EmpiricalLatencyDistribution:
    """Persist a measured latency distribution for a cost model; return it.

    Feature 67's sentence, made concrete: the distribution's samples land
    as the source of truth, and its p50/p95/p99 as the derived view over
    them, keyed by the cost model's ``(venue, version)`` identity and the
    instant the latency was measured.  A re-measurement at a later instant
    adds a row rather than overwriting, so the table accumulates the
    history of how a cost model's latency evolved as shadow runs piled up;
    a re-measurement at the *same* instant upserts onto the one row, which
    is the honest answer for the same snapshot written twice.

    Args:
        distribution: The measured latency distribution to persist.  Its
            samples are the source of truth; its quantiles are recomputed
            on read, so the persisted p50/p95/p99 are a convenience view.
        venue: The cost model's venue — half of the identity the latency is
            priced with (feature 59).
        version: The cost model's version string — the other half.
        measured_at: The measurement instant, an ISO 8601 UTC string.
            Defaults to *now*; a caller that measured at a known instant
            (a batch replay, a test) passes it so the row's key matches the
            measurement, not the write.
        source: Where the samples came from — a shadow-run log path, a
            replay, a test.  Provenance, deliberately outside the key: the
            same distribution measured from two sources at the same instant
            is one snapshot.
        database_url: The store to write to; defaults to ``DATABASE_URL``.

    Any failure of the write — an unconfigured store, an unsupported URL
    scheme, a locked or unwritable database, or a sample set that will not
    serialise — surfaces as
    :class:`~cost_model.errors.CostModelStoreError`.  It is deliberately
    *not* swallowed: a latency distribution that measured but never landed
    is the state feature 67 exists to rule out, exactly as a cost model
    that resolved but never persisted is feature 59's.
    """
    measured_at = measured_at or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    samples = list(distribution.sorted_samples)
    derived = distribution.percentiles(DEFAULT_QUANTILES)
    try:
        samples_json = json.dumps([float(s) for s in samples])
    except (TypeError, ValueError) as exc:
        raise CostModelStoreError(
            f"could not serialise the latency samples for "
            f"{venue!r}/{version!r}: {exc}"
        ) from exc
    try:
        with closing(connect(database_url)) as connection, connection:
            _ensure_schema(connection)
            connection.execute(
                f"""
                INSERT INTO {LATENCY_TABLE} (
                    venue, version, measured_at, source, n,
                    samples, p50, p95, p99
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(venue, version, measured_at) DO UPDATE SET
                    source  = excluded.source,
                    n       = excluded.n,
                    samples = excluded.samples,
                    p50     = excluded.p50,
                    p95     = excluded.p95,
                    p99     = excluded.p99
                """,
                (
                    venue,
                    version,
                    measured_at,
                    source,
                    len(samples),
                    samples_json,
                    derived[50.0],
                    derived[95.0],
                    derived[99.0],
                ),
            )
    except (sqlite3.Error, OSError) as exc:
        raise CostModelStoreError(
            f"could not persist the latency distribution "
            f"{venue!r}/{version!r} measured at {measured_at!r}: {exc}"
        ) from exc
    return distribution


def _row_to_distribution(row: sqlite3.Row) -> EmpiricalLatencyDistribution:
    """Rebuild a distribution from a persisted row — from the samples.

    The samples are the source of truth, so the distribution is always
    reconstructed from them, never from the denormalised p50/p95/p99
    columns: those are a derived view and rebuilding from them would let
    the distribution and the data it summarises drift.  Reading from the
    samples is what makes the round trip lossless.

    The reader selects ``venue, version, measured_at, source, n, samples,
    p50, p95, p99``, so ``samples`` is index 5.  Positional, matching
    :mod:`cost_model.store`: the store's connections do not set a row
    factory, and the column order is the SELECT's contract.
    """
    return EmpiricalLatencyDistribution(
        samples=json.loads(row[5]),
        quantiles=DEFAULT_QUANTILES,
    )


def load_latency_distributions(
    venue: str,
    version: str,
    database_url: Optional[str] = None,
) -> list[tuple[str, EmpiricalLatencyDistribution, Optional[str]]]:
    """Read every persisted latency snapshot for a cost model, newest first.

    Returns ``(measured_at, distribution, source)`` triples ordered by
    ``measured_at`` descending, so the caller sees the full history of how
    a cost model's latency was measured over time — the table is a history,
    and a reader that wanted only the latest would be asking a history
    question and getting a single answer.  An empty list is the honest
    answer for a cost model this store has never measured a latency for: a
    discoverable state, not an exception, on the same stance feature 59's
    reader takes.

    A store that cannot be reached at all surfaces as
    :class:`~cost_model.errors.CostModelStoreError`, the same type a failed
    write raises — the caller asked a question of a store it configured.
    """
    try:
        with closing(connect(database_url)) as connection:
            _ensure_schema(connection)
            rows = connection.execute(
                f"""
                SELECT venue, version, measured_at, source, n,
                       samples, p50, p95, p99
                FROM {LATENCY_TABLE}
                WHERE venue = ? AND version = ?
                ORDER BY measured_at DESC
                """,
                (venue, version),
            ).fetchall()
    except (sqlite3.Error, OSError) as exc:
        raise CostModelStoreError(
            f"could not read the latency distributions "
            f"{venue!r}/{version!r} from the store: {exc}"
        ) from exc
    return [
        (row[2], _row_to_distribution(row), row[3])
        for row in rows
    ]


def load_latest_latency_distribution(
    venue: str,
    version: str,
    database_url: Optional[str] = None,
) -> Optional[EmpiricalLatencyDistribution]:
    """Read the most recently measured latency distribution for a cost model.

    The reader a latency-aware cost computation resolves against: given the
    venue and version a score names, the store answers with the latest
    distribution that was measured — or ``None``, which is the honest
    answer for a cost model whose latency has never been measured.  A cost
    model priced against a latency nothing measured would be pricing
    against the assumed constant feature 67 refuses, so ``None`` is a
    signal the caller must handle, not a default to paper over.
    """
    snapshots = load_latency_distributions(venue, version, database_url)
    if not snapshots:
        return None
    _, distribution, _ = snapshots[0]
    return distribution
