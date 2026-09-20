"""Halting dreaming on a determinism break — feature 143's decision.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 143: *System
halts dreaming when the canary score differs from the recorded constant by more
than 1e-12, which emits a determinism_broken alert.*  docs/nullius-tech-
architecture.md §12 line 677 spells the whole rule as code::

    if abs(score - CANARY_EXPECTED) > 1e-12:
        halt_dreaming()
        alert("replay determinism broken — pool untrustworthy")

and :mod:`canary._replay` deliberately stopped at the ``if``: the replay is the
*measurement* — the score, the recorded constant, the deviation, the ``1e-12``
band, carried as a value — because a replay that also halted would be a canary
that decided its own alert.  This module is the two statements under the
``if``.  It is the one place in the workspace where "the canary broke" becomes
a consequence, and everything here follows from refusing to let that
consequence be anything less than loud, persisted, and irreversible.

Three decisions shape the module, and each is a reading of one word in the
feature: *halts*.

**The halt is a persisted state, and the alert is its emission.**  §12's
snippet makes two calls, and the deployment this workspace assembles needs both
halves of each: ``halt_dreaming()`` must survive the process that pronounced it
(a halt that died with the nightly runner would leave the next night dreaming
over a pool §12 has already called untrustworthy), and ``alert(...)`` must reach
an operator as a thing that can be caught, logged and dispatched by type.  So
:func:`halt_dreaming` writes one row — the break, its arithmetic and its
instant, keyed by the frozen pair's content fingerprint — and then raises
:class:`CanaryDeterminismBrokenError` carrying that record on its ``halt``
attribute.  Raising *is* the emission and the record *is* the payload, the same
stance :mod:`snapshot` takes for its corruption alert; the two are one act
because the feature's own clause makes them one — *halts dreaming …, which
emits a determinism_broken alert*.  The order is load-bearing: the row is
written before the error is raised, so a caller that catches the alert to keep
reporting (a monitor sweeping every pair before paging) still leaves the halt
on record.  §12's sentence is the error's own text:
:data:`HALT_MESSAGE` is line 681 verbatim, so an operator reading a stack trace
reads the same words the architecture spells.

**The comparison is §12's own, read off the replay's result — never re-decided
here.**  The ``1e-12`` lives once, as :data:`canary.DEFAULT_TOLERANCE`, placed
in :mod:`canary._replay` precisely so that this module's halt and that module's
``within_tolerance`` read one threshold ("an operator auditing why dreaming
halted finds the ``1e-12`` in exactly one place").  So the halt is pronounced on
a :class:`~canary.CanaryReplayResult` whose verdict is already carried, under
two guards this module adds and the result cannot supply for itself: the result
must have been measured under :data:`~canary.DEFAULT_TOLERANCE` — a halt
pronounced under any other band, wider *or* narrower, would be a §12 line
nobody wrote, and §12's determinism-break row says widening "is never the fix"
— and the constant the result compared must be the pair's own
``recorded_score``, so a halt cannot be attributed to a pair whose constant was
never the one on trial.  What this module refuses to do is recompute the score
or re-implement the comparison: :func:`canary.replay_pair` is the one
implementation of the score the package's one-provenance rule allows, and a
halt module with a second arithmetic in it would be the drift the canary exists
to catch, wearing the auditor's badge.

**The halt is monotone, and the first break is the fact on record.**  There is
no ``resume_dreaming``, no ``clear``, no path that writes a halt row away — in
this module or in its schema.  §15's recovery row for "Replay
non-determinism" is *Halt dreaming; bisect the image diff*: resuming is an
operator's act performed in the environment, not a call this package could
make, and a halt that code could clear would make "was this score produced
after the break?" unanswerable at exactly the moment feature 144 asks it — the
void-marker feature keys on the break's ``detected_at`` instant, so the record
that answers it has to be the *first* break, not the latest observation.  That
is why a re-run over an already-halted pair writes nothing and reports
``changed=False`` where a re-freeze refreshes its row: a freeze's semantics is
"the latest freeze wins", but a halt's semantics is "the break that first
stopped dreaming is the fact", and moving ``detected_at`` forward on a later
night would quietly shrink the affected window feature 144 exists to widen.
A second, different pair breaking writes a second row — the audit holds every
break — while :meth:`CanaryHaltStore.halted`, the state every dreamer must ask
about, stays the plain §12 reading: any break on record, dreaming halted.

**The guard is a read, and the pool is never edited.**  :meth:`CanaryHaltStore.
require_dreaming_allowed` is the read-time refusal the dreaming cycle's
entrypoint consults — the same shape :mod:`tripwires.excise` gives the replay
pool: the evidence (the halt rows) is never deleted from, and the refusal is
derived from it, so the halt holds no matter which path set it and the audit
stays answerable.  A caller that dreams without asking has not been un-halted;
it has skipped the one door §12 leaves open, and the guard's refusal carries
the record so the skip cannot be mistaken for permission.

What this module deliberately does **not** do is decide the void marker, record
scores, or touch the pool.  Feature 144 voids every score produced after the
break — this module's row is what tells it *after when*, and a halt that also
voided would be two features wearing one verb, the same coupling the replay
refuses.  The recorded constant is written by the replay path against the
reference store (feature 141's tables), not here: this module's one table is
:data:`HALT_TABLE`, created idempotently beside the code that reads it, the
same member-owned-table stance :mod:`tripwires.poison` takes for its audit
rows.  And like every store in this workspace, construction performs no I/O —
the path is resolved on first use, so composing the application never opens a
database, and the factory's scan pays nothing for importing this module.

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime``, ``math`` and
``urllib.parse``; no third-party import at module scope, for the reason the
whole category states: this package is imported on every factory scan,
including the replay path §1 keeps away from anything that could perturb it,
and the halt must not be the member that made that path expensive.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ._errors import CanaryError
from ._reference import CanaryReferencePair, _validated_hash
from ._replay import DEFAULT_TOLERANCE, CanaryReplayResult

__all__ = [
    "DETERMINISM_BROKEN",
    "HALT_MESSAGE",
    "HALT_STORE_COMPONENT_NAME",
    "HALT_TABLE",
    "CanaryDeterminismBrokenError",
    "CanaryHaltStore",
    "DreamHalt",
    "build_halt_store",
    "determinism_broken_error",
    "halt_dreaming",
    "require_dreaming_allowed",
]

#: The alert's kind — the spec's own spelling, and the word an operator or a
#: monitor dispatches on.  app_spec.xml feature 143: *"which emits a
#: determinism_broken alert"*.  Not a free-form message field: the alert this
#: feature emits has exactly one kind, and a halt row carrying any other word
#: would be a row no reader of ``determinism_broken`` could find.
DETERMINISM_BROKEN = "determinism_broken"

#: §12 line 681's alert text, verbatim — *"replay determinism broken — pool
#: untrustworthy"*.  The sentence §12 spells for the ``alert(...)`` call under
#: the ``if``, carried as the one spelling so the error this module raises, the
#: row it writes and the architecture document all say the same words.  A
#: paraphrase here would be a second place for the alert's meaning to drift.
HALT_MESSAGE = "replay determinism broken — pool untrustworthy"

#: This member's own table — one row per halted pair, the state every dreamer
#: asks about and the audit feature 144 keys on.  It is *not* a column on the
#: reference store's tables and it is not the reference pair's row: a
#: determinism break is a fact about the *deployment* (the machine drifted),
#: not about the pair (the pair is exactly what it froze as), and widening
#: feature 141's four tables with a halt column would give the freeze path a
#: decision the replay path owns — the same coupling both modules refuse.
HALT_TABLE = "canary_dream_halt"

#: The component name this member registers its halt store under — a third
#: name rather than a third component under :data:`canary.CANARY_COMPONENT_NAME`,
#: the convention :mod:`tripwires` states for its own three and this member
#: states for its second: the pin sweep answers *is the deployment pinned?*,
#: the reference store answers *what is the frozen pair?*, and this answers
#: *is dreaming halted?* — three different questions on three different
#: lifecycles, and a caller asking for one must not be handed another.
HALT_STORE_COMPONENT_NAME = "canary-dream-halt"

#: The environment variable naming the relational store — the one spelling
#: every store in this workspace already uses (the ledger's, the reference
#: store's, the repository-level conftest's), restated here so each store
#: states its own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

#: ``canary_dream_halt``'s DDL, created idempotently beside the code that reads
#: it — the same member-owned-table stance :mod:`tripwires.poison` takes for
#: ``tripwire_poison``, and deliberately *not* a migration: a migration is
#: loaded by path by its runner and orders against every other version file,
#: while this table has exactly one writer and one reader, both in this module.
#: One row per halted pair, keyed by the pair's content fingerprint — a pair is
#: halted once, and the first break is the row that stays (see the module
#: docstring for why a refresh would shrink feature 144's window).  The alert's
#: kind and §12's arithmetic travel on the row so a reader can recompute the
#: decision from the record alone, the same discipline the poison audit rows
#: and feature 125's verdict both state: a halt is irreversible and must be
#: auditable from what was written.
_HALT_SCHEMA = f"""
-- Feature 143: a determinism break, persisted as the halt of dreaming.  One row
-- per halted pair, keyed by the content fingerprint -- the pair is exactly what
-- it froze as (feature 141's hashes prove it), so what broke is the machine, and
-- the row names the pair the break was observed against.
--
-- `detected_at` is the instant the nightly replay stated the break -- the datum
-- feature 144 keys its void markers on ("every score produced after a detected
-- determinism break"), which is why a later observation over the same pair
-- writes nothing: moving the instant forward would quietly shrink the affected
-- window.  `halted_at` is when this row was written; `alert_kind` is the spec's
-- own word, carried so the row is the alert as well as the state.
CREATE TABLE IF NOT EXISTS {HALT_TABLE} (
    code_hash      CHAR(64) NOT NULL,  -- the broken pair's policy identity
    tree_hash      CHAR(64) NOT NULL,  -- the broken pair's tree identity
    alert_kind     TEXT NOT NULL,      -- 'determinism_broken', the spec's spelling
    score          REAL NOT NULL,      -- the replayed score
    recorded_score REAL NOT NULL,      -- the recorded constant it broke from
    deviation      REAL NOT NULL,      -- abs(score - recorded_score)
    tolerance      REAL NOT NULL,      -- §12's 1e-12, the band that was exceeded
    detected_at    TEXT NOT NULL,      -- when the nightly replay stated the break
    halted_at      TEXT NOT NULL,      -- when the halt was written (ISO-8601 UTC)
    PRIMARY KEY (code_hash, tree_hash)
);
"""

#: The columns of :data:`HALT_TABLE`, in the order the insert names them and the
#: order the read-back unpacks them.  Spelled once so the write and the read
#: cannot drift apart on a column order — the failure a positional
#: ``SELECT *`` invites.
_COLUMNS = (
    "code_hash, tree_hash, alert_kind, score, recorded_score, deviation, "
    "tolerance, detected_at, halted_at"
)


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC.

    Second resolution with microseconds dropped rather than rounded, the same
    spelling :func:`canary._reference_store._utc_now` and
    :func:`ledger.record.utc_now` use, restated here rather than imported so
    this module states its own contract: the stamps order breaks against
    freezes, and dropping — not rounding — keeps a stamp never *after* the
    instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def _validated_instant(name: str, value: Any) -> datetime:
    """A timezone-aware instant — refused otherwise, naming the field.

    The break's instants are load-bearing downstream: ``detected_at`` is the
    datum feature 144's void markers key on, and a naive stamp would compare
    against nothing when that question is asked.  Refused here, at
    construction, where the record that carries it is the one named.
    """
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CanaryError(
            f"a dream halt's {name} must be a timezone-aware datetime, got "
            f"{value!r}; the instant orders the break against the freezes it "
            "broke from, and a naive stamp would raise far from the write "
            "that set it"
        )
    return value


# -- The record -----------------------------------------------------------------


@dataclass(frozen=True)
class DreamHalt:
    """One determinism break: the halt, and the alert it emits.

    A *value* — frozen, self-describing — carrying both halves of feature 143's
    sentence: the state (a pair is halted, from ``detected_at`` on) and the
    alert (``alert_kind`` is the spec's :data:`DETERMINISM_BROKEN`, and
    :attr:`summary` spells §12's arithmetic).  It is what
    :meth:`CanaryHaltStore.halt` writes and returns, what the raised
    :class:`CanaryDeterminismBrokenError` carries on its ``halt`` attribute,
    and what :meth:`CanaryHaltStore.current_halt` reads back — one type for all
    three, so the record an operator pages on and the row the store holds
    cannot be two things that disagree.

    Validated in :meth:`__post_init__` rather than only where it is built,
    because the read path reconstructs one from a stored row: a row edited
    outside this package — a deviation that does not equal its own score and
    constant, a tolerance that is not §12's, a halt within its own band — fails
    to reconstruct rather than loading as a plausible-looking break, the same
    defence :class:`~canary.CanaryReferencePair` applies to its hashes, and for
    the same reason: what downstream trusts is the stored record, and a store
    that could hand back a halt disagreeing with its own arithmetic would
    launder a tamper into an operator's page.

    ``changed`` answers the question a re-run asks — whether *this* call wrote
    the row.  The first break writes it (``True``); a later observation over
    the same pair finds it already held and reports ``False`` while the stored
    record — the *first* break, whose ``detected_at`` feature 144 keys on — is
    the one returned.  The distinction is the one §8's ``tree_appended``
    idiom draws for the evaluator's own one-shot write: a re-observed halt must
    not read as a new one.
    """

    #: The broken pair's policy identity — :attr:`~canary.CanaryPolicy.code_hash`.
    code_hash: str
    #: The broken pair's tree identity — :attr:`~canary.CanaryTree.tree_hash`.
    tree_hash: str
    #: The alert's kind.  Always :data:`DETERMINISM_BROKEN`; carried on the
    #: record so a reader dispatching on the alert kind reads it from the thing
    #: itself, and so a stored row wearing any other word fails to reconstruct.
    alert_kind: str
    #: The score the nightly replay produced.
    score: float
    #: The recorded constant the score broke from.
    recorded_score: float
    #: ``abs(score - recorded_score)`` — the distance that exceeded the band.
    deviation: float
    #: The band that was exceeded — §12's ``1e-12``, never any other.
    tolerance: float
    #: When the nightly replay stated the break.  The datum feature 144's void
    #: markers key on: "every score produced *after* a detected determinism
    #: break".
    detected_at: datetime
    #: When the halt was written to the store.
    halted_at: datetime
    #: Whether the call that produced this record wrote the row.  ``False`` on
    #: a read-back and on a re-observation that found the halt already held.
    changed: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code_hash", _validated_hash("code_hash", self.code_hash)
        )
        object.__setattr__(
            self, "tree_hash", _validated_hash("tree_hash", self.tree_hash)
        )
        if self.alert_kind != DETERMINISM_BROKEN:
            raise CanaryError(
                f"a dream halt's alert_kind is the spec's "
                f"{DETERMINISM_BROKEN!r}, got {self.alert_kind!r}; the halt "
                "this feature writes emits exactly one kind of alert, and a "
                "record carrying any other word is a row no reader of "
                "determinism_broken could find"
            )
        for name, value in (
            ("score", self.score),
            ("recorded_score", self.recorded_score),
            ("deviation", self.deviation),
            ("tolerance", self.tolerance),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise CanaryError(
                    f"a dream halt's {name} must be a real number, got "
                    f"{value!r}; the halt is pronounced on §12's arithmetic, "
                    "and a non-number is not a term the 1e-12 comparison "
                    "could reach"
                )
            if not math.isfinite(float(value)):
                raise CanaryError(
                    f"a dream halt's {name} is not finite ({value!r}); a NaN "
                    "or ±inf would reach the halt record dressed as the "
                    "arithmetic the decision was made on — and §12's "
                    "`abs(score - CANARY_EXPECTED) > 1e-12` is False for a "
                    "NaN, so a NaN is a broken reference, not a break"
                )
        if self.tolerance != DEFAULT_TOLERANCE:
            raise CanaryError(
                f"a dream halt's tolerance is §12's {DEFAULT_TOLERANCE!r}, got "
                f"{self.tolerance!r}; the halt is the second statement under "
                "line 677's `if`, pronounced under the one threshold the "
                "workspace spells once, and a halt measured under any other "
                "band — wider or narrower — is a §12 line nobody wrote "
                "(§12: widening the canary tolerance is never the fix)"
            )
        expected = abs(float(self.score) - float(self.recorded_score))
        if float(self.deviation) != expected:
            raise CanaryError(
                f"a dream halt's deviation ({self.deviation!r}) does not equal "
                f"abs(score - recorded_score) ({expected!r}); the deviation is "
                "the distance the halt is pronounced on, and a record whose "
                "own arithmetic disagrees with itself would lie to the "
                "operator reading it"
            )
        if not float(self.deviation) > float(self.tolerance):
            raise CanaryError(
                f"a dream halt's deviation ({self.deviation!r}) does not "
                f"exceed the tolerance ({self.tolerance!r}); §12's line is "
                "`abs(score - CANARY_EXPECTED) > 1e-12`, strict, and a halt "
                "within its own band would be a stop dreaming was never "
                "told to make"
            )
        object.__setattr__(
            self, "detected_at", _validated_instant("detected_at", self.detected_at)
        )
        object.__setattr__(
            self, "halted_at", _validated_instant("halted_at", self.halted_at)
        )
        if not isinstance(self.changed, bool):
            raise CanaryError(
                f"changed must be a bool, got {self.changed!r} "
                f"({type(self.changed).__name__}); whether this call wrote the "
                "row is one bit, and a truthy-looking non-bool is the value "
                "that would silently misreport a re-observation as a first "
                "break"
            )

    @property
    def summary(self) -> str:
        """One sentence: which pair broke, and the arithmetic it broke on.

        Composed rather than stored, because every part of it is already a
        field — a stored copy would be a second place for the record's own
        numbers to live, and an edited row would then disagree with its own
        summary.  The hashes are spelled in full so an operator reading a log
        line can grep the reference store by them: "which pair broke" is the
        first question §15's recovery ("bisect the image diff") needs answered.
        """
        return (
            f"the canary pair (code_hash={self.code_hash}, "
            f"tree_hash={self.tree_hash}) replays to {self.score}, against the "
            f"recorded constant {self.recorded_score}: deviation "
            f"{self.deviation} exceeds the {self.tolerance} tolerance"
        )

    def to_payload(self) -> dict[str, Any]:
        """The halt as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, so a stored row, a rendered
        mapping and a structured log record name the same things the same way —
        and the instants render as the ISO-8601 text the table stores, so a
        round trip through this mapping and back is the same instant.
        """
        return {
            "code_hash": self.code_hash,
            "tree_hash": self.tree_hash,
            "alert_kind": self.alert_kind,
            "score": self.score,
            "recorded_score": self.recorded_score,
            "deviation": self.deviation,
            "tolerance": self.tolerance,
            "detected_at": self.detected_at.isoformat(),
            "halted_at": self.halted_at.isoformat(),
            "changed": self.changed,
        }


# -- The alert ------------------------------------------------------------------


class CanaryDeterminismBrokenError(CanaryError):
    """§12's ``determinism_broken`` alert, made catchable by type.

    app_spec.xml feature 143: *"which emits a determinism_broken alert."* This
    is that alert.  :func:`halt_dreaming` raises it after the halt is
    persisted — raising is the emission, the record is the payload, the stance
    :mod:`snapshot` takes for its corruption alert — and
    :meth:`CanaryHaltStore.require_dreaming_allowed` raises it again, carrying
    the stored record, when a caller reaches for dreaming while a break is on
    record.  Two raise sites, one type: both are the sentence §12 spells, and a
    caller catching the alert by name catches the halt's every spelling.

    Deliberately its own subclass rather than a fold into
    :class:`~canary.CanaryImageError` (a moved pin) or
    :class:`~canary.CanaryReproducibilityError` (divergent bytes from two runs
    of one signal): the three are three different breaks of §12's contract
    with three different repairs, and this is the one §15's recovery table
    names — *Replay non-determinism: halt dreaming; bisect the image diff*.  A
    caller holding more than one needs the split at the ``except``, because
    re-pinning an image is not bisecting a diff.  A subclass of
    :class:`~canary.CanaryError`, so the package's single ``except`` still
    catches every failure of the canary's assertions, this one included.

    The exception carries the structured record of what was found:
    :attr:`halt` is the :class:`DreamHalt` (the pair, the arithmetic, the
    instants), and the message is §12's own alert text
    (:data:`HALT_MESSAGE`, line 681 verbatim) plus the record's summary —
    built through :func:`determinism_broken_error` at the break, so the
    record and the message cannot drift apart.
    """

    #: The structured record of the break.  Present on every error this module
    #: raises; ``None`` only on a hand-built error with no record behind it.
    halt: Optional[DreamHalt]

    def __init__(self, message: str, halt: Optional[DreamHalt] = None) -> None:
        super().__init__(message)
        self.halt = halt


def determinism_broken_error(halt: DreamHalt) -> CanaryDeterminismBrokenError:
    """Build the alert from its record — the one spelling of the emission.

    §12's alert text plus the record's own summary, so the page an operator
    reads and the row the store holds say the same thing — the same reason
    :func:`snapshot.corruption_error` exists rather than letting every caller
    compose its own message.  The consequence is stated in §15's own words
    (bisect the image diff), because the operator reading it is deciding what
    to do at three in the morning.
    """
    if not isinstance(halt, DreamHalt):
        raise CanaryError(
            f"determinism_broken_error takes a DreamHalt — the record of the "
            f"break — got {halt!r}; the alert's message is composed from the "
            "record's own fields, and an error built from anything else would "
            "be an emission with no record behind it"
        )
    return CanaryDeterminismBrokenError(
        f"{HALT_MESSAGE} ({halt.summary}); dreaming is halted — §15's recovery "
        "is to bisect the image diff before dreaming resumes",
        halt,
    )


# -- The store ------------------------------------------------------------------


def _sqlite_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.
    A non-SQLite scheme is refused loudly — the Postgres store arrives with
    the migration member — and a pathless (in-memory) URL is refused too: an
    in-memory database dies with the connection that opened it, and a halt
    that vanished would leave the next night dreaming over a pool §12 has
    already called untrustworthy.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CanaryError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CanaryError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a "
            "halted dream must stay halted after the night that halted it"
        )
    return Path(path)


class CanaryHaltStore:
    """§12's halt, persisted: one row per broken pair, and the guard that reads it.

    Constructed with the database URL it writes to; :meth:`halt` is feature
    143's persistence half — validate the break, write the row, read it back —
    and the three reads (:meth:`halted`, :meth:`current_halt`,
    :meth:`require_dreaming_allowed`) are what the rest of the system consults,
    the way the replay pool consults its poison marks.  The class resolves its
    path lazily, so constructing one performs no I/O — composition-time work
    must not touch the disk, the contract every store in this workspace states.

    The store holds no score and no constant of its own: every number on a halt
    row arrived on the :class:`~canary.CanaryReplayResult` the caller handed
    :meth:`halt`, and is re-checked against that result's own arithmetic on
    the way in and against the row's own fields on the way out.
    """

    def __init__(self, database_url: str) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CanaryError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # Resolved on first use rather than at construction: building the
        # store is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["CanaryHaltStore"]:
        """The halt store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes
        no halt component — a discoverable state, not an exception — while the
        nightly runner that must halt dreaming is the caller that must not
        find itself in it.
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
        """The SQLite file backing this store, resolved on first use.

        Nothing is created at construction — the URL is translated (and a URL
        this member cannot speak is refused by name) the first time an
        operation needs it.
        """
        if self._path is None:
            self._path = _sqlite_path(self._database_url)
        return self._path

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure the halt table exists, idempotently.

        ``CREATE TABLE IF NOT EXISTS`` — the contract every store in this
        workspace states: a fresh database and an existing one take the same
        path, and the halt table lives beside the only code that reads it (see
        :data:`HALT_TABLE`).  The caller owns the connection; use it as a
        context manager to commit.
        """
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(_HALT_SCHEMA)
        return connection

    # -- Feature 143: the halt ----------------------------------------------

    def halt(
        self,
        pair: CanaryReferencePair,
        result: CanaryReplayResult,
        *,
        detected_at: Optional[datetime] = None,
        halted_at: Optional[datetime] = None,
    ) -> DreamHalt:
        """Persist one determinism break as the halt of dreaming.

        The persistence half of feature 143, stated as an explicit door: the
        break is validated, the row is written, and the stored record is read
        back and returned.  Nothing is raised here — the emission is
        :func:`halt_dreaming`'s, which calls this and then raises the alert —
        so a monitor that wants the record as data can take it from this door
        and keep reporting, exactly the split :mod:`snapshot` draws between
        ``verify`` (returns the alert) and ``open`` (raises it).

        Refuses, in this order, and each refusal names what it is about:

        1. a ``pair`` that is not a :class:`~canary.CanaryReferencePair` or a
           ``result`` that is not a :class:`~canary.CanaryReplayResult`
           (:class:`~canary.CanaryError`) — the halt is a fact about one pair's
           one replay, and half of either is a break with nothing to name;
        2. a result measured under any tolerance but §12's
           :data:`~canary.DEFAULT_TOLERANCE` (:class:`~canary.CanaryError`) —
           the halt is line 677's second statement and cannot be pronounced
           under a band line 677 did not write;
        3. a result that did not break (:class:`~canary.CanaryError`) — the
           same stance :mod:`tripwires.poison` takes for a verdict that passed:
           this door says *write this break down*, and a store that accepted a
           passing result would halt dreaming on a canary that held;
        4. a result whose recorded constant is not the pair's own
           (:class:`~canary.CanaryError`) — the halt is attributed to a pair,
           and the constant on trial must be the one that pair carries.

        A pair already halted writes nothing and returns the stored record
        with ``changed=False``: the *first* break is the fact on record — its
        ``detected_at`` is the instant feature 144's void markers key on, and
        a later observation that moved it would quietly shrink the affected
        window (see the module docstring).
        """
        if not isinstance(pair, CanaryReferencePair):
            raise CanaryError(
                f"halt takes a CanaryReferencePair — the pair the break was "
                f"observed against — got {pair!r}; a halt is a fact about one "
                "frozen pair, and a break with no pair names nothing an "
                "operator could bisect"
            )
        if not isinstance(result, CanaryReplayResult):
            raise CanaryError(
                f"halt takes a CanaryReplayResult — the replay's own score, "
                f"constant, deviation and verdict — got {result!r}; the halt "
                "is pronounced on the comparison the replay already carried, "
                "and a caller-supplied verdict would be a second arithmetic"
            )
        if result.tolerance != DEFAULT_TOLERANCE:
            raise CanaryError(
                f"a halt is pronounced under §12's {DEFAULT_TOLERANCE!r}, got "
                f"a result measured under {result.tolerance!r}: the halt is "
                "line 677's second statement under its own `if`, and a "
                "result measured under any other band — wider or narrower — "
                "is a comparison §12 never wrote (widening the canary "
                "tolerance is never the fix)"
            )
        if not result.broken:
            raise CanaryError(
                "there is nothing to halt on: the replay reports "
                f"{result.message}; this door writes a determinism break, and "
                "a store that accepted a passing result would halt dreaming "
                "on a canary that held"
            )
        if result.recorded_score != pair.recorded_score:
            raise CanaryError(
                "the result's recorded constant "
                f"({result.recorded_score!r}) is not the pair's own "
                f"({pair.recorded_score!r}): the halt is attributed to a "
                "pair, and the constant on trial must be the one that pair "
                "carries — a halt named against a constant the pair never "
                "held would indict the wrong reference"
            )
        detected = _utc_now() if detected_at is None else detected_at
        written = _utc_now() if halted_at is None else halted_at
        with closing(self._connect()) as connection, connection:
            existing = self._read_row(connection, pair)
            if existing is not None:
                # First write wins.  A later observation over an already
                # halted pair is the same halt still holding: the stored
                # detected_at is the datum feature 144 keys on, and moving it
                # forward would shrink the affected window.  The stored record
                # — not the new observation — is what the caller gets back.
                return self._record_from_row(existing, changed=False)
            candidate = DreamHalt(
                code_hash=pair.policy.code_hash,
                tree_hash=pair.tree.tree_hash,
                alert_kind=DETERMINISM_BROKEN,
                score=result.score,
                recorded_score=result.recorded_score,
                deviation=result.deviation,
                tolerance=result.tolerance,
                detected_at=detected,
                halted_at=written,
                changed=True,
            )
            connection.execute(
                f"INSERT INTO {HALT_TABLE} ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.code_hash,
                    candidate.tree_hash,
                    candidate.alert_kind,
                    float(candidate.score),
                    float(candidate.recorded_score),
                    float(candidate.deviation),
                    float(candidate.tolerance),
                    candidate.detected_at.isoformat(),
                    candidate.halted_at.isoformat(),
                ),
            )
            stored = self._read_row(connection, pair)
            if stored is None:
                raise CanaryError(
                    "the halt row vanished inside its own write; a halt that "
                    "cannot be read back is not a halt, and the dreaming this "
                    "store was about to stop has not been stopped"
                )
            return self._record_from_row(stored, changed=True)

    # -- Feature 143: the reads ---------------------------------------------

    def halted(self) -> bool:
        """Whether dreaming is halted — §12's state, as one bit.

        ``True`` when any break is on record: §12's ``halt_dreaming()`` takes
        no argument, and the halt it names is the deployment's, not one
        pair's.  The halt is monotone — nothing in this module writes a row
        away — so once ``True`` it stays ``True`` until the operator's
        recovery (§15: bisect the image diff) is recorded as a fresh reference
        pair in the reference store.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(f"SELECT 1 FROM {HALT_TABLE} LIMIT 1")
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        return row is not None

    def current_halt(self) -> Optional[DreamHalt]:
        """The halt in force — the latest write — or ``None`` when dreaming runs.

        The record is reconstructed through :class:`DreamHalt`'s own
        validation, so a row edited outside this package fails to reconstruct
        rather than loading as a plausible-looking break — the defence the
        reference pair's value types apply to their hashes, and for the same
        reason: the stored halt is what pages an operator, and a store that
        could hand back a record disagreeing with its own arithmetic would
        launder a tamper into a page.  ``changed`` is ``False`` on every
        read-back; the bit names the call that wrote the row, and a read
        wrote nothing.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {_COLUMNS} FROM {HALT_TABLE} "
                "ORDER BY halted_at DESC, detected_at DESC, code_hash LIMIT 1"
            )
            try:
                row = cursor.fetchone()
            finally:
                cursor.close()
        if row is None:
            return None
        return self._record_from_row(row, changed=False)

    def require_dreaming_allowed(self) -> None:
        """The guard: pass while dreaming is allowed, refuse when it is not.

        The read-time refusal the dreaming cycle's entrypoint consults — the
        same shape :mod:`tripwires.excise` gives the replay pool: the halt
        rows are never deleted from, and the refusal is derived from them, so
        the halt holds no matter which path set it.  When a break is on
        record this raises :class:`CanaryDeterminismBrokenError` carrying the
        stored record, so the caller that reaches for dreaming learns *which*
        pair broke, *when*, and by how much — the three questions §15's
        recovery asks first.  A caller that dreams without asking has not been
        un-halted; it has skipped the one door §12 leaves open.
        """
        halt = self.current_halt()
        if halt is not None:
            raise CanaryDeterminismBrokenError(
                f"dreaming is halted: {halt.summary}; the nightly canary broke "
                f"at {halt.detected_at.isoformat()}, and dreaming stays "
                "halted until §15's recovery (bisect the image diff) is "
                "recorded as a fresh reference pair",
                halt,
            )

    # -- The row plumbing ----------------------------------------------------

    def _read_row(
        self, connection: sqlite3.Connection, pair: CanaryReferencePair
    ) -> Optional[tuple]:
        """The stored row for ``pair``'s content fingerprint, or ``None``.

        Keyed by ``(code_hash, tree_hash)`` — the pair's identity, the same
        fingerprint the replay's own comparisons trust — so a halt is a fact
        about the frozen bytes rather than about a store row id that a
        re-freeze would mint anew.
        """
        cursor = connection.execute(
            f"SELECT {_COLUMNS} FROM {HALT_TABLE} "
            "WHERE code_hash = ? AND tree_hash = ?",
            (pair.policy.code_hash, pair.tree.tree_hash),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    @staticmethod
    def _record_from_row(row: tuple, *, changed: bool) -> DreamHalt:
        """Reconstruct one :class:`DreamHalt` from a stored row.

        Every field is re-validated by the value type's own constructor, so
        the read path and the write path hold the same record to the same
        arithmetic.  ``changed`` is supplied by the caller because the row
        itself cannot know it: ``True`` from the write that inserted, ``False``
        from a read-back and from a re-observation that found the halt
        already held.
        """
        return DreamHalt(
            code_hash=row[0],
            tree_hash=row[1],
            alert_kind=row[2],
            score=row[3],
            recorded_score=row[4],
            deviation=row[5],
            tolerance=row[6],
            detected_at=datetime.fromisoformat(row[7]),
            halted_at=datetime.fromisoformat(row[8]),
            changed=changed,
        )


# -- The module-level spelling --------------------------------------------------


def halt_dreaming(
    pair: CanaryReferencePair,
    result: CanaryReplayResult,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    detected_at: Optional[datetime] = None,
) -> None:
    """§12's two statements under the ``if``, as one call.

    The whole of feature 143: when the replay's score differs from the
    recorded constant by more than ``1e-12``, dreaming is halted — the break
    is persisted to the halt store — and the ``determinism_broken`` alert is
    emitted as :class:`CanaryDeterminismBrokenError`, raised *after* the row
    is written so a caller that catches the alert to keep reporting still
    leaves the halt on record.  When the result did not break, the ``if`` was
    not taken: nothing is written, nothing is raised, dreaming continues, and
    the call returns ``None``.

    The store is resolved from ``database_url``, else from ``DATABASE_URL``;
    a deployment that names neither is refused *by name* rather than silently
    doing nothing, because a halt that quietly skipped its write would leave
    dreaming running while the nightly runner believed it had stopped it —
    which is the failure mode this whole feature exists to rule out.  The
    refusal happens before the decision, for the same reason
    :func:`nulloracle.verdict.void_if_detectable` resolves first: the halt
    must be recorded, and a break that goes nowhere is worse than none.

    A result measured under any tolerance but §12's
    :data:`~canary.DEFAULT_TOLERANCE` is refused, and so is a result whose
    recorded constant is not the pair's own — see
    :meth:`CanaryHaltStore.halt` for both refusals' reasons, which are the
    store's because the store is where they are enforced.
    """
    source = os.environ if env is None else env
    url = (
        database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        raise CanaryError(
            f"halt_dreaming pronounces §12's halt and nothing names a store: "
            f"{DATABASE_URL_ENV} is unset (and no database_url was supplied), "
            "so the break could not be written down. §12's halt is a state "
            "that must outlive the nightly run that detected the break — a "
            "halt that silently went nowhere would leave the next night "
            "dreaming over a pool §12 has already called untrustworthy"
        )
    if not result.broken:
        # Line 677's `if` was not taken: no halt, no alert, dreaming
        # continues.  §12's boundary is exactly here, and the not-taken branch
        # is as much the feature as the taken one — a nightly runner that ran
        # green must observe nothing but a quiet return.
        return None
    halt = CanaryHaltStore(url).halt(pair, result, detected_at=detected_at)
    raise determinism_broken_error(halt)


def require_dreaming_allowed(
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """The guard, opening its own store — the dreaming entrypoint's spelling.

    Passes while dreaming is allowed and raises
    :class:`CanaryDeterminismBrokenError` carrying the stored record when a
    break is on record (see :meth:`CanaryHaltStore.require_dreaming_allowed`).
    A deployment that names no store passes vacuously: with no relational
    store there is no reference pair, no recorded constant and no canary to
    break, so there is no halt this guard could be holding — the same
    "no store, no status" answer :func:`nulloracle.verdict.load_verdict`
    gives, kept distinct because a caller that mistook an unconfigured
    deployment for a checked one would dream believing the canary had run.
    """
    source = os.environ if env is None else env
    url = (
        database_url if database_url is not None else source.get(DATABASE_URL_ENV, "").strip()
    )
    if not url:
        return None
    CanaryHaltStore(url).require_dreaming_allowed()


def build_halt_store(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[CanaryHaltStore]:
    """Build the halt store the composed application carries.

    The one-shot convenience the component builder uses, kept beside the class
    so a test and the factory construct it the same way.  Deliberately
    resolves rather than strict: the factory builds this component on every
    ``create_app()``, so it must succeed without a ``DATABASE_URL`` and
    compose ``None`` where the deployment has no relational store — a
    discoverable state, not an exception — rather than taking composition
    down for every unrelated feature in the workspace.  A caller that wants
    the store pointed at a URL uses :class:`CanaryHaltStore` — this function
    is the composition spelling, not the operator's.
    """
    return CanaryHaltStore.resolve(env)
