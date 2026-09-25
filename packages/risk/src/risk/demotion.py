"""Feature 326: the signal demotion the supervisor persists when a promoted
signal's live information coefficient falls below 40 percent of its backtest one.

app_spec.xml, "Risk Supervisor & Kill Switches", feature 326: *"System
persists an automatic demotion when live information coefficient falls below
40 percent of its backtest value."*  ``docs/nullius-tech-architecture.md``
§13.3's trigger table names this feature's row in five words: **live IC < 40%
of backtest IC over a meaningful window — Auto-demote the signal**, and
``docs/alpha-engine-prd.md`` C10 states the consequence from the product side:
*"if live IC falls below 40% of backtest IC over a statistically meaningful
window, demote automatically."*  Read against the modules beside it, the
sentence makes a narrower demand than *"notice a signal that decayed"*: **the
two coefficients are read, never stated by this feature, and both live in the
forward member's own record — the live coefficient is feature 333's column (the
mean of the observed rows) and the backtest coefficient is feature 337's column
(the figure landed once on the record's opening row) — so feature 326 reaches
the *ratio* the forward member computes through that member's own public seam,
and judges the ratio it is handed.**  A member never imports a sibling's tables
(:mod:`forward.schema`'s own isolation law), so the demotion takes the retention
ratio as a caller-supplied input rather than re-reading the forward member's
record itself — the "hand over, never derive" barrier :mod:`risk.feed_staleness`
and :mod:`risk.live_metrics` hold toward the figures they are handed.

Four parts carry the whole contract, and the verb is *persists*:

* **Below 40 percent.**  The comparison is strictly ``<``, on the ratio the
  forward member hands over: a signal is demoted when its live IC is *below*
  40 percent of its backtest IC — when the retention ratio is strictly less
  than 0.4 — and a ratio exactly at 40 percent is *at* the line, so the signal
  is held rather than demoted.  The workspace's boundary convention beside it
  (feature 314's strict ``<``, feature 312's neighbour rule, feature 329's and
  feature 328's ``>``), and the reason the boundary tests in this member's
  suite pin equality rather than approximating it.  The 40 percent is a
  **constant of this module**, not configuration: the spec names the number
  ("40 percent") and names no knob to retune it, so it is spelled once as
  :data:`DEMOTION_BOUND` and a supervisor that guessed a bound would demote on
  a line nobody specified.

* **The ratio is handed over, never derived.**  Neither coefficient is read by
  this feature, and the ratio is not computed here: the caller — the supervisor
  process, which speaks to the forward member — obtains the ratio through
  :func:`forward.forward_ic_retention` (feature 337, which divides the live
  coefficient by the backtest one per signal) and hands the single number over.
  The store's :meth:`RiskSignalDemotionStore.record_demotion` takes the
  ``node_id`` and the ``ratio`` and judges the ratio against the bound; it does
  not name the forward member's columns and does not reach into its tables.
  What the ratio *means* — whether the live IC inverted, whether the backtest
  was zero and the ratio was refused upstream — is the forward member's
  business, settled before the number arrives here.

* **A demotion is persisted.**  The demotion lands in this feature's own table
  (``risk_signal_demotion``), one row per signal — the ``node_id`` is the
  primary key, so a signal that has been demoted stays demoted and a second
  demotion of the same signal writes nothing and returns the standing demotion
  with ``changed=False``, the same first-write-wins law feature 322's kill
  channel holds: a demotion that a later measurement could move would quietly
  rewrite the record of when the signal lost its promotion.  The row carries
  the ratio it was demoted under, the bound it fell below, and the instant the
  demotion was recorded — the instant read back from the standing row rather
  than stamped here, so the recorded moment and the row are one fact.  Only a
  *demoting* ratio lands: a ratio at or above the bound returns ``None``, writes
  nothing and does not so much as open the store (a table of every judgement is
  a table whose demotions an operator has to pick out first).

* **The moment and the row are one fact.**  :data:`demoted_at` is the instant
  the standing row was written, read back from the row after the insert — never
  a moment this module stamped into the value and carried in memory.  On a
  re-filing of an already-demoted signal the returned moment is the *first*
  demotion's, because the row is read back and the first demotion is the fact on
  record — the same discipline feature 322's channel holds toward ``sent_at``.

**Demoting is this module's whole act, and halting is not it.**  A signal
demotion is not a kill of the order layer and not a flatten of the book: it is
the supervisor's decision that one signal no longer holds its promotion, and
the signal's weight is driven to nothing by whichever process consumes the
demotion, not by this module minting a second way to stop the order layer.  So
this module records the demotion and reads the demotions back, and nothing here
sends the kill, drives the engine or flattens — feature 322's channel and
feature 330's flatten own those verbs, exactly as feature 329's clock-skew halt
stops new orders through the channel and leaves the open book to the feature
that owns closing it.

**Like the kill channel and the clock-skew record beside it, this is a table
two processes share.**  The supervisor that demoted and the operator (or
reconciler) reading later are different processes, and §17 leaves no port to
serve a socket on; the relational store both already hold is the medium, and it
is the medium that survives the failure this category is for.  Each operation
opens its own connection, and the member's suite proves the cross-process case
against an actual second interpreter.

**The retry law is the primary key, not a convention.**  One signal is one
demotion: the ``node_id`` primary key holds the table to one row per signal at
the storage layer, so a supervisor that re-files the same signal after a crash
re-reads the demotion it already wrote instead of rewriting the moment the
signal lost its promotion — the check-and-insert runs inside a single
transaction, and a losing race re-reads the winner rather than raising.

**The absence of a store cuts asymmetrically, the clock-skew record's own
split.**  :func:`demote_on_ic_drop` — the measuring process's spelling —
*refuses* when nothing names a store and the ratio has fired: a demotion that
left no record is a demotion the next cycle cannot tell from a signal that was
never judged, which is the record this feature exists to keep.  A ratio at or
above the bound never reaches that refusal, deliberately: there is no demotion
to account for, so an unconfigured deployment that merely judges is not an
error.  :func:`recorded_demotions` — the reader's spelling — answers the empty
tuple on the same absence: recording refuses without a store, so a deployment
that names none holds no demotions, and the empty answer is truthful rather
than a clean bill of signal health.

Storage is the workspace's relational store, addressed by ``DATABASE_URL``
exactly as the channel and the clock-skew record beside it are, and the schema
is created idempotently on connect, so no migration step is needed.  A URL whose
scheme is not ``sqlite`` is refused by name — as an *address* fault, in
:class:`~risk.errors.RiskStoreError` — while the demotion's own terms (a node
that is not a signal identity, a ratio that is not a number, a bound that is not
a band, a stored row no demotion can be reconstructed as) are refused in this
feature's own class, :class:`~risk.errors.RiskSignalDemotionError`.
"""

