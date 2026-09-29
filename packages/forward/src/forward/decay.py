"""Feature 334's endpoint: GET /forward/decay, the observed decay curve.

app_spec.xml, "Forward-Test Tracking", feature 334: *System exposes GET
/forward/decay which returns the observed decay curve for a promoted signal.*
The spec's API summary spells the route's one line — ``GET /forward/decay —
Return the observed forward decay curve for a signal`` — and the route is
already named in the member's own docstrings (the seat and the observation,
record and errors modules all refer to *"feature 334's decay endpoint"* and
*"feature 334's decay curve"*), but no module, endpoint, value or test exists
yet: it is prose waiting for a shape. This module gives it one.

**The curve is the signal's live information coefficient trajectory over its
out-of-sample life** — the very thing prd §5 Loop 3 promises to track
(*"its live forward IC tracked from the promotion date forward"*). After
feature 332 opens the record (one boundary row) and feature 333 appends the
observation rows (one ``live_ic`` per measured day), the record holds an
ordered series of ``(observed_on, live_ic)`` points. Feature 334 is the
*surface* that reads that series back and frames it as a decay curve: each
measured point expressed as an offset in days from the boundary the record
drew. The decay — the information coefficient falling from its early values
toward its later ones — is read off the rows, never re-derived: the curve is
one reading of the record drawn one way, exactly as feature 94's route is one
reading of the ledger's ``k_effective`` derivation.

**The value is frozen and re-derives itself.** :class:`DecayCurve` is a frozen
record of the boundary instant and the ordered points, and
:class:`DecayPoint` is one measured point — ``observed_on``, ``days`` (the
offset from the boundary) and ``live_ic``. ``DecayCurve.__post_init__``
re-derives each point's ``days`` from the boundary and vouches every plotted
coefficient, so a caller cannot hand a planner a point whose offset or figure
nobody measured — the discipline :class:`forward.priors.ForwardHalfLife`
applies to its crossing offset and :class:`forward.retention.IcRetention` to
its ratio.

**The store climbs the member's one ladder, one act later than feature 333's
observation.** :class:`ForwardDecayCurves` is built ``over`` the composed
``forward`` component (reading its ``database_url`` seam) or resolved from
``DATABASE_URL``, and reads the signal's standing rows through feature 332's
own ``_READ_SQL`` and ``_record_from_row`` — one reading of the record, so the
rows this act frames and the rows every other act answered with cannot be two
readings of one table. It refuses what cannot be framed as a curve: a
malformed identity (the ask, before anything is opened), a signal that holds
no record (name the promote step), rows carrying two promotion instants (a
vintage nobody can state — a curve over two boundaries would double-count a
window) and a record with no measured coefficient yet (name the observation
job, never answer an empty curve). The boundary each offset is measured from
is the opening row's ``observed_on`` — the same line feature 333's lower bound
and feature 335's upper bound are measured against, so all three agree on
where out-of-sample began.

**The refusals land in three faces, and the third is the point of the act.**
:class:`~forward.errors.ForwardRecordError` is the malformed ask, settled
before anything is opened. :class:`~forward.errors.ForwardStoreError` is the
read face properly: a store that could not be reached, or rows carrying two
promotion instants — a fault, which repeats until an operator fixes the
database. And :class:`~forward.errors.ForwardAbsentError` — a *subclass* of
that store class — is the two states where the database answered perfectly and
the row is simply not there: **no record for the node**, or **a record nobody
has observed yet**. Those are states of the world rather than faults, and the
distinction is exactly what a route needs in order to answer 404 for a signal
that was never promoted and 503 for a store failure; subclassing rather than
sitting beside the store class is what keeps every existing ``except
ForwardStoreError`` and ``except ForwardError`` catching them unchanged. The
endpoint adds no fallback and catches nothing: a read that fails propagates,
because the alternative — answering a decay curve this route did not read — is
the error direction.

**Neither an absent store nor a failed read is ever answered with a curve.**
No ``DATABASE_URL`` composes no endpoint (:meth:`DecayCurveEndpoint.from_env`
returns ``None``), the same degrade-don't-break stance every store's builder
takes — a decay curve that silently fell back to nothing would read as *"this
signal has no decay"* rather than *"this signal has no database"*, and the two
must not be confused.

**No clock is read anywhere in the module.** Every date in the curve is the
table's own — boundary days, observed days — never the reader's, for the
reason :mod:`forward.observation` refuses a default day: the vintage of a
decay measurement is a fact about the data, and a curve dated "now" would be a
curve revised against whatever the reader happened to start.

Stdlib-only, like the rest of the member, and read by the scoring and
reporting paths that must see a signal's trajectory.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_ABSENT_ERROR_CODE,
    FORWARD_RECORD_ERROR_CODE,
    ForwardAbsentError,
    ForwardError,
    ForwardRecordError,
    ForwardStoreError,
)
from .record import (
    _READ_SQL,
    DATABASE_URL_ENV,
    FORWARD_RECORD_TABLE,
    LIVE_IC_COLUMN,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    PROMOTED_AT_COLUMN,
    ForwardRecord,
    ForwardRecords,
    _record_from_row,
    _sqlite_path,
    _validated_date,
    _validated_instant,
    _validated_live_ic,
    _validated_uuid,
)
from .schema import bootstrap_schema

__all__ = [
    "FORWARD_DECAY_COMPONENT_NAME",
    "FORWARD_DECAY_ROUTE",
    "DecayCurve",
    "DecayCurveEndpoint",
    "DecayPoint",
    "ForwardDecayCurves",
    "build_forward_decay",
    "decay_curve",
]

#: The route this endpoint serves — app_spec.xml's API summary row for the
#: Forward-Test domain, spelled once: ``GET /forward/decay — Return the
#: observed forward decay curve for a signal``. Carried on the class
#: (:attr:`DecayCurveEndpoint.route`) so a composed deployment can state its
#: routes from the components it holds rather than from a string that lives
#: somewhere else.
FORWARD_DECAY_ROUTE = "/forward/decay"

#: The component name feature 334's endpoint registers under — the hyphenated
#: satellite spelling the feature-store member's derived components
#: established (``feature-materialiser``, ``regime-metrics``, …), so a
#: composed deployment reaches the route's read as
#: ``app.get("forward-decay")`` — exactly as ``app.get("ledger-k-effective")``
#: reaches feature 94. Spelled once here so the member, the factory's registry
#: and the seat cannot drift apart. ``forward-decay`` sorts after the
#: unprefixed ``forward`` in the composed application's name-sorted ``order``,
#: clear of the ``fixture-store`` / ``forward`` / ``ingest`` adjacency the
#: unprefixed name is pinned against.
FORWARD_DECAY_COMPONENT_NAME = "forward-decay"


# -- The value --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DecayPoint:
    """One measured point on the decay curve — a day and the coefficient on it.

    The table's own observation row framed as a point: ``observed_on`` is the
    measured day, ``days`` is how many whole days that day sits past the
    boundary feature 332 drew, and ``live_ic`` is the coefficient the row
    carried. It is *frozen* with a ``__post_init__`` that validates each
    field, because a point is not a figure a caller may state — it is the
    row's own day and coefficient, and an instance carrying a day that is not
    a date or a coefficient that is not an information coefficient would put a
    number in front of a planner that nobody measured.
    """

    #: The measured day — ``forward_record.observed_on``, validated by the
    #: record's own date reader rather than restated here: the day is feature
    #: 333's column, and a second spelling of what a day is would be a second
    #: contract for one column.
    observed_on: Any
    #: Whole days from the boundary to this day — the offset that turns a list
    #: of rows into a *decay curve*. Measured, not stated, in ``__post_init__``.
    days: int
    #: The live information coefficient on this day — the table's own copy,
    #: bounded and finite by refusal.
    live_ic: float

    def __post_init__(self) -> None:
        """Validate each field, in declaration order.

        The day is validated first — a curve's horizontal axis is the thing a
        planner reads first — then the offset, then the coefficient. Each is
        refused by its own name rather than resolved, so a malformed point
        names its own fault:

        * **The day is a calendar date.** :func:`forward.record._validated_date`
          refuses a ``datetime`` by name — truncating an instant to a day is a
          choice about offset, and this member makes that choice once, at the
          promotion write.
        * **The offset is a whole count of days, at least zero.** ``bool`` is
          refused first, for the reason every numeric validator in this
          workspace refuses it: ``True`` is ``1``, and a flag where a day count
          belongs would persist an offset nobody dated. A negative count would
          place the point before the boundary the record drew — a day the
          window excludes — and is refused as the ask's own fact.
        * **The coefficient is an information coefficient.**
          :func:`forward.record._validated_live_ic` bounds it in ``[−1, 1]``
          and refuses a NaN or an infinity — the same gate feature 333's writer
          applies on the way in, so a stored coefficient that stopped being one
          is refused here rather than plotted as a measurement.
        """
        _validated_date(self.observed_on, OBSERVED_ON_COLUMN)
        if isinstance(self.days, bool) or not isinstance(self.days, int):
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: a decay point's days must be a "
                f"whole number — got {self.days!r} ({type(self.days).__name__}); "
                "the offset is measured in days from the boundary the record "
                "drew, and a count that is not a whole number of them dates "
                "nothing (feature 334)"
            )
        if self.days < 0:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: a decay point's days must be at "
                f"least 0 — got {self.days}; the offset is measured from the "
                "boundary feature 332 drew, and a day before that boundary is a "
                "day the window excludes, not a point on an out-of-sample curve "
                "(feature 334)"
            )
        _validated_live_ic(self.live_ic)

    def summary(self) -> dict[str, Any]:
        """The point as a JSON-shaped mapping — the day, its offset, its figure.

        The day travels as an ISO string for the same reason every timestamp in
        this member does: the figure is read by operators and dashboards, and
        :mod:`json` has no ``date``. The offset sits between the day and the
        coefficient, so a reader holding this mapping holds the framing that
        turns the row into a curve.
        """
        return {
            OBSERVED_ON_COLUMN: self.observed_on.isoformat(),
            "days": self.days,
            LIVE_IC_COLUMN: self.live_ic,
        }


@dataclass(frozen=True, slots=True)
class DecayCurve:
    """The observed decay curve for one promoted signal — the figure, and its
    evidence.

    The answer of :meth:`ForwardDecayCurves.curve` and :meth:`DecayCurveEndpoint.get`,
    and the value a scoring or reporting process draws a signal's trajectory
    from. It is a *frozen* value whose ``__post_init__`` re-derives the offset
    of every point and vouches every coefficient: the curve is not a figure a
    caller may state, it is arithmetic over the record's own rows, and an
    instance whose points disagree with their own boundary or carry a
    coefficient that is not an information coefficient is refused rather than
    carried — the discipline :class:`forward.priors.ForwardHalfLife` applies to
    its crossing offset and :class:`forward.retention.IcRetention` to its
    ratio.

    **An empty curve is refused, not carried.** A curve with no measured point
    is not a curve — it is the absence feature 333's store refuses by name —
    and carrying it would read as a signal that was measured and never moved,
    which is exactly the shape a healthy signal and an unmeasured one share in
    front of a planner. The store refuses the absence before framing it; a
    value built with no points is a hand that reached past the store, and it is
    refused here too.
    """

    #: The signal this curve is about — ``forward_record.node_id``.
    node_id: str
    #: The boundary instant — the opening row's own ``promoted_at``, off which
    #: every offset is measured. Validated by the record's own instant reader
    #: rather than restated here: the instant is feature 332's, and a second
    #: spelling of what a boundary is would be a second contract for one
    #: column.
    promoted_at: Any
    #: The measured points, in day order — the record's own rows framed as a
    #: curve. The ordering is feature 332's ``_READ_SQL`` day order, not a
    #: choice this value makes.
    points: tuple[DecayPoint, ...]

    @property
    def observed_days(self) -> int:
        """How many days carried a measurement — the size of the breakdown."""
        return len(self.points)

    def __post_init__(self) -> None:
        """Validate the ask, then re-derive every point's offset and compare.

        The identity and the boundary are validated first — a curve is about a
        signal and measured from a boundary, and a malformed one of either is
        refused by its own name before any point is attempted. Then the curve
        is refused when it holds no measured point, and finally every point's
        offset is re-derided from the boundary and its coefficient re-vouched:

        * **The node is a UUID.** :func:`forward.record._validated_uuid`
          canonicalizes it, so the curve's subject is the one the table stores.
        * **The boundary is a timezone-aware instant.**
          :func:`forward.record._validated_instant` normalizes it to UTC — the
          day each offset is measured from is derived from this instant, and a
          naive boundary is one no calendar can place.
        * **The curve holds at least one measured point.** A curve of no points
          is refused: it is the absence the store refuses by name, and carrying
          it would read as a signal that never moved.
        * **Each point's offset is the day's distance from the boundary.**
          Compared exactly, because both are dates this member read off rows —
          ``observed_on`` and the boundary's own UTC date — and a disagreement
          is an offset nobody dated.
        """
        _validated_uuid(self.node_id, NODE_ID_COLUMN)
        boundary = _validated_instant(self.promoted_at, PROMOTED_AT_COLUMN)
        if not self.points:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: a decay curve for node "
                f"{self.node_id} was built with no measured point. A curve is "
                "the signal's observed live-IC rows framed against the boundary "
                "the record drew, and a curve of no points is not a curve — it "
                "is the absence the observation job refuses by name. Nothing is "
                "wrong with the value: the repair is to observe the signal on "
                "days the window is open (feature 333), whose rows are what a "
                "decay curve is framed from (feature 334)"
            )
        boundary_on = boundary.date()
        for point in self.points:
            expected = (point.observed_on - boundary_on).days
            if point.days != expected:
                raise ForwardStoreError(
                    f"{FORWARD_RECORD_ERROR_CODE}: the decay curve for node "
                    f"{self.node_id} carries a point on {point.observed_on.isoformat()} "
                    f"whose days {point.days!r} is not its offset from the "
                    f"boundary {boundary_on.isoformat()} — {expected}. The offset "
                    "is measured in days from the boundary feature 332 drew, and "
                    "a point whose stated offset disagrees with its own day is a "
                    "point nobody dated. Nothing is wrong with the store: the "
                    "repair is to let this feature do the framing (feature 334)"
                )

    def summary(self) -> dict[str, Any]:
        """The curve as a JSON-shaped mapping, for a router or a job log.

        The boundary instant travels as an ISO string for the same reason every
        timestamp in this member does: the figure is read by operators and
        dashboards, and :mod:`json` has no ``datetime``. The points are listed
        in the value's own day order, each as its own ``summary`` mapping, so a
        caller holding this is holding the route's answer exactly as
        :meth:`DecayCurveEndpoint.get` returned it.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            PROMOTED_AT_COLUMN: self.promoted_at.isoformat(),
            "observed_days": self.observed_days,
            "points": [point.summary() for point in self.points],
        }


