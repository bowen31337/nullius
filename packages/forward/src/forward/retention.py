"""Feature 337 — a signal's forward information coefficient retention.

prd §11's table states the secondary promotion criterion in one line:
*"Forward-test IC retention: live IC ÷ backtest IC at 90 days | > 0.5"*, and
§C10 states the consequence in another: *"if live IC falls below 40% of
backtest IC over a statistically meaningful window, demote automatically."*
Both read the same figure, and this module is where it is computed: the live
coefficient divided by the backtest coefficient, **per signal**.

**The verb is *computes*, and that is the whole of the act.**  Neither
coefficient is stated by the caller:

* **The live IC is read, never stated** — it is feature 333's own column.
  The forward record holds one row per day and each row carries the
  coefficient measured on it, so "live IC" is the mean of those rows'
  ``live_ic`` figures: the signal's measured out-of-sample performance over
  the days it was observed, which is what §11's *"at 90 days"* names.  One
  mean, because §11's metric is per *signal* and the record is per *day*.
  ``observed_days`` travels beside the mean as the *evidence* for it: a
  ratio over three days and a ratio over ninety are the same number and are
  not the same fact, and §11's criterion counts days.
* **The backtest IC is stated once and kept.**  It is prd §6.1's
  ``metrics.ic_mean``, measured by the evaluation member and persisted in
  *its* table — and a workspace member never reads a sibling's tables
  (:mod:`forward.schema`'s own isolation law), so the figure cannot be
  fetched and must arrive from the caller.  It arrives through
  :meth:`ForwardIcRetentions.record_backtest_ic`, which lands it on the
  record's own column, ``forward_record.backtest_ic``, and the division
  reads it back off the row.  The figure is therefore written once per
  signal and never moves: a retention ratio that re-asked the evaluator
  would be answering about the evaluator's current state rather than about
  the backtest the signal was promoted on, and §C10's demotion line is
  about the latter.

**This feature's column, this module's only writer.**  ``0108`` declares
three nullable REAL columns on ``forward_record`` and neither writer before
this one may name them: :data:`forward.record._INSERT_SQL` writes the four
columns of the opening row and :data:`forward.observation.
_OBSERVATION_INSERT_SQL` writes the four of an observation, and both
docstrings say why ``backtest_ic`` is absent — *"a statement that cannot
name a column cannot fabricate its value"* — and both assign the column to
this feature.  The landing site is the record's **opening row**, amended in
place, rather than every row: the backtest coefficient is a fact about the
signal before it went out of sample, and stamping it onto rows whose whole
subject is that they are *after* the boundary would put an in-sample figure
on an out-of-sample measurement.

**A zero backtest is refused, never answered.**  Feature 350's own module
and :mod:`scoring._divergence` both decline to charge this ratio, and the
scoring member states the first of the two reasons plainly: it *"is
undefined at zero backtest IC"*.  ``+inf`` is not a retention — it is a
division that did not happen — and ``0.0`` would read as a signal that kept
none of an edge that was never measured.  The repair is the ask: a signal
whose backtest IC is zero has no edge for a live IC to retain.

**The ratio is unbounded, and the missing bound is load-bearing.**  Feature
350's ``ic_ratio`` column is bounded ``[−1, 1]`` because it *is* an
information coefficient; this is a **quotient of two** coefficients and
lives on its own scale, where one is the retention parity line §11 draws
and two is a signal that did twice as well live as it was predicted to.  The
scoring member's second stated reason — that a bound *"reads a forward IC
twice the backtest as a number above one rather than as the same-sized gap
it is"* — is the same argument from the other end: clamping would erase
over-delivery, and over-delivery is exactly the fact §11 and §C10 read.
Negative ratios are answered too, not clamped to zero: a live IC that
inverted is a larger failure than one that fell to nothing, and §C10's 40%
line must be able to tell the two apart.

**No cache, no memo.**  Both inputs are read on every call and the mean is
taken every time.  A retention ratio is the figure §C10 demotes on, and a
demotion decision that read a stale copy would be deciding about a track
record that had already moved.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from .errors import (
    FORWARD_RETENTION_ERROR_CODE,
    ForwardError,
    ForwardRetentionError,
)
from .record import (
    _READ_SQL,
    DATABASE_URL_ENV,
    FORWARD_RECORD_TABLE,
    LIVE_IC_BOUND,
    LIVE_IC_COLUMN,
    NODE_ID_COLUMN,
    OBSERVED_ON_COLUMN,
    PROMOTED_AT_COLUMN,
    ForwardRecord,
    _record_from_row,
    _sqlite_path,
    _validated_date,
    _validated_instant,
    _validated_live_ic,
    _validated_uuid,
)
from .schema import bootstrap_schema

__all__ = [
    "BACKTEST_IC_COLUMN",
    "FORWARD_RETENTION_SEAM",
    "RETENTION_RATIO_KEY",
    "ForwardIcRetentions",
    "IcRetention",
    "forward_ic_retention",
]

#: The column this feature owns and is the only writer of.  Named here
#: rather than restated from :mod:`forward.record`, because that module
#: deliberately does not name it: the column is absent from both insert
#: statements in this member, and the one statement that does name it is
#: this module's own ``UPDATE`` below.
BACKTEST_IC_COLUMN = "backtest_ic"

#: The key the ratio itself travels under in :meth:`IcRetention.summary`.
#: Not a column name — no table holds the ratio, and that is deliberate: it
#: is a quotient of two stored figures and re-deriving it from them is
#: cheaper and safer than keeping a copy that can drift.  The spelling is
#: prd §11's own two words, so a reader of the mapping is reading the
#: criterion's operand.
RETENTION_RATIO_KEY = "retention_ratio"

#: The attribute :meth:`ForwardIcRetentions.over` reads off a composed store
#: — the same one feature 333's observation store reads, and deliberately the
#: same string: both acts write the one table the composed ``forward``
#: component points at, so a second seam spelling would be a second way to
#: name one database.
FORWARD_RETENTION_SEAM = "database_url"

#: Amendment of the opening row, by primary key.  The ``WHERE id = ?`` is the
#: landing-site decision made in SQL: the backtest coefficient belongs on the
#: row that draws the boundary, and keying this statement by ``node_id``
#: would stamp every observation row with a figure measured before any of
#: them existed.
_AMEND_SQL = (
    f"UPDATE {FORWARD_RECORD_TABLE} SET {BACKTEST_IC_COLUMN} = ? WHERE id = ?"
)


# -- Validation -------------------------------------------------------------------


def _validated_backtest_ic(value: Any) -> float:
    """Return ``value`` as a backtest information coefficient, or refuse it.

    The same three gates :func:`forward.record._validated_live_ic` applies —
    a finite real, ``bool`` refused first, bounded by
    :data:`forward.record.LIVE_IC_BOUND` — because the two figures are the
    same *kind* of quantity: prd §6.1's ``metrics.ic_mean`` is an
    information coefficient, computed by the evaluation member on the
    in-sample window rather than by feature 333 on the out-of-sample one.
    A figure outside ``[−1, 1]`` wearing this name is a z-score or an
    information *ratio* handed over under a coefficient's field name, and
    clamping it would persist the maximum coefficient for it.

    **Zero is not refused here, and that is deliberate.**  ``0.0`` is a
    perfectly well-formed information coefficient — it is the figure a
    signal with no measured edge has, and the honest one.  It is refused
    further along, at the division
    (:func:`_undefined`), because the fault is not in the coefficient but
    in the quotient: this validator answers the question *is this a
    coefficient*, and a zero is.  Splitting the gates this way is what lets
    :meth:`ForwardIcRetentions.record_backtest_ic` **store** a zero — the
    figure was measured and the row is where measurements live — while the
    ratio that cannot be computed off it is refused with a message that
    names the real reason.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"{BACKTEST_IC_COLUMN} must be the backtest information "
            f"coefficient as a real number — got {value!r} "
            f"({type(value).__name__}); the retention ratio this feature "
            "computes is the live IC divided by this figure, so a value "
            "that is not one number leaves the quotient with no divisor "
            "(prd §11's *\"Forward-test IC retention: live IC ÷ backtest IC "
            "at 90 days\"*). Pass the coefficient the evaluation member "
            "measured on the in-sample window (prd §6.1's metrics.ic_mean, "
            "feature 337)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"{BACKTEST_IC_COLUMN} must be finite — got {narrowed!r}; a NaN "
            "would make the retention ratio a NaN and a NaN compares false "
            "against every §C10 threshold, so the demotion line would never "
            "fire and the signal would read as though it were fine, and an "
            "infinity is not a coefficient at all. The figure is what a "
            "backtest measured, and a value that is not one is not a "
            "measurement any later reader can account with (feature 337)"
        )
    if not -LIVE_IC_BOUND <= narrowed <= LIVE_IC_BOUND:
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"{BACKTEST_IC_COLUMN} must be an information coefficient in "
            f"[{-LIVE_IC_BOUND}, {LIVE_IC_BOUND}] — got {narrowed!r}. An "
            "information coefficient is a correlation and lives in that "
            "interval by construction, whatever the estimator: a figure "
            "outside it is not a large IC but a number that has stopped "
            "being one, and the likeliest things wearing its name are a "
            "z-score, a hit rate or an information ratio. Refused rather "
            "than clamped, because the ratio divides by this figure and a "
            "clamped divisor would hand §C10's demotion line a number "
            "nobody measured (feature 337)"
        )
    return narrowed