from __future__ import annotations

import math
import os
import sqlite3
import uuid
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from ._identity import process_identity
from .errors import (
    SIGNAL_DEMOTION_CODE,
    RiskSignalDemotionError,
    RiskStoreError,
)

__all__ = [
    "DATABASE_URL_ENV",
    "DEMOTION_BOUND",
    "NODE_ID_COLUMN",
    "RISK_SIGNAL_DEMOTION_TABLE",
    "RiskSignalDemotionStore",
    "SignalDemotion",
    "demote_on_ic_drop",
    "recorded_demotions",
]

#: The workspace-wide environment variable naming the relational store —
#: the one spelling every store in this workspace already uses, restated
#: here so this module states its own contract and imports no sibling's.
DATABASE_URL_ENV = "DATABASE_URL"

#: The ratio below which a signal is demoted — 40 percent, the spec's own
#: number.  A **constant of this module**, not configuration: app_spec.xml
#: feature 326 names "40 percent" and names no knob to retune it, so a
#: supervisor that guessed a bound would demote on a line nobody specified.
#: The comparison is strictly ``<`` (a ratio exactly at the bound is held,
#: not demoted), the workspace's boundary convention beside it.
DEMOTION_BOUND = 0.4

#: This feature's own table — one row per *demoted* signal.  Deliberately not
#: the kill channel's table and not a column on the forward member's record:
#: ``risk_order_kill`` is the order layer's *state* that stands, the demotion
#: is a *signal* event, and forcing it into either shape would break the law
#: the other exists to hold.
RISK_SIGNAL_DEMOTION_TABLE = "risk_signal_demotion"

#: The column that names the demoted signal — the forward record's ``node_id``,
#: the signal identity the demotion is about.  Restated rather than imported
#: from :mod:`forward.record`, for the reason every store in this member
#: restates its helpers: a member reaches into no sibling's private name, so a
#: later change to one table's column cannot silently move another's.
NODE_ID_COLUMN = "node_id"