# -- The store --------------------------------------------------------------------


class ForwardDecayCurves:
    """Feature 334's store: the observed decay curve for a promoted signal.

    Constructed with the database URL the records live in; :meth:`curve` reads
    the signal's standing rows and frames them as a :class:`DecayCurve`. The
    class resolves its path lazily, so constructing one performs no I/O:
    composition-time work must not touch the disk, the contract every store in
    this workspace states.

    **Duck-built from the composed component.** :meth:`over` reads the URL off
    anything that exposes one — the composed ``forward`` component, a
    :class:`~forward.record.ForwardRecords` a caller built itself — so the
    decay reader and the record opener point at the one database the deployment
    names, without an ``isinstance`` the loader's synthetic module names would
    defeat.

    **There is no cache.** A memo of a previous curve would make *what has this
    signal measured?* a question about this process's history — and the readers
    asking it (a scoring process, a reporting job, an operator a quarter later)
    all run somewhere else entirely. The rows are the only record, so they are
    the only thing an answer is drawn from, on every call, in every process.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the decay curves are read from.

        The URL is validated here, before any call, because it is a fact about
        the *store* rather than about any one curve: a URL that is not a
        non-empty string names no table, and a store that accepted one would
        fail identically on every read — the wrong place for a deployment to
        discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. A decay curve is a framing of the "
                "signal's observed live-IC rows, and a store pointed at nothing "
                "has no rows to frame (feature 334)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> ForwardDecayCurves | None:
        """The decay store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every store
        in this workspace treats its configuration. Absent is not an error: it
        is a deployment without a relational store, which composes no decay
        endpoint — a discoverable state, not an exception — while the reader
        that must draw a signal's curve is the one that must not find itself in
        it. A curve that went nowhere is a trajectory that never landed, and a
        planner reading an empty answer could not tell it from a flat one.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardDecayCurves:
        """The decay store over a composed forward-record store.

        The bridge from the seat to this act: a caller holding the composed
        ``forward`` component (:func:`app.modules.forward.
        forward_records_component`) asks this one question and holds the reader
        for the same database the component points at — one URL, one table, the
        record's read and the observation's write cannot point at two
        databases. The one thing read is the store's ``database_url``; there is
        no ``isinstance`` to defeat, and no second store constructed beside the
        component to keep consistent, because the URL *is* the component's own.
        """
        url = getattr(records, "database_url", None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardDecayCurves is built over a forward-record store — "
                f"something exposing a 'database_url' string (the composed "
                "'forward' component, or a ForwardRecords); got "
                f"{type(records).__name__}, which names no database. A decay "
                "curve is a framing of the rows the record holds, so the reader "
                "points at the record's own database by construction (feature "
                "334)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store reads decay curves from."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated the first
        time an operation needs it, by the member's one spelling of that
        translation (:func:`forward.record._sqlite_path`), so a URL this member
        cannot speak is refused in the member's one vocabulary whichever store
        translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, bringing the two tables it names up.

        The same statement of intent every store in this member makes, over the
        same two owners: :func:`forward.schema.bootstrap_schema` runs the
        owning migrations' own ``statements("sqlite")`` — ``0118`` for ``node``
        and ``0108`` for ``forward_record`` — so this store authors no DDL,
        spells no column and cannot drift from the schema's owner. This feature
        adds **no table and no column**: the curve is framed on rows features
        332 and 333 already write, and the act here is a pair of ``SELECT`` s
        and nothing else.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, and the pragma is what makes the row's reference hold
        against a hand that reaches past this store with a raw connection.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                bootstrap_schema(connection)
        except ForwardError:
            # The schema adapter's own refusals arrive in this member's
            # vocabulary already — re-raised untouched (and the connection
            # closed) rather than re-framed, for the reason
            # :meth:`forward.record.ForwardRecords._connect` states.
            connection.close()
            raise
        except sqlite3.Error as exc:
            connection.close()
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: {FORWARD_RECORD_TABLE} could not "
                f"be brought to the revision a decay curve needs at {path}: "
                f"{exc}. The table is created by "
                "migrations/versions/0108_forward_and_universe_tables.py and its "
                "parent by 0118_node_table.py; this store runs those files' own "
                "statements and authors none of its own (feature 334)"
            ) from exc
        return connection

    # -- Feature 334: the curve ---------------------------------------------

    def curve(self, node_id: Any) -> DecayCurve:
        """Answer one signal's observed decay curve.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, *before* anything is
           opened, so a malformed identity is refused without touching a
           database and a refused call leaves no file behind.
        2. **Read the signal's standing rows** — the record whose observations
           the curve frames. No rows is a refusal by name (:func:`_absent_record`):
           the curve job ran ahead of the promote step, and the repair is
           feature 332's act, which is this feature's declared parent and not an
           incidental precondition. Rows carrying more than one ``promoted_at``
           are refused too (:func:`_one_vintage`): a record is one vintage, and
           this store will not frame a curve over a boundary nobody can state.
        3. **Refuse the unobserved record** (:func:`_no_observation`) — a curve
           over no measured days is not a curve, and answering one would read as
           a signal that was measured and never moved.
        4. **Frame the measured rows** — each observation row becomes a point,
           its offset measured in days from the opening row's ``observed_on``,
           the one boundary the record carries.

        **The answer is drawn from the rows, not from the arguments.** The
        ``promoted_at`` the curve carries is the standing record's; each
        ``live_ic`` is the table's own copy read back; and the boundary each
        offset is measured from is the opening row's own day — the UTC date of
        the promotion instant feature 332 stamped, the same line feature 333's
        lower bound and feature 335's upper bound are measured against.

        Refuses, in this order, each naming what it is about: a malformed
        identity (:class:`~forward.errors.ForwardRecordError`, the ask face —
        settled before anything is opened); an absent record or an unobserved
        record (:class:`~forward.errors.ForwardAbsentError`, the *absence* face
        — the database answered and the row is not there, each naming its
        one-call repair); and a two-vintage fault
        (:class:`~forward.errors.ForwardStoreError`, the fault face — rows a
        hand reached past this member to write, which no retry repairs).
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        with closing(self._connect()) as connection:
            standing = self._rows(connection, node)
        if not standing:
            raise _absent_record(node)
        opening = _one_vintage(node, standing)
        observed = [row for row in standing if row.observed]
        if not observed:
            raise _no_observation(node, opening)
        boundary_on = opening.observed_on
        points = tuple(
            DecayPoint(
                observed_on=row.observed_on,
                days=(row.observed_on - boundary_on).days,
                live_ic=row.live_ic,
            )
            for row in observed
        )
        return DecayCurve(
            node_id=node,
            promoted_at=opening.promoted_at,
            points=points,
        )

    # -- The words ----------------------------------------------------------

    def _rows(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """The signal's standing rows, oldest day first — the record itself.

        Feature 332's own read spelling — :data:`forward.record._READ_SQL` and
        :func:`forward.record._record_from_row` — used rather than restated, so
        the rows this act frames a curve on and the rows every other act in the
        member answered with cannot be two readings of one table: one
        ``SELECT``, one constructor, two acts over one record. A validation
        refusal off a row is the record contract's own
        (:class:`~forward.errors.ForwardRecordError`) and propagates as itself,
        because it names the row it came off — the node is inside the message —
        and re-framing it would only push a second wording in front of the one
        an operator needs.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [_record_from_row(row, node) for row in rows]