def _validated_ratio(value: Any) -> float:
    """Return ``value`` as a retention ratio, or refuse it.

    Two gates and **no bound**, and the missing one is the load-bearing
    decision of this feature.  The value must be a finite real and ``bool``
    is refused first, exactly as above — a ratio is a number and ``True``
    is not one.  What is *not* checked is an interval, because a retention
    ratio has none:

    * **Above one is the interesting case, not a fault.**  A live IC
      larger than the backtest IC is the signal that did better out of
      sample than the backtest predicted, and :mod:`scoring._divergence`
      declines to charge on this ratio for precisely the reason a bound
      would be wrong: it *"reads a forward IC twice the backtest as a
      number above one rather than as the same-sized gap it is"*.  Clamping
      to one would erase over-delivery — the fact §11's criterion and
      §C10's demotion line both exist to read.
    * **Below zero is a larger failure, not a floor.**  A live IC that
      inverted is worse than one that fell to zero, and §C10's 40% line
      cannot be enforced against a figure that was clamped flat at zero:
      both would read as equally dead.

    The contrast with feature 350 is deliberate and named here so the two
    are not mistaken for one another: ``ops.live_metrics``' ``ic_ratio``
    column *is* an information coefficient and *is* bounded ``[−1, 1]``;
    this is a quotient of two of them and is not.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            "the retention ratio must be a real number — got "
            f"{value!r} ({type(value).__name__}); it is the live IC divided "
            "by the backtest IC, and a ratio that is not one number is not "
            "a retention (feature 337)"
        )
    narrowed = float(value)
    if not math.isfinite(narrowed):
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            "the retention ratio must be finite — got "
            f"{narrowed!r}. Both operands are validated finite coefficients "
            "and a zero divisor is refused before the division, so an "
            "infinite or NaN quotient means the arithmetic did not run on "
            "the two figures this feature read (feature 337)"
        )
    return narrowed


def _validated_count(value: Any) -> int:
    """Return ``value`` as an observed-day count, or refuse it.

    Whole, positive, not a ``bool``: the count is how many of the record's
    rows carried a measurement, and it is the *evidence* §11's criterion
    carries.  Zero is refused rather than answered, because a ratio over no
    days is not a ratio over zero days — the mean it divides would have no
    addends, and this feature refuses that state earlier, by name, as a
    signal that has not been observed at all
    (:func:`_no_observation`).  A count reaching here as zero would be a
    caller asserting the absence the store already checks.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            "observed_days must be the number of days the signal was "
            f"measured as a whole number — got {value!r} "
            f"({type(value).__name__}); the count is the evidence prd §11's "
            "*\"at 90 days\"* criterion is stated over, and a ratio taken "
            "over an unstated number of days is a figure §C10's demotion "
            "line would act on without knowing how much track record stood "
            "behind it (feature 337)"
        )
    if value < 1:
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"observed_days must be at least 1 — got {value}; a signal with "
            "no observed day has no live coefficient for a retention ratio "
            "to be taken over, and the absence is this member's own refusal "
            "rather than a zero to be answered (feature 337)"
        )
    return value


