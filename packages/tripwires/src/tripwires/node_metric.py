"""Persisting perturbation_stability as a node metric — feature 130's persistence half.

app_spec.xml, "Leakage Tripwires", feature 130: *"System jitters a declared
lookback by plus or minus 10 percent, persisting perturbation_stability as a
node metric."*  :mod:`tripwires.lookback` states the figure; this module is
where the second half of the sentence happens — the figure lands on the node
row itself, in the column the migration has been holding for it.

**The column, and why it exists after three features of not being written.**
``migrations/versions/0114_node_metrics.py`` creates seven metric columns on
``node`` and names this one ``perturb_stability REAL``, nullable with no
default, and every one of this member's stores has since walked past it:
feature 131 writes its mark, 132 reads the pool, 129 writes its own table
and *says why it does not write this column* — a single ``REAL`` holds one
number, while §C6 declares four perturbation axes whose figures are only
meaningful side by side, so 129 keys its table by ``(node_id, axis)`` and
leaves the node column "to feature 130, exactly as 0114's own docstring
leaves it".  This is feature 130, and the sentence that arrives with it is
the one that answers 129's deferred question: the single number the column
holds is *this feature's* — the lookback-jitter axis', the axis the same
sentence that says *persisting* names.  The four figures still live side by
side in 129's table; the column is the one axis the spec asks to be readable
off the node itself, beside its other metrics, without joining anything.

**Why requiring the node row is this store's own decision, and the opposite
of 129's.**  The stability ledger requires no node row, and its docstring
says why: a figure is legitimately known before the tree is handed the node
(§6.1 puts step 10 before the trial is debited), so refusing would force two
writes into an order the pipeline does not have.  A *column* write is the
other case.  The ledger's row is self-standing — keyed by its own
``(node_id, axis)``, it brings its own existence with it — while this write
is an ``UPDATE`` against a row some other feature owns, and there is nothing
to update when the tree does not hold the node: SQLite's ``UPDATE`` would
match zero rows and report success, and the caller would be told a metric
was persisted that no node carries.  So the store reads first, refuses a
node the tree does not hold by name, and only then writes — the
"looks done, is not" failure this category exists to prevent, in the one
place this feature could have committed it.

**The refresh, and what ``superseded`` is for.**  Re-measuring a node is the
normal case, not the exception — a re-run under a different seed or a
tightened bar produces a new figure for the same node, and the column holds
the newest one, the same refresh-on-the-key discipline 129's table keeps.
What a column cannot do is keep the old row the way a table can, so the
record this store returns carries the previous value as ``superseded``:
``None`` for a first measurement, the overwritten number for a refresh.  The
*column* keeps only the latest — that is what a node metric is — and the
receipt is where the history of the write survives, for the caller that
needs to say how much the figure moved.

**The schema path, and why it is an ``ALTER`` and not a bootstrap column.**
The node bootstrap (``node_bootstrap_schema``, feature 131's) creates 0118's
five structural columns plus ``poisoned_at`` — the columns *this member's
earlier features* read or write — and this column deliberately did not join
them, for the same restraint 129's table docstring states: a bootstrap is
what a feature brings for itself.  This feature brings its column the way
131 paved for a table the migration made without it: probe
``PRAGMA table_info``, and issue the ``ALTER TABLE ... ADD COLUMN
perturb_stability REAL`` when the column is missing.  Either starting point
— a database this store bootstrapped, or one the orchestrator migrated
through 0114 — ends at the same shape, and ``ALTER ... ADD COLUMN`` on a
table with rows leaves them ``NULL``, which is the column's own spelling of
*never measured*.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime`` and the same
``urllib.parse`` translation every store in this member uses; no third-party
import at module scope, so the factory's scan — which imports this package
to fire its ``@register`` — pays nothing for this module.  Construction
performs no I/O (the path is resolved on first use), so composing an
application never opens a database.

**What this module does not do.**  It does not measure anything (that is
:mod:`tripwires.lookback`, a pure function of mappings), write the stability
table (129's, and still 129's — a lookback verdict *may* be recorded there
by :func:`~tripwires.stability.record_stability`, which is the composition
the two stores' tests prove coexist), poison a subtree (131) or excise a
pool (132).  It writes one column on one row and reads it back.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import TripwireNodeMetricError, TripwirePoisonError
from .layout import (
    DATABASE_URL_ENV,
    NODE_ID_COLUMN,
    NODE_METRIC_COLUMN,
    NODE_TABLE,
    dialect_of,
    node_bootstrap_schema,
    sqlite_path,
    validated_instant,
    validated_node_id,
)
from .lookback import LOOKBACK_AXIS, LookbackRerunVerdict
from .seed_rerun import PERTURBATION_STABILITY_NAME

__all__ = [
    "COMPONENT_NAME",
    "NodeMetricRecord",
    "NodeMetricStore",
    "node_metric_of",
    "record_node_metric",
]

#: The component name this member registers its node metric store under — a
#: fifth name rather than a fifth method on the probe component, the same
#: convention :mod:`tripwires.stability` states for its own: the probe answers
#: *what is the composed tripwire suite?* while this answers *what is the
#: composed store a node metric is persisted to?*, and a caller asking for one
#: must not be handed the other.  Beside ``"tripwires-stability"`` rather than
#: inside it for the reason that store's builder gives: the two write two
#: different kinds of thing (a keyed row versus a column on another feature's
#: row), refuse two different sets of callers, and a caller that asked for the
#: ledger and was handed this store would be writing the node column when it
#: meant to append a figure.
COMPONENT_NAME = "tripwires-node-metric"

#: The fields this persistence reads off a verdict, checked **structurally**
#: rather than by ``isinstance`` — the same seam every validator in this
#: member states: the factory's scan imports this member under a synthetic
#: module name (``_nullius_scanned_tripwires``), so a suite that also imported
#: ``tripwires`` canonically holds two distinct ``LookbackRerunVerdict``
#: classes for one source file, and ``isinstance`` cannot hold across them.
#:
#: A *shorter* list than the stability store's, and that is the design rather
#: than the residue: that store writes a row that must be re-derivable from
#: its own terms, so it reads the statistics and the seeds and the horizon
#: back; this store writes **one column** — the figure and nothing beside it —
#: so the terms it needs are the identity (``node_id``, ``tripwire``,
#: ``axis``), the figure with its bar, and the decision.  A producer carrying
#: more is fine; a producer carrying less has nothing this store persists.
_NODE_METRIC_FIELDS = (
    "node_id",
    "tripwire",
    "axis",
    "rejected",
    "outcome",
    "stability",
    "stability_threshold",
)


def _validate_verdict(verdict: Any) -> Any:
    """Hold a lookback verdict to everything a column write must not take on trust.

    The shape check, the probe check and the outcome-word check are the
    stability store's, stated a second time because the field list is a
    different one.  The check that is **this store's alone** is the axis: the
    node column is single-valued, so it holds one axis' figure — this
    feature's, the lookback-jitter axis the same sentence that says
    *persisting* names — and a verdict from any other axis would overwrite it
    with another perturbation's number, which is precisely the drift 129's
    ``(node_id, axis)`` key exists to prevent.  The seed axis' figure, the
    subsample axis' and feature 128's-to-come belong in that table; a caller
    holding one of those verdicts and this store has made the wrong call, and
    the refusal names the axis it arrived with.
    """
    missing = [field for field in _NODE_METRIC_FIELDS if not hasattr(verdict, field)]
    if missing:
        raise TripwireNodeMetricError(
            f"a node metric is persisted from a lookback re-run verdict, and "
            f"{type(verdict).__name__} carries none of {', '.join(missing)}; the "
            "column's value comes from the verdict, and a producer whose terms "
            "the store cannot read would leave it writing a figure it cannot "
            "check"
        )
    if verdict.tripwire != PERTURBATION_STABILITY_NAME:
        raise TripwireNodeMetricError(
            f"a node metric is persisted from the {PERTURBATION_STABILITY_NAME!r} "
            f"probe, and this verdict names {verdict.tripwire!r}; feature 125's "
            "probe states a *detection* and feature 131 persists it as a "
            "poisoning — a detection written into the node's metric column "
            "would read as a perturbation measurement that was never taken"
        )
    if verdict.axis != LOOKBACK_AXIS:
        raise TripwireNodeMetricError(
            f"the node's perturb_stability column holds the {LOOKBACK_AXIS!r} "
            f"axis' figure — feature 130's own sentence — and this verdict "
            f"carries axis {verdict.axis!r}; the node column is one number, and "
            "writing another perturbation's figure into it would make the node "
            "metric read as whichever axis was scheduled last. The stability "
            "table is where every axis' figure lives side by side"
        )
    if not isinstance(verdict.rejected, bool):
        raise TripwireNodeMetricError(
            f"a lookback verdict's rejected is a boolean, got "
            f"{verdict.rejected!r}"
        )
    expected_outcome = "tripwire_fail" if verdict.rejected else "ok"
    if verdict.outcome != expected_outcome:
        raise TripwireNodeMetricError(
            f"the lookback verdict says rejected={verdict.rejected!r} but "
            f"carries outcome {verdict.outcome!r}; the outcome word is the "
            "decision's own translation into §8's vocabulary, and the column is "
            "what survives the in-memory value — a node whose word disagreed "
            "with its bit would classify a pass at the ledger as a failure"
        )
    for field in ("stability", "stability_threshold"):
        value = getattr(verdict, field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TripwireNodeMetricError(
                f"a lookback verdict's {field} must be a number, got {value!r}"
            )
        if not math.isfinite(float(value)):
            raise TripwireNodeMetricError(
                f"a lookback verdict's {field} is not finite ({value!r}); a NaN "
                "or ±inf would reach the node row dressed as a stability "
                "figure"
            )
    if float(verdict.stability_threshold) <= 0.0:
        raise TripwireNodeMetricError(
            f"a lookback verdict's configured stability threshold is positive, "
            f"got {verdict.stability_threshold!r}; a threshold of zero rejects "
            "every candidate the jitter moved at all — which is every "
            "candidate — and a negative one rejects none"
        )
    return verdict


# -- The shared parsers, under this module's error ---------------------------------
#
# The three functions below are the *only* places this module reads or
# normalizes a value through :mod:`tripwires.layout`, and every one of them is
# a thin translation rather than a second implementation: the check itself is
# shared, so this member cannot hold two opinions about what a node id or a
# stored instant is.  Only the *vocabulary* differs, for the reason
# :mod:`tripwires.stability` states for its own three wrappers — a caller in
# the evaluation loop catches :class:`~tripwires.TripwireNodeMetricError`
# because the node metric is what it asked to persist, and a `DATABASE_URL`
# this member cannot speak, a node id that cannot join the tree's key, or an
# unparseable stamp arriving as :class:`~tripwires.TripwirePoisonError` is
# precisely the case that caller did not catch.  Feature 131 *owns* those
# refusals — they are written in its vocabulary and its suite pins them — so
# the fix belongs here at the seam, not by widening 131's error to cover a
# feature it knows nothing about.


def _node_metric_path(database_url: str) -> Path:
    """The file ``database_url`` names, under *this* module's error.

    :func:`~tripwires.layout.sqlite_path` refuses a URL this member cannot
    speak with :class:`~tripwires.TripwirePoisonError`.  A node metric store
    handed one of those has to answer in its own vocabulary: the store's
    docstring promises that ``resolve`` returning ``None`` means *a deployment
    without a relational store*, and a caller that writes ``except
    TripwireNodeMetricError`` around the persistence half — the one thing that
    catches "the lookback figure never reached the node row" — would miss a
    misrouted ``DATABASE_URL`` entirely and take the process down with an
    error from the poisoning feature.
    """
    try:
        return sqlite_path(database_url)
    except TripwirePoisonError as exc:
        raise TripwireNodeMetricError(
            f"the node metric store could not be addressed: {exc}"
        ) from exc


def _node_metric_node_id(value: Any) -> str:
    """Validate a node id — :func:`~tripwires.layout.validated_node_id`, here.

    The member has exactly one node-id normalization and this is not a second
    one.  Every value this store writes joins ``node.id UUID PRIMARY KEY``,
    and it matters more here than anywhere else in the member: the write is an
    ``UPDATE ... WHERE id = ?``, so a mixed-case or braced spelling of one
    node would match zero rows and read back as a successful persistence of
    nothing.
    """
    try:
        return validated_node_id(value)
    except TripwirePoisonError as exc:
        raise TripwireNodeMetricError(
            f"a node metric could not name its node: {exc}"
        ) from exc


def _node_metric_instant(value: Any) -> dt.datetime:
    """Validate a measurement stamp, refusing one that is not usable.

    :func:`~tripwires.layout.validated_instant` under this module's error.
    That function's own messages say *a poisoning instant*, which is right
    where it was written and wrong here: the instant this module validates is
    when a **node metric** was written, and a caller told its figure was
    refused because of a *poisoning* would go looking in the wrong feature.
    The validation is shared; the sentence is not.
    """
    try:
        return validated_instant(value)
    except TripwirePoisonError as exc:
        raise TripwireNodeMetricError(
            f"a node metric's recorded-at is not a usable instant: {exc}"
        ) from exc


@dataclass(frozen=True)
class NodeMetricRecord:
    """The receipt of one column write — the figure, and what it superseded.

    What :meth:`NodeMetricStore.record` returns: the value that landed on the
    node row, the bar it was judged against, the decision, and — the field no
    other record in this member carries — the value the write **replaced**,
    ``None`` for a first measurement.  The column keeps only the newest
    figure; the receipt is where the history of the write survives, and a
    caller that needs to say how much a re-measurement moved the node's
    metric reads it here rather than wishing the column kept versions.

    Deliberately *not* the verdict type, for the reason
    :class:`~tripwires.stability.StabilityRecord` gives: the reading half of a
    store must not depend on the producing half being in memory.  And
    deliberately *lighter* than that record: the ledger's row carries every
    term the figure is re-derivable from because a table row can; this
    receipt carries what a column write actually did, which is one number,
    one bar, one decision and one predecessor.
    """

    #: The node the figure landed on, canonical UUID text.
    node_id: str
    #: The axis whose figure the column holds — always ``lookback-jitter``;
    #: the validator refuses any other before a write happens.
    axis: str
    #: The probe that fired — always ``perturbation-stability``.
    tripwire: str
    #: The figure itself — the number this feature's sentence says is the
    #: node metric.
    stability: float
    #: The configured bar the figure was judged against, in the same units.
    stability_threshold: float
    #: Whether that bar was exceeded — carried so the receipt alone can say
    #: which side of the decision the persisted figure fell on.
    rejected: bool
    #: §8's word for the decision — ``ok`` or ``tripwire_fail``.
    outcome: str
    #: The value this write replaced — ``None`` for a first measurement, the
    #: overwritten number for a refresh.  The column keeps only the newest;
    #: the receipt is where the write's history survives.
    superseded: float | None
    #: When the write happened, UTC — not when the figure was measured.  A
    #: parameter of ``record`` for the same reason 131's and 129's stamps are:
    #: a replay can stamp the instant the measurement *happened*.
    recorded_at: dt.datetime

    def __post_init__(self) -> None:
        # Validates only, like the records it sits beside; the writer above
        # has already validated the verdict these terms came from, and the
        # constructor of a value this module builds normalizes nothing.
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise TripwireNodeMetricError(
                f"a node metric names the node it landed on, got "
                f"{self.node_id!r}"
            )
        for name in ("axis", "tripwire", "outcome"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise TripwireNodeMetricError(
                    f"a node metric record's {name} must be a non-empty name, "
                    f"got {value!r}; the receipt says *which* measurement "
                    "landed, and a blank one is an uninterpretable write"
                )
        if self.axis != LOOKBACK_AXIS:
            raise TripwireNodeMetricError(
                f"the node's perturb_stability column holds the "
                f"{LOOKBACK_AXIS!r} axis' figure, and this receipt claims axis "
                f"{self.axis!r}; the validator refuses another axis's verdict "
                "before a write happens, so a receipt naming one was built "
                "somewhere other than this store"
            )
        if self.tripwire != PERTURBATION_STABILITY_NAME:
            raise TripwireNodeMetricError(
                f"a node metric is persisted from the "
                f"{PERTURBATION_STABILITY_NAME!r} probe, and this receipt "
                f"names {self.tripwire!r}"
            )
        if self.outcome not in ("tripwire_fail", "ok"):
            raise TripwireNodeMetricError(
                f"a node metric record's outcome is §8's 'ok' or "
                f"'tripwire_fail', got {self.outcome!r}"
            )
        if not isinstance(self.rejected, bool):
            raise TripwireNodeMetricError(
                f"a node metric record's rejected is a boolean, got "
                f"{self.rejected!r}"
            )
        if self.rejected != (self.outcome == "tripwire_fail"):
            raise TripwireNodeMetricError(
                f"a node metric record says rejected={self.rejected!r} and "
                f"outcome {self.outcome!r}; the two spellings of one fact "
                "cannot disagree, and the receipt is what a reader holds "
                "after the verdict is gone"
            )
        for field in ("stability", "stability_threshold"):
            value = getattr(self, field)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TripwireNodeMetricError(
                    f"a node metric record's {field} must be a number, got "
                    f"{value!r}"
                )
            if not math.isfinite(float(value)):
                raise TripwireNodeMetricError(
                    f"a node metric record's {field} is not finite "
                    f"({value!r}); a NaN or ±inf would reach a caller dressed "
                    "as a node metric"
                )
            object.__setattr__(self, field, float(value))
        if self.stability_threshold <= 0.0:
            raise TripwireNodeMetricError(
                f"a node metric record's configured stability threshold is "
                f"positive, got {self.stability_threshold!r}"
            )
        if self.superseded is not None:
            if isinstance(self.superseded, bool) or not isinstance(
                self.superseded, (int, float)
            ):
                raise TripwireNodeMetricError(
                    f"a node metric record's superseded value is a number or "
                    f"absent, got {self.superseded!r}; it is what the write "
                    "replaced, and anything else would read as a figure"
                )
            if not math.isfinite(float(self.superseded)):
                raise TripwireNodeMetricError(
                    f"a node metric record's superseded value is not finite "
                    f"({self.superseded!r})"
                )
            object.__setattr__(self, "superseded", float(self.superseded))
        if not isinstance(self.recorded_at, dt.datetime):
            raise TripwireNodeMetricError(
                f"a node metric record's recorded-at must be a datetime, got "
                f"{self.recorded_at!r} ({type(self.recorded_at).__name__})"
            )
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise TripwireNodeMetricError(
                f"a node metric record's recorded-at must be timezone-aware; "
                f"got the naive datetime "
                f"{self.recorded_at.isoformat()!r}. A naive stamp would be "
                "read back as an instant the store never meant"
            )

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return (
            f"NodeMetricRecord(node={self.node_id!r}, axis={self.axis!r}, "
            f"stability={self.stability:.4f} against "
            f"{self.stability_threshold:.4f}, "
            f"superseded={self.superseded!r}, outcome={self.outcome!r})"
        )


def _utc_now() -> dt.datetime:
    """The current UTC instant, truncated to the second.

    Truncated because the stamp is a *record of a write* — the same precision
    feature 131's and 129's stamps carry — and sub-second digits would make
    two runs of one persistence differ in a field no reader consults at that
    resolution.
    """
    return dt.datetime.now(dt.UTC).replace(microsecond=0)


class NodeMetricStore:
    """Feature 130's persistence: the lookback figure, on the node row itself.

    Constructed with the database URL it writes to; :meth:`record` puts a
    verdict's figure into ``node.perturb_stability``; :meth:`metric_of` reads
    the column back.  The class resolves its path lazily, so constructing one
    performs no I/O — composition-time work must not touch the disk, the
    contract every store in this workspace states.

    **It requires the node row, and that is the deliberate opposite of
    feature 129's store.**  See the module docstring for the whole argument;
    the short form is that a ledger row brings its own existence with it while
    a column write is an ``UPDATE`` against a row another feature owns, and an
    ``UPDATE`` that matched nothing would report a metric persisted that no
    node carries.  The refusal is by name, before the write.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise TripwireNodeMetricError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction ---------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> NodeMetricStore | None:
        """The store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        node metric component — a discoverable state, not an exception — while
        the evaluation loop that must persist §C6's node metric is the caller
        that must not find itself in it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store writes to."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file backing this store, resolved on first use."""
        if self._path is None:
            self._path = _node_metric_path(self._database_url)
        return self._path

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store writes, idempotently.

        Public for the reason :meth:`~tripwires.poison.PoisonStore.
        ensure_schema` is: an operator pointing this member at a database the
        orchestrator has not migrated yet runs it once, and a test seeds a
        node into exactly the schema the store will read.

        It bootstraps ``node`` as well, and then adds this feature's own
        column if the table came without it — the two paths the module
        docstring names: a database the orchestrator migrated through 0114
        already carries ``perturb_stability`` and is left byte-for-byte as it
        was; a database this store bootstrapped gets the five structural
        columns first and the metric column by the same ``ALTER`` the
        migration's own shape implies.
        """
        with closing(sqlite3.connect(self.path)) as connection, connection:
            self._apply_schema(connection)

    def _has_metric_column(self, connection: sqlite3.Connection) -> bool:
        """Whether the ``node`` table already carries this feature's column.

        ``PRAGMA table_info`` rather than a try/except around the ``ALTER``:
        a probe is a read, it cannot half-apply, and its refusal — unlike an
        exception swallowed to detect the same fact — carries no risk of
        masking a *different* error in the statement it stands in for.  This
        is feature 131's ``_has_poisoned_column`` path, restated because
        SQLite's ``ADD COLUMN`` carries no ``IF NOT EXISTS`` and there is no
        statement that both creates and migrates.
        """
        rows = connection.execute(f"PRAGMA table_info({NODE_TABLE})").fetchall()
        return any(row[1] == NODE_METRIC_COLUMN for row in rows)

    def _apply_schema(self, connection: sqlite3.Connection) -> None:
        """The DDL itself, on a connection the caller already holds open."""
        connection.executescript(node_bootstrap_schema(dialect_of(connection)))
        if not self._has_metric_column(connection):
            connection.execute(
                f"ALTER TABLE {NODE_TABLE} ADD COLUMN {NODE_METRIC_COLUMN} REAL"
            )

    def _connect(self) -> sqlite3.Connection:
        """Open the database, bringing it to this store's shape first.

        The caller owns the connection; use it as a context manager to commit.
        """
        self.ensure_schema()
        return sqlite3.connect(self.path)

    # -- Feature 130: the node metric -------------------------------------------

    def record(
        self,
        verdict: LookbackRerunVerdict,
        *,
        recorded_at: dt.datetime | None = None,
    ) -> NodeMetricRecord:
        """Persist the verdict's stability figure onto its node's row.

        The whole of the persistence half in one call: the verdict is checked
        to be a lookback-axis perturbation-stability record whose outcome word
        is its own decision, its node id is normalized, the previous column
        value is read, and the figure is written to
        ``node.perturb_stability`` — one ``UPDATE``, one transaction.

        **A passing verdict is written**, for the reason the stability
        ledger's :meth:`~tripwires.stability.StabilityStore.record` writes
        one: the metric's consumer (the triage figure, feature 134) needs the
        figures that were supposed to be small as much as the ones that were
        not, and a column that only ever held rejections would make
        ``perturb_stability`` read as a failure flag rather than a
        measurement.

        ``recorded_at`` defaults to the current UTC instant truncated to the
        second.  It is a parameter so a replay can stamp the instant the
        measurement *happened* rather than the instant the retry ran — the
        same reason feature 131's ``poisoned_at`` and 129's ``recorded_at``
        are parameters, and the same reason it is validated: a naive datetime
        would place the write hours from the trial that produced it and
        nothing would look wrong.

        Refuses, in this order, and each refusal names what it is about:

        1. a producer the store cannot read — a missing field list, a
           ``tripwire`` that is not the perturbation-stability probe, an
           ``axis`` that is not the lookback axis, or an outcome word that
           disagrees with the verdict's own ``rejected``
           (:class:`~tripwires.TripwireNodeMetricError`);
        2. a node id that cannot join the tree's key;
        3. **a node the tree does not hold** — the store's own refusal, and
           the deliberate opposite of the stability ledger's no-row-required
           stance: a column write needs the row it updates, and an
           ``UPDATE`` against nothing would report a metric persisted that no
           node carries;
        4. a write that did not land — the rowcount check, which cannot fire
           inside one transaction unless the row vanished between the read
           and the write, and which exists so it cannot pass silently if it
           ever does.
        """
        checked = _validate_verdict(verdict)
        node = _node_metric_node_id(checked.node_id)
        stamp = (
            _utc_now() if recorded_at is None else _node_metric_instant(recorded_at)
        )
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                f"SELECT {NODE_METRIC_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            ).fetchone()
            if row is None:
                raise TripwireNodeMetricError(
                    f"the discovery tree does not hold node {node!r}, and a "
                    "node metric is a column on the node's own row — there is "
                    "nothing to update. The stability ledger accepts a node "
                    "it does not hold because a figure is known before the "
                    "tree is handed the node; this write is the step after "
                    "that one, and persisting against nothing would report a "
                    "metric no node carries"
                )
            previous = None if row[0] is None else float(row[0])
            cursor = connection.execute(
                f"UPDATE {NODE_TABLE} SET {NODE_METRIC_COLUMN} = ? "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (float(checked.stability), node),
            )
            if cursor.rowcount != 1:
                raise TripwireNodeMetricError(
                    f"the node metric write for {node!r} matched "
                    f"{cursor.rowcount} rows where it must match exactly one; "
                    "the row was read moments before in this same transaction, "
                    "so a mismatch means the write did not land and reporting "
                    "success would be the exact 'looks done, is not' failure "
                    "this category exists to prevent"
                )
        return NodeMetricRecord(
            node_id=node,
            axis=checked.axis,
            tripwire=checked.tripwire,
            stability=checked.stability,
            stability_threshold=checked.stability_threshold,
            rejected=checked.rejected,
            outcome=checked.outcome,
            superseded=previous,
            recorded_at=stamp,
        )

    def metric_of(self, node_id: Any) -> float:
        """Read a node's persisted perturbation_stability — the metric itself.

        Returns the column's value, and refuses the two states a caller could
        mistake for one:

        * a node the tree does not hold — the same refusal the write makes,
          because a column on no row is no metric at all;
        * a node whose column is still ``NULL`` — *never measured*, which is
          a different sentence from *measured at zero*.  A default would
          record a measurement nobody took, and ``0.0`` specifically would
          read as a candidate perfectly stable under the jitter, the most
          flattering figure the axis can state.

        That refusal is this read's reason to exist beside a bare ``SELECT``:
        the column is one number with two ways to be absent, and a caller
        that cannot tell them apart cannot tell a stable node from an
        unmeasured one.
        """
        node = _node_metric_node_id(node_id)
        with closing(self._connect()) as connection:
            row = connection.execute(
                f"SELECT {NODE_METRIC_COLUMN} FROM {NODE_TABLE} "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            ).fetchone()
        if row is None:
            raise TripwireNodeMetricError(
                f"the discovery tree does not hold node {node!r}, and a node "
                "metric is a column on the node's own row — there is no "
                "metric to read"
            )
        if row[0] is None:
            raise TripwireNodeMetricError(
                f"node {node!r} has no perturb_stability persisted; the node "
                "was never re-run on the lookback-jitter axis, which is a "
                "different state from one whose figure was measured and found "
                "small — a caller handed a default here would record a "
                "measurement nobody took"
            )
        return float(row[0])


# -- The two module-level entry points -------------------------------------------


def record_node_metric(
    verdict: LookbackRerunVerdict,
    *,
    database_url: str | None = None,
    store: NodeMetricStore | None = None,
    recorded_at: dt.datetime | None = None,
) -> NodeMetricRecord:
    """Persist ``verdict``'s figure as its node's metric — feature 130.

    The module-level spelling of :meth:`NodeMetricStore.record`, for a caller
    that has a verdict and wants the feature rather than an object: it
    composes a store from ``DATABASE_URL`` (or the URL handed to it) and
    writes the column.  A ``store`` may be handed in instead, which is what
    the composed component is and what a test passes to pin the database it
    wrote to.

    Refuses a call that names no store — neither a ``store`` nor a
    ``database_url`` nor a ``DATABASE_URL`` in the environment — with
    :class:`~tripwires.TripwireNodeMetricError` rather than silently doing
    nothing.  That is the stance :func:`~tripwires.stability.record_stability`
    takes and it is the right one here for the same reason: the feature's
    sentence is *"persisting perturbation_stability as a node metric"*, and a
    no-op that returned successfully would report that sentence satisfied by
    a deployment that has nowhere to write it.
    """
    resolved = store if store is not None else _store_for(database_url)
    if resolved is None:
        raise TripwireNodeMetricError(
            f"a node metric is persisted to a relational store, and nothing "
            f"names one: pass a store, a database_url, or set "
            f"{DATABASE_URL_ENV}. A no-op here would report the feature's own "
            "sentence — 'persisting perturbation_stability as a node metric' "
            "— as satisfied by a deployment that has nowhere to write it"
        )
    return resolved.record(verdict, recorded_at=recorded_at)


def _store_for(database_url: str | None) -> NodeMetricStore | None:
    """A store from an explicit URL or the environment, or ``None``."""
    if database_url is not None:
        return NodeMetricStore(database_url)
    return NodeMetricStore.resolve()


def node_metric_of(node_id: Any, *, database_url: str | None = None) -> float:
    """Read one node's persisted perturbation_stability — the module-level spelling.

    The read half of :func:`record_node_metric`, and the one a triage or an
    operator reaches for: it composes a store the same way and returns the
    metric, refusing by name when the node was never measured (see
    :meth:`NodeMetricStore.metric_of`).  Symmetric with the write on purpose —
    a feature whose sentence says persist must have a way to read what it
    persisted, or the sentence is unverifiable from outside this process.
    """
    store = _store_for(database_url)
    if store is None:
        raise TripwireNodeMetricError(
            f"a node metric is read from a relational store, and nothing "
            f"names one: pass a database_url or set {DATABASE_URL_ENV}"
        )
    return store.metric_of(node_id)