# -- The private refusals ---------------------------------------------------------


def _one_vintage(node: str, standing: list[ForwardRecord]) -> ForwardRecord:
    """The record's opening row, after checking the record is one record.

    The one-vintage law read back, in this module's own vocabulary — the same
    check :meth:`forward.observation.ForwardObservations._one_vintage` and
    :func:`forward.retention._one_vintage` make in theirs, restated here
    because each module refuses in its own words and a curve framed from two
    boundaries is a curve nobody measured. The opening row is ``standing[0]``
    because :data:`forward.record._READ_SQL` orders by ``observed_on``, which is
    a property of the ordering clause and not of any object.
    """
    instants = {row.promoted_at for row in standing}
    if len(instants) > 1:
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: the {FORWARD_RECORD_TABLE} rows for "
            f"node {node} carry {len(instants)} different {PROMOTED_AT_COLUMN} "
            "values — "
            + ", ".join(sorted(t.isoformat() for t in instants))
            + ". A forward record is one vintage: feature 332 opens one row per "
            "signal carrying one instant, and every observation carries that "
            "same instant, so rows disagreeing about it are a hand that reached "
            "past this store. A decay curve framed over two boundaries would "
            "double-count a window whose observations belong to one, and move "
            "campaign planning on a timescale nobody measured — repair the "
            "rows, then read the curve (feature 334)"
        )
    return standing[0]