# -- The answer -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IcRetention:
    """One signal's forward IC retention — the figure, and its evidence.

    The answer of :meth:`ForwardIcRetentions.retention`, and the value §11's
    criterion and §C10's demotion line both read.  It is a *frozen* value
    with a ``__post_init__`` that re-derives the quotient and compares: the
    ratio is not a field a caller may state, it is the arithmetic this class
    performs over the two coefficients, and an instance whose ``ratio``
    disagrees with its own operands is refused rather than carried.  That is
    the same discipline :class:`forward.reconciliation.ReconciledFillCosts`
    applies to its difference — a derived figure is checked against its
    derivation, so a caller cannot hand §C10 a ratio that does not divide.
    """

    #: The signal this retention is about — ``forward_record.node_id``.
    node_id: str
    #: The instant the record went out of sample, off the opening row.  It is
    #: the record's own ``promoted_at``, validated by the record's own
    #: validator rather than restated here: the field is feature 332's, and a
    #: second spelling of what a stamp is would be a second contract for one
    #: column.
    promoted_at: Any
    #: The latest day a coefficient was observed on — feature 333's column,
    #: validated by its own date reader for the same reason.
    observed_on: Any
    #: How many days carried a measurement — the mean's denominator.
    observed_days: int
    #: The mean of the record's observed ``live_ic`` figures.
    live_ic: float
    #: The backtest coefficient the caller landed on the opening row.
    backtest_ic: float
    #: ``live_ic / backtest_ic`` — unbounded, and zero-divisor refused.
    ratio: float

    def __post_init__(self) -> None:
        """Validate every field, then re-derive the quotient and compare.

        The field validators run first and in the order the fields are
        declared, so a malformed constituent is refused by its own name
        before the arithmetic is attempted.  Then the two laws that are
        about the *ratio* rather than about any one field:

        * **A zero divisor is refused** (:func:`_undefined`), because the
          quotient is undefined and neither ``inf`` nor ``0.0`` is an
          honest answer to it.
        * **The ratio must equal its own division.**  ``!=`` rather than a
          tolerance, for the reason :mod:`forward.reconciliation` compares
          its difference exactly: both are arithmetic this member performed
          itself over figures it read, so a disagreement is not rounding —
          it is a value that was never the quotient of its operands.
        """
        _validated_uuid(self.node_id, NODE_ID_COLUMN)
        _validated_instant(self.promoted_at, PROMOTED_AT_COLUMN)
        _validated_date(self.observed_on, OBSERVED_ON_COLUMN)
        _validated_count(self.observed_days)
        live = _validated_live_ic(self.live_ic)
        backtest = _validated_backtest_ic(self.backtest_ic)
        if backtest == 0.0:
            raise _undefined(self.node_id)
        ratio = _validated_ratio(self.ratio)
        if ratio != live / backtest:
            raise ForwardRetentionError(
                f"{FORWARD_RETENTION_ERROR_CODE}: "
                f"the retention ratio {ratio!r} is not the live IC "
                f"({live!r}) divided by the backtest IC ({backtest!r}), "
                f"which is {live / backtest!r}. The ratio is not a figure a "
                "caller may state: prd §11's criterion is *\"live IC ÷ "
                "backtest IC at 90 days\"* and §C10 demotes on it, so an "
                "instance whose own operands do not produce its ratio would "
                "put a number in front of the demotion line that nobody "
                "computed. Nothing is wrong with the store: the repair is "
                "to let this feature do the division (feature 337)"
            )

    def row(self) -> tuple[str, int, float, float, float]:
        """The answer as a flat tuple, in :meth:`summary`'s own order."""
        return (
            self.node_id,
            self.observed_days,
            self.live_ic,
            self.backtest_ic,
            self.ratio,
        )

    def summary(self) -> dict[str, Any]:
        """The answer as a JSON-shaped mapping, for a router or a job log.

        The two instants and their days travel as ISO strings for the same
        reason every timestamp in this member does: the figure is read by
        operators and dashboards, and :mod:`json` has no datetime.  The
        ratio is the last key and is named the way §11 names it, so a reader
        holding this mapping is holding the criterion's own operand rather
        than a figure that needs re-deriving.
        """
        return {
            NODE_ID_COLUMN: self.node_id,
            PROMOTED_AT_COLUMN: self.promoted_at.isoformat(),
            OBSERVED_ON_COLUMN: self.observed_on.isoformat(),
            "observed_days": self.observed_days,
            LIVE_IC_COLUMN: self.live_ic,
            BACKTEST_IC_COLUMN: self.backtest_ic,
            RETENTION_RATIO_KEY: self.ratio,
        }