#: ``risk_signal_demotion``'s DDL, created idempotently beside the code that
#: reads it — the same member-owned-table stance :mod:`risk.kill` and
#: :mod:`risk.clock_skew` take, and deliberately *not* a migration: this table
#: has exactly one writer and one reader, both in this module.
#:
#: The ``node_id`` primary key is the one-row-per-signal law stated where
#: neither this module's discipline nor a reviewer's attention has to hold it:
#: a demotion is a *state* per signal, not a log, and a second row for one
#: signal — from a racing supervisor, a looping restart, or a raw ``INSERT`` at
#: a sqlite3 prompt — would rewrite the moment the signal lost its promotion.
#: The two ``CHECK``s are the record's own terms stated where a raw insert from
#: another tool cannot quietly break them — a bound that is not a band, and a
#: ratio that did not actually fall below it — but they are not the *law*:
#: SQLite lets ``PRAGMA ignore_check_constraints`` past a ``CHECK``, which is
#: exactly why :class:`SignalDemotion` re-judges its own arithmetic on every
#: construction, including the read path.
_SCHEMA = f"""
-- Feature 326: the signal demotion the supervisor persists when a promoted
-- signal's live IC falls below 40 percent of its backtest IC.  Exactly one row
-- per signal: the first demotion's ratio, bound and moment are the fact on
-- record, and every later demotion of the same signal writes nothing
-- (first-write-wins, like feature 322's kill and feature 329's clock skew).
--
-- `retention_ratio` is the live IC divided by the backtest IC, handed over by
-- the forward member's public seam (feature 337) — unbounded, and the figure
-- §C10's demotion line acts on.  `demotion_bound` is the 40 percent line,
-- stored on the row so a later retune cannot silently re-judge the demotions
-- it already took.  `demoted_at` is the instant the row was written, read back
-- from the standing row rather than stamped into the value.  `node_id` is the
-- demoted signal's identity; `supervisor_process_id` is the process that
-- judged it (see risk.process_identity).
--
-- node_id PRIMARY KEY is the one-row-per-signal law; the two CHECKs are the
-- belt, and the value layer is the law.
CREATE TABLE IF NOT EXISTS {RISK_SIGNAL_DEMOTION_TABLE} (
    node_id               TEXT PRIMARY KEY,
    retention_ratio       REAL NOT NULL,
    demotion_bound        REAL NOT NULL,
    demoted_at            TEXT NOT NULL,
    supervisor_process_id TEXT NOT NULL,
    CHECK (demotion_bound > 0),
    CHECK (retention_ratio < demotion_bound)
);
"""

#: The columns of :data:`RISK_SIGNAL_DEMOTION_TABLE`, in the order the read
#: names them and the order the reconstruction unpacks them.  Spelled once so
#: the write and the read cannot drift apart on a column order — the failure a
#: positional ``SELECT *`` invites.  ``node_id`` is present here (it is the
#: read's key) and named first in the insert's VALUES, the one column the
#: caller supplies.
_COLUMNS = (
    "node_id, retention_ratio, demotion_bound, demoted_at, supervisor_process_id"
)


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into the filesystem path it names.

    The same translation :mod:`risk.kill` and :mod:`risk.clock_skew` state, in
    this module's own words, for the reason each of them restates it: a store
    reaches into no sibling's private helper, so a later change to one table's
    address handling cannot silently move another's.  ``sqlite:///foo.db`` is
    relative, ``sqlite:////foo.db`` is absolute, and any other scheme is
    refused by name.

    Raises :class:`~risk.errors.RiskStoreError`, **not** this feature's own
    class: an address this member cannot speak is an *address* fault with an
    address repair — point the deployment at a database this store can open —
    which is the face :class:`~risk.errors.RiskStoreError` exists for.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise RiskStoreError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: the "
            "signal demotion record speaks sqlite:/// (the spec's "
            f"single-machine allowance); point {DATABASE_URL_ENV} at the "
            "sqlite database the signal demotions are recorded in (feature 326)"
        )
    if parsed.netloc not in ("", "localhost"):
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r} (feature 326)"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise RiskStoreError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an "
            "in-memory database would die with the connection that opened it, "
            "and a signal demotion that vanished would leave a demotion this "
            "feature exists to account for with nothing on disk to account for "
            "it (feature 326)"
        )
    return Path(path)


def _isoformat_utc(moment: datetime) -> str:
    """Render ``moment`` in the one canonical form this table stores.

    Every row this store writes goes through here — one UTC offset, one
    format — and the read path parses what :func:`datetime.fromisoformat`
    accepts and refuses the rest, so a row another tool wrote in another
    spelling never survives into a read unparsed.
    """
    return moment.astimezone(UTC).isoformat()


def _require_aware(moment: object, what: str) -> datetime:
    """Return ``moment`` as a timezone-aware datetime, or refuse it by name.

    A naive timestamp cannot say unambiguously *when* a signal was demoted,
    and a demotion whose moment cannot be ordered cannot take its place in a
    reconciliation — the same discipline :mod:`risk.kill` holds its ``sent_at``
    to, and the reason it is checked here rather than assumed.
    """
    if not isinstance(moment, datetime):
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be a datetime, not "
            f"{type(moment).__name__} (feature 326)"
        )
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be timezone-aware; a "
            "demotion must say unambiguously when the signal lost its "
            "promotion, or the record cannot be ordered against anything "
            "(feature 326)"
        )
    return moment


