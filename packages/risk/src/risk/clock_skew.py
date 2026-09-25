"""Feature 329: the measured clock skew that halted trading, persisted.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 329: *"System
persists the measured clock skew that halted trading when it exceeded the
threshold against exchange server time."*  ``docs/nullius-tech-architecture.md``
§13.3 line 717 puts the supervisor *"as a separate process with kill
authority over the execution engine"*, and the trigger table directly
below it names this feature's row in five words: **clock skew vs.
exchange server time > threshold — Halt.**  ``docs/alpha-engine-prd.md``
C10 names the same subject from the product side.  Read against the
module beside it, the sentence makes a narrower demand than *"notice a
clock that drifted"*: **the skew is measured against the venue's own
reading, a skew inside the band is not this feature's business, and the
measurement that stopped trading is on disk before the supervisor's
process ends.**  Four parts carry the whole contract:

* **Measured.**  :func:`measure_clock_skew` is a pure function over two
  caller-supplied instants — this clock's reading of a probe and the
  exchange server's reading of the same probe — so the measurement is
  reproducible from the two values a later reconciliation has in hand,
  and the module itself *never reads a clock to measure one*: the probe
  belongs to whoever speaks to the venue (a caller holding two
  timestamps), and the only instant this module mints is
  ``recorded_at``, when the store wrote the row.  The skew is *signed*
  (``local_time - exchange_server_time``), because the direction is the
  whole of the repair — a clock running fast is corrected backward, one
  running slow forward, and a magnitude that dropped the sign would send
  an operator to the wrong correction.
* **When it exceeded the threshold.**  The comparison is strictly
  ``>``, on both sides of zero (``abs(skew) > threshold``): §13.3's own
  symbol, and the workspace's boundary convention beside it (feature
  312's neighbour rule, :class:`canary._halt.DreamHalt`'s
  ``deviation <= tolerance`` refusal, feature 314's ``<``).  The
  threshold is *configuration*, not a constant of this module: §13.3
  says "threshold" and names no number, so it arrives as a required
  keyword with no default — a supervisor that guessed a band would halt
  on a skew nobody configured it to halt on.
* **Against exchange server time.**  The venue's reading is a field on
  the record, not a detail of the measurement: the row carries both
  ``exchange_server_time`` and ``local_time``, so the skew on it can be
  re-derived by a reader who trusts neither the writer nor the number it
  wrote — which is exactly what :class:`ClockSkewHalt` does with every
  row it reconstructs.
* **Persists.**  The record lands in this feature's own table
  (``risk_clock_skew``), and it lands for *every* halting measurement:
  only a skew that exceeded the band is persisted, so a probe inside the
  band returns ``None``, writes nothing and does not open the store at
  all (a table of every probe is a table whose halting rows an operator
  has to pick out first), and every halt this feature fires leaves
  exactly one row.  A halt that could not be recorded is *raised*, never
  shrugged past: the record is what distinguishes a clock halt from a
  supervisor that died for an unrelated reason, and a halt with nothing
  on disk to account for it is the hole this table exists to fill.

**Halting is feature 322's channel and feature 330's flatten, not a verb
of this module.**  The record says *why trading stopped*; stopping it is
the kill instruction the channel already carries, and this module drives
it through :class:`~risk.kill.RiskKillSwitch` rather than minting a
second way to stop the order layer.  So the halt path is, in order:
measure, refuse a skew inside the band, **send the kill**, then **write
the row**.  The order is not arbitrary.  ``halted_at`` is the standing
instruction's own ``sent_at``, read back from the channel — never a
moment this module stamped — so the channel has to be consulted first,
for the same reason :mod:`risk.flatten` reads the standing instruction
before it drives the engine: a record whose halt moment this module
invented would be a second, drifting answer to *"since when has trading
been stopped?"*, and the channel already holds the first.

The halting direction also decides the crash window.  A supervisor that
dies between the send and the write leaves a standing kill with its own
sender and moment on it — the halt is durable, the reason for it is what
was lost, and an operator reconciling sees a kill that stands with no
clock-skew row beside it.  Had the order been reversed, a supervisor that
died between the write and the send would leave a row asserting trading
had stopped for a clock fault *when it never stopped at all* — a
confident fiction about the exact thing this category exists to prevent,
and the one failure a record-keeper must not manufacture.  So an
unrecordable halt raises
:class:`~risk.errors.RiskClockSkewError` and the caller retries into a
store that works; the channel's own failure raises its own class from
the channel, unmasked, because a send that did not land is a halt that
did not happen and there is nothing to record.

**Like the kill channel and the ledger beside it, this is a table two
processes share.**  The supervisor that measured and the operator (or
reconciler) reading later are different processes, and §17 leaves no
port to serve a socket on; the relational store both already hold is the
medium, and it is the medium that survives the failure this category is
for.  Each operation opens its own connection, and the member's suite
proves the cross-process case against an actual second interpreter.

**The retry law is a uniqueness constraint, not a convention.**  One
probe is one measurement: the same ``(local_time, exchange_server_time)``
pair is the same row, so a supervisor that re-measures the same probe
after a crash re-reads the record it already wrote instead of filing a
second halt for one fault — the check-and-insert runs inside a single
transaction, and a losing race re-reads the winner rather than raising.
A *different* probe that also exceeds the band is a different row,
because it is a different measurement.

**The absence of a store cuts asymmetrically, the ledger's own split.**
:func:`halt_on_clock_skew` — the measuring process's spelling — *refuses*
when nothing names a store: a halt that left no record is a halt the next
operator cannot tell from a supervisor that died for an unrelated reason,
which is the record this feature exists to keep.  :func:`measured_clock_skews`
— the reader's spelling — answers an empty tuple on the same absence:
recording refuses without a store, so a deployment that names none holds
no halting measurements, and the empty answer is truthful rather than a
clean bill of clock health.

**What this module deliberately does not do.**  It does not *decide the
threshold*: that is configuration (§13.3's word, no number), passed in by
the caller.  It does not *probe the venue*: feature 328 owns the feed
watchdog and this feature owns the comparison of two readings a caller
already holds.  It does not *correct the clock*: the repair is an
operator's act, and the signed skew on every row is what tells them which
way.  And it does not *flatten*: feature 330 owns the flatten and feature
323's door drives it, so a clock-skew halt stops new orders through the
channel and leaves the open book to the feature that owns closing it.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as the channel beside it is, and the schema is created
idempotently on connect, so no migration step is needed.  A URL whose
scheme is not ``sqlite`` is refused by name — as an *address* fault, in
:class:`~risk.errors.RiskStoreError` — while the measurement's own terms
(an instant that is naive, a threshold that states no band, a stored row
no measurement can be reconstructed as) are refused in this feature's own
class, :class:`~risk.errors.RiskClockSkewError`.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._identity import process_identity
from .errors import (
    CLOCK_SKEW_CODE,
    RiskClockSkewError,
    RiskStoreError,
)
from .kill import RiskKillSwitch

__all__ = [
    "DATABASE_URL_ENV",
    "RISK_CLOCK_SKEW_TABLE",
    "ClockSkewHalt",
    "RiskClockSkewStore",
    "halt_on_clock_skew",
    "measure_clock_skew",
    "measured_clock_skews",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: This feature's own table — one row per *halting* clock-skew
#: measurement.  Deliberately not the kill channel's table and not a
#: column on it: ``risk_order_kill`` is the *state* that stands (one row,
#: first-write-wins), ``risk_halt_event`` is the *log* of every halt
#: (append-only), and this is the *measurement* that caused one halt —
#: two instants and the arithmetic between them, which neither of the
#: others has a column for and neither should grow.
RISK_CLOCK_SKEW_TABLE = "risk_clock_skew"

#: ``risk_clock_skew``'s DDL, created idempotently beside the code that
#: reads it — the same member-owned-table stance :mod:`risk.kill` and
#: :mod:`risk.halt_events` take, and deliberately *not* a migration: this
#: table has exactly one writer and one reader, both in this module.
#:
#: The ``UNIQUE (local_time, exchange_server_time)`` pair is the retry
#: law: one probe is one measurement, so a supervisor that re-measures
#: the same probe re-reads the row it already wrote rather than filing a
#: second halt for one fault.  The two ``CHECK``s are the record's own
#: terms stated where a raw insert from another tool cannot quietly break
#: them — a band that is not a band, and a measurement that did not
#: actually exceed it, are both rows no halt can be reconstructed as.
#: They are not, however, the *law*: SQLite lets
#: ``PRAGMA ignore_check_constraints`` past them, which is exactly why
#: :class:`ClockSkewHalt` re-judges its own arithmetic on every
#: construction, including the read path (see its docstring).
_SCHEMA = f"""
-- Feature 329: the measured clock skew that halted trading, one row per
-- halting measurement.  Not the kill channel (risk_order_kill -- the state
-- that stands) and not the halt ledger (risk_halt_event -- every halt ever):
-- this table holds the *measurement*, the two instants and the arithmetic
-- between them, so a later reader can re-derive the skew that stopped
-- trading rather than taking a number's word for it.
--
-- `measured_skew_seconds` is local_time - exchange_server_time, *signed*:
-- the direction is the repair (a clock running fast is corrected backward).
-- `threshold_seconds` is the configured band the probe exceeded -- stored on
-- the row, not read from configuration at read time, because the band that
-- fired is a fact about the halt and a deployment that retunes the band must
-- not silently re-judge the halts it already took.
-- `halted_at` is the standing kill instruction's own sent_at, read back from
-- the channel -- never a moment this feature stamped.  Both probe instants
-- and both record instants are ISO 8601 UTC.
--
-- UNIQUE (local_time, exchange_server_time) is the retry law: the same probe
-- measured twice is the same measurement, and re-filing it would report one
-- clock fault as two halts.
CREATE TABLE IF NOT EXISTS {RISK_CLOCK_SKEW_TABLE} (
    sequence              INTEGER PRIMARY KEY AUTOINCREMENT,
    measured_skew_seconds REAL NOT NULL,
    threshold_seconds     REAL NOT NULL,
    exchange_server_time  TEXT NOT NULL,
    local_time            TEXT NOT NULL,
    halted_at             TEXT NOT NULL,
    supervisor_process_id TEXT NOT NULL,
    recorded_at           TEXT NOT NULL,
    CHECK (threshold_seconds > 0),
    CHECK (abs(measured_skew_seconds) > threshold_seconds),
    UNIQUE (local_time, exchange_server_time)
);