# -- The store --------------------------------------------------------------------


class ForwardIcRetentions:
    """Feature 337's store: the backtest IC a signal was promoted on, and its ratio.

    Two acts over one column and one division.  :meth:`record_backtest_ic`
    lands the caller-stated coefficient on the record's opening row;
    :meth:`retention` reads it back and divides the record's own live
    coefficients by it.  Both work through
    :data:`forward.record._READ_SQL` — one reading of ``forward_record``
    across features 332, 333, 340 and this one, so the rows this act amends
    and the rows the opener answered with cannot be two readings of one
    table.

    Constructed over a URL, or over a composed store through :meth:`over`,
    the ladder features 333 and 340 both climb: the classmethod reads the
    ``database_url`` off whatever the component is, the store methods do
    the work, and the module-level spelling resolves ``DATABASE_URL``.
    """

    def __init__(self, database_url: str) -> None:
        """Wire the store to the database the coefficients live in.

        The URL is validated here, before any call, because it is a fact
        about the *store* rather than about any one signal: a URL that is
        not a non-empty string names no table, and a store that accepted
        one would fail identically on every call — the wrong place for a
        deployment to discover a wiring fault.
        """
        if not isinstance(database_url, str) or not database_url.strip():
            raise ForwardRetentionError(
                f"{FORWARD_RETENTION_ERROR_CODE}: "
                f"{DATABASE_URL_ENV} must be a non-empty database URL. The "
                "backtest coefficient is a column on the forward record and "
                "the retention ratio is read off that record's rows, so a "
                "store pointed at nothing has nowhere to land the figure "
                "prd §11's criterion divides by (feature 337)"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Path | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(cls, env: Mapping[str, str] | None = None) -> ForwardIcRetentions | None:
        """The retention store ``DATABASE_URL`` names, or ``None``.

        An empty or whitespace-only value counts as unset, the way every
        store in this workspace treats its configuration — the reader's
        spelling, and deliberately the same one :meth:`forward.observation.
        ForwardObservations.resolve` answers with: a deployment with no
        relational store holds no retention reader, which is a discoverable
        state rather than an exception.  The *writer* spellings below refuse
        instead, because a coefficient that went nowhere is a figure nobody
        can recover, while a ratio nobody computed can be computed later
        off the rows that still hold both operands.
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @classmethod
    def over(cls, records: Any) -> ForwardIcRetentions:
        """The retention store over a composed forward-record store.

        The bridge from the seat to these acts: a caller holding the
        composed ``forward`` component (:func:`app.modules.forward.
        forward_records_component`) asks this one question and holds the
        reader and writer for the same database the component points at —
        one URL, one table, three acts.  The one thing read is the store's
        ``database_url``; there is no ``isinstance`` to defeat, and no
        second store constructed beside the component to keep consistent,
        because the URL *is* the component's own.
        """
        url = getattr(records, FORWARD_RETENTION_SEAM, None)
        if not isinstance(url, str) or not url.strip():
            raise TypeError(
                "ForwardIcRetentions is built over a forward-record store — "
                f"something exposing a {FORWARD_RETENTION_SEAM!r} string "
                "(the composed 'forward' component, or a ForwardRecords); "
                f"got {type(records).__name__}, which names no database. "
                "The backtest coefficient lands on a column of the forward "
                "record, so the writer and the reader share one URL by "
                "construction (feature 337)"
            )
        return cls(url)

    @property
    def database_url(self) -> str:
        """The database URL this store reads and amends."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The SQLite file behind the records, resolved on first use.

        Nothing is created at construction — the URL is translated the
        first time an operation needs it, by the member's one spelling of
        that translation (:func:`forward.record._sqlite_path`), so a URL
        this member cannot speak is refused in the member's one vocabulary
        whichever store translated it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the records' database, bringing the two tables it names up.

        The same statement of intent every store in this member makes, over
        the same two owners: :func:`forward.schema.bootstrap_schema` runs
        the owning migrations' own ``statements("sqlite")`` — ``0118`` for
        ``node`` and ``0108`` for ``forward_record`` — so this store authors
        no DDL, spells no column and cannot drift from the schema's owner.
        This feature adds **no table and no column**: ``backtest_ic`` is
        ``0108``'s own third REAL column, declared nullable and commented as
        the backtest side of this very ratio, and the act here is an
        ``UPDATE`` of a column the migration already drew.

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
            raise ForwardRetentionError(
                f"{FORWARD_RETENTION_ERROR_CODE}: "
                f"{FORWARD_RECORD_TABLE} could not be brought to the "
                f"revision a retention ratio needs at {path}: {exc}. The "
                "table is created by "
                "migrations/versions/0108_forward_and_universe_tables.py and "
                "its parent by 0118_node_table.py; this store runs those "
                "files' own statements and authors none of its own "
                "(feature 337)"
            ) from exc
        return connection

    def _rows(
        self, connection: sqlite3.Connection, node: str
    ) -> list[ForwardRecord]:
        """The signal's standing rows, oldest day first — the record itself.

        Feature 332's own read spelling — :data:`forward.record._READ_SQL`
        and :func:`forward.record._record_from_row` — used rather than
        restated, so the rows this act divides and the rows the record's
        opener answered with cannot be two readings of one table, and the
        rows it amends are the rows the observation writer appended to.  A
        validation refusal off a row is the record contract's own
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

    # -- Feature 337: the coefficient, and the division ---------------------

    def record_backtest_ic(
        self, node_id: Any, *, backtest_ic: Any
    ) -> tuple[ForwardRecord, bool]:
        """Land the backtest coefficient on a signal's opening row.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, the coefficient
           as a finite real in ``[−1, 1]`` — *before* anything is opened,
           so a malformed coefficient is refused without touching a
           database and a refused call leaves no row and no file behind.
           A ``0.0`` passes here and is refused at the division instead:
           see :func:`_validated_backtest_ic`.
        2. **Read the signal's standing rows.**  No rows is a refusal by
           name (:func:`_absent_record`) — a coefficient needs the record
           whose column it lands in, exactly as an observation does.
        3. **Answer the retry, or refuse the disagreement, or amend.**  A
           standing opening row already carrying *this* coefficient is the
           same figure arriving twice — the answer is the row as it stands,
           with ``created=False``.  A row carrying a *different* coefficient
           is two claims about one signal's backtest, and the store refuses
           to choose: last-wins would revise the baseline §11's criterion
           divides by, which is the same self-editing this member's record
           and observation tables exist to make impossible.  An unfilled
           column takes the ``UPDATE``.
        4. **Read back and answer with the row**, inside the same
           transaction as the write, so every figure in the answer is the
           table's own.

        **The amendment names the opening row by ``id``.**  The figure is a
        fact about the signal *before* the boundary, so it belongs on the
        row that draws the boundary and on no other; keying the ``UPDATE``
        by ``node_id`` would stamp every out-of-sample row with an
        in-sample figure.

        **A zero is stored, and the refusal comes later.**  This act's
        question is *was a coefficient measured*, and zero is an answer to
        it; :meth:`retention` asks *can this coefficient be divided by*, and
        a zero is not.  Splitting them means the row holds what the
        evaluation member actually measured, and the refusal an operator
        reads names the division rather than accusing the figure.
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        coefficient = _validated_backtest_ic(backtest_ic)
        with closing(self._connect()) as connection, connection:
            standing = self._rows(connection, node)
            if not standing:
                raise _absent_record(node)
            opening = _one_vintage(node, standing)
            if opening.backtest_ic is not None:
                return _answer_standing(node, opening, coefficient), False
            connection.execute(_AMEND_SQL, (coefficient, opening.id))
            amended = self._row_at(connection, node, opening.observed_on)
        if amended is None:
            raise ForwardRetentionError(
                f"{FORWARD_RETENTION_ERROR_CODE}: "
                f"{BACKTEST_IC_COLUMN} was written to {FORWARD_RECORD_TABLE} "
                f"row {opening.id} for node {node} but the row could not be "
                "read back inside the same transaction. The write and its "
                "read-back are one act: an answer assembled from the "
                "arguments would report a figure the table may not hold "
                "(feature 337)"
            )
        return amended, True

    def retention(self, node_id: Any) -> IcRetention:
        """Compute a signal's forward IC retention — 337's act.

        The steps, in the order they must happen:

        1. **Validate the ask** — the node as an identity, before anything
           is opened.
        2. **Read the signal's standing rows**, and refuse by name when the
           table holds none (:func:`_absent_record`) or when they disagree
           about the record's vintage (:func:`_one_vintage`).  This is
           ``depends_on="335"`` read off the store: the ratio is taken over
           feature 333's observations, so it needs the record and the rows
           that extend it.
        3. **Take the live IC** — the mean of the rows that carried a
           measurement, with the count beside it as the evidence.  No such
           row is a refusal, not a zero (:func:`_no_observation`): a signal
           observed on no day has no measured live performance, and §11's
           criterion is stated over a 90-day window rather than over
           whatever happens to be in the table.
        4. **Read the backtest IC off the opening row**, refusing its
           absence by name (:func:`_no_backtest`) — the caller has not yet
           landed the figure, and the repair is :meth:`record_backtest_ic`.
           The stored value is validated on the way *out* as well as on the
           way in, because SQLite's column affinity does not enforce a
           range and a hand on the table can put anything in a REAL column.
        5. **Refuse a zero divisor** (:func:`_undefined`) and divide.

        **Both operands are read; neither is a parameter.**  That is the
        feature's sentence — *computes ... as live divided by backtest* —
        taken literally: a caller cannot supply the live IC, because the
        record holds it, and cannot supply the ratio, because
        :class:`IcRetention` re-derives it.

        **The mean is over the observed rows only.**  A record's rows are
        one per day from the boundary to the window's close, and a row
        whose ``live_ic`` is null is a day the observation job did not
        reach — an absence, not a measured zero.  Averaging nulls in as
        zeroes would let a signal with three measurements and eighty-seven
        missed days read as a signal that collapsed, which is a fabrication
        of exactly the kind this table's append-only law guards against.
        ``observed_days`` carries the count so the difference is visible.
        """
        node = _validated_uuid(node_id, NODE_ID_COLUMN)
        with closing(self._connect()) as connection:
            standing = self._rows(connection, node)
        if not standing:
            raise _absent_record(node)
        opening = _one_vintage(node, standing)
        observed = [row for row in standing if row.live_ic is not None]
        if not observed:
            raise _no_observation(node, opening)
        stored = opening.backtest_ic
        if stored is None:
            raise _no_backtest(node, opening)
        backtest = _validated_backtest_ic(stored)
        if backtest == 0.0:
            raise _undefined(node)
        live = sum(float(row.live_ic) for row in observed) / len(observed)
        return IcRetention(
            node_id=node,
            promoted_at=opening.promoted_at,
            observed_on=max(row.observed_on for row in observed),
            observed_days=len(observed),
            live_ic=live,
            backtest_ic=backtest,
            ratio=live / backtest,
        )

    def _row_at(
        self, connection: sqlite3.Connection, node: str, day: Any
    ) -> ForwardRecord | None:
        """The signal's row for one day, or ``None`` when the table holds none.

        The read-back half of the amendment: the answer is drawn from the
        table inside the write's own transaction, so every figure the caller
        holds is the table's own.  Reached through the same
        :data:`forward.record._READ_SQL` the standing check used, so there
        is one reading of the record in this act and the write and its
        verification cannot disagree about what a row is.

        Keyed by ``(node, day)`` rather than by the ``id`` the ``UPDATE``
        named, because the day is the column the read is shaped by and
        feature 332's table holds one row per day.  The two agree whenever
        the row is intact; a hand that moved a row's day between the write
        and the read is exactly the state this answers ``None`` for, and
        :meth:`record_backtest_ic` refuses it rather than answering with a
        row it did not write.
        """
        for row in self._rows(connection, node):
            if row.observed_on == day:
                return row
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"{type(self).__name__}(database_url={self._database_url!r})"


# -- The private refusals ---------------------------------------------------------


def _one_vintage(node: str, standing: list[ForwardRecord]) -> ForwardRecord:
    """The record's opening row, after checking the record is one record.

    The opening row is the earliest by ``observed_on`` — the promotion day,
    which feature 332 wrote and no observation can share — and its
    ``promoted_at`` is the boundary every row carries while its ``id`` is
    what this feature's amendment names.  The *check* beside it is the
    one-vintage law read back: feature 332's retry law writes one instant
    per record and feature 333's appends preserve it, so rows that disagree
    are a hand that reached past the member, and the record they leave is
    one whose boundary nobody can state.

    Refusing here is cheaper than discovering it from the ratio, where a
    mean over rows carrying two different boundaries would read as a decay
    nobody measured.  The opening row is ``standing[0]`` because
    :data:`forward.record._READ_SQL` orders by ``observed_on`` — the same
    fact :meth:`forward.observation.ForwardObservations._one_vintage` relies
    on, stated here rather than imported because it is a property of the
    ordering clause and not of any object.
    """
    instants = {row.promoted_at for row in standing}
    if len(instants) > 1:
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"the {FORWARD_RECORD_TABLE} rows for node {node} carry "
            f"{len(instants)} different promoted_at values — "
            + ", ".join(sorted(t.isoformat() for t in instants))
            + ". A forward record is one vintage: feature 332 opens one row "
            "per signal carrying one instant, and every observation carries "
            "that same instant, so rows disagreeing about it are a hand "
            "that reached past this store. A retention ratio taken over "
            "them would divide a live IC measured across two different "
            "boundaries by one backtest figure, and §C10's demotion line "
            "would act on the result — repair the rows, then compute "
            "(feature 337)"
        )
    return standing[0]


