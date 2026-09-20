"""Persisting the node metrics — feature 80's other half.

app_spec.xml feature 80: *"System computes ic_mean, ic_tstat, ir_standalone
and turnover, **persisting each as a scalar on the node record**."*  The
computation lives in :mod:`evaluator._metrics`; this module writes the four
scalars down.  The split is the one this package already uses four times —
``_identity`` computes and ``_store`` persists for feature 70, ``_costs`` and
``_cost_store`` for 79, ``_capacity`` and ``_capacity_store`` for 82,
``_decay`` and ``_decay_store`` for 81 — and for the same reason: a caller that
had to wire the two together at every call site would eventually wire them
together differently at one of them.

**What "the node record" is, and why this store does not write it.**  §9.1's
``node`` table is the tree store's own — it carries the node's identity,
provenance triple, code hash, agent fields and the ``ic_mean`` / ``ic_tstat`` /
``ir_standalone`` / ``turnover`` columns feature 101 adds — and the tree store
is written by the tree member (feature 85), not by the evaluator: the evaluator
owns the *metrics*, the tree member owns the *table*, and the two meet at one
boundary.  This module does not write the ``node`` table: it owns the
*evaluator's* half of the feature — computing the four scalars and getting them
somewhere durable and checkable — and it stores them in the workspace's
relational store, addressed by ``DATABASE_URL``, the same stance feature 79's
cost store, feature 81's decay store and feature 82's capacity store take and
argue.  The caller holding a node and the tree store is what later writes the
four columns, reading this store through :meth:`NodeMetricsStore.load`, so the
node row and the row this store writes cannot disagree about what was measured,
and the two writers of one evaluation's scalars share one source.

**The grain: one row per evaluation per cost model.**  The four scalars are one
value per evaluation — measured over one pinned horizon (:data:`METRICS_HORIZON`,
the shortest the priced panel covers) — so the table is keyed
``(node_id, venue, version)``, the same key the signal-returns grid, the capacity
table and the decay table carry, and for the same reason: two fee schedules net
different post-cost returns out of the same gross ones, so the IC, IR and
turnover measured under one are not partial answers to a question about the
other, and §15 treats a changed cost model as its own failure case rather than
as noise.  There is no second table: unlike feature 82's pair, the four scalars
are one object, and splitting them across tables would create a half-written
state a reader would have to refuse rather than a check it could perform — the
scalars travel on one row, in one transaction, and the single row is either
wholly consistent with itself or refused.

**Assign-once in effect, though the write is an upsert**, on the same terms the
signal-returns, capacity and decay stores state: the primary key names the
evaluation and the cost model, so a re-measurement over the same bundle
refreshes the stored scalars rather than adding a second row — and a duplicate
row would read to the live loop as a second observation of the same signal.
The upsert rewrites the measured values and nothing that *names* the row, so it
cannot re-key a stored metrics into a different one.  A *changed* number under
an existing key is not refused: the key names the inputs, so a changed number is
a producer that re-measured, and the last write wins.  What is refused is a row
that cannot be *believed* — an ic_mean that is not the mean of its own stored
series, or a series that does not reconstruct.

**Schema.**  Floats round-trip exactly (JSON numbers are Python reprs; SQLite
TEXT is exact), so the read path's comparisons are exact rather than tolerant,
which is what lets the ic_mean-versus-series check be an equality rather than a
tolerance.  The per-date ``ic_series`` is stored in full rather than summarised,
because it is the series the artifact files separately as ``ic_series.parquet``
(feature 169) and the series feature 80's ``ic_tstat`` is computed over: a mean
alone cannot be re-read as a series, and the stored row could not be checked
against itself without it.  The schema is created idempotently on connect —
``CREATE TABLE IF NOT EXISTS``, the contract every store in this package states
— so a fresh database and an existing one take one path and no migration step is
needed for this member.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import unquote, urlparse

from ._costs import CostModelRef, cost_model_ref
from ._errors import EvaluatorMetricsError, EvaluatorStoreError
from ._metrics import NodeMetrics

__all__ = [
    "DATABASE_URL_ENV",
    "NODE_METRICS_TABLE",
    "NodeMetricsStore",
    "load_node_metrics",
    "persist_node_metrics",
]

#: The environment variable naming the relational store — the one spelling the
#: identity, cost, decay and capacity stores already use, restated here so each
#: store states its own contract (and so no store imports another's).
DATABASE_URL_ENV = "DATABASE_URL"

#: The table the node metrics live in — one row per evaluation per cost model,
#: carrying the four scalars beside the per-date IC series they reduce from.
#: Named for §9.1's ``node`` record, which the tree member writes from this row.
NODE_METRICS_TABLE = "node_metrics"

_SCHEMA = f"""
-- Feature 80: the node metrics, one row per evaluation per cost model.
--
-- The grain is per-evaluation because the four scalars are: ic_mean, ic_tstat,
-- ir_standalone and turnover, each measured over one pinned horizon
-- (METRICS_HORIZON, the shortest the priced panel covers).  `(node_id, venue,
-- version)` is the key — the key the signal-returns grid, the capacity table
-- and the decay table already carry, for the same reason: two fee schedules
-- net different post-cost returns out of the same gross ones, and the metrics
-- are measured against those net returns, so the cost model is in the identity
-- of the metrics rather than beside it.
--
-- `ic_series` is stored in full rather than summarised because it is the series
-- the artifact files separately as `ic_series.parquet` (feature 169) and the
-- series `ic_tstat` is computed over: a mean alone cannot be re-read as a
-- series, and the stored row could not be checked against itself without it.
-- The read path re-derives ic_mean from the series and refuses a row whose
-- stored ic_mean is not its own series' mean — the tamper defence the
-- signal-returns reader applies to `gross - charge` and the capacity reader to
-- a capacity that does not solve from its own terms.
-- `ic_series` maps each ISO date to its information coefficient.
CREATE TABLE IF NOT EXISTS {NODE_METRICS_TABLE} (
    node_id         TEXT NOT NULL,  -- the evaluation these metrics measure
    venue           TEXT NOT NULL,  -- feature 59's cost model pair
    version         TEXT NOT NULL,
    snapshot_name   TEXT NOT NULL,  -- provenance: which sealed world
    horizon         INT  NOT NULL,  -- METRICS_HORIZON: the horizon reduced over
    dates           INT  NOT NULL,  -- the denominator behind ic_mean, ic_tstat
    ic_mean         REAL NOT NULL,  -- the mean per-date information coefficient
    ic_se           REAL NOT NULL,  -- standard error of that mean
    ic_tstat        REAL NOT NULL,  -- ic_mean / ic_se
    ir_standalone   REAL NOT NULL,  -- the equal-weight book's information ratio
    turnover        REAL NOT NULL,  -- the equal-weight book's mean turnover
    turnover_dates  INT  NOT NULL,  -- how many rebalances turnover averaged over
    ic_series       TEXT NOT NULL,  -- JSON map of ISO date to coefficient
    PRIMARY KEY (node_id, venue, version)
);
"""


# -- The JSON spellings ---------------------------------------------------------


def _series_to_json(ic_series: Mapping[dt.date, float]) -> str:
    """The per-date IC series as one JSON object, keyed by ISO date.

    The series whose mean is ``ic_mean`` — the series the artifact files as
    ``ic_series.parquet`` and ``ic_tstat`` is computed over.  Floats serialize
    as their repr, which round-trips exactly, so the read path's re-derivation
    is a bitwise comparison rather than a tolerant one.
    """
    return json.dumps(
        {day.isoformat(): ic_series[day] for day in sorted(ic_series)}
    )


def _decode_series(payload: Any, *, node_id: str) -> dict[dt.date, float]:
    """The stored IC series, back as the dates it came from.

    Every key must be an ISO date and every value a finite number; the series
    is then handed to :class:`NodeMetrics`, which re-derives ``ic_mean`` from it
    and refuses a record that is not its own series' mean — so this decode
    captures, and the record's construction *is* the tamper check.
    """
    try:
        decoded = json.loads(payload)
    except ValueError as exc:
        raise EvaluatorStoreError(
            f"the stored node metrics' ic_series for node {node_id!r} are not "
            f"valid JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict) or not decoded:
        raise EvaluatorStoreError(
            f"the stored node metrics' ic_series for node {node_id!r} are not "
            "a non-empty object keyed by ISO date; rows are written with the "
            "series in full, so these did not come out of this store's writer"
        )
    series: dict[dt.date, float] = {}
    for key, value in decoded.items():
        try:
            day = dt.date.fromisoformat(key)
        except (TypeError, ValueError) as exc:
            raise EvaluatorStoreError(
                f"the stored node metrics' ic_series for node {node_id!r} "
                f"carries {key!r}, which is not an ISO 8601 calendar date; "
                "series are written as ISO date strings"
            ) from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluatorStoreError(
                f"the stored node metrics' ic_series for node {node_id!r} on "
                f"{key!r} carries {value!r}, which is not a number; a stored "
                "coefficient is a finite number"
            )
        if not math.isfinite(float(value)):
            raise EvaluatorStoreError(
                f"the stored node metrics' ic_series for node {node_id!r} on "
                f"{key!r} carries {value!r}, which is not finite; a stored "
                "coefficient is a finite number"
            )
        series[day] = float(value)
    return series


def _sqlite_path(database_url: str) -> Optional[Path]:
    """Translate a ``sqlite:///`` URL into a path (``None`` for in-memory).

    The same convention the identity, cost, decay and capacity stores document:
    ``sqlite:///foo.db`` is relative, an absolute path carries its leading slash
    after the triple, and any other scheme is refused loudly rather than
    silently mis-parsed.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise EvaluatorStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise EvaluatorStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    return Path(path) if path else None