-- The reader's sweep is over the probe's own moment (whole table, or the
-- suffix from an anchor), so that is the indexed column; the sequence
-- tiebreak rides the same scan.
CREATE INDEX IF NOT EXISTS {RISK_CLOCK_SKEW_TABLE}_local_time
    ON {RISK_CLOCK_SKEW_TABLE} (local_time);
"""

#: The columns of :data:`RISK_CLOCK_SKEW_TABLE`, in the order the insert
#: names them and the order the read-back unpacks them.  Spelled once so
#: the write and the read cannot drift apart on a column order — the
#: failure a positional ``SELECT *`` invites.  ``sequence`` is
#: deliberately absent from the write and present in the read: it is the
#: row's own number, minted by the insert, never supplied by the caller.
_COLUMNS = (
    "measured_skew_seconds, threshold_seconds, exchange_server_time, "
    "local_time, halted_at, supervisor_process_id, recorded_at"
)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`risk.kill` and :mod:`risk.halt_events`
    state, in this module's own words, for the reason each of them
    restates it: a store reaches into no sibling's private helper, so a
    later change to one table's address handling cannot silently move
    another's.  ``sqlite:///foo.db`` is relative, ``sqlite:////foo.db`` is
    absolute, and any other scheme is refused by name.

    Raises :class:`~risk.errors.RiskStoreError`, **not** this feature's
    own class: an address this member cannot speak is an *address* fault
    with an address repair — point the deployment at a database this
    store can open — which is the face :class:`~risk.errors.RiskStoreError`
    exists for, the split the channel and the ledger already state.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RiskStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "clock skew record speaks sqlite:/// (the spec's single-machine "
            f"allowance); point {DATABASE_URL_ENV} at the sqlite database "
            "the halting clock skew measurements are recorded in "
            "(feature 329)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 329)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened "
            "it, and a clock skew measurement that vanished would leave a "
            "halt this feature exists to account for with nothing on disk "
            "to account for it (feature 329)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this store writes goes through here — one UTC offset, one
    format, one width policy — and the read path parses what
    :func:`datetime.fromisoformat` accepts and refuses the rest, so a row
    another tool wrote in another spelling never survives into a read
    unparsed.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* a clock was read,
    and a skew computed from an ambiguous instant is a number with no
    direction and no meaning — the same discipline :mod:`risk.kill` holds
    its ``sent_at`` to, and the reason it is checked here rather than
    assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 329)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: {what} must be timezone-aware; a skew "
            "measured against a naive reading is a skew against no "
            "particular instant, and the halt it caused could not be "
            "ordered against anything (feature 329)"
        )
    return moment


def _require_real(value: object, what: str) -> float:
    """Return ``value`` as a finite real number, or refuse it by name.

    ``bool`` is refused *before* the number check, deliberately and for
    the reason :mod:`ops.live_metrics` refuses it: ``isinstance(True,
    int)`` is true in Python, so a ``threshold_seconds=True`` would pass
    a naive numeric check and halt on a band of one second.  Non-finite
    values are refused too — ``nan`` compares false against everything,
    so a ``nan`` threshold would make the boundary judgement below answer
    "inside the band" for a skew of any size, which is the one direction
    this feature must never fail in.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: {what} must be a real number of seconds, "
            f"got {value!r} ({type(value).__name__}) (feature 329)"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: {what} must be finite, got {value!r}; a "
            "band that is not a number band cannot be exceeded, and a "
            "skew judged against it would be judged against nothing "
            "(feature 329)"
        )
    return number