def _answer_standing(
    node: str, opening: ForwardRecord, coefficient: float
) -> ForwardRecord:
    """Resolve an opening row that already carries a figure: retry or refusal.

    The two outcomes are the same column read two ways and the difference is
    the coefficient.  The *same* figure arriving twice — the backfill
    re-ran, the worker died between the ``UPDATE`` and the response — is not
    an error and moves nothing: the standing row is returned exactly as it
    is, ``id`` and stamps and figure included.

    A *different* figure is two claims about one signal's backtest, and the
    store refuses to choose between them.  Both silent resolutions are
    wrong: last-wins would move the baseline §11's criterion divides by and
    §C10 demotes against, so a signal could be demoted — or spared — by a
    figure that arrived after the decision; and first-wins would leave the
    caller holding a response that contradicts the coefficient it just
    supplied, which is worse than a refusal because it looks like success.
    The repair is to reconcile the two measurements offline, not to move the
    one the record holds.

    The comparison is over the *coefficient* and not over the whole row, and
    that is deliberate: feature 333 fills ``live_ic`` on other rows and
    feature 340 fills ``realized_cost_bps``, so a caller re-supplying the
    same backtest long after the record has been annotated must not be
    refused for disagreeing about columns this act never writes.
    """
    if opening.backtest_ic == coefficient:
        return opening
    raise ForwardRetentionError(
        f"{FORWARD_RETENTION_ERROR_CODE}: "
        f"node {node} already holds a backtest information coefficient "
        f"{opening.backtest_ic!r} on its record's opening row (promoted at "
        f"{opening.promoted_at.isoformat()}), and this request would record "
        f"{coefficient!r}. A signal has one backtest: prd §11's criterion "
        "is *\"live IC ÷ backtest IC at 90 days\"* and §C10 demotes on that "
        "ratio, so a second figure would leave the denominator of every "
        "later ratio unstated — the signal could be demoted, or spared, "
        "depending on which measurement a reader happened to find. Nothing "
        "is wrong with the store: the repair is to reconcile the two "
        "backtests offline, not to move the one the record holds "
        "(feature 337)"
    )