def _absent_record(node: str) -> ForwardAbsentError:
    """The absence refusal: no record, so no curve to draw.

    A decay curve is the signal's observed live-IC rows framed against the
    boundary feature 332's opening row draws, and a signal with no record has
    no rows and no boundary — opening one silently to frame from would
    fabricate the very thing the record exists to fix. The repair is the
    pipeline's, in the order the loop runs: promote first, then the record
    opens, then the job observes, then the curve can be read.

    Raised as :class:`~forward.errors.ForwardAbsentError` — the *decidable*
    half of the store vocabulary — so a caller serving this read over HTTP can
    answer 404 for a signal that was simply never promoted, and reserve 503
    for a database that could not be read at all. The node is named in the
    message, so the caller does not have to parse prose to attribute the
    absence to a signal.
    """
    return ForwardAbsentError(
        f"{FORWARD_ABSENT_ERROR_CODE}: {FORWARD_RECORD_TABLE} holds no row for "
        f"{NODE_ID_COLUMN} {node}, so there is no curve to draw. The decay "
        "curve is the signal's observed live-IC rows framed against the "
        "boundary the record drew, and a signal with no record has no rows and "
        "no boundary — whether or not its promotion was decided. Open the "
        "record first (POST /forward/promote, feature 332), then observe it on "
        "days the window is open (feature 333), then ask for its curve (feature "
        "334)"
    )


