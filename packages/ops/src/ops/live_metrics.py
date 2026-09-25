"""Feature 350's store: the live metrics, in the relational store the
deployment names.

app_spec.xml, "Observability & Dashboards", feature 350: *System persists
live metrics covering information coefficient ratio, fill cost in basis
points, order reject rate and feed staleness.*  The category's root
(feature 341, the GET /metrics/fdr-deploy route) established the seam the
later features hang from; this module is the persistence half of docs §16's
live-metrics line — *"**Live metrics:** live-vs-backtest IC ratio, realized
vs. modeled fill costs in bps, order reject rate, WS staleness, rate-limit
headroom"* — narrowed to the four the sentence names.

**The store owns no figure of its own.**  The member's law, stated in its
package docstring, is delegation, and it holds here as firmly as it does for
feature 341's route: the IC ratio is the scoring/evaluator members'
derivation (feature 337's forward IC retention, the evaluator's ``ic_mean``);
the fill cost is feature 340's ``reconciled_fill_costs``; the reject rate is
the router member's ``SubmissionHealth.rejection_ratio``; the staleness is the
risk member's halt quantity.  A store that reached into any of those members
to *compute* its metric would be a second spelling of a derivation that member
already owns, and would couple the metrics table's construction to four
siblings the factory scan could not promise are on ``sys.path`` at build time.
So the store **computes none of the four**: it accepts a ``(metric, value)``
pair handed over already measured — the same "hand over, never derive"
barrier feature 267 states for its pair and feature 340 states for its cost —
and validates the value against the shape the metric's *name* fixes.

**The four names are a closed set, and each name carries its own bound.**  The
sentence names exactly four, and a value stored under any other name is a
metric nobody measured and there is no column to put it in, so an unknown
metric is refused by name — the same closed-vocabulary discipline feature 306
holds for the book's kinds.  Each of the four is a finite real, but the bound
that makes it a *live metric* and not a corrupted number is the one its name
fixes:

* ``ic_ratio`` — the live-vs-backtest information-coefficient ratio.  An
  information coefficient is a correlation, bounded ``[-1, 1]`` by
  construction (the evaluator's ``ic_mean`` is one; the scoring member's
  ``IC_BOUND`` pins the bound), so the ratio is a finite real inside the
  correlation bound ``[-1, 1]`` — a live IC that flipped sign from backtest
  answers a negative ratio down to ``-1``, and that sign is the fact, but a
  value outside ``[-1, 1]`` could not be a ratio of two correlations and is
  refused at the door.
* ``fill_cost_bps`` — realized vs. modeled fill cost, in basis points.  Basis
  points is the unit feature 340's ``forward_cost_reconciliation`` already
  persists in, and a cost can be negative (price improvement), so this is a
  finite real with no sign bound — the unit is the column's own name, exactly
  as 340 states.  Refused only when not finite.
* ``reject_rate`` — the order reject rate.  A rate is a fraction of
  submissions, bounded ``[0, 1]`` — the router member's ``SubmissionHealth``
  answers ``rejected / total``, and a fraction of submissions cannot exceed
  one.  Refused outside ``[0, 1]``.
* ``feed_staleness_s`` — feed staleness, a WS-age duration in seconds.  A
  duration is a non-negative finite real — the risk member's staleness halt
  (docs §16 line 724: *"Data feed staleness > threshold"*) measures the same
  quantity this row records.  Refused when negative or not finite.

A value that is not a finite real at all — a count, a flag, a ``None``
standing in for an unread gauge — is refused before any bound is consulted
(``bool`` refused before real, the family's law), because none of the four is
a count or a flag, and the likeliest thing wearing the value's name at this
seam is a *count* of orders or rejects, which a bound would price as a metric
nobody measured.

**One metric, one column, the others NULL.**  The four values are four
nullable ``REAL`` columns in the member's own table ``ops_live_metrics``, and
a row records exactly one metric's value: the insert names the one column and
leaves the other three NULL by shape, so a row is never two metrics at once
and the ``(metric, logged_at)`` key never collides across metrics.  This is
the same discipline feature 267's store takes for its own columns and the
migration-tree convention states for REAL columns written NULL by insert
shape.  The key is ``(metric, logged_at)`` — ``logged_at`` an ISO 8601 UTC
instant (second resolution, string order chronological), the same label shape
feature 267's ``computed_at`` takes, so the series read orders by it — and the
write is an upsert on that key: a re-run of the same measurement at the same
instant refreshes the value, never appends a doubled row.

**The store is the workspace's one relational store, addressed the way every
member store addresses it.**  ``DATABASE_URL``, ``sqlite:///`` on a single
machine (docs §16's *"single Postgres metrics table ... the simpler option is
defensible"*, the spelling the replay member's metrics store and the bootstrap
member's pool take), the schema created idempotently on connect —
``CREATE TABLE IF NOT EXISTS``, the contract every store in this workspace
states — so no migration step is needed and no shared schema file is touched.
The class resolves its path lazily, so constructing one performs no I/O:
composition-time work must not touch the disk.  The ask is validated whole —
metric, value, instant — before a connection is opened, the ordering this
member states for every write and feature 267 states for its read: a broken
ask never reaches the store.  The store's own failures (no configured
``DATABASE_URL``, a scheme it cannot speak, a locked or unwritable database)
surface in this member's vocabulary (:class:`~ops.errors.LiveMetricError`, the
original chained), never swallowed — a live metric that measured but never
landed is the state this feature exists to rule out, exactly as a figure that
measured but never landed is feature 267's.

**The component beside the route and the dashboard.**  This is the ops
member's third component name and its second store-bound one — the growth the
member's own registration reserved when feature 341 landed and the app-package
seat reserved beside it (*"344-347's and 350's persisted metrics arrive as
this member's own tables"*).  :data:`OPS_LIVE_METRIC_COMPONENT_NAME`
(``ops-live-metric``) registers a builder that resolves ``DATABASE_URL`` and
answers ``None`` when nothing names a store — the degrade-don't-break stance
every store-bound builder here takes, for the same reason the pool's and the
scorer's builders take it: the factory builds every component on every
``create_app()`` call, and a deployment without a relational store must still
compose.  *No store is configured* and *the store is broken* are different
facts, and only the second may ever be quiet; a caller that needs a row
refuses to proceed rather than silently persisting nowhere — a metrics table
with a hole in it where a live reading should be is exactly the
quietly-defaulted number this feature exists to rule out.

**What this law deliberately does not do.**  It computes none of the four
(each is the source member's derivation, handed over already measured); it
opens no route (feature 342's lamps and 343's coverage are the category's
*expose* features); it renders no dashboard (feature 351's sentence and the
observability member's); it persists no row but its own — the research-metrics
row is 344's, the FDR_deploy rows are the scoring member's (feature 267), and
this table's one subject is the four live metrics.  It persists no rate-limit
headroom either: §16's live-metrics line names five, the sentence names four,
and the one it leaves out is deliberately out of scope — a feature is the
sentence it lands, and a fifth metric a caller could not validate against a
named source member would be a metric nobody measured.

Stdlib-only, like the rest of the member: :mod:`datetime` for the row's
label, :mod:`math` for the finiteness gate, :mod:`os` for the one ambient the
workspace's stores share, :mod:`sqlite3` for the store,
:mod:`contextlib`/:mod:`pathlib`/:mod:`urllib.parse` for the connection's
plumbing, :mod:`numbers` for the figures — no third-party import at module
scope, so the factory's scan (which imports this package to fire its
``@register`` builders) pays nothing for the law.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from contextlib import closing
from numbers import Real
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from .errors import LiveMetricError

__all__ = [
    "DATABASE_URL_ENV",
    "OPS_LIVE_METRIC_COMPONENT_NAME",
    "LIVE_METRIC_TABLE",
    "LIVE_METRICS",
    "LiveMetric",
    "LiveMetricsStore",
]

#: The environment variable naming the relational store — the one spelling
#: every member store in this workspace already uses (the bootstrap member's
#: pool, the replay member's metrics and score rows, feature 267's own
#: FDR_deploy store), restated here so this module states its own contract
#: and imports no sibling's.  §16's "single Postgres metrics table",
#: ``sqlite:///`` on a single machine.
DATABASE_URL_ENV = "DATABASE_URL"

#: The four live metrics this store persists — the closed set the sentence
#: names, each a member of which is a column in the table and a name a value
#: may be recorded under.  A value handed in under any other name is refused:
#: there is no column for it and no source member whose derivation fixes its
#: shape, so it is a metric nobody measured.  The order is the table's column
#: order and the :meth:`latest` read's answer order, so the four spellings —
#: the sentence, this constant, the schema and the read — cannot drift apart.
LIVE_METRICS = (
    "ic_ratio",
    "fill_cost_bps",
    "reject_rate",
    "feed_staleness_s",
)

#: The component name the live-metrics store registers under — this member's
#: third, beside :data:`~ops.OPS_COMPONENT_NAME` (the fdr-deploy route) and
#: :data:`~ops.OPS_DASHBOARD_COMPONENT_NAME` (the dashboard) the way
#: ``bootstrap-pool`` sits beside ``bootstrap``.  The growth was reserved by
#: the member's own registration when feature 341 landed and the app-package
#: seat reserved beside it (*"344-347's and 350's persisted metrics arrive as
#: this member's own tables"*), and spelled here, in the member's ``__init__``
#: and in the app-package seat (:mod:`app.modules.ops.live_metrics`) — two
#: spellings of one name the member's suite asserts agree.  Prefixed with the
#: member's own name because a composed application's ``order`` is name-sorted
#: and the store must sort *beside* — never inside — the member's other
#: components.
OPS_LIVE_METRIC_COMPONENT_NAME = "ops-live-metric"

#: The table the live-metrics rows live in — this member's own, in the
#: relational store ``DATABASE_URL`` names, created idempotently on connect so
#: no migration step is needed and no shared schema file is touched.  Named
#: member-first and subject-second (the way ``scoring_fdr_deploy`` and
#: ``forward_cost_reconciliation`` are named) so a reader of the store can
#: tell whose research row it is holding: the ops member's, for the live
#: metrics.
LIVE_METRIC_TABLE = "ops_live_metrics"

#: The per-metric bound — the shape the metric's *name* fixes, which a value
#: must fit to be the live metric it claims rather than a corrupted number.
#: Each entry is a ``(low, high)`` pair, inclusive, or ``None`` for an unbound
#: side: ``ic_ratio`` is a finite real in ``[-1, 1]`` and ``fill_cost_bps`` is
#: finite with no sign bound (a sign-flipped IC and a price-improving cost are
#: the facts), ``reject_rate``
#: is a fraction of submissions in ``[0, 1]``, and ``feed_staleness_s`` is a
#: non-negative duration.  Carried once so the validation, the schema comment
#: and the tests cannot drift apart on what "a valid value" means for each.
_IC_RATIO = "ic_ratio"
_FILL_COST_BPS = "fill_cost_bps"
_REJECT_RATE = "reject_rate"
_FEED_STALENESS_S = "feed_staleness_s"

_BOUNDS: dict[str, tuple[Optional[float], Optional[float]]] = {
    _IC_RATIO: (-1.0, 1.0),
    _FILL_COST_BPS: (None, None),
    _REJECT_RATE: (0.0, 1.0),
    _FEED_STALENESS_S: (0.0, None),
}

_SCHEMA = f"""
-- Feature 350: live metrics per instant — information coefficient ratio,
-- fill cost in basis points, order reject rate and feed staleness (docs
-- §16's live-metrics line, narrowed to the four the sentence names).
--
-- One row per (metric, logged_at).  `metric` is the closed-set name
-- (feature 350's four), `logged_at` an ISO 8601 UTC instant (second
-- resolution — string order is chronological, which is the order the
-- series read answers, the direction a reader watches a live metric
-- across).  The key is that pair, so a re-run of the same measurement at
-- the same instant refreshes the value rather than doubling the row.
--
-- The four values are four nullable REAL columns, and a row records
-- exactly one metric's value: the insert names the one column and leaves
-- the other three NULL by shape, so a row is never two metrics at once
-- and the (metric, logged_at) key never collides across metrics.  Each
-- value is validated against the bound its name fixes before it is
-- written (see ops.live_metrics): ic_ratio is a finite real in [-1, 1],
-- fill_cost_bps is finite with no sign bound, reject_rate is in [0, 1],
-- feed_staleness_s is a non-negative duration.
CREATE TABLE IF NOT EXISTS {LIVE_METRIC_TABLE} (
    metric           TEXT NOT NULL,  -- the closed-set name: one of feature 350's four
    logged_at        TEXT NOT NULL,  -- ISO 8601 UTC: when the metric was measured
    ic_ratio         REAL,           -- live-vs-backtest IC ratio (finite, in [-1, 1])
    fill_cost_bps    REAL,           -- realized vs. modeled fill cost, basis points (finite)
    reject_rate      REAL,           -- order reject rate, a fraction of submissions in [0, 1]
    feed_staleness_s REAL,           -- feed staleness, a WS-age duration in seconds (>= 0)
    PRIMARY KEY (metric, logged_at)
);
"""

#: One metric's value, validated and placed in its own column — the write.
#: The metric name selects the column; the other three are bound NULL by the
#: column list, so the insert shape is the one-metric-per-row law made
#: literal.  Upsert on (metric, logged_at): a re-run of the same measurement
#: at the same instant refreshes the value, never appends a doubled row.
_UPSERT = f"""
INSERT INTO {LIVE_METRIC_TABLE} (
    metric, logged_at, ic_ratio, fill_cost_bps, reject_rate, feed_staleness_s
) VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT(metric, logged_at) DO UPDATE SET
    ic_ratio         = excluded.ic_ratio,
    fill_cost_bps    = excluded.fill_cost_bps,
    reject_rate      = excluded.reject_rate,
    feed_staleness_s = excluded.feed_staleness_s
"""

#: One metric's rows, oldest first — the series read, in the direction a
#: reader watches a live metric across.
_SELECT_SERIES = (
    f"SELECT logged_at, ic_ratio, fill_cost_bps, reject_rate, feed_staleness_s "
    f"FROM {LIVE_METRIC_TABLE} WHERE metric = ? ORDER BY logged_at ASC"
)

class LiveMetric:
    """The metric's name and the bound its name fixes.

    The closed set of four, each a column in the table and a name a value may
    be recorded under.  A :class:`LiveMetric` is the ask's metric, validated
    as read — a member of :data:`LIVE_METRICS`, never a caller's free-form
    string — because the loader imports members under synthetic names and a
    plain string check would refuse the very value composition produced, and
    because a value stored under a name the table does not know is a metric
    nobody measured and there is no column to put it in.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        if name not in LIVE_METRICS:
            raise LiveMetricError(
                f"a live metric is one of {', '.join(LIVE_METRICS)} — the "
                f"closed set docs §16's live-metrics line names and the "
                f"sentence persists — and {name!r} is not one. A value stored "
                f"under a name the table does not know is a metric nobody "
                f"measured and there is no column to put it in; the repair is "
                f"the caller's (the metric it meant to record), never a new "
                f"column grown around a name nobody validated (feature 350)"
            )
        object.__setattr__(self, "name", name)


def _the_value(metric: str, value: object) -> float:
    """Narrow the handed-over figure to a finite ``float`` inside the bound
    the metric's name fixes.

    The value is handed over already measured — the source member's number,
    never recomputed here — and validated as read, the proof a duck-typed
    carrier owes because no constructor stands behind it.  ``bool`` is refused
    before real (``True`` is ``1`` in Python, and a flag where a live metric
    belongs would silently answer one nobody measured), a non-real is refused
    (the likeliest wearer of the value's name at this seam being a *count* of
    orders or rejects, which no bound would price as a metric), and a value
    outside the bound the metric's name fixes is refused rather than clamped —
    a clamped value would answer a live metric nobody measured.

    The bound is the metric's own: ``ic_ratio`` is a finite real in
    ``[-1, 1]`` and ``fill_cost_bps`` is finite with no sign bound,
    ``reject_rate`` is in ``[0, 1]``, ``feed_staleness_s`` is non-negative — so
    a value that could not be the metric it claims is refused at the door, and
    the metric's name is stated in the refusal so the repair (the number the
    source member actually measured)
    is actionable.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise LiveMetricError(
            f"the live metric {metric!r} is a finite real number — the "
            f"source member's measurement, handed over — and this value is "
            f"not one (got {value!r}, {type(value).__name__}). None of the "
            f"four is a count or a flag, and the likeliest thing wearing the "
            f"value's name at this seam is a count of orders or rejects, which "
            f"no bound would price as the live metric it claims (feature 350)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise LiveMetricError(
            f"the live metric {metric!r} must be finite, got {narrowed!r}: a "
            f"NaN or infinity would be a live reading the store silently "
            f"persisted and a later dashboard drew, and a live metric is a "
            f"measurement an operator steers by, not a number that has "
            f"stopped being one (feature 350)"
        )
    low, high = _BOUNDS[metric]
    if low is not None and narrowed < low:
        raise LiveMetricError(
            f"the live metric {metric!r} must be at least {low!r} — a "
            f"{_the_metric_words(metric)} — got {narrowed!r}. A value below "
            f"the bound could not be the metric it claims, and clamping it "
            f"would answer a live reading nobody measured (feature 350)"
        )
    if high is not None and narrowed > high:
        raise LiveMetricError(
            f"the live metric {metric!r} must be at most {high!r} — a "
            f"{_the_metric_words(metric)} — got {narrowed!r}. A value above "
            f"the bound could not be the metric it claims, and clamping it "
            f"would answer a live reading nobody measured (feature 350)"
        )
    return narrowed


def _the_metric_words(metric: str) -> str:
    """The bound's reason, in the metric's own words — stated in the refusal
    so the repair is actionable.
    """
    if metric == _REJECT_RATE:
        return "reject rate, a fraction of submissions"
    if metric == _FEED_STALENESS_S:
        return "feed staleness, a non-negative duration"
    # ic_ratio: a finite real inside the correlation bound [-1, 1] — a sign-
    # flipped IC answers a negative ratio down to -1, but a value outside
    # [-1, 1] could not be a ratio of two correlations.
    if metric == _IC_RATIO:
        return "information coefficient ratio, a finite real in [-1, 1]"
    return "fill cost in basis points, which can be negative"


def _instant_of(logged_at: Optional[str]) -> str:
    """The row's label — the caller's instant, or the wall clock's now.

    ``logged_at`` defaults to *now* (UTC, second resolution — the spelling
    :meth:`datetime.datetime.isoformat` produces and the one the series read's
    ``ORDER BY`` stays chronological under), because a caller that measured at
    a known instant passes it so the row's label matches the measurement
    rather than the write.  An explicit instant must be a non-empty string —
    it is the key half and the label the series read orders by, and a label
    that is not a nameable instant orders nothing.
    """
    if logged_at is None:
        return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    if not isinstance(logged_at, str) or not logged_at.strip():
        raise LiveMetricError(
            f"a live metric's logged_at is an ISO 8601 UTC string — got "
            f"{logged_at!r} ({type(logged_at).__name__}). The instant is the "
            f"key half of the row and the label the series read orders by, so "
            f"a value that is not a nameable instant orders nothing; pass the "
            f"instant the metric was measured at, or nothing and let the write "
            f"stamp its own (feature 350)"
        )
    return logged_at


class LiveMetricsStore:
    """§16's live metrics, in the relational store the deployment names.

    Constructed with the database URL it persists into; :meth:`record` lands
    one metric's measured value as its row, :meth:`latest` answers the most
    recent value of each of the four, and :meth:`series` answers one metric's
    rows oldest-first — the sequence a reader watches the live metric across.
    The class resolves its path lazily, so constructing one performs no I/O —
    composition-time work must not touch the disk, the contract every store in
    this workspace states — and the schema is created idempotently on the
    first connect, so no migration step is needed.

    Hand-written with ``__slots__`` and no ``__dict__``: a store is a holder,
    not a value, and there is no shadow state beside the URL for a caller to
    park a figure in.  Not frozen: the URL it holds is live deployment state,
    and the rows live in the database, never in the process — the store holds
    no cache of the values it wrote, so a value read back is a fact about the
    world rather than about this process's history.
    """

    __slots__ = ("_database_url", "_path")

    def __init__(self, database_url: str) -> None:
        # The URL is held, not resolved: validating it would touch the
        # filesystem or parse a scheme, and constructing a store is
        # composition-time work (the builder runs on every
        # create_app()) that must not refuse.  A URL this store cannot
        # speak is refused by name at first use, where the operator's
        # repair belongs.
        if not isinstance(database_url, str) or not database_url.strip():
            raise LiveMetricError(
                f"the live-metrics store is constructed with a database URL, "
                f"and this one is not a non-empty string (got "
                f"{database_url!r}, {type(database_url).__name__}): pass the "
                f"relational store to persist the live metrics into — "
                f"sqlite:///path/to/store.db, the spelling every member "
                f"store in this workspace takes (feature 350, docs §16)"
            )
        self._database_url = database_url.strip()
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Any = None) -> "LiveMetricsStore | None":
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        live-metric component — a discoverable state, not an exception — while
        the caller that must persist a live reading is the one that must not
        find itself in it.  The split is the one every resolve-shaped builder
        in this workspace states: this method answers *what is composed*, and
        the caller who needs a row and resolves ``None`` refuses to proceed
        rather than silently persisting nowhere — a metrics table with a hole
        in it where a live reading should be is exactly the quietly-defaulted
        number this feature exists to rule out.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store persists into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this store cannot speak is refused by name) the first time an operation
        needs it, which is the same laziness every store class in this
        workspace states for the same reason.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    # -- The verbs ------------------------------------------------------------

    def record(
        self,
        metric: object,
        value: object,
        *,
        logged_at: Optional[str] = None,
    ) -> None:
        """Persist one metric's measured value — the value handed over,
        validated against the bound the metric's name fixes.

        ``metric`` is the metric's name — text one of :data:`LIVE_METRICS`,
        validated to a :class:`LiveMetric` — and ``value`` is the already-
        measured figure, validated as read (a finite real inside the bound the
        metric's name fixes; ``bool`` refused before real).  ``logged_at``
        defaults to *now* (UTC, second resolution); a caller that measured at a
        known instant passes it so the row's label matches the measurement.

        The ask is validated whole — metric, value, instant — **before a
        connection is opened**, so a malformed ask never reaches the store and
        a refused record leaves no half-written row and no database file at
        all.  The write is an upsert on ``(metric, logged_at)``: a re-run of
        the same measurement at the same instant refreshes the value, never
        appends a doubled row.

        Any failure of the write — an unconfigured store, an unsupported URL
        scheme, a locked or unwritable database — surfaces as
        :class:`~ops.errors.LiveMetricError`, chained to the original and
        deliberately not swallowed: a live metric that measured but never
        landed is the state this feature exists to rule out.
        """
        metric_name = LiveMetric(metric).name
        narrowed = _the_value(metric_name, value)
        instant = _instant_of(logged_at)
        try:
            with closing(self._connect()) as connection, connection:
                connection.execute(
                    _UPSERT,
                    (metric_name, instant, *_the_row_values(metric_name, narrowed)),
                )
        except LiveMetricError:
            raise
        except (sqlite3.Error, OSError) as exc:
            # The store's own failure, translated: a caller catching this
            # member's base class must catch a live metric that measured but
            # never landed, and the original is chained so the operator still
            # sees the database's own words — never swallowed, never retried
            # over a value that already measured.
            raise LiveMetricError(
                f"could not persist the live metric {metric_name!r} into the "
                f"store: {exc!r}. The live metrics are docs §16's live-metrics "
                f"line, the readings an operator watches the running system "
                f"by, so a reading that measured but never landed is the state "
                f"feature 350 exists to rule out — the failure is surfaced, and "
                f"the repair is the store's (the original refusal is chained), "
                f"never a re-run over a value that already measured (feature "
                f"350, docs §16)"
            ) from exc

    def latest(self) -> dict[str, Optional[float]]:
        """The most recent value of each of the four, as ``{metric: value}``.

        One row per metric, the newest ``logged_at`` — the four tiles a later
        dashboard or expose-route would draw.  A metric with no row answers
        ``None`` (an absence, never ``0.0`` — a zero is a *measurement*, and a
        live metric that was never recorded is not a zero).  Each value is read
        off its own column, never recomputed: the store answers what was
        written, the stance feature 267 takes toward its own rows.  The newest
        per metric is picked in Python over a single oldest-first scan, so the
        read is one connection and the answer does not depend on a window
        function the store cannot promise.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT metric, logged_at, ic_ratio, fill_cost_bps, "
                    f"reject_rate, feed_staleness_s FROM {LIVE_METRIC_TABLE} "
                    f"ORDER BY metric, logged_at ASC"
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise LiveMetricError(
                f"could not read the latest live metrics from the store: "
                f"{exc!r}. The live metrics are the readings an operator "
                f"watches the running system by, so a store that cannot be "
                f"asked is surfaced rather than answered around; the repair is "
                f"the store's (the original refusal is chained) (feature 350)"
            ) from exc
        result: dict[str, Optional[float]] = {metric: None for metric in LIVE_METRICS}
        for metric, _instant, ic_ratio, fill_cost_bps, reject_rate, feed_staleness_s in rows:
            # Oldest-first, so the last row seen for a metric is its newest;
            # the value is read off the metric's own column, the others NULL.
            result[metric] = {
                "ic_ratio": ic_ratio,
                "fill_cost_bps": fill_cost_bps,
                "reject_rate": reject_rate,
                "feed_staleness_s": feed_staleness_s,
            }[metric]
        return result

    def series(self, metric: object) -> list[tuple[str, float]]:
        """One metric's rows, oldest first — the trend a reader watches the
        live metric across.

        ``(logged_at, value)`` pairs ordered by the row's instant — the
        direction a reader watches the live metric across.  An empty list is
        the honest answer for a metric that was never recorded: a discoverable
        state, not an exception and not a fabricated first point.  The metric
        is validated to a :class:`LiveMetric` before a connection is opened, so
        an unknown metric names no series.
        """
        metric_name = LiveMetric(metric).name
        column = _COLUMN_OF[metric_name]
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT logged_at, {column} FROM {LIVE_METRIC_TABLE} "
                    f"WHERE metric = ? ORDER BY logged_at ASC",
                    (metric_name,),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise LiveMetricError(
                f"could not read the {metric_name!r} series from the store: "
                f"{exc!r}. The live metrics are the readings an operator "
                f"watches the running system by, so a store that cannot be "
                f"asked is surfaced rather than answered around; the repair is "
                f"the store's (the original refusal is chained) (feature 350)"
            ) from exc
        return [(str(logged_at), value) for logged_at, value in rows]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        # Names the store and the URL it holds — a URL is not a secret,
        # and a repr is a debugging aid — and nothing else: the rows
        # live in the database, and the values are the caller's.
        return f"{type(self).__name__}({self._database_url!r})"

    # -- The connection ------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Open the database this store reads and writes.

        The URL is translated on first use (a scheme this store cannot speak is
        refused by name here, at the operation that needed it), the schema is
        created idempotently (``CREATE TABLE IF NOT EXISTS``, the contract
        every store in this workspace states), and the caller owns the
        connection — use it as a context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection


def _the_row_values(metric: str, value: float) -> tuple[float, float, float, float]:
    """The four column values for one metric's row — the metric's value in its
    own column, the other three NULL by shape.

    The insert names the one column and leaves the other three NULL, so a row
    is never two metrics at once and the ``(metric, logged_at)`` key never
    collides across metrics.  The order matches :data:`_UPSERT`'s column list:
    ``ic_ratio, fill_cost_bps, reject_rate, feed_staleness_s``.
    """
    columns = {
        _IC_RATIO: 0,
        _FILL_COST_BPS: 1,
        _REJECT_RATE: 2,
        _FEED_STALENESS_S: 3,
    }
    values = [None, None, None, None]
    values[columns[metric]] = value
    return (values[0], values[1], values[2], values[3])  # type: ignore[return-value]


#: The value column for each metric — the read's contract, spelled once so the
#: SELECTs and the insert cannot drift apart on which column a metric lives in.
_COLUMN_OF = {
    _IC_RATIO: "ic_ratio",
    _FILL_COST_BPS: "fill_cost_bps",
    _REJECT_RATE: "reject_rate",
    _FEED_STALENESS_S: "feed_staleness_s",
}


def _sqlite_path(database_url: str) -> Path:
    """The SQLite file a ``sqlite:///`` URL names — this store's own spelling
    of the translation every store in this workspace performs.

    Only ``sqlite:///`` speaks (docs §16's single-machine allowance), any other
    scheme refused loudly rather than silently mis-parsed so a misrouted
    Postgres URL cannot hide behind a mysterious file, no host but ``localhost``
    admitted, and a URL with no path refused — the same three refusals the
    replay member's metrics store and the bootstrap member's pool state for
    their own connections, restated because a member states its own contract.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise LiveMetricError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            f"live-metrics store speaks sqlite:/// (docs §16's 'single "
            f"Postgres metrics table', the simpler option the section defends "
            f"at this scale), the same refusal every store in this workspace "
            f"documents — a Postgres metrics table arrives with the versioned "
            f"migration member, and pretending to speak it here would hide a "
            f"misrouted URL behind a mysterious file (feature 350)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise LiveMetricError(
            f"the live-metrics store's sqlite {DATABASE_URL_ENV} must not "
            f"carry a host, got {parsed.netloc!r} (feature 350)"
        )
    path = unquote(parsed.path)
    path = path.removeprefix("/")
    if not path:
        raise LiveMetricError(
            f"the live-metrics store's sqlite {DATABASE_URL_ENV} carries no "
            f"database path (feature 350)"
        )
    return Path(path)