def _absent_record(node: str) -> ForwardRetentionError:
    """The absence refusal: no record, so nothing to carry a coefficient.

    This feature's ``depends_on="335"`` made load bearing, through feature
    332: the backtest coefficient is a column on ``forward_record``, and a
    store that opened a record silently to hold it would fabricate the
    boundary it failed to read — the same fabrication both prior writers in
    this member refuse, refused here on the third column.

    The repair is specific and ordered, and it is the pipeline's rather than
    the database's: open the record (``POST /forward/promote``, feature
    332), then record the coefficient the signal was promoted on.
    """
    return ForwardRetentionError(
        f"{FORWARD_RETENTION_ERROR_CODE}: "
        f"{FORWARD_RECORD_TABLE} holds no row for {NODE_ID_COLUMN} {node}, "
        f"so there is no record whose {BACKTEST_IC_COLUMN} this request "
        "could fill. The backtest coefficient lands on the opening row "
        "feature 332 wrote — the row that draws the boundary between "
        "backtest and out-of-sample — and a signal with no record has no "
        "baseline for prd §11's retention ratio to divide by, whether or "
        "not its promotion was decided. Open the record first (POST "
        "/forward/promote, feature 332), then record its backtest IC "
        "(feature 337)"
    )


def _no_observation(node: str, opening: ForwardRecord) -> ForwardRetentionError:
    """The unobserved refusal: a record with nothing measured on it yet.

    Answered rather than zeroed.  A live IC of zero is a *measurement* — the
    signal was measured and kept none of its edge, which is §C10's demotion
    candidate — while a record with no observation at all has no live
    performance to report, and the two must not read alike.  A signal
    promoted this morning would be demoted by lunchtime on the strength of a
    job that had not run.

    The repair is feature 333's act, on schedule.
    """
    return ForwardRetentionError(
        f"{FORWARD_RETENTION_ERROR_CODE}: "
        f"node {node}'s forward record (promoted at "
        f"{opening.promoted_at.isoformat()}, day "
        f"{opening.observed_on.isoformat()}) holds no row carrying a "
        "live_ic, so there is no measured live performance for a retention "
        "ratio to be taken over. A live IC of zero would mean the signal "
        "was measured and kept none of its edge — a demotion candidate "
        "under prd §C10 — while this record has not been measured at all, "
        "and answering zero here would put the first in front of the "
        "demotion line on the strength of the second. Nothing is wrong with "
        "the store: the repair is to observe the signal on days the window "
        "is open (feature 333), which is what §11's *\"at 90 days\"* "
        "criterion counts (feature 337)"
    )