def _no_observation(node: str, opening: ForwardRecord) -> ForwardAbsentError:
    """The unobserved refusal: a record with nothing measured on it yet.

    Answered rather than zeroed or returned empty. A curve of no points would
    read as a signal that was measured and never moved — while this record has
    not been measured at all, and the two must not read alike in front of a
    planner. The repair is feature 333's act, on schedule.

    Raised as :class:`~forward.errors.ForwardAbsentError` for the reason
    :func:`_absent_record` states: this too is a *state of the world* rather
    than a fault — the database answered, and the row it answered with is the
    honest opening row 0108 declares — so the route answers 404 and names the
    observation job, never 503.
    """
    return ForwardAbsentError(
        f"{FORWARD_ABSENT_ERROR_CODE}: node {node}'s "
        f"forward record (promoted at {opening.promoted_at.isoformat()}, day "
        f"{opening.observed_on.isoformat()}) holds no row carrying a live_ic, "
        "so there is no curve to draw. A curve of no points would read as a "
        "signal that was measured and never moved, while this record has not "
        "been measured at all, and answering it would read as a flat curve in "
        "front of a planner that moves campaign planning. Nothing is wrong with "
        "the store: the repair is to observe the signal on days the window is "
        "open (feature 333), whose rows are what a decay curve is framed from "
        "(feature 334)"
    )