# -- The store -------------------------------------------------------------------


class NodeMetricsStore:
    """Reads and writes the ``node_metrics`` table for one database.

    Bound to a database URL at construction; construction performs no I/O (the
    path is resolved and the schema created on first use), so composing an
    application that carries this store touches no disk — the stance every store
    in this workspace takes.  Like the identity, cost, decay and capacity stores
    and unlike the snapshot member's manifest store, it refuses rather than
    degrading when no store is configured: feature 80's text is "persisting",
    and the four scalars are what the node record and the live loop read back.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None
        self._resolved = False

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Optional[Mapping[str, str]] = None) -> "NodeMetricsStore":
        """The store ``DATABASE_URL`` names, or a refusal when it names none.

        An empty or whitespace-only value counts as unset, the way the shared
        fixtures treat an empty ``TEST_DATABASE_URL``.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "")
        if raw is None or not raw.strip():
            raise EvaluatorStoreError(
                f"{DATABASE_URL_ENV} is not set, so there is no store to "
                "persist the node metrics into (app_spec.xml feature 80); set "
                f"{DATABASE_URL_ENV} to the system's database"
            )
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The URL this store was bound to."""
        return self._database_url

    # -- The row ------------------------------------------------------------

    def persist(self, metrics: NodeMetrics) -> NodeMetrics:
        """Write one evaluation's four scalars; return the record that was written.

        The four scalars are written beside the per-date IC series they reduce
        from, in one row and one transaction, so a reader never sees a scalar
        whose terms are missing.  One upsert on the evaluation's key, so a
        re-measurement over the same bundle refreshes the stored scalars rather
        than adding a second row — a duplicate would read to the live loop as a
        second observation of the same signal.

        The upsert refreshes the measured values and nothing that *names* the
        row, so a re-measurement cannot re-key a stored metrics.  A store that
        cannot be reached, an unsupported URL scheme, a locked or unwritable
        database — every one surfaces as :class:`~evaluator.EvaluatorStoreError`,
        deliberately not swallowed: scalars that were measured and never landed
        are the state feature 80's "persisting" exists to rule out.
        """
        if not isinstance(metrics, NodeMetrics):
            raise EvaluatorMetricsError(
                "persist_node_metrics writes step 8's own result — a "
                f"NodeMetrics — got {type(metrics).__name__}; the four scalars "
                "it stores carry the cost model the returns were priced under, "
                "and anything else has none"
            )
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    f"""
                    INSERT INTO {NODE_METRICS_TABLE} (
                        node_id, venue, version, snapshot_name, horizon, dates,
                        ic_mean, ic_se, ic_tstat, ir_standalone, turnover,
                        turnover_dates, ic_series
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id, venue, version) DO UPDATE SET
                        snapshot_name   = excluded.snapshot_name,
                        horizon         = excluded.horizon,
                        dates           = excluded.dates,
                        ic_mean         = excluded.ic_mean,
                        ic_se           = excluded.ic_se,
                        ic_tstat        = excluded.ic_tstat,
                        ir_standalone   = excluded.ir_standalone,
                        turnover        = excluded.turnover,
                        turnover_dates  = excluded.turnover_dates,
                        ic_series       = excluded.ic_series
                    """,
                    (
                        metrics.node_id,
                        metrics.cost_model.venue,
                        metrics.cost_model.version,
                        metrics.snapshot_name,
                        metrics.horizon,
                        metrics.dates,
                        metrics.ic_mean,
                        metrics.ic_se,
                        metrics.ic_tstat,
                        metrics.ir_standalone,
                        metrics.turnover,
                        metrics.turnover_dates,
                        _series_to_json(metrics.ic_series),
                    ),
                )
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not persist the node metrics for node "
                f"{metrics.node_id!r}: {exc}"
            ) from exc
        return metrics

    def load(
        self,
        node_id: str,
        cost_model: Union[CostModelRef, object],
    ) -> Optional[NodeMetrics]:
        """Read one evaluation's four scalars back, or ``None``.

        The reader the tree member's node-row writer (feature 85) resolves
        against: given the node and the cost model a score names, answer with
        the metrics that were stored — or ``None``, the honest answer for an
        evaluation this store never measured, on the same stance the identity,
        cost, decay and capacity stores' readers take.

        The ``(venue, version)`` the caller names is *part of the question*,
        not a filter over it: scalars measured under one fee schedule are not a
        partial answer to a question about another.

        What comes back is *checked*, not trusted: the stored series is decoded
        and the record is rebuilt from it, and :class:`NodeMetrics` re-derives
        ``ic_mean`` from that series and refuses a record that is not its own
        terms' answer — so a row whose scalars were edited while its series was
        left alone is refused here rather than handed back as a plausible-looking
        set of numbers.
        """
        if not isinstance(node_id, str) or not node_id.strip():
            raise EvaluatorStoreError(
                "a node id must be a non-empty string to read the node metrics "
                f"by, got {node_id!r}"
            )
        ref = cost_model_ref(cost_model)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"""
                    SELECT snapshot_name, horizon, dates, ic_mean, ic_se,
                           ic_tstat, ir_standalone, turnover, turnover_dates,
                           ic_series
                    FROM {NODE_METRICS_TABLE}
                    WHERE node_id = ? AND venue = ? AND version = ?
                    """,
                    (node_id, ref.venue, ref.version),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise EvaluatorStoreError(
                f"could not read the node metrics for node {node_id!r} under "
                f"{ref.reference}: {exc}"
            ) from exc
        if row is None:
            return None
        (
            snapshot_name,
            horizon,
            dates,
            ic_mean,
            ic_se,
            ic_tstat,
            ir_standalone,
            turnover,
            turnover_dates,
            series_json,
        ) = row
        series = _decode_series(series_json, node_id=node_id)
        try:
            metrics = NodeMetrics(
                node_id=node_id,
                snapshot_name=snapshot_name,
                cost_model=ref,
                horizon=horizon,
                dates=dates,
                ic_mean=ic_mean,
                ic_se=ic_se,
                ic_tstat=ic_tstat,
                ir_standalone=ir_standalone,
                turnover=turnover,
                turnover_dates=turnover_dates,
                ic_series=series,
            )
        except EvaluatorMetricsError as exc:
            raise EvaluatorStoreError(
                f"the stored node metrics row for node {node_id!r} under "
                f"{ref.reference} does not reconstruct: {exc}; the row was "
                "written or edited outside this package, and a scalar that is "
                "not its own series' mean is a number the node record would "
                "trust and be wrong by"
            ) from exc
        return metrics

    # -- Connection ---------------------------------------------------------

    def _resolve_path(self) -> Optional[Path]:
        """Resolve the sqlite path once, refusing schemes this store cannot read.

        Deferred out of ``__init__`` so construction performs no I/O.  An
        in-memory URL resolves to ``None``, which :meth:`_connect` reads as
        "use ``:memory:``" — per-connection, which is why the schema is created
        on every connect rather than cached.
        """
        if self._resolved:
            return self._path
        self._path = _sqlite_path(self._database_url)
        self._resolved = True
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the store and ensure its schema exists.

        Idempotent on every connect, so a fresh database and an existing one
        take the same path.  The caller owns the connection.
        """
        self._resolve_path()
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path)
        else:
            connection = sqlite3.connect(":memory:")
        with connection:
            connection.executescript(_SCHEMA)
        return connection