def _no_backtest(node: str, opening: ForwardRecord) -> ForwardRetentionError:
    """The unfilled-denominator refusal: no backtest IC landed yet.

    The column is nullable by ``0108``'s own shape — feature 332 opens the
    record and knows nothing about the backtest, this feature fills it — so
    its null is a state rather than a fault, and it is named as one.  The
    alternative readings are both fabrications: treating the absence as zero
    would refuse as undefined a signal whose figure simply has not arrived,
    and treating it as the live IC would answer a ratio of one for every
    signal nobody had measured yet — the best possible retention handed to a
    criterion that promotes on it.

    The repair is this feature's own writer, and it is one call.
    """
    return ForwardRetentionError(
        f"{FORWARD_RETENTION_ERROR_CODE}: "
        f"node {node}'s forward record was opened at "
        f"{opening.promoted_at.isoformat()} carrying no "
        f"{BACKTEST_IC_COLUMN}, so the retention ratio has no divisor. The "
        "column is nullable because feature 332 opens the record and this "
        "feature fills it, so its absence is a state rather than a fault: "
        "no backtest figure has been recorded for this signal yet. Neither "
        "silent reading is honest — zero would refuse as undefined a signal "
        "whose figure has merely not arrived, and the live IC would answer a "
        "ratio of one for every unmeasured signal, handing prd §11's "
        "criterion its best possible value. Nothing is wrong with the "
        "store: the repair is to record the coefficient the evaluation "
        "member measured on the in-sample window "
        "(ForwardIcRetentions.record_backtest_ic, prd §6.1's "
        "metrics.ic_mean, feature 337)"
    )