# -- The endpoint -----------------------------------------------------------------


class DecayCurveEndpoint:
    """Serves GET /forward/decay over one :class:`ForwardDecayCurves`.

    Constructed with the store it reads; :meth:`get` is the route. The endpoint
    holds no state of its own — no cache of a previous curve — because the
    decay curve must be the rows' state at the moment it is asked for: an
    observation that lands between two reads must move the second answer, and a
    cached curve would make the route depend on when the reader happened to
    start. The rows in the table are the only record of what was measured, so
    they are the only thing the answer is drawn from, on every request, in
    every process.
    """

    #: The route this endpoint serves — :data:`FORWARD_DECAY_ROUTE`, pinned as
    #: a class attribute so ``DecayCurveEndpoint.route`` states the contract
    #: without an instance.
    route = FORWARD_DECAY_ROUTE

    def __init__(self, curves: ForwardDecayCurves) -> None:
        # Duck-checked rather than isinstance-guarded, exactly as feature 94's
        # endpoint is and for the same reason: the factory's scan imports this
        # member under an alias module, so the *composed* store is structurally
        # a ForwardDecayCurves but never the same class object a direct import
        # yields. The contract is the curve seam, and that is what is checked —
        # an object that can only read rows is refused here rather than
        # answering the route with a curve the store never stated. The check
        # reads ``getattr`` against a sentinel, so an absent attribute is
        # distinguished from a present-``None`` one, and the loader's
        # synthetic-name copies are judged as well as canonical stores.
        _missing = object()
        if getattr(curves, "curve", _missing) is _missing or not callable(
            getattr(curves, "curve", None)
        ):
            raise TypeError(
                "DecayCurveEndpoint speaks a ForwardDecayCurves (something with "
                "a callable curve()); got "
                f"{type(curves).__name__}. The route returns the observed decay "
                "curve for a signal (feature 334), not a store that cannot frame "
                "one."
            )
        self._curves = curves

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None
    ) -> DecayCurveEndpoint | None:
        """The endpoint over the records ``DATABASE_URL`` names, or ``None``.

        Resolves the store exactly as the member's own builder does
        (:meth:`ForwardDecayCurves.resolve`), so the endpoint, the composed
        ``forward-decay`` component and the module-level spelling always point
        at the same database. No ``DATABASE_URL`` composes no endpoint — an
        unconfigured store is a discoverable state, not an error — while a
        deployment whose reader must draw a signal's curve is the one that must
        not find itself in it.
        """
        curves = ForwardDecayCurves.resolve(env)
        return None if curves is None else cls(curves)

    @property
    def curves(self) -> ForwardDecayCurves:
        """The store this endpoint reads."""
        return self._curves

    # -- The route ----------------------------------------------------------

    def get(self, node_id: Any) -> DecayCurve:
        """Answer one GET /forward/decay: the signal's observed decay curve.

        The whole of feature 334 at its seam. The route takes the signal
        identity a GET *for a signal* must state — a path or query parameter in
        an HTTP adapter — and delegates the whole read — validation, the
        standing rows, the framing — to the store's :meth:`~ForwardDecayCurves.curve`,
        returning the :class:`DecayCurve` the store answered with. A caller that
        wants the JSON-shaped mapping asks the curve
        (:meth:`DecayCurve.summary`), which draws it from the same value rather
        than from a second read.

        Refusals are the store's: a malformed identity raises
        :class:`~forward.errors.ForwardRecordError` from the ask; an absent
        record or an unobserved one raise
        :class:`~forward.errors.ForwardAbsentError` — the two states a 404
        answers, both naming the node and the act that produces the row; and a
        two-vintage fault raises its parent
        :class:`~forward.errors.ForwardStoreError`, which is the 503. Nothing
        here is caught, because the alternative — answering a decay curve this
        route did not read — is the error direction.
        """
        return self._curves.curve(node_id)