# -- The module-level spellings the pipeline calls -----------------------------


def persist_node_metrics(
    metrics: NodeMetrics,
    database_url: Optional[str] = None,
) -> NodeMetrics:
    """Persist step 8's four scalars; return the record that was written.

    Feature 80's two verbs, joined: :func:`evaluator.compute_node_metrics`
    computes the four scalars and this writes them down.  ``database_url`` falls
    back to ``DATABASE_URL``, and a missing store is refused by name rather than
    silently skipped — feature 80 says "persisting", so scalars that never
    landed are the gap it exists to close.
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to persist "
            "the node metrics into (app_spec.xml feature 80); set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return NodeMetricsStore(url.strip()).persist(metrics)


def load_node_metrics(
    node_id: str,
    cost_model: Union[CostModelRef, object],
    database_url: Optional[str] = None,
) -> Optional[NodeMetrics]:
    """Read one evaluation's four scalars back, or ``None``.

    The functional spelling of :meth:`NodeMetricsStore.load`, for a caller that
    has no store object and only a node and a cost model: the store is resolved
    from ``DATABASE_URL``, and a missing one is refused by name rather than
    answered with a ``None`` that would read as "never measured".
    """
    url = (
        database_url
        if database_url is not None
        else os.environ.get(DATABASE_URL_ENV)
    )
    if not url or not url.strip():
        raise EvaluatorStoreError(
            f"{DATABASE_URL_ENV} is not set, so there is no store to read the "
            f"node metrics for node {node_id!r} from; set "
            f"{DATABASE_URL_ENV} to the system's database, or pass one "
            "explicitly"
        )
    return NodeMetricsStore(url.strip()).load(node_id, cost_model)