def _require_uuid(value: object, what: str) -> str:
    """Return ``value`` as a canonical signal identity, or refuse it by name.

    The demotion is about a signal, and a signal is a promoted signal's
    ``node_id`` — a UUID.  A ``node_id`` that is not a UUID names no signal
    this member can demote, and a demotion about a signal that cannot be named
    is unattributable.  A :class:`~uuid.UUID` is accepted and canonicalised to
    its text, so a caller holding the object and a caller holding the string
    are judged by one spelling — the same stance the member that owns the
    signal domain takes toward its own ``node_id``.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if not isinstance(value, str):
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be a signal identity — a "
            f"UUID — got {value!r} ({type(value).__name__}); the demotion is "
            "about one promoted signal, and a node that is not a UUID names "
            "no signal this member can demote (feature 326)"
        )
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} {value!r} is not a signal "
            "identity — a UUID — and a demotion about a signal that cannot "
            "be named is unattributable (feature 326)"
        ) from exc


def _require_ratio(value: object, what: str) -> float:
    """Return ``value`` as a finite real retention ratio, or refuse it by name.

    The ratio is the live IC divided by the backtest IC — handed over by the
    forward member's seam, unbounded — and it is the figure §C10's demotion
    line acts on, so it must be one real number.  ``bool`` is refused *before*
    the number check, deliberately and for the reason :mod:`ops.live_metrics`
    refuses it: ``isinstance(True, int)`` is true in Python, so a
    ``ratio=True`` would pass a naive numeric check and demote on a band of
    one.  Non-finite values are refused too — ``nan`` compares false against
    everything, so a ``nan`` ratio would never fall below the bound and a
    demoted signal would read as though it were fine, which is the one
    direction this feature must never fail in.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be the retention ratio — "
            f"the live IC divided by the backtest IC — as a real number, got "
            f"{value!r} ({type(value).__name__}); the demotion line compares "
            "this figure against the bound, and a ratio that is not one "
            "number leaves the comparison with no operand (feature 326)"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be finite, got {value!r}; "
            "a non-finite ratio would never fall below the bound and a "
            "demoted signal would read as though it were fine, which is the "
            "one direction this feature must never fail in (feature 326)"
        )
    return number


def _require_bound(value: object) -> float:
    """Return ``value`` as a strictly positive band, or refuse it by name.

    The bound is :data:`DEMOTION_BOUND` (40 percent) by default — a constant
    of this module, not configuration — but a bound of zero or less is not a
    band, it is a supervisor that demotes on every signal: every ratio other
    than exactly zero falls below a non-positive bound, so a deployment that
    passed one has configured a demotion rather than a tolerance.  The refusal
    is here, in the value layer, rather than only in the schema's ``CHECK``,
    because the schema's constraint is bypassable and this judgement is the
    one that decides whether a demotion fires at all.
    """
    number = _require_ratio(value, "demotion_bound")
    if number <= 0:
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: demotion_bound must be greater than "
            f"zero, got {value!r}; every ratio other than exactly zero falls "
            "below a non-positive bound, so a bound of "
            f"{value!r} demotes on every signal rather than on a fallen one "
            "(feature 326)"
        )
    return number


def _require_text(value: object, what: str) -> str:
    """Return ``value`` as non-empty stripped text, or refuse it by name.

    The judging process's label, which is a *statement* about who demoted the
    signal — a label that states nothing is a demotion nobody can attribute,
    and the absence of an attribution is the one thing a supervisor's record
    cannot leave an operator to guess at.
    """
    if not isinstance(value, str) or not value.strip():
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: {what} must be non-empty text, got "
            f"{value!r} ({type(value).__name__}) (feature 326)"
        )
    return value.strip()


# -- The record -------------------------------------------------------------------