def _undefined(node: str) -> ForwardRetentionError:
    """The undefined-quotient refusal: a zero backtest IC.

    The figure is well-formed — :func:`_validated_backtest_ic` accepts it
    and :meth:`ForwardIcRetentions.record_backtest_ic` stores it — and the
    refusal is about the *division*, not about the coefficient.  A signal
    whose measured in-sample IC is zero has no edge for a live IC to retain,
    and the quotient that would say how much of it survived has no value.

    The two silent answers are both wrong and are named in the message:
    ``inf`` is a division that did not happen wearing a number's clothes,
    and ``0.0`` reads as a signal that kept none of its edge — which is what
    a live IC of zero means, and is not what this is.  :mod:`scoring.
    _divergence` declines to charge on this ratio for exactly this reason,
    stating it as the first of its two grounds: the ratio *"is undefined at
    zero backtest IC"*.  This member agrees with the scoring member by
    refusing rather than by inventing a convention.

    The repair is the ask: a signal with no measured in-sample edge has no
    retention to compute.
    """
    return ForwardRetentionError(
        f"{FORWARD_RETENTION_ERROR_CODE}: "
        f"node {node}'s forward record carries a backtest information "
        "coefficient of 0.0, so the retention ratio is undefined. The figure "
        "itself is well-formed — zero is what a signal with no measured "
        "in-sample edge has, and the record holds it — but the quotient prd "
        "§11 states (*\"live IC ÷ backtest IC at 90 days\"*) has no value: "
        "neither infinity, which is a division that did not happen wearing a "
        "number's clothes, nor zero, which would read as a signal that kept "
        "none of an edge that was never measured. The scoring member "
        "declines to charge on this ratio on the same ground. Nothing is "
        "wrong with the store: the repair is the ask — a signal whose "
        "backtest IC is zero has no retention to compute (feature 337)"
    )


# -- The module-level spelling ----------------------------------------------------


def _resolved_store(
    database_url: str | None, env: Mapping[str, str] | None
) -> ForwardIcRetentions:
    """The store the module-level spelling reads through, or a refusal.

    An explicit URL wins, else ``DATABASE_URL``, and a deployment that names
    neither is refused *by name* rather than silently answering nothing —
    the same seam :func:`forward.observation._resolved_store` resolves for
    the observation act, and for the same reason: the silence would be the
    dangerous failure.  A deployment that could not say where forward
    records live would read no ratio at all, and §C10's demotion line is a
    decision that has to be made every cycle rather than only when a caller
    remembers to name a database.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url or not str(url).strip():
        raise ForwardRetentionError(
            f"{FORWARD_RETENTION_ERROR_CODE}: "
            f"no database is named — {DATABASE_URL_ENV} is unset (and no "
            "database_url was supplied), so no forward IC retention can be "
            "computed. The ratio divides a column of the forward record by "
            "that record's live coefficients, so a store resolved from "
            "nothing is a refusal rather than a silent answer of the "
            "caller's own choosing (feature 337)"
        )
    return ForwardIcRetentions(url)


def forward_ic_retention(
    node_id: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> IcRetention:
    """Compute one signal's forward IC retention — the module-level spelling.

    The feature's sentence as one call, for the caller that wants the figure
    without holding a store — §C10's demotion check, a dashboard, a test.
    The store is resolved from ``database_url``, else from ``DATABASE_URL``,
    exactly as :func:`forward.observation.forward_observation` resolves the
    observation act's, so a caller reading through one spelling and the
    other is reading the same database.

    **No coefficient is a parameter, and that is the feature.**  The live IC
    is read from feature 333's rows and the backtest IC from the opening
    row's own column, so this call cannot be handed a ratio it did not
    compute: the only way the answer's operands can differ from the table's
    is for the table to move underneath the read, and each is read once
    inside one call.  The complementary act — landing the backtest figure —
    is the store's, because a one-call writer with nobody to tell about a
    retry would report a write that did not happen.
    """
    return _resolved_store(database_url, env).retention(node_id)