def _require_threshold(value: object) -> float:
    """Return ``value`` as a strictly positive band, or refuse it by name.

    §13.3 says *threshold* and names no number, so the band is
    configuration — but a band of zero or less is not configuration, it
    is a supervisor that halts on every probe: every skew that is not
    exactly zero exceeds a non-positive threshold, so a deployment that
    passed one has configured a halt rather than a tolerance.  The
    refusal is here, in the value layer, rather than only in the schema's
    ``CHECK``, because the schema's constraint is bypassable and this
    judgement is the one that decides whether a halt fires at all.
    """
    number = _require_real(value, "threshold_seconds")
    if number <= 0:
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: threshold_seconds must be greater than "
            f"zero, got {value!r}; every skew other than exactly zero "
            "exceeds a non-positive band, so a threshold of "
            f"{value!r} halts on every probe rather than on a clock fault "
            "(feature 329)"
        )
    return number


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    Used for the recording process's label, which is a *statement* about
    who wrote the row — a label that states nothing is a halt nobody can
    attribute, and the absence of an attribution is the one thing a
    supervisor's record cannot leave an operator to guess at.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}) (feature 329)"
        )
    return value.strip()


def _require_sequence(value: object) -> int:
    """Return ``value`` as a row sequence, or refuse it by name.

    The sequence is the row's ``AUTOINCREMENT`` number — minted by the
    insert, monotone, never reused — so a caller never supplies one and a
    row carrying ``0``, a negative, a bool dressed as an int, or anything
    that is not an ``int`` is a row this store did not write.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: a clock skew record's sequence is the "
            f"number the table minted, an int, got {value!r} "
            f"({type(value).__name__}) (feature 329)"
        )
    if value < 1:
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: a clock skew record's sequence is numbered "
            f"from 1 upward, got {value!r}; AUTOINCREMENT never mints 0 or "
            "a negative, and a row wearing one is a row this store did not "
            "write (feature 329)"
        )
    return value


# -- The measurement ------------------------------------------------------------


def measure_clock_skew(
    *, exchange_server_time: datetime, local_time: datetime
) -> float:
    """The signed skew, in seconds, between this clock and the venue's.

    Feature 329's first word, and deliberately a *pure function over two
    readings*: ``exchange_server_time`` is the venue's own stamp on a
    probe message and ``local_time`` is this process's stamp on the same
    probe, so the result is reproducible by any later reader holding the
    two values — and this module never reads a clock to measure one, the
    same stance :mod:`risk.halt_events` takes toward the instants it is
    handed.

    The result is ``local_time - exchange_server_time`` and it is
    **signed**: positive means this clock is ahead of the venue's and the
    correction is backward, negative means it is behind.  §13.3's trigger
    is a magnitude (``> threshold``), so :func:`_exceeds` takes the
    absolute value at the comparison — but the *record* keeps the sign,
    because a magnitude alone sends an operator to the wrong correction.

    Both readings must be timezone-aware.  Two aware readings in different
    zones are the same instant compared correctly — Python subtracts them
    by their UTC offsets — so a venue stamping in ``+00:00`` and a host
    reading in ``+09:00`` need no normalisation here.

    Raises :class:`~risk.errors.RiskClockSkewError` for a reading that is
    naive or not a moment at all.
    """
    local = _require_aware(local_time, "local_time")
    exchange = _require_aware(exchange_server_time, "exchange_server_time")
    return (local - exchange).total_seconds()


def _exceeds(skew_seconds: float, threshold_seconds: float) -> bool:
    """Whether a measured skew exceeds the configured band — §13.3's ``>``.

    Strictly greater, on both sides of zero: a skew exactly at the
    threshold is *inside* the band and is not this feature's business.
    The workspace's boundary convention beside it — feature 312's
    neighbour rule, :class:`canary._halt.DreamHalt`'s ``deviation <=
    tolerance`` refusal, feature 314's strict ``<`` — and the reason the
    boundary tests in this member's suite pin equality rather than
    approximating it.

    The absolute value is taken *here*, at the judgement, and not in
    :func:`measure_clock_skew`: the trigger fires on drift in either
    direction (a clock running ahead is as dangerous as one running
    behind), while the record keeps the sign for the repair.
    """
    return abs(skew_seconds) > threshold_seconds


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class ClockSkewHalt:
    """One halting clock-skew measurement: the skew, the band, and the halt.

    A *value* — frozen, self-describing — carrying the whole of feature
    329's sentence: this clock read ``local_time`` where the exchange
    server read ``exchange_server_time``, the difference was
    ``measured_skew_seconds``, that exceeded the configured
    ``threshold_seconds``, and trading stopped at ``halted_at`` — the
    moment the standing kill instruction landed, read back from the
    channel rather than stamped here.  The row was written at
    ``recorded_at`` by ``supervisor_process_id``, and it holds the
    table's own number in ``sequence``.

    **The arithmetic is re-derived, not trusted.**  ``__post_init__``
    computes ``local_time - exchange_server_time`` and refuses a record
    whose ``measured_skew_seconds`` disagrees with it, so the number on a
    row is never the *only* place the skew lives: the two instants beside
    it are the measurement, and this class is the one judgement over both.
    That is what makes the read path safe — every row
    :meth:`RiskClockSkewStore.skews` hands back is reconstructed through
    here, so a row edited outside this package (a skew that does not
    match its own instants, a band that is not a band, a probe that never
    actually exceeded the band it claims) fails to reconstruct rather
    than loading as a plausible-looking halt.  The schema's ``CHECK``s
    say the same thing at the storage layer, but they are the *belt*:
    SQLite lets ``PRAGMA ignore_check_constraints`` past a ``CHECK``, and
    this validation is the law that cannot be bypassed by anything short
    of editing this file.

    **The band fired is stored, not re-read from configuration.**  A
    deployment that retunes its threshold must not silently re-judge the
    halts it already took: whether *this* halt was justified is decided
    against the band in force at the time, which is the band on the row.

    Every field here has a column, and that is deliberate: this value is
    what a row *is*, so a record read back from the table and a record
    the write path returned are the same eight facts, and a reader never
    has to ask which of the two it is holding.
    """

    #: The record's number in the table — the ``AUTOINCREMENT`` key of the
    #: row it landed in.  Monotone, never reused, and the number an
    #: operator cites when a report must point at one halt.
    sequence: int
    #: The measured skew: ``local_time - exchange_server_time``, in
    #: seconds, **signed**.  Positive is a clock running ahead of the
    #: venue's (corrected backward), negative one running behind.
    measured_skew_seconds: float
    #: The configured band the skew exceeded, as it stood when the halt
    #: fired.  §13.3 says "threshold" and names no number, so this is
    #: configuration the caller supplied — strictly positive, and stored
    #: on the row so a later retune cannot re-judge this halt.
    threshold_seconds: float
    #: The venue's own reading of the probe — the sentence's *"against
    #: exchange server time"*, and the half of the measurement a reader
    #: who trusts the writer's arithmetic would not have to store, kept
    #: because trusting the writer's arithmetic is exactly what this
    #: record exists to avoid.
    exchange_server_time: datetime
    #: This clock's reading of the same probe.  The pair of instants is
    #: the measurement; ``measured_skew_seconds`` is their difference and
    #: is re-derived from them in :meth:`__post_init__`.
    local_time: datetime
    #: When trading stopped — the standing kill instruction's own
    #: ``sent_at``, read back from the channel by
    #: :meth:`RiskClockSkewStore.halt_on_skew`.  Never a moment this
    #: module stamped, so the record's halt moment and the channel's row
    #: are one fact rather than two that could drift.
    halted_at: datetime
    #: The identity of the process that measured and recorded the halt
    #: (see :func:`risk.process_identity`) — never accepted from an
    #: unlabelled default, keyword-only to override, so the record names
    #: the process that wrote it exactly as the channel's rows do.
    supervisor_process_id: str
    #: When the table wrote this row.  The store's own fact, never the
    #: caller's to state, and deliberately beside ``halted_at``: the gap
    #: between the two is itself a fact an operator reads off a
    #: supervisor that measured a fault and took a while to stop trading.
    recorded_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "sequence", _require_sequence(self.sequence))
        object.__setattr__(
            self,
            "threshold_seconds",
            _require_threshold(self.threshold_seconds),
        )
        local = _require_aware(self.local_time, "local_time")
        exchange = _require_aware(self.exchange_server_time, "exchange_server_time")
        _require_aware(self.halted_at, "halted_at")
        _require_aware(self.recorded_at, "recorded_at")
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )
        measured = _require_real(self.measured_skew_seconds, "measured_skew_seconds")
        expected = (local - exchange).total_seconds()
        if measured != expected:
            raise RiskClockSkewError(
                f"{CLOCK_SKEW_CODE}: measured_skew_seconds {measured!r} "
                f"disagrees with its own instants — local_time "
                f"{_isoformat_utc(local)} minus exchange_server_time "
                f"{_isoformat_utc(exchange)} is {expected!r}; the two "
                "readings are the measurement and the number beside them "
                "is their difference, so a record where they disagree is "
                "a row no halt can be reconstructed as (feature 329)"
            )
        object.__setattr__(self, "measured_skew_seconds", measured)
        if not _exceeds(measured, self.threshold_seconds):
            raise RiskClockSkewError(
                f"{CLOCK_SKEW_CODE}: a clock skew record is a *halting* "
                f"measurement, and this one's skew {measured!r}s does not "
                f"exceed its threshold {self.threshold_seconds!r}s; a probe "
                "inside the band is not this feature's business, and a row "
                "filed for one would report a halt that never fired "
                "(feature 329)"
            )

    @property
    def direction(self) -> str:
        """Which way this clock is off: ``"ahead"`` or ``"behind"``.

        The repair, named: a clock running ahead of the venue's is
        corrected backward and one running behind forward, and an operator
        reading a row with only the magnitude in hand has to work out
        which — so the record states it.  Derived from the sign of
        :attr:`measured_skew_seconds` rather than stored, because a stored
        copy would be a second place for the sign to live and an edited
        row would then disagree with its own summary.
        """
        return "ahead" if self.measured_skew_seconds >= 0 else "behind"

    @property
    def summary(self) -> str:
        """One sentence: how far off the clock was, and that it halted.

        Composed rather than stored, for the reason
        :attr:`~risk.halt_events.HaltEvent.summary` is: every part is
        already a field, and a stored copy would disagree with an edited
        row.  The skew is rendered signed and the direction spelled, so
        one line answers both *how bad* and *which way* — the two
        questions an operator triaging a clock halt asks, in that order.
        """
        behind_or_ahead = self.direction
        return (
            f"clock skew record {self.sequence}: this clock ran "
            f"{abs(self.measured_skew_seconds):.6f}s {behind_or_ahead} of "
            f"exchange server time ({self.exchange_server_time.isoformat()}), "
            f"exceeding the {self.threshold_seconds:.6f}s band; trading was "
            f"halted at {_isoformat_utc(self.halted_at)}, recorded by "
            f"{self.supervisor_process_id}"
        )


# -- The store ------------------------------------------------------------------


class RiskClockSkewStore:
    """Records the clock skew that halted trading, and reads the rows back.

    Bound to a database URL at construction; construction performs no I/O,
    so composing an application never touches the database and a store
    costs nothing until a halt is recorded or the table is read.  Each
    operation opens its own connection (creating the schema idempotently
    if absent), the discipline every store in this workspace follows —
    which is what makes a measurement a *separate supervisor process*
    recorded readable from the process that reconciles later: the
    database, not any process's memory, is the coordination point, and §17
    leaves no other channel to try.

    Two faces, one object: the supervisor calls :meth:`halt_on_skew`; the
    operator or reconciler calls :meth:`skews`.  Neither face holds state
    beyond the URL, this process's identity and the kill switch the halt
    path drives, so a restarted anything reads the same rows as the
    process it replaced — and appends to them, which is what makes this
    table a record rather than a state.

    **The switch is composed, not passed.**  :meth:`halt_on_skew` stops
    trading through feature 322's :class:`~risk.kill.RiskKillSwitch` over
    *this* store's own URL, built lazily on first use rather than at
    construction: the channel and the record are two tables in one
    database, which is the only arrangement in which ``halted_at`` can be
    read off the channel in the same breath as the row is written, and a
    store built during composition must not open a connection to learn
    that.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RiskStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._process_id: str | None = None
        self._switch: RiskKillSwitch | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RiskClockSkewStore | None:
        """The table ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance every
        store in this workspace takes.  What a caller does with the
        ``None`` is the caller's direction to decide, and the two
        directions this table cuts are deliberately split in this module:
        :func:`halt_on_clock_skew` refuses on it,
        :func:`measured_clock_skews` answers an empty tuple on it (see the
        module docstring for why the asymmetry is the feature, not an
        accident).
        """
        source = os.environ if env is None else env
        raw = source.get(DATABASE_URL_ENV, "").strip()
        if not raw:
            return None
        return cls(raw)

    @property
    def database_url(self) -> str:
        """The database URL this store records and reads through."""
        return self._database_url

    @property
    def path(self) -> Path:
        """The sqlite file this store's URL names, resolved.

        The translation :meth:`_connect` performs, exposed so a caller —
        an operator backing the file up before a retune, a test asserting
        two stores share one database — can name the file without opening
        a connection to learn where it is.  Refuses a URL this member
        cannot speak, in :class:`~risk.errors.RiskStoreError`, for the
        reason :func:`_sqlite_path` gives.
        """
        return _sqlite_path(self._database_url)

    @property
    def process_id(self) -> str:
        """This process's identity — the label its rows file under.

        Resolved once, on first use, rather than at construction, so a
        store built during composition does not read the host or the pid
        before a caller has asked it anything; the value cannot change for
        the life of the process, so caching it is a fact about the process
        rather than about the store — and it is the same
        :func:`risk.process_identity` the kill channel files its rows
        under, so one operator grep splits both tables' labels the same
        way.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

    @property
    def switch(self) -> RiskKillSwitch:
        """The kill channel this store halts through, over its own URL.

        Built on first use, not at construction, so composing a store
        opens nothing; feature 322's switch performs no I/O until it is
        asked to send or read either, so the laziness here is about the
        object graph rather than about the connection — but it keeps a
        store that is only ever *read* from composing a halting component
        it has no use for.
        """
        if self._switch is None:
            self._switch = RiskKillSwitch(self._database_url)
        return self._switch

    def _connect(self) -> sqlite3.Connection:
        path = _sqlite_path(self._database_url)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_SCHEMA)
        return connection

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads, idempotently.

        Public so a caller that reaches this store through another store's
        composition, and a test seeding a row into exactly the schema the
        store will read, can prepare the table without reaching for the
        private :meth:`_connect` — the same door :mod:`risk.kill` and
        :mod:`risk.halt_events` leave open, for the same reason.  Every
        statement is ``CREATE … IF NOT EXISTS``, so a fresh database and
        one this member already prepared take the same path.
        """
        self._connect().close()

    # -- The supervisor's face -------------------------------------------------

    def halt_on_skew(
        self,
        *,
        local_time: datetime,
        exchange_server_time: datetime,
        threshold_seconds: float,
        supervisor_process_id: str | None = None,
    ) -> ClockSkewHalt | None:
        """Measure the skew; if it exceeded the band, halt and record it.

        Feature 329's whole first half, in one call and one order.  The
        caller hands the two readings of one probe and the band in force;
        nothing else.  ``supervisor_process_id`` defaults to *this*
        process's identity, read from the kernel rather than accepted from
        the caller, the same label and for the same reason the kill
        switch's send refuses a caller-supplied one; it is keyword-only so
        a caller on the supervisor's own path does not pass it at all.

        **Inside the band returns ``None`` and touches nothing.**  A skew
        that did not exceed the threshold is not a halt — §13.3's trigger
        is ``>``, strictly — so this method writes no row, sends no kill
        and does not so much as open the store: the caller's probe loop
        can run at whatever rate the venue is spoken to, and a table of
        every probe would be a table whose halting rows an operator has to
        pick out first.  ``None`` is the answer, not an empty record: an
        inside-the-band probe has no row number, no halt moment and no
        measurement worth persisting, and a zero-valued record would have
        to invent all three.

        **Outside the band: send the kill, then write the row.**  The
        order is the design (see the module docstring): ``halted_at`` is
        the standing instruction's own ``sent_at``, read back from the
        channel, so the channel is consulted first, and a supervisor that
        dies between the two leaves a kill that stands rather than a row
        claiming a halt that never happened.  The kill is *idempotent* —
        feature 322's channel is first-write-wins, so a second halting
        measurement over an already-killed order layer writes nothing
        there and returns the first instruction, which is the moment
        trading actually stopped and therefore the honest ``halted_at``
        for this row too.

        **One probe, one row.**  ``(local_time, exchange_server_time)`` is
        unique, so re-measuring the same probe — a supervisor restarting
        after a crash, a retry after an unrecordable write — re-reads the
        row it already wrote instead of filing a second halt for one
        fault.  The check and the insert run inside one transaction, and a
        losing race re-reads the winner rather than raising, the answer
        :mod:`forward.reconciliation` gives to its own uniqueness law.

        Returns the stored record — the row that landed, not a
        re-derivation of the ask — so a caller logging the halt holds the
        number the table minted for it.  Raises
        :class:`~risk.errors.RiskClockSkewError` for a reading that is
        naive, a threshold that states no band, or a row that could not be
        written (an unrecordable halt is the hole this feature exists to
        fill); the channel's own failures raise from the channel, unmasked,
        because a kill that did not land is a halt that did not happen and
        there is nothing to record.
        """
        threshold = _require_threshold(threshold_seconds)
        local = _require_aware(local_time, "local_time")
        exchange = _require_aware(exchange_server_time, "exchange_server_time")
        skew = (local - exchange).total_seconds()
        if not _exceeds(skew, threshold):
            return None
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        halted_at = self.switch.send(supervisor_process_id=sender).sent_at
        recorded_at = datetime.now(UTC)
        return self._insert(
            skew_seconds=skew,
            threshold_seconds=threshold,
            exchange_server_time=exchange,
            local_time=local,
            halted_at=halted_at,
            supervisor_process_id=sender,
            recorded_at=recorded_at,
        )

    # The reader's face -------------------------------------------------------

    def skews(self, *, since: datetime | None = None) -> tuple[ClockSkewHalt, ...]:
        """Every recorded clock-skew halt, oldest first — the read.

        Without ``since``, the whole table, in the order the probes were
        taken; with it, the suffix from the anchor.  The bound is
        inclusive, the workspace's window convention, so a halt measured
        at exactly the anchor instant is part of the story the anchor
        begins — the same convention :meth:`risk.halt_events.
        RiskHaltEventStore.events` states for its own sweep, and for the
        same reason: an operator reconciling *"what has happened since the
        kill at T?"* must not have the event at T excluded by a boundary
        they did not choose.

        Ordering is by the probe's own moment (``local_time``, the indexed
        column), with the table's sequence breaking same-instant ties in
        the order the rows were written.  A late-recorded halt (probe in
        the past, row written since) takes its place at its own moment,
        not at the moment of the write, because the sweep answers *when did
        the clocks disagree*, not *when did we find out*.

        **The window is a filter over the stored spelling.**  The bound is
        compared against the string the table holds, which is correct
        exactly because every row *this store* writes goes through
        :func:`_isoformat_utc` — one UTC offset, one format.  A row another
        tool wrote in another spelling may therefore sort outside a window
        it "should" fall in, and that is the safe direction: such a row is
        simply not counted, rather than counted into a reconciliation on a
        comparison the reader cannot justify.  Rows that *are* inside are
        reconstructed through :class:`ClockSkewHalt`'s own validation, so
        nothing survives into a read unjudged.

        Fails with :class:`~risk.errors.RiskStoreError` when the table
        could not be read, and with
        :class:`~risk.errors.RiskClockSkewError` when a stored row is not a
        measurement this store could have written — the refusal, not a
        skip: a skipped row is a halt an operator would never learn about.
        """
        clause = ""
        parameters: list[object] = []
        if since is not None:
            clause = " WHERE local_time >= ?"
            parameters.append(_isoformat_utc(_require_aware(since, "since")))
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT sequence, {_COLUMNS}
                    FROM {RISK_CLOCK_SKEW_TABLE}{clause}
                    ORDER BY local_time, sequence
                    """,
                    parameters,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the clock skew record: {exc}"
            ) from exc
        return tuple(self._halt_from_row(row) for row in rows)

    # -- The row plumbing ----------------------------------------------------

    def _insert(
        self,
        *,
        skew_seconds: float,
        threshold_seconds: float,
        exchange_server_time: datetime,
        local_time: datetime,
        halted_at: datetime,
        supervisor_process_id: str,
        recorded_at: datetime,
    ) -> ClockSkewHalt:
        """Land one halting measurement, or re-read the one already there.

        The retry law lives here rather than in :meth:`halt_on_skew`, so
        the check-and-insert is one transaction: the row for this probe is
        looked for first, and only a miss inserts.  A concurrent writer
        that wins the race between the two raises ``IntegrityError`` on
        the ``UNIQUE`` pair, and that is not an error — it is the answer
        arriving from the other process, so the winner's row is re-read
        and returned.

        **The re-read uses a plain connection, deliberately.**  The failed
        insert may still hold a write lock, and :meth:`_connect` would take
        one of its own to run the schema bootstrap — so re-reading through
        it could block against a transaction this call is still inside.
        Opening ``sqlite3.connect`` on the file directly reads the
        committed row without contending for the lock, the same recovery
        :mod:`forward.reconciliation` performs on its own ``IntegrityError``
        path.
        """
        values = (
            skew_seconds,
            threshold_seconds,
            _isoformat_utc(exchange_server_time),
            _isoformat_utc(local_time),
            _isoformat_utc(halted_at),
            supervisor_process_id,
            _isoformat_utc(recorded_at),
        )
        existing = self._row_at(local_time, exchange_server_time)
        if existing is not None:
            return self._halt_from_row(existing)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT INTO {RISK_CLOCK_SKEW_TABLE} (
                        {_COLUMNS}
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                sequence = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            # Either another process recorded this same probe between the
            # read above and this insert, or the table refused the row for
            # a reason no re-read will satisfy.  The two are told apart by
            # asking the table, not by trusting the exception: one probe is
            # one measurement, so a row for this probe *is* this
            # measurement's record and the loser hands it back rather than
            # reporting a conflict where there is none.  No row means the
            # refusal was something else -- a constraint a tampered table
            # grew, a trigger -- and it belongs to this feature's
            # vocabulary, not the driver's (see this method's docstring for
            # why the re-read goes through a plain connection).
            raced = self._row_at(local_time, exchange_server_time, plain=True)
            if raced is None:
                raise RiskClockSkewError(
                    f"{CLOCK_SKEW_CODE}: the clock skew of {skew_seconds!r}s "
                    f"over the {threshold_seconds!r}s band exceeded the "
                    f"threshold and trading was halted, but the measurement "
                    f"could not be recorded: {exc}. The halt stands -- the "
                    "row is the record of why, and a halt with nothing on "
                    "disk to account for it is indistinguishable from a "
                    "supervisor that died for an unrelated reason "
                    "(feature 329)"
                ) from exc
            return self._halt_from_row(raced)
        except (sqlite3.Error, OSError) as exc:
            raise RiskClockSkewError(
                f"{CLOCK_SKEW_CODE}: the clock skew of {skew_seconds!r}s "
                f"over the {threshold_seconds!r}s band exceeded the "
                "threshold and trading was halted, but the measurement "
                f"could not be recorded: {exc}. The halt stands -- the row "
                "is the record of why, and a halt with nothing on disk to "
                "account for it is indistinguishable from a supervisor that "
                "died for an unrelated reason (feature 329)"
            ) from exc
        if sequence is None:
            raise RiskClockSkewError(
                f"{CLOCK_SKEW_CODE}: the clock skew record landed without "
                "the table minting it a number; a halt that cannot be cited "
                "cannot be reconciled, and the record this feature exists "
                "for would hold a row no report can point at (feature 329)"
            )
        return ClockSkewHalt(
            sequence=sequence,
            measured_skew_seconds=skew_seconds,
            threshold_seconds=threshold_seconds,
            exchange_server_time=exchange_server_time,
            local_time=local_time,
            halted_at=halted_at,
            supervisor_process_id=supervisor_process_id,
            recorded_at=recorded_at,
        )

    def _row_at(
        self,
        local_time: datetime,
        exchange_server_time: datetime,
        *,
        plain: bool = False,
    ) -> tuple | None:
        """The row for one probe, or ``None`` — the uniqueness law's read.

        The lookup key is the ``UNIQUE (local_time, exchange_server_time)``
        pair, compared in the table's own stored spelling, so the retry
        law and this read agree on what "the same probe" means by
        construction rather than by two spellings happening to match.

        ``plain`` opens the file directly, without running the schema
        bootstrap — the recovery path :meth:`_insert` needs after an
        ``IntegrityError`` (see its docstring).  It is a parameter rather
        than a second method so the lookup key stays spelled once.
        """
        parameters = (_isoformat_utc(local_time), _isoformat_utc(exchange_server_time))
        statement = f"""
            SELECT sequence, {_COLUMNS}
            FROM {RISK_CLOCK_SKEW_TABLE}
            WHERE local_time = ? AND exchange_server_time = ?
            """
        if plain:
            path = _sqlite_path(self._database_url)
            connection = sqlite3.connect(path)
        else:
            connection = self._connect()
        try:
            with closing(connection):
                rows = connection.execute(statement, parameters).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the clock skew record for the probe at "
                f"{parameters[0]} against {parameters[1]}: {exc}"
            ) from exc
        if not rows:
            return None
        return rows[0]

    @staticmethod
    def _halt_from_row(row: tuple) -> ClockSkewHalt:
        """Rebuild one stored row, refusing a value no measurement can be.

        The refusal is the point: this table is written by this store, but
        SQLite will accept anything another tool inserts — and will let
        ``PRAGMA ignore_check_constraints`` past its own ``CHECK``\\ s — so
        a row wearing a moment no parser accepts, a skew that disagrees
        with its own instants, a band that is not a band, or a probe that
        never actually exceeded the band it claims would otherwise read
        back as a halt nobody recorded, or fail to read back as one
        somebody did.  The value layer is where that judgement lives (see
        :class:`ClockSkewHalt`); this method is what makes the refusal
        *findable*, naming the row it came from so an operator gets the row
        to repair rather than a complaint about a value with no address.
        """
        (
            sequence,
            measured_raw,
            threshold_raw,
            exchange_raw,
            local_raw,
            halted_raw,
            sender,
            recorded_raw,
        ) = row
        moments: dict[str, datetime] = {}
        for what, raw in (
            ("exchange_server_time", exchange_raw),
            ("local_time", local_raw),
            ("halted_at", halted_raw),
            ("recorded_at", recorded_raw),
        ):
            try:
                moments[what] = datetime.fromisoformat(raw)
            except (TypeError, ValueError) as exc:
                raise RiskClockSkewError(
                    f"{CLOCK_SKEW_CODE}: the clock skew row numbered "
                    f"{sequence!r} carries {what} {raw!r}, which is not an "
                    "ISO 8601 moment this store can order a sweep by "
                    "(feature 329)"
                ) from exc
        try:
            return ClockSkewHalt(
                sequence=sequence,
                measured_skew_seconds=measured_raw,
                threshold_seconds=threshold_raw,
                exchange_server_time=moments["exchange_server_time"],
                local_time=moments["local_time"],
                halted_at=moments["halted_at"],
                supervisor_process_id=sender,
                recorded_at=moments["recorded_at"],
            )
        except RiskClockSkewError as refusal:
            raise RiskClockSkewError(
                f"{refusal} — the row this came from is clock skew record "
                f"{sequence!r}, recorded by {sender!r} at "
                f"{recorded_raw!r} (feature 329)"
            ) from refusal


# -- The module-level spellings ---------------------------------------------------


def halt_on_clock_skew(
    *,
    local_time: datetime,
    exchange_server_time: datetime,
    threshold_seconds: float,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    supervisor_process_id: str | None = None,
) -> ClockSkewHalt | None:
    """Measure the skew and halt on it, opening the record from the environment.

    The supervisor's one call: resolve the table from ``database_url``,
    else from ``DATABASE_URL``, then hand the probe and the band to
    :meth:`RiskClockSkewStore.halt_on_skew`.  Returns the stored record
    when the skew exceeded the band and ``None`` when it did not — a probe
    inside the band is not a halt, so this spelling has the same two
    answers as the method it delegates to, and neither answer opens a
    store that is not configured when the clock is fine.

    A deployment that names no store is refused *by name* once the skew
    has been measured and found to exceed the band, because from that
    moment trading must stop and nothing would record why: the kill would
    be sent (the channel is reachable from the same URL this store cannot
    find) and the row accounting for it would go nowhere, leaving an
    operator a standing kill they cannot attribute to a clock — the hole
    this feature exists to fill.  A probe *inside* the band never reaches
    that refusal, deliberately: there is no halt to account for, so an
    unconfigured deployment that merely polls is not an error.  The
    refusal's ordering is the module's own (see the module docstring):
    the band is judged first, because a refusal that fired on every probe
    would be a refusal on a healthy clock.

    The refusal happens before the measurements are validated by the
    store — a skew already computed from two instances is a skew whose
    readings parse, and the store's own vocabulary names the row and the
    band it could not write, so this spelling adds the one fact the store
    cannot know: that *no database was named at all*.  The reader's
    direction answers an empty tuple on the same absence; see
    :func:`measured_clock_skews`.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        threshold = _require_threshold(threshold_seconds)
        local = _require_aware(local_time, "local_time")
        exchange = _require_aware(exchange_server_time, "exchange_server_time")
        if not _exceeds((local - exchange).total_seconds(), threshold):
            return None
        raise RiskClockSkewError(
            f"{CLOCK_SKEW_CODE}: halt_on_clock_skew halts on feature 329's "
            f"clock skew and nothing names a store: {DATABASE_URL_ENV} is "
            "unset (and no database_url was supplied), so the halt could "
            "not be recorded. The clock has run far enough off the exchange "
            "server's time to stop trading, and a halt that left no record "
            "of the measurement is one an operator cannot tell from a "
            "supervisor that died for an unrelated reason"
        )
    return RiskClockSkewStore(url).halt_on_skew(
        local_time=local_time,
        exchange_server_time=exchange_server_time,
        threshold_seconds=threshold_seconds,
        supervisor_process_id=supervisor_process_id,
    )


def measured_clock_skews(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    since: datetime | None = None,
) -> tuple[ClockSkewHalt, ...]:
    """The recorded clock-skew halts — the reader's spelling.

    Every halting measurement the named table holds, oldest first, or the
    suffix from ``since`` (see :meth:`RiskClockSkewStore.skews`).  A
    deployment that names no store answers an empty tuple: recording
    refuses without a store, so a deployment that names none holds no
    clock-skew halts to read, and the empty answer is the truthful one —
    the same *"no store, no status"* stance :func:`risk.require_orders_allowed`
    takes, kept distinct because a caller that mistook an unconfigured
    deployment for an empty record would read a table with no halts in it
    and call it a clock that has never drifted.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return ()
    return RiskClockSkewStore(url).skews(since=since)