@dataclass(frozen=True)
class SignalDemotion:
    """One signal demotion: the ratio, the bound, and the moment it was recorded.

    A *value* — frozen, self-describing — carrying the whole of feature 326's
    sentence: this signal's retention ratio fell below ``demotion_bound``, and
    the signal was demoted at ``demoted_at`` — the instant read back from the
    standing row rather than stamped here — by ``supervisor_process_id``.  The
    row was the table's own ``node_id``, and ``changed`` answers whether the
    call that produced this record wrote the row.

    **The arithmetic is re-derived, not trusted.**  ``__post_init__`` refuses a
    record whose ratio is not below its bound, so the comparison on a row is
    never the *only* place the demotion lives: the ratio and the bound beside it
    are the measurement, and this class is the one judgement over both.  That is
    what makes the read path safe — every row :meth:`RiskSignalDemotionStore.
    demotions` hands back is reconstructed through here, so a row edited outside
    this package (a ratio not below the bound it claims to have fallen below, a
    bound that is not a band) fails to reconstruct rather than loading as a
    plausible-looking demotion.  The schema's ``CHECK``s say the same thing at
    the storage layer, but they are the *belt*: SQLite lets ``PRAGMA
    ignore_check_constraints`` past a ``CHECK``, and this validation is the law
    that cannot be bypassed by anything short of editing this file.

    **The bound fired is stored, not re-read from configuration.**  A
    deployment that retunes its :data:`DEMOTION_BOUND` must not silently
    re-judge the demotions it already took: whether *this* demotion was
    justified is decided against the bound in force at the time, which is the
    bound on the row.

    Every field here has a column, and that is deliberate: this value is what a
    row *is*, so a record read back from the table and a record the write path
    returned are the same five facts, and a reader never has to ask which of the
    two it is holding.
    """

    #: The demoted signal's identity — the forward record's ``node_id``, a
    #: UUID.  The table's primary key, and the one row per signal.
    node_id: str
    #: The retention ratio the signal was demoted under — the live IC divided
    #: by the backtest IC, handed over by the forward member's seam.  Unbounded,
    #: and the figure §C10's demotion line acts on.
    ratio: float
    #: The bound the ratio fell below — :data:`DEMOTION_BOUND` (40 percent) by
    #: default, stored on the row so a later retune cannot re-judge it.
    bound: float
    #: When the signal was demoted — the standing row's own instant, read back
    #: from the row rather than stamped here, so the moment and the row are one
    #: fact.  The first demotion's moment on a re-filing.
    demoted_at: datetime
    #: The identity of the process that judged and recorded the demotion (see
    #: :func:`risk.process_identity`) — never accepted from an unlabelled
    #: default, keyword-only to override, so the record names the process that
    #: wrote it exactly as the kill channel's rows do.
    supervisor_process_id: str
    #: Whether the call that produced this record wrote the row.  ``True`` on
    #: the first demotion of a signal; ``False`` on a read-back and on a
    #: re-filing that found the demotion already standing — the distinction
    #: feature 322's kill takes for its own one-shot write, so a re-filed
    #: demotion must not read as a new one.
    changed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _require_uuid(self.node_id, NODE_ID_COLUMN))
        ratio = _require_ratio(self.ratio, "retention_ratio")
        object.__setattr__(self, "ratio", ratio)
        object.__setattr__(self, "bound", _require_bound(self.bound))
        _require_aware(self.demoted_at, "demoted_at")
        object.__setattr__(
            self,
            "supervisor_process_id",
            _require_text(self.supervisor_process_id, "supervisor_process_id"),
        )
        if not (ratio < self.bound):
            raise RiskSignalDemotionError(
                f"{SIGNAL_DEMOTION_CODE}: a signal demotion is a *demoting* "
                f"measurement, and this one's ratio {ratio!r} is not below "
                f"its bound {self.bound!r}; a signal at or above the bound is "
                "held, not demoted, and a row filed for one would report a "
                "demotion that never fired (feature 326)"
            )

    @property
    def summary(self) -> str:
        """One sentence: which signal fell below the bound, and by how much.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the record's own
        facts to live, and an edited row would then disagree with its own
        summary.  The ratio and the bound are rendered so an operator reading a
        log line learns how far the live IC had fallen below the backtest one.
        """
        return (
            f"signal demotion for {self.node_id}: retention ratio "
            f"{self.ratio!r} fell below the {self.bound!r} bound "
            f"({_isoformat_utc(self.demoted_at)}), recorded by "
            f"{self.supervisor_process_id}"
        )


# -- The store --------------------------------------------------------------------