# -- The module-level spelling ----------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardDecayCurves:
    """The decay store the module-level spelling reads through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering nothing. The
    silence would be the dangerous failure here and not the refusal: a
    deployment that could not say where forward records live would leave a
    promoted signal with a curve nobody could draw, and §5's 90-day track
    record would begin — unmeasured — the moment nobody was looking.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardStoreError(
            f"{FORWARD_RECORD_ERROR_CODE}: no database is named — "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), so "
            "the decay curve cannot be read. A promoted signal's trajectory is "
            "its observed live-IC rows, and a store resolved from nothing is a "
            "refusal rather than a silent answer of the caller's own choosing "
            "(feature 334)"
        )
    return ForwardDecayCurves(url)


def decay_curve(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> DecayCurve:
    """Read one signal's observed decay curve — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the curve
    without holding a store — a pipeline step reading a promoted signal's
    trajectory, an operator backfilling a signal whose curve was never read, a
    test. The store is resolved from ``database_url``, else from
    ``DATABASE_URL``, exactly as :func:`forward.record.forward_record` resolves
    the store it writes through, so a caller reading through one spelling and
    the other is reading and framing the same rows.

    The answer is the **curve the table frames** — the same value
    :meth:`DecayCurveEndpoint.get` returns — so a caller reading through one
    spelling and the other reads the same curve.
    """
    return _resolved_store(database_url, env).curve(node_id)


# -- The component ----------------------------------------------------------------


def build_forward_decay() -> ForwardDecayCurves | None:
    """Component builder: the GET /forward/decay endpoint over this database.

    Takes no arguments — that is the factory's registration protocol — and
    resolves the store from the environment exactly as
    :func:`build_forward_records` does, so the route reads the database the
    process is actually pointed at and can never serve a curve drawn from a
    different database than the composed ``"forward"`` component names. Returns
    ``None`` when no ``DATABASE_URL`` is set: an unconfigured store contributes
    no route either, a discoverable state — while the reader that must draw a
    signal's curve is the caller that must not find itself in it. Never raises,
    and construction performs no I/O: the path is resolved on first use and the
    schema is brought up on the first read, so composing the application neither
    opens a database nor creates a table.
    """
    store = ForwardDecayCurves.resolve()
    return None if store is None else DecayCurveEndpoint(store)
