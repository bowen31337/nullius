"""Persisting the live IC a promoted signal measures — feature 333, the
tracking half of the record feature 332 opened.

app_spec.xml, "Forward-Test Tracking", feature 333: *System persists one
forward_record per promoted signal carrying live information coefficient
observations over time.*  Its declared parent is feature 332 — the record —
and the sentence is the second clause of the loop
docs/alpha-engine-prd.md §5 calls *"the only source of genuinely
uncontaminated evidence"*::

    - Every promoted signal is timestamped and its live forward IC tracked
      from the promotion date forward.
    - After 90 days, that signal has a track record on data that **did not
      exist when the hypothesis was formed.**

Feature 332 was the *timestamped* half — one row, one instant, no
measurement.  This module is the *tracked* half: the observations that
accumulate behind that row, one per day, each carrying the coefficient
measured on that day's data.  Nothing about the record 332 opened moves
while they land.

**One row per observation date, and the table was shaped for this feature
before it existed.**  ``0108``'s own comment beside ``forward_record`` says
the shape: *"One row per promoted signal per observation date: ``promoted_at``
is when the hypothesis was frozen, ``observed_on`` the day the live IC was
read, and the pair is the vintage a forward record exists to carry."*  The
promotion-day row feature 332 opens is day zero — carrying no measurement,
by the same comment's reason that a ``NOT NULL`` would force a fabricated
zero — and this module appends the days after it.  A signal's forward
record, read whole, is its opening row plus every observation row that has
landed: :meth:`~forward.record.ForwardRecords._node_records` already orders
them ``observed_on`` and already documents that more than one row is *the
expected shape of a measured signal rather than a corruption*.

**The observation joins the record, not the promotion.**  The
``promoted_at`` an observation row carries is read off the record's own
standing rows — the one instant feature 332 wrote, read back — and never
re-read from the registry.  Three reasons, in decreasing weight:

* **Every row of one record carries the one boundary.**  The vintage pair is
  per-*record*: the instant on an observation row is not a fresh fact about
  the promotion, it is the same fact the opening row already carries, and
  the only spelling of it that cannot disagree with the rows beside it is
  the rows beside it.
* **A second reading could disagree.**  The registry row is editable after
  the record opened (feature 293's stamp is an ``UPDATE`` away), and an
  observation that re-read it would append rows carrying a different
  instant than the record's standing ones — the two-vintages fault this
  table exists to make impossible, built one row at a time.
* **The seam is 332's, and it stays 332's.**
  :func:`~forward.window.read_promotion_window` is reached exactly once per
  record — at the open — and this module never touches it.

Two consequences follow and both are deliberate.  There is **no registry
read** (the promotion is not being re-read; a signal whose promotion went
missing is a signal whose record still stands, and the observation joins what
stands), and there is **no ``forward_days`` default** — the horizon is a
required keyword the caller must supply, because the registry holds the
criteria *hash* and sha256 is one-way, so the 90-day length cannot be
recovered from the record and must arrive from the caller, exactly as feature
300 and feature 332 both demand.

**Feature 335: the window's far edge.**  A forward observation is honest only
while the window is open, so this module refuses an observation whose day
falls *at or after* the window's close — the upper bound that complements
feature 333's lower one, together confining observations to the half-open
``[opened_at, opened_at + forward_days)``.  The close is computed from the
record's *own* ``promoted_at`` — the same instant the standing rows already
carry — handed to feature 300's ``window_closes_at`` arithmetic through the
seam (:func:`~forward.window.read_window_close`), and **never re-read from the
registry**: the lower bound (feature 333) and the upper bound (feature 335)
must both be measured against the one instant the record carries, or a
registry edit between the two would let them diverge — the two-vintages fault
this member exists to prevent.  The instant is the record's; only the
arithmetic is borrowed.  A malformed horizon therefore surfaces as
:class:`~forward.errors.ForwardRecordError` — the ask face, validated *before*
anything is opened, exactly as feature 332 validates its own ``forward_days``
at record.py:952 — so a bad horizon touches no database.  Only a horizon that
has passed the ask reaches the seam, and there the promotion member's
``window_closes_at`` arithmetic is the sole remaining authority; should it ever
refuse the instant it is handed, that refusal is translated to
:class:`~forward.errors.ForwardPromotionError`, the same translation feature
332's promote path takes — because the repair is one repair from where this
member stands: the horizon must be the promotion's pre-registered
``min_forward_days`` (feature 291's criteria), and the instant must be
feature 293's stamp (feature 300).

**The observation date is stated, beside the observation it belongs to.**
Feature 332's own request docstring made the promise this module keeps:
*"Feature 333 — which appends observation rows rather than opening the
record — is where an observation date is stated, and it states it beside
the observation it belongs to."*  Required, with **no default and no
clock**: the day an observation belongs to is the day the measured data
closed, not the day the writer happened to run — a backfill for a missed
day states a past date, which is why deriving the day from ``utc_now()`` is
a design this module refuses to offer rather than a convenience it
forgets to.  A :class:`~datetime.datetime` is refused by name, for the
reason :func:`~forward.record._validated_date` states: truncating an
instant to a day is a choice about which offset the day is read in.

**Strictly after the boundary day, and why the boundary day itself is
refused.**  ``observed_on`` must name a day *after* the promotion instant's
own UTC date.  Day zero — the boundary day — is the opening row's own day:
the record landed on it carrying no measurement, and an observation row
dated to it would be two rows for one date and a "live IC" measured over a
span that began at the instant the deciding evaluation itself ran.  Every
day before it is worse: a measurement on data that existed when the
hypothesis was formed, wearing the vintage of data that did not — the
contamination §5's loop and ``0108``'s table exist to exclude.  Both are
refused as *disagreements with the standing record*
(:class:`~forward.errors.ForwardIdentityError`): the record has already
fixed when its signal went out of sample, and the request asserts a date
that boundary excludes.

**The window's far edge, and how a day is measured against an instant.**  The
close the seam returns is an *instant* (the promotion stamp plus the horizon —
2026-03-01T12:00 plus 90 days is 2026-05-30T12:00, not a day), while an
observation names a *date*.  The two are compared by reading the observation
date as the instant at the *start* of its day (its 00:00 UTC), and refusing
when that instant is at or after the close: a day whose whole span begins at
or after the window's end carries no honest measurement.  The asymmetry is
feature 300's half-open interval, read straight off :meth:`~promotion.forward.
PromotionWindow.open_at` — the closing instant is excluded, so the last honest
day is the one whose start-of-day still precedes the close.  With the pinned
fixture boundary (opened 2026-03-01T12:00, 90 days) the close is
2026-05-30T12:00 and the last admissible day is 2026-05-30; 2026-05-31 begins
at 2026-05-31T00:00, past the close, and is refused.  The conversion runs the
date through feature 300's own instant rule rather than inventing a second
midnight convention, so the day arithmetic and the window arithmetic agree on
one calendar.

**The coefficient is a correlation, and the bound is a fact.**  A live
information coefficient is bounded in ``[−1, 1]`` whatever the estimator,
finite, and refused rather than clamped — the argument
:func:`~forward.record._validated_live_ic` states at length.  The
validator lives on the row contract (:mod:`forward.record`) rather than
here so that a row *read back* carries the same check a row *written* did —
SQLite's dynamically typed columns would otherwise serve a hand-edited
``2.5`` to feature 334's curve and feature 337's ratio as a measurement.

**The insert names four columns, and that is its honesty.**
:data:`_OBSERVATION_INSERT_SQL` names ``node_id``, ``promoted_at``,
``observed_on`` and ``live_ic`` — and *cannot* name ``backtest_ic``
(feature 337's ratio reads that column; filling it is another act) or
``realized_cost_bps`` (whose filler is no feature of this table: feature
340's sentence prices *per rebalance*, a grain no column here names, and
its reconciliations land in their own table —
:mod:`forward.reconciliation`), the same structural
discipline feature 332's three-column insert states: a writer that cannot
name a column cannot fabricate its value.  The ``promoted_at`` it binds is
the record's own, read — the caller states no instant, exactly as feature
332's request body states none, and for the same reason.

**One row per date per signal, held in the write path.**  ``0108`` declares
no ``UNIQUE (node_id, observed_on)`` — the spec's schema block and the
migration's DDL both stop at ``id PRIMARY KEY`` — and this member authors
no DDL to add one, so the law lives where feature 332's one-signal law and
feature 293's once-only close live: a check-and-insert inside one
transaction on one connection.  A **retry** — the same date and the same
coefficient; the observation job running twice, the worker dying between
the row landing and the response leaving — is answered by the standing row
with ``created=False``, exactly as :meth:`~forward.record.Forwards.
open_record` answers a retried promote and
:meth:`~promotion.decision.PromotionDecisions.record_decision` a re-decided
promotion.  A **disagreement** — the same date naming a different
coefficient — is refused, because the alternative is the track record
editing itself: last-wins would revise a measurement after feature 334's
decay curve and feature 337's retention ratio may already have accounted
for it, and a caller reading the record a day apart would watch history
move.

**Rows need not arrive in day order.**  A missed day measured later is
still a measurement of *that day's* data — data that still did not exist
when the hypothesis was formed — so out-of-order arrival is served rather
than refused, and ``_READ_SQL``'s ``ORDER BY observed_on`` is what keeps
the record reading chronologically however it was written.  The one date
the record will never accept is the one before its boundary.

**A record whose rows carry two instants is refused, not extended.**  Every
row of one record carries the same ``promoted_at`` — feature 332's retry
law writes it that way and this module's appends preserve it — so rows
that disagree are a hand that reached past the member, and appending onto
them would compound a fault every later reader inherits.  The refusal is
the store's (:class:`~forward.errors.ForwardStoreError`), because nothing
about the ask is wrong and the repair is to the table.

**No component, no route, no second registration.**  The member's
registered surface stays feature 332's one store — the same stance the
promotion member's post-291 features take and for the same reason: the
composed ``forward`` component is the deployment's one table pointer, and
this store is the same table in the same database, constructed from the
composed store's own URL (:meth:`ForwardObservations.over`) or resolved
from ``DATABASE_URL`` (:meth:`ForwardObservations.resolve`).  The spec's
API summary names two routes for this domain — ``POST /forward/promote``
(feature 332) and ``GET /forward/decay`` (feature 334) — and *"persists"*
is not *"exposes"*: the writer is a seam, and feature 334's reader is what
makes its rows visible.

**Stdlib only, and import-cheap.**  ``os``, ``sqlite3`` and the typing
shapes at module scope, everything else from this member's own modules —
no third-party import and no import of another workspace member, so the
factory's scan imports this package for the near-nothing it always did and
an observation costs its caller only the store it already held.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_IDENTITY_ERROR_CODE,
    FORWARD_RECORD_ERROR_CODE,
    ForwardError,
    ForwardIdentityError,
    ForwardStoreError,
)
from .record import (
    _READ_SQL,
    DATABASE_URL_ENV,
    LIVE_IC_COLUMN,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    PROMOTED_AT_COLUMN,
    ForwardRecord,
    _record_from_row,
    _sqlite_path,
    _validated_date,
    _validated_forward_days,
    _validated_live_ic,
    _validated_uuid,
)
from .schema import FORWARD_RECORD_TABLE, bootstrap_schema
from .window import read_window_close

__all__ = [
    "FORWARD_OBSERVATION_SEAM",
    "ForwardObservations",
    "forward_observation",
]

#: The insert that lands one observation, with the column list it names in
#: the order the placeholders bind.  Four of the table's seven columns:
#: ``id`` is absent because ``0108`` declares a ``DEFAULT`` that mints a UUID
#: on both dialects, ``backtest_ic`` and ``realized_cost_bps`` are absent
#: because they are feature 337's and feature 340's columns — a statement
#: that cannot name a column cannot fabricate its value, which is the same
#: discipline :data:`forward.record._INSERT_SQL` states for the three the
#: opening write refuses to name.  ``promoted_at`` *is* named, and its value
#: is the record's own standing instant, read — never the caller's.
_OBSERVATION_INSERT_SQL = (
    f"INSERT INTO {FORWARD_RECORD_TABLE} "
    f"({NODE_ID_COLUMN}, {PROMOTED_AT_COLUMN}, {OBSERVED_ON_COLUMN}, "
    f"{LIVE_IC_COLUMN}) "
    "VALUES (?, ?, ?, ?)"
)

#: The one attribute :meth:`ForwardObservations.over` reads off the composed
#: store, spelled once so the constructor and its refusal name the same seam.
#: The URL is all this act needs from the component — the observation writes
#: the same table the composed store points at — and it is read as an
#: attribute rather than checked as a class for the reason every seam in this
#: workspace states: the loader imports a member under a synthetic module
#: name, so the composed store is structurally a ``ForwardRecords`` and never
#: the same class object a direct import yields.
FORWARD_OBSERVATION_SEAM = "database_url"


class ForwardObservations:
    """Appends live IC observations onto standing records — feature 333's act.

    Constructed with the database URL the records live in;
    :meth:`append_observation` lands one observation row on a signal's
    standing record, answering ``(record, created)`` — the row as the table
    holds it, and whether *this* call appended it.  The class resolves its
    path lazily, so constructing one performs no I/O: composition-time work
    must not touch the disk, the contract every store in this workspace
    states.

    **Duck-built from the composed component.**  :meth:`over` reads the URL
    off anything that exposes one — the composed ``forward`` component, a
    :class:`~forward.record.ForwardRecords` a caller built itself — so the
    observation writer and the record opener point at the one database the
    deployment names, without an ``isinstance`` the loader's synthetic
    module names would defeat.

    **There is no cache.**  A memo of observed days would make *what has
    this signal measured?* a question about this process's history — and the
    readers asking it (feature 334's decay endpoint, feature 337's ratio,
    an operator a quarter later) all run somewhere else entirely.  The rows
    are the only record, so they are the only thing an answer is drawn
    from, on every call, in every process.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the observations land in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one observation: a URL that
        is not a non-empty string names no table, and a store that accepted
        one would fail identically on every observation — the wrong place
        for a deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: {DATABASE_URL_ENV} must be a "
                "non-empty database URL. A live IC observation is a row in "
                "the database the deployment names, and a store pointed at "
                "nothing has nowhere to carry the measurement a signal's "
                "track record is made of (feature 333)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> ForwardObservations | None:
        """The observation store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no observation writer — a discoverable state, not an exception —
        while the daily job that has just measured a promoted signal is,
        like the caller that must open a record, the one that must not find
        itself in it.  A measurement that went nowhere is a day of the track
        record that never landed, and §5's 90-day figure cannot be re-read
        off a calendar that does not hold it.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardObservations:
        """The observation store over a composed forward-record store.

        The bridge from the seat to this act: a caller holding the composed
        ``forward`` component (``create_app().get("forward")``) asks this
        one question and holds the
        writer for the same database the component points at — one URL, one
        table, two acts.  The one thing read is the store's
        ``database_url``; there is no ``isinstance`` to defeat, and no
        second store constructed beside the component to keep consistent,
        because the URL *is* the component's own.
        """
        url = getattr(records, FORWARD_OBSERVATION_SEAM, None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardObservations is built over a forward-record store — "
                f"something exposing a {FORWARD_OBSERVATION_SEAM!r} string "
                f"(the composed 'forward' component, or a ForwardRecords); "
                f"got {type(records).__name__}, which names no database. An "
                "observation lands in the same table the record opened in, "
                "so the two acts share one URL by construction (feature 333)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store appends into."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated the first
        time an operation needs it, by the member's one spelling of that
        translation (:func:`forward.record._sqlite_path`), so a URL this
        member cannot speak is refused in the member's one vocabulary
        whichever store translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, bringing the two tables it names up.

        The same statement of intent :meth:`forward.record.ForwardRecords.
        _connect` makes, over the same two owners: :func:`forward.schema.
        bootstrap_schema` runs the owning migrations' own
        ``statements("sqlite")`` — ``0118`` for ``node`` and ``0108`` for
        ``forward_record`` — so this store authors no DDL, spells no column
        and cannot drift from the schema's owner.  The set is the member's
        one set for statements naming ``forward_record``: this module's
        ``INSERT`` writes through the child table's foreign key, so the
        parent must be resolvable exactly when the opening write needed it.

        No parent probe of its own, because the probe is the record: an
        observation is refused outright when the signal holds no standing
        rows (see :meth:`append_observation`), and a signal whose record
        stands had its node checked by the feature that opened it — the one
        reachable exception is a hand that deleted the node afterwards, and
        the foreign key below is what catches it.

        **The foreign keys.** ``PRAGMA foreign_keys = ON`` — SQLite's own
        default is off, and the pragma is what makes the row's reference
        hold against a hand that reaches past this store with a raw
        connection.

        The caller owns the connection; use it as a context manager to
        commit, which is what the write here does.
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
                f"{FORWARD_RECORD_ERROR_CODE}: the database at {path} could "
                f"not be brought to the revision an observation needs: "
                f"{exc}. The {FORWARD_RECORD_TABLE} table is created by "
                "migrations/versions/0108_forward_and_universe_tables.py "
                "and its parent by 0118_node_table.py; this store runs "
                "those files' own statements and authors none of its own "
                "(feature 333)"
            ) from exc
        return connection

    # -- Feature 333: the observation ---------------------------------------

    def append_observation(
        self,
        node_id: Any,
        *,
        observed_on: Any,
        live_ic: Any,
        forward_days: Any,
    ) -> tuple[ForwardRecord, bool]:
        """Land one live IC observation on a signal's record — 333's act, 335's bound.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, the day as a
           calendar date (a ``datetime`` refused by name), the coefficient
           as a finite real in ``[−1, 1]`` — *before* anything is opened, so
           a malformed observation is refused without touching a database
           and a refused call leaves no row and no file behind.
        2. **Read the signal's standing rows** — the record whose
           observations these are.  No rows is a refusal by name: the
           observation job ran ahead of the promote step, and the repair is
           feature 332's act, which is this feature's declared parent and
           not an incidental precondition.  Rows carrying more than one
           ``promoted_at`` are refused too: a record is one vintage, and
           this store will not extend one whose boundary nobody can state.
        3. **Check the day against both edges of the window.**  The record's
           opening row is the earliest (``_READ_SQL`` orders by
           ``observed_on``), and its ``promoted_at`` is the boundary every
           observation row carries.  A day *on or before* that instant's own
           UTC date is refused (feature 333's lower bound — the boundary day
           is the opening row's, and an earlier one measures in-sample data
           under an out-of-sample vintage).  A day *at or after* the window's
           close is refused (feature 335's upper bound — the window has
           closed, and the signal's track record is complete).  The close is
           computed from the record's own ``promoted_at`` through the seam
           (:func:`~forward.window.read_window_close`), never re-read from the
           registry, so the two bounds are measured against the one instant
           the record carries — and the horizon is validated as part of that
           computation, so a malformed ``forward_days`` is refused as a length
           rather than surfacing from inside the arithmetic.
        4. **Answer the retry, or refuse the disagreement, or write.**  A
           standing row for *this* date carrying *this* coefficient is the
           same observation arriving twice — returned untouched, with
           ``created=False``.  A standing row carrying a *different*
           coefficient is refused: the measurement that landed on a day is
           that day's fact, and the record does not edit itself.  An absent
           date takes the insert.
        5. **Read back and answer with the row**, inside the same
           transaction as the write, so the minted ``id`` and every figure
           in the answer are the table's own.

        **The answer is drawn from the row, not from the arguments.**  The
        ``promoted_at`` the returned record carries is the standing
        record's; the ``live_ic`` is the table's own copy read back; and the
        ``bool`` says whether *this* call appended the row — ``False`` is a
        retry answered by the standing observation.

        **What this act never does.**  It never opens a record (feature
        332's act, and the one this feature's ``depends_on`` names); it
        never re-reads the promotion registry (the instant is the record's
        own, read once at the open, and the close is computed from that
        instant, not re-read); it never fills ``backtest_ic`` or
        ``realized_cost_bps`` (``backtest_ic`` is feature 337's to read,
        and ``realized_cost_bps`` is nobody's to fill from here — feature
        340 prices *per rebalance*, a grain this table does not name, and
        the insert cannot name either column).

        ``forward_days`` is a **required keyword with no default** — the
        registry holds the criteria *hash* and sha256 is one-way, so the
        90-day length cannot be recovered from the record and must arrive
        from the caller, exactly as feature 300 and feature 332 both demand.

        Refuses, in this order, each naming what it is about: a malformed
        identity, day, coefficient or horizon
        (:class:`~forward.errors.ForwardRecordError`, the ask face — the
        horizon validated before anything is opened, the same move feature
        332 makes with its own ``forward_days``); a signal that holds no
        record, a record whose rows carry two instants, a store this member
        cannot speak, a horizon that names no computable window, or a row
        that could not be read back
        (:class:`~forward.errors.ForwardStoreError`); and a day the record's
        window excludes — before its boundary or after its close — or a date
        that already holds a different measurement
        (:class:`~forward.errors.ForwardIdentityError`).
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        day = _validated_date(observed_on, OBSERVED_ON_COLUMN)
        coefficient = _validated_live_ic(live_ic)
        # Feature 335's horizon, validated as part of the ask and before any
        # I/O — the same move feature 332 makes with its own ``forward_days``
        # (:meth:`forward.record.ForwardRecords.open_record`): the registry
        # holds the criteria *hash* and sha256 is one-way, so the length
        # cannot be recovered from the record and must arrive from the caller
        # as a positive count of whole days, or the request never opens a
        # database.  A malformed or non-positive horizon is refused as a
        # length, naming the repair, before a file is touched.
        horizon = _validated_forward_days(forward_days)
        with closing(self._connect()) as connection, connection:
            standing = self._record_rows(connection, node)
            if not standing:
                raise _absent_record(node)
            opening = self._one_vintage(node, standing)
            boundary = opening.promoted_at.date()
            if day <= boundary:
                raise _before_the_boundary(node, opening, day)
            # Feature 335: the window's far edge.  The close is computed from
            # the record's *own* promoted_at — the same instant the standing
            # rows already carry — handed to feature 300's arithmetic through
            # the seam, and never re-read from the registry: the lower bound
            # (feature 333) and this upper bound must both be measured against
            # the one instant the record carries, or a registry edit between
            # the two would let them diverge.  The day is read as the instant
            # at the start of its day, and refused when that instant is at or
            # after the close — the half-open interval's excluded closing edge.
            close = read_window_close(opening.promoted_at, forward_days=horizon)
            day_start = _instant_of(day)
            if day_start >= close:
                raise _after_the_window(node, opening, horizon, day, close)
            for row in standing:
                if row.observed_on == day:
                    # The retry: the standing row answers, and ``created``
                    # is the one bit this wrapper adds to
                    # ``_answer_standing``'s verdict.
                    return self._answer_standing(node, row, coefficient), False
            try:
                connection.execute(
                    _OBSERVATION_INSERT_SQL,
                    (
                        node,
                        opening.promoted_at.isoformat(),
                        day.isoformat(),
                        coefficient,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ForwardStoreError(
                    f"{FORWARD_RECORD_ERROR_CODE}: the observation for node "
                    f"{node} on {day.isoformat()} could not be written: "
                    f"{exc}. The insert names a signal whose record this "
                    "store read as standing — so a constraint that refused "
                    "anyway is a database whose tables are not the ones this "
                    "deployment migrated, or a node row deleted by hand "
                    "after the record opened (the foreign key is what "
                    "catches it; the record's opener checked the rest) "
                    "(feature 333)"
                ) from exc
            written = self._row_for(connection, node, day)
        if written is None:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: the observation for node "
                f"{node} on {day.isoformat()} could not be read back after "
                "the write. An observation has to be accounted for — §5's "
                "track record is these rows, feature 334's curve reads them "
                "and feature 337's ratio divides them — and a row that "
                "cannot be re-read is a measurement this store cannot vouch "
                "for (feature 333)"
            )
        return written, True

    # -- The words ----------------------------------------------------------

    def _record_rows(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """The signal's standing rows, oldest day first — the record itself.

        Feature 332's own read spelling — :data:`forward.record._READ_SQL`
        and :func:`forward.record._record_from_row` — used rather than
        restated, so the rows this act appends to and the rows the record's
        opener answered with cannot be two readings of one table: one
        ``SELECT``, one constructor, two acts over one record.  A validation
        refusal off a row is the record contract's own
        (:class:`~forward.errors.ForwardRecordError`) and propagates as
        itself, because it names the row it came off — the node is inside
        the message — and re-framing it would only push a second wording in
        front of the one an operator needs.
        """
        cursor = connection.execute(_READ_SQL, (node,))
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
        return [_record_from_row(row, node) for row in rows]

    def _row_for(
        self, connection: sqlite3.Connection, node: str, day: Any
    ) -> ForwardRecord | None:
        """The signal's row for one day, or ``None`` when the table holds none.

        The read-back half of the write: the answer is drawn from the table
        inside the write's own transaction, so the ``id`` and every figure
        the caller holds are the table's own.  Reached through the same
        ``_READ_SQL`` the standing check used, so there is one reading of
        the record in this act and the write and its verification cannot
        disagree about what a row is.
        """
        for row in self._record_rows(connection, node):
            if row.observed_on == day:
                return row
        return None

    def _one_vintage(
        self, node: str, standing: list[ForwardRecord]
    ) -> ForwardRecord:
        """The record's opening row, after checking the record is one record.

        The opening row is the earliest by ``observed_on`` — the promotion
        day, which feature 332 wrote and no observation can share — and its
        ``promoted_at`` is the boundary every row this act appends will
        carry.  The *check* beside it is the one-vintage law read back:
        feature 332's retry law writes one instant per record and this
        module's appends preserve it, so rows that disagree are a hand that
        reached past the member, and the boundary they leave is one nobody
        can state.  Refusing here is cheaper than discovering it from
        feature 334's curve, where two instants would read as a decay
        nobody measured.

        The boundary day is derived from ``promoted_at`` and not from the
        opening row's ``observed_on``: the instant is the boundary, the day
        column its derived shadow, and a hand that edited the shadow must
        not move the line the instant draws.
        """
        instants = {row.promoted_at for row in standing}
        if len(instants) > 1:
            raise ForwardStoreError(
                f"{FORWARD_RECORD_ERROR_CODE}: the {FORWARD_RECORD_TABLE} "
                f"rows for node {node} carry {len(instants)} different "
                f"{PROMOTED_AT_COLUMN} values — "
                + ", ".join(sorted(t.isoformat() for t in instants))
                + ". A forward record is one vintage: feature 332 opens one "
                "row per signal carrying one instant, and every observation "
                "this member appends carries that same instant, so rows "
                "disagreeing about it are a hand that reached past this "
                "store. Appending onto them would compound a fault every "
                "later reader inherits — repair the rows, then observe "
                "(feature 333)"
            )
        return standing[0]

    def _answer_standing(
        self, node: str, standing: ForwardRecord, coefficient: float
    ) -> ForwardRecord:
        """Resolve a date that already holds a row: the retry, or the refusal.

        The two outcomes are the same date read two ways and the difference
        is the coefficient.  The *same* observation arriving twice — the job
        re-ran, the worker died between the row and the response — is not an
        error and moves nothing: the standing row is returned exactly as it
        is, ``id`` and stamps and figure included.  A *different* coefficient
        is two measurements claiming one day, and the store refuses to
        choose between them: last-wins would revise a fact feature 334's
        curve and feature 337's ratio may already have read, which is the
        track record editing itself — the one revision, beside moving the
        boundary, this table exists to make impossible.
        """
        if standing.live_ic == coefficient:
            return standing
        raise ForwardIdentityError(
            f"{FORWARD_IDENTITY_ERROR_CODE}: node {node} already holds an "
            f"observation for {standing.observed_on.isoformat()} carrying "
            f"{LIVE_IC_COLUMN} {standing.live_ic!r}, and this request would "
            f"write {coefficient!r}. A forward record is append-only: the "
            "measurement that landed on a day is that day's fact — feature "
            "334's decay curve and feature 337's retention ratio read these "
            "rows, and §C10's demotion line reads their ratio — so "
            "overwriting one would revise a track record after readers may "
            "already have accounted for it. Nothing is wrong with the body "
            "or the store: the repair is to reconcile the two measurements "
            "offline, not to move the one the record holds (feature 333)"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


def _absent_record(node: str) -> ForwardStoreError:
    """The absence refusal: no record, so nothing to observe onto.

    This feature's ``depends_on="332"`` made load bearing.  The observation
    job ran ahead of the promote step: the signal may well be promoted —
    the registry row closed, the instant stamped — but the record is what
    an observation joins, and a writer that opened one silently would
    fabricate the boundary it failed to read.  That is the same fabrication
    :meth:`forward.record.ForwardRecords.open_record` refuses on the
    promotion side, refused here on the record side: an observation row
    with no opening row before it is a track record whose day zero nobody
    drew.

    The repair is specific and ordered, and it is the pipeline's rather
    than the database's: open the record (``POST /forward/promote``,
    feature 332), then observe onto it.
    """
    return ForwardStoreError(
        f"{FORWARD_RECORD_ERROR_CODE}: {FORWARD_RECORD_TABLE} holds no row "
        f"for {NODE_ID_COLUMN} {node}, so there is no record whose "
        f"{LIVE_IC_COLUMN} this observation could extend. An observation "
        "joins the record feature 332 opened — the row that draws the "
        "boundary between backtest and out-of-sample — and a signal with "
        "no record has a track record that never began, whether or not its "
        "promotion was decided. Open the record first (POST "
        "/forward/promote, feature 332), then observe onto it (feature 333)"
    )


def _instant_of(day: dt.date) -> dt.datetime:
    """The instant at the start of a calendar day — its 00:00 UTC.

    The one conversion between the two calendars an observation spans: the day
    an observation names is a :class:`~datetime.date`, while the window's close
    (feature 300's ``opened_at + forward_days``) is an *instant*.  A day is
    measured against the close by the instant at which it begins, and a day
    whose whole span starts at or after the close carries no honest
    measurement — so ``day_start >= close`` is the refusal, and the last
    admissible day is the one whose midnight still precedes the close.  The
    day is read at UTC rather than at any local offset, the same choice
    :func:`~forward.record._validated_date` makes when it refuses to truncate
    an instant to a day without naming the clock the day is read in.
    """
    return dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC)


def _before_the_boundary(
    node: str, opening: ForwardRecord, day: Any
) -> ForwardIdentityError:
    """The vintage refusal: a day the record's own boundary excludes.

    The standing record has already fixed when its signal went out of
    sample — ``promoted_at``, on the opening row — and this request asserts
    an observation on a day that boundary excludes.  The boundary day
    itself is the opening row's own: the record landed on it carrying no
    measurement (``0108``'s comment: *"a freshly promoted signal has no
    observation yet"*), and a "live IC" for day zero would be measured over
    a span that began at the instant the deciding evaluation itself ran.
    An earlier day is worse and is the reason the table exists: data that
    existed when the hypothesis was formed, wearing the vintage of data
    that did not.

    Both are the disagreement :class:`~forward.errors.ForwardIdentityError`
    states — two claims about one record's vintage, the store refusing to
    choose — and the repair is to stop asking: the days an observation may
    name are the days after the boundary, one row each.
    """
    return ForwardIdentityError(
        f"{FORWARD_IDENTITY_ERROR_CODE}: node {node}'s forward record went "
        f"out of sample at {opening.promoted_at.isoformat()} (day "
        f"{opening.promoted_at.date().isoformat()}, the opening row's own), "
        f"and this request would observe on {day.isoformat()} — a day the "
        "record's boundary excludes. An observation is a measurement on "
        "data that did not exist when the hypothesis was formed (prd §5's "
        "loop), so the first day it can honestly name is the day after the "
        "boundary: the boundary day is the record's day zero and carries no "
        "measurement by the migration's own comment, and an earlier day "
        "would measure in-sample data under an out-of-sample vintage — the "
        "contamination this table exists to exclude. Nothing is wrong with "
        "the store: the repair is to observe only on days after the "
        "boundary (feature 333)"
    )


def _after_the_window(
    node: str, opening: ForwardRecord, forward_days: Any, day: Any, close: Any
) -> ForwardIdentityError:
    """The window-close refusal: a day the window has already closed before.

    The complement of :func:`_before_the_boundary`.  The standing record has
    already fixed the span over which its signal is measured — ``promoted_at``
    plus the horizon the caller registered — and this request asserts an
    observation on a day that span excludes.  The close is the window's
    excluded edge (feature 300's half-open interval), so a day beginning at or
    after it is a measurement taken after the signal stopped being out of
    sample: its 90-day track record is complete, and a further observation
    would be a measurement the window that produced the record never covered.

    The refusal is the same disagreement :class:`~forward.errors.
    ForwardIdentityError` states for the lower bound — two claims about one
    record's window, the store refusing to choose — and it names the close and
    the last admissible day, so the repair is to stop asking: the days an
    observation may name are the days the window is open.
    """
    last_day = _instant_of(close.date())
    last_admissible = last_day if last_day < close else last_day - dt.timedelta(days=1)
    return ForwardIdentityError(
        f"{FORWARD_IDENTITY_ERROR_CODE}: node {node}'s forward record was "
        f"open for {forward_days} days from {opening.promoted_at.isoformat()} "
        f"and closed at {close.isoformat()} (feature 300's half-open window — "
        "the closing instant is excluded), and this request would observe on "
        f"{day.isoformat()}, a day whose start ({_instant_of(day).isoformat()}) "
        f"is at or after the close. A forward observation is a measurement on "
        "data that did not exist when the hypothesis was formed, taken while "
        "the window is still open (prd §5's loop): at the close the signal "
        "*has* its 90-day track record, and a further observation would be a "
        "measurement the window that produced the record never covered. The "
        f"last day this record can honestly name is {last_admissible.date().isoformat()}. "
        "Nothing is wrong with the store: the repair is to observe only on "
        "days the window is still open (feature 335)"
    )


# -- The module-level spelling ----------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardObservations:
    """The store the module-level spelling writes through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering nothing —
    the same seam :func:`forward.record._resolved_store` resolves for the
    opening act.  The silence would be the dangerous failure here and not
    the refusal: a deployment that could not say where forward records live
    would drop the day's measurement on the floor, and §5's 90-day track
    record is a count of days that cannot be re-measured after the fact.
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
            f"{DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the live IC observation cannot be persisted. A "
            "signal's track record is these rows, and a store resolved "
            "from nothing is a refusal rather than a silent answer of the "
            "caller's own choosing (feature 333)"
        )
    return ForwardObservations(url)


def forward_observation(
    node_id: Any,
    *,
    observed_on: Any,
    live_ic: Any,
    forward_days: Any,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ForwardRecord:
    """Land one live IC observation — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the act
    without holding a store — the daily observation job, a backfill for a
    missed day, a test.  The store is resolved from ``database_url``, else
    from ``DATABASE_URL``, exactly as :func:`forward.record.forward_record`
    resolves the opening act's, so a caller reading through one spelling
    and the other is reading and writing the same database.

    ``forward_days`` is a **required keyword with no default**, the way
    feature 300 and feature 332 both take it: the registry holds the
    criteria *hash* and sha256 is one-way, so the 90-day length cannot be
    recovered from the record and must arrive from the caller — the same
    reason the store's own :meth:`append_observation` demands it.

    The answer is the **row the table holds** rather than a ``(record,
    created)`` pair, for the reason the opening act's own module-level
    spelling states: an act asked for as one call has nobody to tell about
    a retry, and the record it returns is the same value either way.  A
    caller that needs to know whether *this* call appended the row asks the
    store (:meth:`ForwardObservations.append_observation`).
    """
    return _resolved_store(database_url, env).append_observation(
        node_id, observed_on=observed_on, live_ic=live_ic, forward_days=forward_days
    )[0]