class RiskSignalDemotionStore:
    """Records the signal demotions the supervisor persists, and reads them back.

    Bound to a database URL at construction; construction performs no I/O, so
    composing an application never touches the database and a store costs
    nothing until a demotion is recorded or the table is read.  Each operation
    opens its own connection (creating the schema idempotently if absent), the
    discipline every store in this workspace follows — which is what makes a
    demotion readable from a *different* process than the one that judged it:
    the database, not any process's memory, is the coordination point, and §17
    leaves no other channel to try.

    Two faces, one object: the supervisor calls :meth:`record_demotion`; the
    operator or reconciler calls :meth:`demotion_for` and :meth:`demotions`.
    Neither face holds state beyond the URL, this process's identity and the
    table, so a restarted anything reads the same rows as the process it
    replaced — and appends to them, which is what makes this table a record
    rather than a state.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise RiskStoreError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        self._process_id: str | None = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Mapping[str, str] | None = None
    ) -> RiskSignalDemotionStore | None:
        """The table ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset — absent is a
        discoverable deployment state, not an exception, the stance every store
        in this workspace takes.  What a caller does with the ``None`` is the
        caller's direction to decide, and the two directions this table cuts are
        deliberately split in this module: :func:`demote_on_ic_drop` refuses on
        it, :func:`recorded_demotions` answers an empty tuple on it (see the
        module docstring for why the asymmetry is the feature, not an accident).
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

        The translation :meth:`_connect` performs, exposed so a caller — an
        operator backing the file up before a retune, a test asserting two
        stores share one database — can name the file without opening a
        connection to learn where it is.  Refuses a URL this member cannot
        speak, in :class:`~risk.errors.RiskStoreError`, for the reason
        :func:`_sqlite_path` gives.
        """
        return _sqlite_path(self._database_url)

    @property
    def process_id(self) -> str:
        """This process's identity — the label its demotion rows file under.

        Resolved once, on first use, rather than at construction, so a store
        built during composition does not read the host or the pid before a
        caller has asked it anything; the value cannot change for the life of
        the process, so caching it is a fact about the process rather than
        about the store — and it is the same :func:`risk.process_identity` the
        kill channel files its rows under, so one operator grep splits both
        tables' labels the same way.
        """
        if self._process_id is None:
            self._process_id = process_identity()
        return self._process_id

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
        composition, and a test seeding a demotion into exactly the schema the
        store will read, can prepare the table without reaching for the private
        :meth:`_connect` — the same door :mod:`risk.kill` and
        :mod:`risk.clock_skew` leave open, for the same reason.  Every
        statement is ``CREATE … IF NOT EXISTS``, so a fresh database and one
        this member already prepared take the same path.
        """
        self._connect().close()

    # -- The supervisor's face -------------------------------------------------

    def record_demotion(
        self,
        node_id: object,
        *,
        ratio: object,
        bound: object = DEMOTION_BOUND,
        supervisor_process_id: str | None = None,
    ) -> SignalDemotion | None:
        """Judge the ratio against the bound; if it fell below, persist a demotion.

        Feature 326's whole act, in one call.  The caller hands the signal's
        identity and the retention ratio the forward member computed — nothing
        else.  ``bound`` defaults to :data:`DEMOTION_BOUND` (40 percent), the
        module's own constant; ``supervisor_process_id`` defaults to *this*
        process's identity, read from the kernel rather than accepted from the
        caller, the same label and for the same reason the kill channel's send
        refuses a caller-supplied one.

        **At or above the bound returns ``None`` and touches nothing.**  A ratio
        that is not below the bound is not a demotion — the comparison is
        strictly ``<`` — so this method writes no row and does not so much as
        open the store: the caller's judgement loop can run at whatever rate the
        forward member is spoken to, and a table of every judgement would be a
        table whose demotions an operator has to pick out first.  ``None`` is the
        answer, not an empty record.

        **Below the bound: write the row, first-write-wins.**  ``node_id`` is the
        primary key, so a signal that has been demoted stays demoted, and a
        re-filing of the same signal writes nothing and returns the standing
        demotion with ``changed=False`` — the first demotion's ratio, bound and
        moment are the fact on record, and a later demotion that moved them would
        quietly rewrite when the signal lost its promotion.  The ``INSERT OR
        IGNORE`` is also the race answer: two supervisors demoting the same
        signal concurrently both succeed, the row's first writer is on record,
        and the loser reads the winner's demotion back as the standing one.

        Returns the stored record — the row that landed, not a re-derivation of
        the ask — so a caller logging the demotion holds the fact rather than the
        judgement.  Raises :class:`~risk.errors.RiskSignalDemotionError` for a
        node that is not a signal identity, a ratio that is not a number, or a
        bound that is not a band; :class:`~risk.errors.RiskStoreError` for a row
        that could not be written (an unrecordable demotion is the hole this
        feature exists to fill).
        """
        node = _require_uuid(node_id, NODE_ID_COLUMN)
        ratio_value = _require_ratio(ratio, "retention_ratio")
        bound_value = _require_bound(bound)
        if not (ratio_value < bound_value):
            return None
        sender = (
            self.process_id
            if supervisor_process_id is None
            else _require_text(supervisor_process_id, "supervisor_process_id")
        )
        demoted_at = datetime.now(UTC)
        try:
            with closing(self._connect()) as connection, connection:
                cursor = connection.execute(
                    f"""
                    INSERT OR IGNORE INTO {RISK_SIGNAL_DEMOTION_TABLE} (
                        node_id, retention_ratio, demotion_bound,
                        demoted_at, supervisor_process_id
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        node,
                        ratio_value,
                        bound_value,
                        _isoformat_utc(demoted_at),
                        sender,
                    ),
                )
                changed = cursor.rowcount == 1
                row = self._row_for(connection, node)
        except sqlite3.IntegrityError as exc:
            # Either another process recorded this same signal between the
            # check and this insert, or the table refused the row for a reason
            # no re-read will satisfy.  The two are told apart by asking the
            # table, not by trusting the exception: one signal is one demotion,
            # so a row for this signal *is* this demotion's record and the loser
            # hands it back rather than reporting a conflict where there is
            # none.  No row means the refusal was something else -- a constraint
            # a tampered table grew, a trigger -- and it belongs to this
            # feature's vocabulary, not the driver's (see this method's
            # docstring for why the re-read goes through a plain connection).
            raced = self._row_for(self._connect(), node)
            if raced is None:
                raise RiskSignalDemotionError(
                    f"{SIGNAL_DEMOTION_CODE}: the signal demotion of {node} at "
                    f"{_isoformat_utc(demoted_at)} could not be recorded: "
                    f"{exc}. The demotion stands -- the row is the record of "
                    "why, and a demotion with nothing on disk to account for it "
                    "is indistinguishable from a signal that was never judged "
                    "(feature 326)"
                ) from exc
            return self._demotion_from_row(raced, changed=False)
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not record the demotion of {node} at "
                f"{_isoformat_utc(demoted_at)}: {exc}"
            ) from exc
        if row is None:
            # The write reported success and the read inside the same
            # transaction found nothing -- the one state that cannot be true of
            # a committed INSERT, and the one a demotion must never shrug into a
            # quiet return: the demotion did not land.
            raise RiskStoreError(
                "the signal demotion vanished inside its own write; a "
                "demotion that cannot be read back has not been recorded, and "
                "the signal this record was about to demote still holds its "
                "promotion (feature 326)"
            )
        return self._demotion_from_row(row, changed=changed)

    # -- The reader's face ----------------------------------------------------

    def demotion_for(self, node_id: object) -> SignalDemotion | None:
        """The standing demotion for one signal, or ``None`` when it holds none.

        The reader's primary question — *has this signal been demoted?* —
        answered by reconstructing the row through :class:`SignalDemotion`'s own
        validation, so a row edited outside this package fails to reconstruct
        rather than loading as a plausible-looking demotion.  ``changed`` is
        ``False`` on every read-back; the bit names the call that wrote the row,
        and a read wrote nothing.
        """
        node = _require_uuid(node_id, NODE_ID_COLUMN)
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    f"SELECT {_COLUMNS} FROM {RISK_SIGNAL_DEMOTION_TABLE} "
                    "WHERE node_id = ?",
                    (node,),
                ).fetchone()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the standing demotion for {node}: {exc}"
            ) from exc
        if row is None:
            return None
        return self._demotion_from_row(row, changed=False)

    def demotions(self) -> tuple[SignalDemotion, ...]:
        """Every recorded demotion, ordered by signal identity — the read.

        The whole table, in the order of the signal identity, so a reconciler
        sweeps the demotions deterministically.  Fails with
        :class:`~risk.errors.RiskStoreError` when the table could not be read,
        and with :class:`~risk.errors.RiskSignalDemotionError` when a stored row
        is not a demotion this store could have written — the refusal, not a
        skip: a skipped row is a demotion an operator would never learn about.
        """
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"SELECT {_COLUMNS} FROM {RISK_SIGNAL_DEMOTION_TABLE} "
                    "ORDER BY node_id"
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            raise RiskStoreError(
                f"could not read the signal demotions: {exc}"
            ) from exc
        return tuple(self._demotion_from_row(row, changed=False) for row in rows)

    # -- The row plumbing ----------------------------------------------------

    def _row_for(
        self, connection: sqlite3.Connection, node: str
    ) -> tuple | None:
        """The row for one signal, or ``None`` — the primary-key read.

        The lookup key is the ``node_id`` primary key, compared in the table's
        own stored spelling, so the retry law and this read agree on what "the
        same signal" means by construction.  Reached through the same
        connection the insert ran on, so the write and its verification cannot
        disagree about what a row is.
        """
        cursor = connection.execute(
            f"SELECT {_COLUMNS} FROM {RISK_SIGNAL_DEMOTION_TABLE} WHERE node_id = ?",
            (node,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    def _demotion_from_row(self, row: tuple, *, changed: bool) -> SignalDemotion:
        """Rebuild one stored row, refusing a value no demotion can be.

        The refusal is the point: this table is written by this store, but
        SQLite will accept anything another tool inserts — and will let
        ``PRAGMA ignore_check_constraints`` past its own ``CHECK``\\ s — so a row
        wearing a moment no parser accepts, a ratio not below the bound it claims
        to have fallen below, or a bound that is not a band would otherwise read
        back as a demotion nobody recorded.  The value layer is where that
        judgement lives (see :class:`SignalDemotion`); this method is what makes
        the refusal *findable*, naming the signal it came from so an operator
        gets the row to repair rather than a complaint about a value with no
        address.
        """
        node_id, ratio_raw, bound_raw, demoted_at_raw, sender = row
        try:
            demoted_at = datetime.fromisoformat(demoted_at_raw)
        except (TypeError, ValueError) as exc:
            raise RiskSignalDemotionError(
                f"{SIGNAL_DEMOTION_CODE}: the signal demotion row for "
                f"{node_id!r} carries demoted_at {demoted_at_raw!r}, which is "
                "not an ISO 8601 moment this store can order a sweep by "
                "(feature 326)"
            ) from exc
        try:
            return SignalDemotion(
                node_id=node_id,
                ratio=ratio_raw,
                bound=bound_raw,
                demoted_at=demoted_at,
                supervisor_process_id=sender,
                changed=changed,
            )
        except RiskSignalDemotionError as refusal:
            # The value layer validates the row, and this re-raise is what makes
            # the refusal *findable*: ``SignalDemotion`` sees one row and cannot
            # know which one, while a reader holding the store can name the
            # signal the bad row came from -- so an operator gets the row to
            # repair rather than a complaint about a value with no address.
            raise RiskSignalDemotionError(
                f"{refusal} — the row this came from is the demotion for "
                f"{node_id!r}, recorded by {sender!r} at {demoted_at_raw!r} "
                "(feature 326)"
            ) from refusal


# -- The module-level spellings ---------------------------------------------------


def demote_on_ic_drop(
    node_id: object,
    *,
    ratio: object,
    bound: object = DEMOTION_BOUND,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
    supervisor_process_id: str | None = None,
) -> SignalDemotion | None:
    """Judge a signal's ratio against the bound, opening the record from the env.

    The supervisor's one call: resolve the table from ``database_url``, else
    from ``DATABASE_URL``, then hand the signal and the ratio to
    :meth:`RiskSignalDemotionStore.record_demotion`.  Returns the stored record
    when the ratio fell below the bound and ``None`` when it did not — a ratio
    at or above the bound is not a demotion, so this spelling has the same two
    answers as the store it delegates to, and neither answer opens a store that
    is not configured when the signal is fine.

    A deployment that names no store is refused *by name* once the ratio has
    been judged to have fired, because from that moment the signal is demoted
    and nothing would record why: the demotion would be judged (the ratio is in
    hand) and the row accounting for it would go nowhere, leaving an operator a
    demoted signal they cannot account for — the hole this feature exists to
    fill.  A ratio at or above the bound never reaches that refusal,
    deliberately: there is no demotion to account for, so an unconfigured
    deployment that merely judges is not an error.  The reader's direction
    answers an empty tuple on the same absence; see :func:`recorded_demotions`.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        # Judge the ratio before demanding a store, so the no-store refusal is
        # about a *fired* demotion, not a signal that was never judged.
        _require_uuid(node_id, NODE_ID_COLUMN)
        ratio_value = _require_ratio(ratio, "retention_ratio")
        bound_value = _require_bound(bound)
        if not (ratio_value < bound_value):
            return None
        raise RiskSignalDemotionError(
            f"{SIGNAL_DEMOTION_CODE}: demote_on_ic_drop judges feature 326's "
            f"signal demotion and nothing names a store: {DATABASE_URL_ENV} is "
            f"unset (and no database_url was supplied), so the demotion could "
            f"not be recorded. The signal's live IC has fallen below its "
            f"backtest one, and a demotion that left no record of it is one the "
            f"next cycle cannot tell from a signal that was never judged"
        )
    return RiskSignalDemotionStore(url).record_demotion(
        node_id,
        ratio=ratio,
        bound=bound,
        supervisor_process_id=supervisor_process_id,
    )


def recorded_demotions(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[SignalDemotion, ...]:
    """The recorded signal demotions — the reader's spelling.

    Every demotion the named table holds, ordered by signal identity.  A
    deployment that names no store answers an empty tuple: recording refuses
    without a store, so a deployment that names none holds no demotions to read,
    and the empty answer is the truthful one — the same *"no store, no status"*
    stance :func:`risk.require_orders_allowed` takes, kept distinct because a
    caller that mistook an unconfigured deployment for an empty record would
    read a table with no demotions in it and call it a set of signals that never
    decayed.
    """
    source = os.environ if env is None else env
    url = (
        database_url
        if database_url is not None
        else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return ()
    return RiskSignalDemotionStore(url).demotions()
