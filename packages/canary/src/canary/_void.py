"""Voiding every score produced after a determinism break — feature 144.

app_spec.xml, "Determinism Guarantees & Nightly Canary", feature 144: *System
persists a void marker on every score produced after a detected determinism
break, rather than letting bad data age into good data.*  docs/nullius-tech-
architecture.md states the same act as the closing clause of key interaction #5: a
deviation beyond ``1e-12`` "halts dreaming and marks scores produced in the
affected window as void".

:mod:`canary._halt` is the half that *detects*: feature 143 replays the frozen
pair, and when the score misses the recorded constant by more than §12's
``1e-12`` it writes the break down and raises the ``determinism_broken`` alert.
Its record carries ``detected_at`` and its docstring names the reason that field
is the *first* break rather than the latest — feature 144's void markers key on
it, and moving it forward would shrink the window this module exists to widen.
This module is the other half: what the break *costs* the data it was measured
over.

Four decisions shape it, and each is a reading of one word in the feature.

**The sweep reads the replay pool, because "every score" is a quantifier over
rows this member does not own.**  Feature 144's sentence has a subject the
member cannot count from its own tables: the scores are ``replay_score`` rows,
created by ``migrations/versions/0109_replay_score_and_policy_revision.py`` and
written by the replay member (features 245-255).  A store that asked a caller to
hand it the scores would leave the feature hollow — a mechanism nothing drives,
voiding rows nobody enumerated — which is precisely the failure §12 describes
when it calls non-determinism the thing that "does not announce itself; it just
slowly makes every conclusion wrong".  So this module reaches the pool the way
:mod:`tripwires.excise` reaches it for feature 132 — by **restating the shape**,
the table's name, its eight columns and the DDL a database the orchestrator has
not migrated yet gets — rather than by importing it.  The layering rule this
member shares with ``tripwires`` is why the restatement is the only available
reach: the canary is imported on every factory scan and, more sharply, on the
replay path §1 keeps away from anything that could perturb it, so a member whose
import pulled a second member into that path would have a determinism story
(§12) with a moving part it cannot name.  A shared vocabulary spelled twice with
one provenance comment beats an import that couples two packages, and that is
``tripwires.layout``'s reasoning stated for the pool's own shape.

**Nothing is written to the pool, and the marker is this member's own table.**
``replay_score`` is read-only from here, on exactly the terms feature 132 leaves
it: the rows are the *evidence* — ``0109``'s own word — and a feature that
deleted or flagged them would be rewriting the reason a past policy revision was
selected, which is also the pool mutation feature 270 forbids during a dreaming
cycle.  So the void marker is a row in ``canary_void_marker``, created
idempotently beside the one module that reads it, the same member-owned-table
stance :mod:`canary._halt` takes for ``canary_dream_halt``.  The refusal is then
*derived* from the marker plus the window, which is what makes it hold whichever
path wrote what: :meth:`CanaryVoidMarkerStore.unvoided_scores` refuses a row in
the window whether or not a sweep has run over it yet, so there is no lag in
which a score is bad and still served.

**The window's edge is the *earliest* break on record, and it is strict.**
Feature 144's word is *after*, and it is a quantifier over an interval, so the
boundary has to be one instant rather than a set of them.  Two frozen pairs
breaking on two nights give two halt rows, and a score produced between them was
produced after the deployment's determinism broke — pair A measured it, and A's
break is the reason the score is untrustworthy — so the honest edge is the
earliest ``detected_at`` (:meth:`~canary.CanaryHaltStore.first_halt`, a read
this feature added to the halt store rather than a second reader of its table).
The edge is **monotone**: another break can only move it earlier, never later,
so the affected window only ever widens and a score once void stays void — the
"does not age into good data" half of the sentence, made structural.  And the
comparison is strict, ``produced_at > detected_at``, matching §12 line 677's own
strict ``>``: a score written at the same second the break was detected is not
*after* it.  Second-resolution stamps — the spelling every clock in this
workspace uses — make that reachable, so it is a decision rather than an
accident.

**A marker cites a break, or it is refused.**  :meth:`CanaryVoidMarkerStore.mark`
refuses outright when no break is on record, and that is the feature's whole
point read as a guard: a marker written against a canary that held would taint
good data, and the sentence this feature answers is about bad data, not about
its absence.  The recorded hashes and the edge ride on every marker row so a
marker is self-describing — the discipline :class:`~canary.DreamHalt` states for
its own arithmetic — and a row edited outside this package fails to reconstruct
rather than loading as a plausible-looking taint.

What this module deliberately does **not** do is decide the break (feature 143's
``1e-12``, in :mod:`canary._replay` and :mod:`canary._halt`), halt dreaming (the
halt store's), or refuse a poisoned subtree (``tripwires``', for a different
reason entirely: a tripwire failure indicts a *branch* of the discovery tree,
while a determinism break indicts a *window of time*, and the two refusals
compose without either needing to know the other).

**Stdlib only, and import-cheap.**  ``sqlite3``, ``datetime``, ``os``, ``uuid``
and ``urllib.parse``; no third-party import at module scope, for the reason the
whole category states: this package is imported on every factory scan, and the
void sweep must not be the member that made that scan expensive.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ._errors import CanaryError
from ._halt import (
    DETERMINISM_BROKEN,
    CanaryHaltStore,
    DreamHalt,
)

__all__ = [
    "DATABASE_URL_ENV",
    "VOID_MARKER_COMPONENT_NAME",
    "VOID_STATUS",
    "VOID_TABLE",
    "CanaryVoidMarkerError",
    "CanaryVoidMarkerStore",
    "VoidMarker",
    "VoidSweep",
    "VoidWindow",
    "build_void_marker_store",
    "mark_void_score",
    "require_score_usable",
    "unvoided_scores",
    "void_scores_after_break",
]

#: The marker's status word — the workspace's one spelling of *void*.
#: ``nulloracle.verdict.CALIBRATION_STATUS_VOID`` writes the same four letters
#: onto a campaign §7.4's guard indicts, and this module writes them onto a
#: score §12's canary indicts; the two are different grain but the same verdict,
#: and a reader scanning for "which of these numbers may I still use?" must not
#: have to know both spellings.
VOID_STATUS = "VOID"

#: This member's own table — one row per voided score, and the audit of what a
#: determinism break cost.  Deliberately *not* a column on ``replay_score``: the
#: pool is the replay member's and its schema is ``0109``'s, so a column added to
#: it would be this feature legislating for a table it does not own — the
#: restraint :mod:`tripwires.layout` states for feature 132 — and it would also
#: make the refusal *stateful* in the wrong direction, since a flag on the score
#: row can be cleared while a marker in this member's own table can only be
#: written.  It is not a column on :data:`canary._halt.HALT_TABLE` either: a
#: halt is one row per broken pair, and a void marker is one row per score, so
#: folding them would put an unbounded set of scores in the row that names the
#: break.
VOID_TABLE = "canary_void_marker"

#: The component name this member registers its void-marker store under — a
#: fourth name rather than a fourth component under any of the three that exist.
#: The convention :mod:`tripwires` states for its own four and this member states
#: for its third: the pin sweep answers *is the deployment pinned?*, the
#: reference store *what is the frozen pair?*, the halt store *is dreaming
#: halted?*, and this one *is this score still usable?* — four questions on four
#: lifecycles, and a caller asking for one must not be handed another.
VOID_MARKER_COMPONENT_NAME = "canary-void-marker"

#: The environment variable naming the relational store — the one spelling every
#: store in this workspace already uses, restated here so each store states its
#: own contract and none imports another's.
DATABASE_URL_ENV = "DATABASE_URL"

# -- The replay pool's shape, restated -------------------------------------------
#
# The four names below are ``migrations/versions/0109_replay_score_and_policy_revision.py``'s,
# restated rather than imported for the reason the module docstring gives at
# length: the replay member does not exist yet, and this member's layering rule
# forbids importing another even when one arrives.  They are spelled once, here,
# beside the DDL a database without the table gets, which is exactly the shape
# :mod:`tripwires.layout` takes for the same table and the same reason.

#: The pool feature 144 sweeps.  ``0109`` creates it; the replay member writes
#: it; this member only reads it.
REPLAY_SCORE_TABLE = "replay_score"

#: The score row's own key — the value a void marker is keyed by.  The marker
#: names a *row* rather than a ``(policy, world)`` pair because a row's identity
#: is what the pool serves from, and a marker keyed by anything a second insert
#: could reproduce would void the wrong score.
REPLAY_SCORE_ID_COLUMN = "id"

#: When the row was written — ``0109``: ``TIMESTAMPTZ NOT NULL DEFAULT NOW()``.
#: **The column the whole feature turns on**: feature 144's window is a
#: comparison on it, so "produced after a detected determinism break" is
#: exactly ``created_at > detected_at``.
REPLAY_SCORE_CREATED_AT_COLUMN = "created_at"

#: The score the row carries — ``0109``: ``score REAL NOT NULL``.  Read only so
#: a sweep can report *what it cost*, the way feature 132's account reports the
#: scores it refused rather than a bare count.
REPLAY_SCORE_SCORE_COLUMN = "score"

#: The policy revision the row scored.  Read for the same reporting reason: an
#: operator reading a voided window needs to know *which* revisions' evidence
#: the break invalidated.
REPLAY_SCORE_POLICY_VERSION_COLUMN = "policy_version"

#: ``replay_score``'s columns as this module reads them, in ``0109``'s order.
#: Spelled once for the reason ``tripwires.layout`` spells its own: the DDL, the
#: sweep's SELECT and any report over the rows must not drift apart on what a
#: score row is made of.
REPLAY_SCORE_COLUMNS = (
    REPLAY_SCORE_ID_COLUMN,
    REPLAY_SCORE_POLICY_VERSION_COLUMN,
    "world_id",
    "beta",
    REPLAY_SCORE_SCORE_COLUMN,
    "committed_pick",
    "is_holdout",
    REPLAY_SCORE_CREATED_AT_COLUMN,
)

#: The SQLite spelling of ``NOW()`` — ``0109``'s own expression, and the **outer**
#: parentheses are load-bearing: SQLite's ``DEFAULT`` grammar accepts a function
#: call only when the entire expression is parenthesised, so the unparenthesised
#: spelling is a syntax error that takes the whole ``CREATE TABLE`` down with it.
_SQLITE_NOW_DEFAULT = "(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"

#: The SQLite spelling of ``gen_random_uuid()`` — ``0118``'s expression,
#: verbatim, an RFC 4122 version-4 UUID built from ``randomblob``.  Same grammar
#: reason for the parentheses; the variant and version nibbles are the ones a v4
#: UUID must carry rather than whatever the random source produced.
_SQLITE_UUID_DEFAULT = (
    "(lower("
    "hex(randomblob(4)) || '-' || hex(randomblob(2)) || '-4' || "
    "substr(hex(randomblob(2)), 2) || '-' || "
    "substr('89ab', abs(random()) % 4 + 1, 1) || "
    "substr(hex(randomblob(2)), 2) || '-' || hex(randomblob(6))"
    "))"
)


def _search_path(database_url: str) -> Path:
    """Translate a ``sqlite:///`` URL into a filesystem path.

    The SQLAlchemy convention the workspace's ``DATABASE_URL`` already uses,
    restated here rather than imported so each store states its own contract.  A
    non-SQLite scheme is refused loudly — the Postgres store arrives with the
    migration member — and a pathless (in-memory) URL is refused too, for a
    reason specific to this feature: an in-memory database dies with the
    connection that opened it, so a marker written there would be gone the
    moment the caller looked — a score that reads as void while the pool goes on
    serving it, which is the one outcome a refusal must not produce.
    """
    parsed = urlparse(database_url)
    if parsed.scheme != "sqlite":
        raise CanaryVoidMarkerError(
            f"unsupported {DATABASE_URL_ENV} scheme {parsed.scheme!r}: this "
            "store speaks sqlite:/// (the spec's single-machine allowance); "
            f"point {DATABASE_URL_ENV} at a sqlite database"
        )
    if parsed.netloc not in ("", "localhost"):
        raise CanaryVoidMarkerError(
            f"sqlite {DATABASE_URL_ENV} must not carry a host, got "
            f"{parsed.netloc!r}"
        )
    path = unquote(parsed.path).removeprefix("/")
    if not path or path == ":memory:":
        raise CanaryVoidMarkerError(
            f"sqlite {DATABASE_URL_ENV} carries no database path: an in-memory "
            "database would die with the connection that opened it, and a void "
            "marker written there is gone the moment the caller looks — a score "
            "that reads as void while the pool goes on serving it"
        )
    return Path(path)


def _dialect_of(connection: object) -> str:
    """Name the dialect of a DBAPI connection, conservatively.

    ``0118``'s own function, restated: only ``sqlite`` is recognised positively
    and everything else is reported as ``other``, receiving the spec's Postgres
    spelling — the production target is Postgres (§9.1), and an unrecognised
    driver is far likelier to be Postgres-compatible than to share SQLite's
    ``DEFAULT`` grammar.
    """
    module = type(connection).__module__ or ""
    if module.split(".")[0] == "sqlite3":
        return "sqlite"
    return "other"


def replay_pool_bootstrap_schema(dialect: str = "other") -> str:
    """The DDL that brings a database without a ``replay_score`` table to 0109's shape.

    Feature 132's reach, restated here for feature 144's use, and deliberately
    the *same* shape ``0109`` creates — eight columns in the migration's order,
    the two dialect splits the migration makes (``DEFAULT gen_random_uuid()`` and
    ``DEFAULT NOW()``, neither of which SQLite's ``DEFAULT`` grammar accepts
    unparenthesised), and a ``NOT NULL`` on the primary key the spec's bare
    ``UUID PRIMARY KEY`` leaves implicit.

    **Why this member creates a table it does not own.**  The pool belongs to the
    replay member and the migration owns its schema.  A store that has to *read*
    the pool against a database the orchestrator has not migrated yet has two
    options: fail on a missing table, or create the one the migration would.  The
    second is what every store in this workspace does, and it is safe for exactly
    the reason the other bootstrap schemas are: every statement is
    ``IF NOT EXISTS``, so a database the migration already built is left
    byte-for-byte as it was.

    **The restraint.**  Nothing here adds a column the migration does not
    declare — not even one this feature would find convenient.  A ``voided_at``
    column on ``replay_score`` is the tempting one and it is exactly wrong, for
    the reason :data:`VOID_TABLE` gives at length.  Feature 144 writes nothing to
    this table.
    """
    uuid_default = _SQLITE_UUID_DEFAULT if dialect == "sqlite" else "gen_random_uuid()"
    now_default = _SQLITE_NOW_DEFAULT if dialect == "sqlite" else "NOW()"
    return f"""
    CREATE TABLE IF NOT EXISTS {REPLAY_SCORE_TABLE} (
        {REPLAY_SCORE_ID_COLUMN} UUID NOT NULL PRIMARY KEY
            DEFAULT {uuid_default},
        {REPLAY_SCORE_POLICY_VERSION_COLUMN} TEXT NOT NULL,
        world_id               UUID NOT NULL,
        beta                   REAL NOT NULL,
        {REPLAY_SCORE_SCORE_COLUMN} REAL NOT NULL,
        committed_pick         UUID,
        is_holdout             BOOLEAN NOT NULL DEFAULT FALSE,
        {REPLAY_SCORE_CREATED_AT_COLUMN} TIMESTAMPTZ NOT NULL
            DEFAULT {now_default}
    )
    """


#: ``canary_void_marker``'s DDL, created idempotently beside the code that reads
#: it — the same member-owned-table stance :mod:`canary._halt` takes for
#: ``canary_dream_halt``.  One row per voided score, keyed by the score's own
#: ``replay_score.id``: a score is void once, and a re-sweep finds the marker
#: already held rather than writing a second opinion about the same row.
#:
#: `detected_at` is the *edge of the affected window* — the earliest break on
#: record, not necessarily the break that caused this particular sweep — carried
#: on every marker so the row is self-describing: a reader can recompute
#: `produced_at > detected_at` from the record alone and see for themselves that
#: the score was in the window.  The pair's hashes ride along for the same reason:
#: an operator asking *which reference's drift cost me these scores?* reads the
#: answer off the marker rather than re-deriving it from a halt row that may since
#: have been joined by others.
_CREATE_MARKER_TABLE = f"""
-- Feature 144: a score produced after a detected determinism break, persisted as
-- void.  One row per score, keyed by the score's own id -- the marker names a
-- row, not a (policy, world) pair, because a row's identity is what the pool
-- serves from.
--
-- `status` is the workspace's one spelling of the verdict ('VOID'); `alert_kind`
-- is feature 143's own word, carried so a reader dispatching on the break's kind
-- finds it on the marker too and not only on the halt row.  `changed` is
-- deliberately absent: it is a property of the call that wrote the row, not a
-- fact about the score.
CREATE TABLE IF NOT EXISTS {VOID_TABLE} (
    score_id    TEXT NOT NULL PRIMARY KEY,  -- replay_score.id, canonical UUID text
    produced_at TEXT NOT NULL,              -- replay_score.created_at
    detected_at TEXT NOT NULL,              -- the affected window's edge
    code_hash   TEXT NOT NULL,              -- the pair that measured the break
    tree_hash   TEXT NOT NULL,
    alert_kind  TEXT NOT NULL,              -- 'determinism_broken', feature 143's
    status      TEXT NOT NULL,              -- 'VOID', the workspace's spelling
    marked_at   TEXT NOT NULL               -- when this marker was written
);
"""

#: The marker table's columns, in the order the insert names them and the order
#: the read-back unpacks them.  Spelled once so the write and the read cannot
#: drift apart on a column order — the failure a positional ``SELECT *`` invites.
_MARKER_COLUMNS = (
    "score_id, produced_at, detected_at, code_hash, tree_hash, alert_kind, "
    "status, marked_at"
)


def _utc_now() -> datetime:
    """The current instant, timezone-aware UTC.

    Second resolution with microseconds dropped rather than rounded, the same
    spelling :func:`canary._halt._utc_now` and :func:`ledger.record.utc_now` use,
    restated here rather than imported so this module states its own contract:
    the stamp orders void markers against the breaks they cite, and dropping —
    not rounding — keeps a stamp never *after* the instant observed.
    """
    return datetime.now(timezone.utc).replace(microsecond=0)


def _validated_instant(name: str, value: Any) -> datetime:
    """A timezone-aware instant — refused otherwise, naming the field.

    A naive stamp is refused rather than assumed to be UTC, and here that is
    load-bearing twice over: the window's whole computation is a comparison
    between ``produced_at`` and ``detected_at``, and comparing a naive datetime
    against an aware one raises ``TypeError`` at the comparison — deep inside a
    sweep, far from the record that carried it.  Refused here, at construction,
    where the field that is wrong is the one named.
    """
    if not isinstance(value, datetime):
        raise CanaryVoidMarkerError(
            f"a void marker's {name} must be a datetime, got {value!r} "
            f"({type(value).__name__}); the window is a comparison on it, and "
            "a non-datetime is a term that comparison cannot reach"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanaryVoidMarkerError(
            f"a void marker's {name} must be timezone-aware; got the naive "
            f"datetime {value.isoformat()!r}. The affected window is a "
            "comparison between this instant and the break's, and an aware/"
            "naive comparison raises far from the write that set it"
        )
    return value


def _validated_score_id(value: Any) -> str:
    """Validate a score id, returning it in canonical UUID text.

    Accepts a :class:`uuid.UUID` or any text :func:`uuid.UUID` parses, and
    returns the lowercased hyphenated rendering — the same normalization
    :func:`tripwires.layout.validated_node_id` and :func:`ledger.record.
    _validated_uuid` apply, and for the same reason: the value joins a UUID
    primary key, and a mixed-case or braced spelling of one score would read as
    two — so a re-sweep would write a second marker for a score already marked,
    or fail to find the one it wrote.

    A malformed id is refused rather than stored: a marker keyed by something
    that cannot join the pool's key is a taint on no row, and the caller would
    be told a score was voided while the pool went on serving it.
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise CanaryVoidMarkerError(
                "a void marker must name the score it voids, got an empty "
                "string; a marker keyed by nothing taints no row, and the pool "
                "would go on serving the score it claims to have voided"
            )
        try:
            return str(uuid.UUID(text))
        except (ValueError, AttributeError, TypeError) as exc:
            raise CanaryVoidMarkerError(
                f"a score id must be a UUID or its text spelling, got {value!r}: "
                f"{exc}; score ids join `replay_score.id`, and a key that cannot "
                "join it names no row in the pool"
            ) from exc
    raise CanaryVoidMarkerError(
        f"a score id must be a UUID or its text spelling, got {value!r} "
        f"({type(value).__name__}); void markers are keyed by the score row's "
        "own id, and a key that cannot join the pool keys no score"
    )


def _parsed_instant(name: str, value: Any) -> datetime:
    """Parse a stored instant, refusing one that is not a usable stamp.

    SQLite hands back the text this module wrote (``isoformat()``) or, for a row
    a migration's own default produced,
    ``strftime('%Y-%m-%dT%H:%M:%fZ')`` — both of which
    :func:`datetime.fromisoformat` parses, the second's ``Z`` being the UTC
    designator Python accepts.  An unparseable value is refused by name rather
    than returned as a string, for the reason :func:`_validated_instant` gives
    from the other side: a caller comparing a string against a datetime would
    find them unequal always, and a window that silently compares as *empty* is
    a refusal that reads as "there is nothing to void".
    """
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CanaryVoidMarkerError(
            f"the stored {name} {value!r} could not be parsed: {exc}; the "
            "affected window is a comparison on this column, and a stamp no "
            "reader can parse is a window nobody can check"
        ) from exc


# -- The window ------------------------------------------------------------------


@dataclass(frozen=True)
class VoidWindow:
    """The affected window — the interval feature 144's markers key on.

    A *value*: the edge (the earliest break on record), the pair that measured
    it, and the alert kind and status the markers carry.  It is what
    :meth:`CanaryVoidMarkerStore.window` returns and what every marker is
    validated against, so "this score is in the affected window" is one answer
    rather than a comparison each caller spells for itself.

    The edge is exclusive — :meth:`contains` is ``produced_at > detected_at``,
    strict, matching §12 line 677's own strict ``>`` and feature 144's word
    *after*.  A window with an inclusive boundary would void the score written
    at the very instant the break was detected, which was produced *as* the
    break and not after it.

    Deliberately not a pair of instants and nothing else.  A bare
    ``(start, end)`` would leave every marker's hashes to be re-derived from
    whichever halt row happened to be in force when the marker was written,
    which is exactly the coupling :data:`_CREATE_MARKER_TABLE` avoids by
    carrying them.
    """

    #: The window's edge — the earliest ``detected_at`` on record.  Scores
    #: produced strictly after this instant are void.
    detected_at: datetime
    #: The broken pair's policy identity — ``canary_policy.code_hash``.
    code_hash: str
    #: The broken pair's tree identity — ``canary_tree.tree_hash``.
    tree_hash: str
    #: The break's kind — always :data:`~canary.DETERMINISM_BROKEN`.
    alert_kind: str
    #: The verdict the markers carry — always :data:`VOID_STATUS`.
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "detected_at", _validated_instant("detected_at", self.detected_at)
        )
        for name in ("code_hash", "tree_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or value != value.lower():
                raise CanaryVoidMarkerError(
                    f"a void window's {name} must be a 64-character lowercase "
                    f"hex digest, got {value!r}; it names the frozen pair whose "
                    "drift produced the window, and a hash of the wrong width "
                    "or shape names no reference"
                )
        if self.alert_kind != DETERMINISM_BROKEN:
            raise CanaryVoidMarkerError(
                f"a void window's alert_kind is the spec's "
                f"{DETERMINISM_BROKEN!r}, got {self.alert_kind!r}; feature 144's "
                "window is opened by feature 143's break and by nothing else"
            )
        if self.status != VOID_STATUS:
            raise CanaryVoidMarkerError(
                f"a void window's status is {VOID_STATUS!r}, got {self.status!r}; "
                "the window and the markers it produces carry one verdict, and a "
                "window naming any other word would open onto markers that "
                "disagree with it"
            )

    def contains(self, produced_at: Any) -> bool:
        """Whether a score produced at ``produced_at`` falls in the window.

        Strictly after the edge — see the class docstring.  The instant is
        validated, so a naive one is refused here rather than raising a
        ``TypeError`` out of a comparison whose meaning the caller was still
        working out.
        """
        return _validated_instant("produced_at", produced_at) > self.detected_at

    def to_payload(self) -> dict[str, Any]:
        """The window as a plain mapping, for a log line or an operator's report."""
        return {
            "detected_at": self.detected_at.isoformat(),
            "code_hash": self.code_hash,
            "tree_hash": self.tree_hash,
            "alert_kind": self.alert_kind,
            "status": self.status,
        }


# -- The record ------------------------------------------------------------------


@dataclass(frozen=True)
class VoidMarker:
    """One voided score: the taint, its reason, and the window it fell in.

    A *value* — frozen, self-describing — and the thing
    :meth:`CanaryVoidMarkerStore.mark` writes and returns,
    :meth:`CanaryVoidMarkerStore.markers` reads back, and
    :class:`CanaryVoidMarkerRefusedError` carries.  One type for all three, so
    the record an operator reads and the row the store holds cannot be two
    things that disagree — the stance :class:`~canary.DreamHalt` takes for the
    halt.

    Validated in :meth:`__post_init__` rather than only where it is built, because
    the read path reconstructs one from a stored row: a row edited outside this
    package — a ``produced_at`` that is not after the ``detected_at`` it cites, a
    status that is not :data:`VOID_STATUS`, a hash of the wrong width — fails to
    reconstruct rather than loading as a plausible-looking taint.  What
    downstream trusts is the stored record, and a store that could hand back a
    marker disagreeing with its own window would launder a tamper into a refusal.

    ``changed`` answers the question a re-sweep asks — whether *this* call wrote
    the row.  The first marking writes it (``True``); a later sweep over the same
    score finds it already held and reports ``False`` while the stored record is
    the one returned.  The distinction is the one §8's ``tree_appended`` idiom
    draws, and :class:`~canary.DreamHalt` draws for the same reason: a
    re-observed marker must not read as a new one.
    """

    #: The voided score's own key — ``replay_score.id``, canonical UUID text.
    score_id: str
    #: When the score was produced — ``replay_score.created_at``.
    produced_at: datetime
    #: The affected window's edge: the earliest break on record when this marker
    #: was written.  Carried so the row is self-describing.
    detected_at: datetime
    #: The broken pair's policy identity — ``canary_policy.code_hash``.
    code_hash: str
    #: The broken pair's tree identity — ``canary_tree.tree_hash``.
    tree_hash: str
    #: The break's kind — always :data:`~canary.DETERMINISM_BROKEN`.
    alert_kind: str
    #: The verdict — always :data:`VOID_STATUS`.
    status: str
    #: When this marker was written to the store.
    marked_at: datetime
    #: Whether the call that produced this record wrote the row.  ``False`` on a
    #: read-back and on a re-sweep that found the marker already held.
    changed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "score_id", _validated_score_id(self.score_id))
        object.__setattr__(
            self, "produced_at", _validated_instant("produced_at", self.produced_at)
        )
        object.__setattr__(
            self, "detected_at", _validated_instant("detected_at", self.detected_at)
        )
        for name in ("code_hash", "tree_hash"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or value != value.lower()
                or any(c not in "0123456789abcdef" for c in value)
            ):
                raise CanaryVoidMarkerError(
                    f"a void marker's {name} must be a 64-character lowercase "
                    f"hex digest, got {value!r}; it names the frozen pair whose "
                    "drift voided this score, and a hash of the wrong width or "
                    "shape names no reference"
                )
        if self.alert_kind != DETERMINISM_BROKEN:
            raise CanaryVoidMarkerError(
                f"a void marker's alert_kind is the spec's "
                f"{DETERMINISM_BROKEN!r}, got {self.alert_kind!r}; feature 144 "
                "voids scores on feature 143's break and on nothing else"
            )
        if self.status != VOID_STATUS:
            raise CanaryVoidMarkerError(
                f"a void marker's status is {VOID_STATUS!r}, got {self.status!r}; "
                "the workspace spells this verdict one way, and a marker "
                "carrying any other word is a row no reader of VOID could find"
            )
        object.__setattr__(
            self, "marked_at", _validated_instant("marked_at", self.marked_at)
        )
        if not self.produced_at > self.detected_at:
            raise CanaryVoidMarkerError(
                f"a void marker's produced_at ({self.produced_at.isoformat()!r}) "
                f"is not after the detected_at it cites "
                f"({self.detected_at.isoformat()!r}); feature 144 voids every "
                "score produced *after* a detected determinism break, and a "
                "marker at or before the edge would taint a score the break did "
                "not touch — the opposite of what this feature is for"
            )
        if not isinstance(self.changed, bool):
            raise CanaryVoidMarkerError(
                f"changed must be a bool, got {self.changed!r} "
                f"({type(self.changed).__name__}); whether this call wrote the "
                "row is one bit, and a truthy-looking non-bool is the value that "
                "would silently misreport a re-sweep as a first marking"
            )

    @property
    def summary(self) -> str:
        """One sentence: which score was voided, when produced, and by what.

        Composed rather than stored, because every part of it is already a field
        — a stored copy would be a second place for the record's own values to
        live, and an edited row would then disagree with its own summary.
        """
        return (
            f"the score {self.score_id} produced at "
            f"{self.produced_at.isoformat()} is {self.status}: it falls after "
            f"the determinism break at {self.detected_at.isoformat()} "
            f"(code_hash={self.code_hash}, tree_hash={self.tree_hash})"
        )

    def to_payload(self) -> dict[str, Any]:
        """The marker as a plain mapping, for a log line or an operator's report.

        The field names are the record's own, so a stored row, a rendered mapping
        and a structured log record name the same things the same way — and the
        instants render as the ISO-8601 text the table stores, so a round trip
        through this mapping and back is the same instant.
        """
        return {
            "score_id": self.score_id,
            "produced_at": self.produced_at.isoformat(),
            "detected_at": self.detected_at.isoformat(),
            "code_hash": self.code_hash,
            "tree_hash": self.tree_hash,
            "alert_kind": self.alert_kind,
            "status": self.status,
            "marked_at": self.marked_at.isoformat(),
            "changed": self.changed,
        }


@dataclass(frozen=True)
class VoidSweep:
    """The account of one sweep: the window, what it cost, and what it found.

    Feature 144's sentence turned into a report.  *"every score produced after a
    detected determinism break"* is :attr:`window` and the rows it selects;
    :attr:`marked` is the subset this sweep actually wrote (a re-sweep over an
    already-marked pool reports none, with ``changed=False`` on each, so running
    the sweep twice is observably the same refusal — the idempotence feature 132
    states for its own read); :attr:`already_marked` is the subset found held.

    :attr:`refused` is the honest middle term and it is worth naming: the pool
    rows *actually* void, whether this sweep wrote their markers or an earlier
    one did.  It is derived from the window rather than from :attr:`marked`,
    because a caller asking "which scores may I no longer use?" wants the answer
    after a second sweep as much as after the first.  :attr:`pool_size` rides
    along so the cost is legible without a second query — the shape
    :class:`~tripwires.ExcisedBranch` takes for its own account.
    """

    #: The affected window this sweep applied.
    window: VoidWindow
    #: The markers this sweep wrote, oldest score first.
    marked: tuple[VoidMarker, ...]
    #: The markers this sweep found already held, oldest score first.
    already_marked: tuple[VoidMarker, ...]
    #: Every pool row the window refuses — the union of the two above.
    refused: tuple[VoidMarker, ...]
    #: How many rows the pool held when this sweep was computed.
    pool_size: int

    def __post_init__(self) -> None:
        if not isinstance(self.window, VoidWindow):
            raise CanaryVoidMarkerError(
                f"a void sweep carries the window it applied, got "
                f"{self.window!r} ({type(self.window).__name__}); a sweep whose "
                "window is not recorded cannot be audited — an operator could "
                "not tell which break voided a score"
            )
        for name in ("marked", "already_marked", "refused"):
            entries = getattr(self, name)
            for entry in entries:
                if not isinstance(entry, VoidMarker):
                    raise CanaryVoidMarkerError(
                        f"a void sweep's {name} holds VoidMarker values, got "
                        f"{entry!r} ({type(entry).__name__})"
                    )
                if not self.window.contains(entry.produced_at):
                    raise CanaryVoidMarkerError(
                        f"a void sweep reports a marker for a score produced at "
                        f"{entry.produced_at.isoformat()}, which is not after "
                        f"this sweep's window edge "
                        f"({self.window.detected_at.isoformat()}); a marker "
                        "outside the window it was swept under would refuse a "
                        "score the break did not touch"
                    )
            object.__setattr__(self, name, tuple(entries))
        if isinstance(self.pool_size, bool) or not isinstance(self.pool_size, int):
            raise CanaryVoidMarkerError(
                f"a void sweep's pool_size must be an integer, got "
                f"{self.pool_size!r} ({type(self.pool_size).__name__})"
            )
        if self.pool_size < 0:
            raise CanaryVoidMarkerError(
                f"a void sweep's pool_size must not be negative, got "
                f"{self.pool_size!r}"
            )
        if len(self.refused) > self.pool_size:
            raise CanaryVoidMarkerError(
                f"a void sweep refuses {len(self.refused)} score(s) out of a "
                f"pool of {self.pool_size}; a pool cannot hold fewer rows than "
                "it refuses, so the account and the pool describe different "
                "databases"
            )
        if len(self.refused) != len(self.marked) + len(self.already_marked):
            raise CanaryVoidMarkerError(
                f"a void sweep refuses {len(self.refused)} score(s) but reports "
                f"{len(self.marked)} newly marked and "
                f"{len(self.already_marked)} already marked; the refused set is "
                "exactly the union of those two, and an account that disagrees "
                "with its own parts is a report nobody can act on"
            )

    @property
    def newly_marked_count(self) -> int:
        """How many markers this sweep wrote — zero on a re-sweep."""
        return len(self.marked)

    @property
    def refused_score_ids(self) -> tuple[str, ...]:
        """The ids of every pool row the window refuses, oldest first."""
        return tuple(entry.score_id for entry in self.refused)

    def to_payload(self) -> dict[str, Any]:
        """The sweep as a plain mapping, for a log line or an operator's report."""
        return {
            "window": self.window.to_payload(),
            "pool_size": self.pool_size,
            "newly_marked_count": self.newly_marked_count,
            "refused_score_count": len(self.refused),
            "refused_score_ids": list(self.refused_score_ids),
            "marked": [entry.to_payload() for entry in self.marked],
            "already_marked": [entry.to_payload() for entry in self.already_marked],
        }


# -- The alert -------------------------------------------------------------------


class CanaryVoidMarkerError(CanaryError):
    """A score could not be voided, or a void marker could not be read.

    This member's one refusal for feature 144, and deliberately its own subclass
    rather than a fold into :class:`~canary.CanaryDeterminismBrokenError`: that
    error *is* the break (feature 143's alert, raised when the canary's score
    drifts), while this one is about the *bookkeeping* the break implies — a
    marker citing no break, a score that predates the window, a row that cannot
    be parsed.  A caller catching the alert wants to stop the night's run; a
    caller catching this one wants to know which score it could not taint.  It
    is a subclass of :class:`~canary.CanaryError`, so the package's single
    ``except`` still catches every failure of the canary's assertions.
    """


# -- The store -------------------------------------------------------------------


class CanaryVoidMarkerStore:
    """Feature 144's read and write: the pool swept, the markers, and the guard.

    Constructed with the database URL it writes to; :meth:`window` is the
    affected interval, :meth:`mark` and :meth:`sweep` are the writes,
    :meth:`markers` and :meth:`unvoided_scores` are the reads, and
    :meth:`require_score_usable` is the guard a replay path consults.  The class
    resolves its path lazily, so constructing one performs no I/O — the contract
    every store in this workspace states, and the reason composing the
    application never opens a database.

    **It reads the halt store rather than the halt table.**  The window's edge is
    feature 143's fact, and this store asks :class:`~canary.CanaryHaltStore` for
    it — the same stance :meth:`tripwires.ReplayPool.marks` takes toward feature
    131's store.  A second reader of ``canary_dream_halt`` would be a second
    opinion about when the deployment broke, and the two could disagree at
    exactly the moment an operator asked which scores were affected.
    """

    def __init__(
        self, database_url: str, *, halt_store: Optional[CanaryHaltStore] = None
    ) -> None:
        if not isinstance(database_url, str) or not database_url.strip():
            raise CanaryVoidMarkerError(
                f"{DATABASE_URL_ENV} must be a non-empty database URL"
            )
        self._database_url = database_url.strip()
        # The break lives in the same database and is read through the store
        # that writes it.  A store may be handed in so a test pins one, but it
        # must name the same file — see :meth:`_halt_store`.
        self._halt = halt_store
        # Resolved on first use rather than at construction: building the store
        # is composition-time work and must not touch the disk.
        self._path: Optional[Path] = None

    # -- Construction -------------------------------------------------------

    @classmethod
    def resolve(
        cls, env: Optional[Mapping[str, str]] = None
    ) -> Optional["CanaryVoidMarkerStore"]:
        """The void-marker store ``DATABASE_URL`` names, or ``None`` when it names none.

        An empty or whitespace-only value counts as unset.  Absent is not an
        error: it is a deployment without a relational store, which composes no
        void-marker component — a discoverable state, not an exception — while
        the nightly runner that must void the affected window is the caller that
        must not find itself in it.
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
        this member cannot speak is refused by name) the first time an operation
        needs it.
        """
        if self._path is None:
            self._path = _search_path(self._database_url)
        return self._path

    @property
    def halts(self) -> CanaryHaltStore:
        """Feature 143's store — where the break that opens the window lives.

        Exposed because the two features answer two halves of §12 and a caller
        auditing a voiding needs both: this store says *which scores are
        refused*, and the halt store says *when and on what* the deployment
        broke.  Handing back the composed instance rather than a fresh one keeps
        the two on one lifecycle, which is what makes "the window is the halt's
        own instant" a property of one object graph.
        """
        return self._halt_store()

    def _halt_store(self) -> CanaryHaltStore:
        """The halt store this void store reads its window edge through.

        A store handed to the constructor is used only when it names the same
        file; one pointed elsewhere would make "the window opens on the break"
        a sentence about two different databases, and the failure would be
        invisible — a void store refusing scores from one pool while an operator
        read a fully halted tree in another.

        **This store's own path resolves first**, before the halt store is
        reached — a translation at the seam, not a formality.  Feature 143's
        :func:`canary._halt._sqlite_path` refuses a URL it cannot speak with
        :class:`~canary.CanaryError`, and a caller that asked *which scores are
        void?* and caught :class:`CanaryVoidMarkerError` would miss it: the
        refusal would escape as the wrong type, naming the halt store for a
        store this caller never asked about.  Resolving :attr:`path` first
        raises *this* member's error, naming this store, for the same malformed
        URL — the error vocabulary a caller of feature 144 is written against.
        """
        # Resolving this store's own path raises CanaryVoidMarkerError for a URL
        # this store cannot speak — before feature 143's translator is reached.
        mine = self.path
        if self._halt is None:
            self._halt = CanaryHaltStore(self._database_url)
        elif self._halt.path != mine:
            raise CanaryVoidMarkerError(
                f"the void store reads {mine} but was handed a halt store "
                f"reading {self._halt.path}; a window opened on another "
                "database's break would void the wrong scores — or none — while "
                "the record showed the deployment halted"
            )
        return self._halt

    def _connect(self) -> sqlite3.Connection:
        """Open the database and ensure both shapes exist, idempotently.

        The halt table first, through feature 143's store — the window's edge is
        read from it, so a database without it is one this store cannot answer
        *when did the deployment break?* about — then ``0109``'s ``replay_score``
        through :func:`replay_pool_bootstrap_schema`, then this member's own
        marker table.  The order is the dependency order and not a formality:
        the sweep joins the marker table to the pool, and both are read against
        the halt's instant.

        ``CREATE TABLE IF NOT EXISTS`` throughout — the contract every store in
        this workspace states: a fresh database, a migrated one and one this
        member already prepared all take the same path and leave the same
        schema.  The caller owns the connection; use it as a context manager to
        commit.
        """
        path = self.path
        # Read through feature 143's store so the halt schema is created by the
        # module that owns it, rather than by a second spelling here — the same
        # reach :meth:`tripwires.ReplayPool.ensure_schema` makes for feature
        # 131's store, and through its public door for the same reason.
        self._halt_store().ensure_schema()
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        with connection:
            connection.executescript(replay_pool_bootstrap_schema(_dialect_of(connection)))
            connection.executescript(_CREATE_MARKER_TABLE)
        return connection

    def ensure_schema(self) -> None:
        """Bring the database to the shape this store reads, idempotently.

        Public for the same reason :meth:`canary.CanaryHaltStore.ensure_schema`
        and :meth:`tripwires.ReplayPool.ensure_schema` are: an operator pointing
        this member at a database the orchestrator has not migrated yet runs it
        once, and a test seeds a pool into exactly the schema the store will
        read.
        """
        self._connect().close()

    # -- The window ---------------------------------------------------------

    def window(self) -> Optional[VoidWindow]:
        """The affected window — or ``None`` when no break is on record.

        Opened on :meth:`~canary.CanaryHaltStore.first_halt`: the *earliest*
        break on record, not the latest, so a second break on another pair can
        only move the edge earlier and the affected window only ever widens (see
        the module docstring).  ``None`` is the honest answer for a deployment
        whose canary has held — there is no window, so no score is void — and it
        is deliberately distinct from an *empty* window: a caller must be able to
        tell "the canary held" from "the canary broke and nothing was produced
        after it", exactly as :meth:`~canary.CanaryHaltStore.halted` keeps
        "halted" apart from "no store".
        """
        halt = self._halt_store().first_halt()
        if halt is None:
            return None
        return self._window_from(halt)

    @staticmethod
    def _window_from(halt: DreamHalt) -> VoidWindow:
        """The window a stored halt opens — one spelling, used by every read.

        Every method that needs a window builds it here, so "the edge is the
        halt's ``detected_at``" is stated once and a later read cannot apply a
        different boundary from the one a marker was written under.
        """
        return VoidWindow(
            detected_at=halt.detected_at,
            code_hash=halt.code_hash,
            tree_hash=halt.tree_hash,
            alert_kind=halt.alert_kind,
            status=VOID_STATUS,
        )

    # -- Feature 144: the write ---------------------------------------------

    def mark(
        self,
        score_id: Any,
        produced_at: Any,
        *,
        marked_at: Optional[datetime] = None,
    ) -> VoidMarker:
        """Persist one void marker — the score, and the window it fell in.

        The explicit door, the shape :meth:`canary.CanaryHaltStore.halt` takes:
        the taint is validated, the row is written, and the stored record is read
        back and returned.  Nothing is raised here — a monitor sweeping a pool
        wants the records as data — so a caller that wants the guard asks
        :meth:`require_score_usable` instead.

        Refuses, in this order, and each refusal names what it is about:

        1. a ``score_id`` that cannot join the pool's key
           (:class:`CanaryVoidMarkerError`) — a marker on no row;
        2. a ``produced_at`` that is not timezone-aware
           (:class:`CanaryVoidMarkerError`) — the window is a comparison, and an
           aware/naive one raises far from the write that set it;
        3. **no break on record** (:class:`CanaryVoidMarkerError`) — feature 144
           voids scores *after a detected determinism break*, and a marker
           written with no break behind it would taint good data against a
           canary that held;
        4. a ``produced_at`` that is not strictly after the window's edge
           (:class:`CanaryVoidMarkerError`) — the score predates the break, and
           a marker outside the window would void *good* data, which is the one
           thing this feature must never do.

        A score already marked writes nothing and returns the stored record with
        ``changed=False``: the first marking is the fact, and a re-sweep must not
        read as a new refusal (see :class:`VoidMarker`).  The stored record's
        ``detected_at`` is the *first* sweep's edge, which — the edge being
        monotone — is never later than a later sweep's.
        """
        score = _validated_score_id(score_id)
        produced = _validated_instant("produced_at", produced_at)
        halt = self._halt_store().first_halt()
        if halt is None:
            raise CanaryVoidMarkerError(
                f"nothing is void: no determinism break is on record, so there "
                f"is no affected window for the score {score!r} to fall in. "
                "Feature 144 voids scores produced *after* a detected break, and "
                "a marker written with no break behind it would taint a score "
                "against a canary that held"
            )
        window = self._window_from(halt)
        if not window.contains(produced):
            raise CanaryVoidMarkerError(
                f"the score {score!r} was produced at {produced.isoformat()}, "
                f"which is not after the determinism break at "
                f"{window.detected_at.isoformat()}; feature 144 voids every "
                "score produced *after* a detected break, and a marker outside "
                "the window would void good data — the opposite of what this "
                "feature is for"
            )
        written = _utc_now() if marked_at is None else marked_at
        with closing(self._connect()) as connection, connection:
            existing = self._read_row(connection, score)
            if existing is not None:
                # First write wins.  A re-sweep over an already-marked score is
                # the same taint still holding: the stored record — not the new
                # observation — is what the caller gets back.
                return self._record_from_row(existing, changed=False)
            candidate = VoidMarker(
                score_id=score,
                produced_at=produced,
                detected_at=window.detected_at,
                code_hash=window.code_hash,
                tree_hash=window.tree_hash,
                alert_kind=window.alert_kind,
                status=window.status,
                marked_at=written,
                changed=True,
            )
            connection.execute(
                f"INSERT INTO {VOID_TABLE} ({_MARKER_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.score_id,
                    candidate.produced_at.isoformat(),
                    candidate.detected_at.isoformat(),
                    candidate.code_hash,
                    candidate.tree_hash,
                    candidate.alert_kind,
                    candidate.status,
                    candidate.marked_at.isoformat(),
                ),
            )
            stored = self._read_row(connection, score)
            if stored is None:
                raise CanaryVoidMarkerError(
                    "the void marker vanished inside its own write; a marker "
                    "that cannot be read back is not persisted, and the score "
                    "it claims to have voided is still being served"
                )
            return self._record_from_row(stored, changed=True)

    def sweep(self, *, marked_at: Optional[datetime] = None) -> Optional[VoidSweep]:
        """Void every pool score in the window — feature 144's verb.

        Reads ``replay_score``, selects every row whose ``created_at`` falls in
        the window, and marks each one not already marked; returns the account.
        ``None`` when no break is on record — there is no window, so there is
        nothing to void, and the quiet return is the counterpart of
        :func:`canary.halt_dreaming`'s untaken branch.

        **The pool is never written to.**  This method inserts marker rows into
        this member's own table and nothing else; the score rows are read and
        left exactly as they were, for the reason :data:`VOID_TABLE` gives at
        length.  Running the sweep twice is therefore the same refusal — the
        second run reports the same :attr:`VoidSweep.refused` with
        :attr:`VoidSweep.marked` empty — which is the idempotence feature 132
        states for its own read, and the property that lets a nightly runner call
        this unconditionally.

        Rows are taken oldest-first by ``(created_at, id)`` so the account reads
        in production order and a report of a voided window is deterministic
        across nights.
        """
        halt = self._halt_store().first_halt()
        if halt is None:
            return None
        window = self._window_from(halt)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"SELECT {REPLAY_SCORE_ID_COLUMN}, "
                f"       {REPLAY_SCORE_CREATED_AT_COLUMN} "
                f"FROM {REPLAY_SCORE_TABLE} "
                f"ORDER BY {REPLAY_SCORE_CREATED_AT_COLUMN}, "
                f"         {REPLAY_SCORE_ID_COLUMN}"
            ).fetchall()
            pool_size = len(rows)
            marked: list[VoidMarker] = []
            already: list[VoidMarker] = []
            written = _utc_now() if marked_at is None else marked_at
            for raw_id, raw_produced in rows:
                # A row whose instant cannot be read cannot be placed in or out
                # of the window, so it is neither voided nor served: the sweep
                # stops rather than guessing a boundary for it.  That is a broken
                # pool, not a broken determinism — and the refusal names the
                # column, which is what an operator needs to repair it.
                produced = _parsed_instant("created_at", raw_produced)
                if not window.contains(produced):
                    continue
                score = _validated_score_id(raw_id)
                existing = self._read_row(connection, score)
                if existing is not None:
                    already.append(self._record_from_row(existing, changed=False))
                    continue
                candidate = VoidMarker(
                    score_id=score,
                    produced_at=produced,
                    detected_at=window.detected_at,
                    code_hash=window.code_hash,
                    tree_hash=window.tree_hash,
                    alert_kind=window.alert_kind,
                    status=window.status,
                    marked_at=written,
                    changed=True,
                )
                connection.execute(
                    f"INSERT INTO {VOID_TABLE} ({_MARKER_COLUMNS}) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        candidate.score_id,
                        candidate.produced_at.isoformat(),
                        candidate.detected_at.isoformat(),
                        candidate.code_hash,
                        candidate.tree_hash,
                        candidate.alert_kind,
                        candidate.status,
                        candidate.marked_at.isoformat(),
                    ),
                )
                stored = self._read_row(connection, score)
                if stored is None:
                    raise CanaryVoidMarkerError(
                        "the void marker vanished inside its own write; a "
                        "marker that cannot be read back is not persisted, and "
                        "the score it claims to have voided is still being "
                        "served"
                    )
                marked.append(self._record_from_row(stored, changed=True))
        return VoidSweep(
            window=window,
            marked=tuple(marked),
            already_marked=tuple(already),
            refused=tuple(marked) + tuple(already),
            pool_size=pool_size,
        )

    # -- Feature 144: the reads ---------------------------------------------

    def markers(self) -> tuple[VoidMarker, ...]:
        """Every void marker on record, oldest score first.

        The audit: *which scores has a determinism break cost us?*  Ordered by
        ``(produced_at, score_id)`` so the report reads in production order and a
        re-read is deterministic.  ``changed`` is ``False`` on every read-back;
        the bit names the call that wrote the row, and a read wrote nothing.
        """
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                f"SELECT {_MARKER_COLUMNS} FROM {VOID_TABLE} "
                "ORDER BY produced_at, score_id"
            )
            try:
                rows = cursor.fetchall()
            finally:
                cursor.close()
        return tuple(self._record_from_row(row, changed=False) for row in rows)

    def voided(self, score_id: Any) -> bool:
        """Whether ``score_id`` carries a void marker — asked of the record.

        The one-bit question, and deliberately distinct from the *derived*
        refusal :meth:`require_score_usable` applies: this answers "has a marker
        been written for this row?", while the guard answers "may this row be
        used?".  A row written after the break but not yet swept is not
        :meth:`voided` and is still refused, and keeping the two apart is what
        lets an operator see the difference between a sweep that has run and one
        that has not.
        """
        with closing(self._connect()) as connection:
            return self._read_row(connection, _validated_score_id(score_id)) is not None

    def unvoided_scores(self) -> tuple[dict[str, Any], ...]:
        """The pool rows this system may still use — feature 144's read.

        Every ``replay_score`` row that is **neither in the window nor marked**,
        in ``(created_at, id)`` order.  This is the read a dreaming or replay
        path makes, and it is the shape :meth:`tripwires.ReplayPool.survivors`
        takes for feature 132: the refusal applied for the caller rather than
        left as an exercise.

        **The refusal is derived, so there is no lag.**  A row written after the
        break is excluded whether or not :meth:`sweep` has run over it, because
        membership in the window is computed from the halt's own instant.  That
        matters for the feature's stated purpose — bad data must not "age into
        good data" — since a design that refused only what a sweep had already
        marked would serve a bad score for as long as the nightly sweep was
        late, which is exactly the window §12 says nobody notices.

        When no break is on record every row is returned: the canary held, so
        nothing is void.  Each row is a plain mapping of ``0109``'s eight
        columns — this store does not own the pool's value type and will not
        invent one, the same restraint :mod:`tripwires.layout` states for the
        shape it restates.
        """
        halt = self._halt_store().first_halt()
        window = None if halt is None else self._window_from(halt)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"SELECT {', '.join(REPLAY_SCORE_COLUMNS)} "
                f"FROM {REPLAY_SCORE_TABLE} "
                f"ORDER BY {REPLAY_SCORE_CREATED_AT_COLUMN}, "
                f"         {REPLAY_SCORE_ID_COLUMN}"
            ).fetchall()
            marked = {
                row[0]
                for row in connection.execute(
                    f"SELECT score_id FROM {VOID_TABLE}"
                ).fetchall()
            }
        survivors: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(zip(REPLAY_SCORE_COLUMNS, row))
            score_id = _validated_score_id(payload[REPLAY_SCORE_ID_COLUMN])
            payload[REPLAY_SCORE_ID_COLUMN] = score_id
            if score_id in marked:
                continue
            if window is not None:
                produced = _parsed_instant(
                    "created_at", payload[REPLAY_SCORE_CREATED_AT_COLUMN]
                )
                if window.contains(produced):
                    continue
            survivors.append(payload)
        return tuple(survivors)

    def require_score_usable(self, score_id: Any) -> None:
        """The guard: pass while a score may be used, refuse when it may not.

        The read-time refusal a dreaming or replay path consults before
        aggregating a score — the same shape
        :meth:`~canary.CanaryHaltStore.require_dreaming_allowed` gives the
        dreaming cycle's entrypoint and :mod:`tripwires.excise` gives the replay
        pool: the markers are never deleted from, and the refusal is derived
        from them plus the window, so it holds no matter which path wrote what.
        A caller that aggregates a void score has not been told it was fine; it
        has skipped the one door this feature leaves open.

        **A committed marker is required, not merely a window.**  A score inside
        the window with nothing marked for it yet is refused too, and the message
        says so plainly — that is the derived refusal
        :meth:`unvoided_scores` applies, and it is the one that matters for a row
        written between sweeps.  But a score with no marker *and* outside the
        window passes: there is nothing to refuse it on, and inventing a refusal
        would taint a row feature 144 never indicted.
        """
        score = _validated_score_id(score_id)
        halt = self._halt_store().first_halt()
        with closing(self._connect()) as connection:
            row = self._read_row(connection, score)
            if row is None:
                if halt is not None:
                    window = self._window_from(halt)
                    produced = self._produced_of(connection, score)
                    if produced is not None and window.contains(produced):
                        raise CanaryVoidMarkerError(
                            f"the score {score!r} was produced at "
                            f"{produced.isoformat()}, after the determinism "
                            f"break at {window.detected_at.isoformat()}: "
                            "feature 144 voids it, and no marker has been "
                            "written for it yet — sweep the pool before using "
                            "its scores"
                        )
                return None
            marker = self._record_from_row(row, changed=False)
        raise CanaryVoidMarkerError(
            f"the score {score!r} is {marker.status}: {marker.summary}; it was "
            "produced after a detected determinism break, and §12's recovery is "
            "to bisect the image diff and re-score the affected window rather "
            "than to aggregate a number the break may have moved",
            marker,
        )

    # -- The row plumbing ----------------------------------------------------

    @staticmethod
    def _produced_of(connection: sqlite3.Connection, score: str) -> Optional[datetime]:
        """When the pool row ``score`` was produced, or ``None`` if it is not there.

        A score id that names no pool row is not refused: the id may be one the
        caller has not written yet, or one from another deployment, and refusing
        it would be this feature indicting a row it never saw.  The guard's
        question is about a score's *taint*, and an absent row carries none.
        """
        cursor = connection.execute(
            f"SELECT {REPLAY_SCORE_CREATED_AT_COLUMN} FROM {REPLAY_SCORE_TABLE} "
            f"WHERE {REPLAY_SCORE_ID_COLUMN} = ?",
            (score,),
        )
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
        if row is None:
            return None
        return _parsed_instant("created_at", row[0])

    def _read_row(
        self, connection: sqlite3.Connection, score_id: str
    ) -> Optional[tuple]:
        """The stored marker row for ``score_id``, or ``None``.

        Keyed by the score's own id — a row's identity, the value the pool
        serves from — so a marker is a fact about one score rather than about a
        store row id a re-insert would mint anew.
        """
        cursor = connection.execute(
            f"SELECT {_MARKER_COLUMNS} FROM {VOID_TABLE} WHERE score_id = ?",
            (score_id,),
        )
        try:
            return cursor.fetchone()
        finally:
            cursor.close()

    @staticmethod
    def _record_from_row(row: Sequence[Any], *, changed: bool) -> VoidMarker:
        """Reconstruct one :class:`VoidMarker` from a stored row.

        Every field is re-validated by the value type's own constructor, so the
        read path and the write path hold the same record to the same window.  A
        row edited outside this package — a ``produced_at`` no longer after its
        ``detected_at``, a status that is not ``VOID`` — fails to reconstruct
        rather than loading as a plausible-looking taint.  ``changed`` is
        supplied by the caller because the row itself cannot know it.
        """
        return VoidMarker(
            score_id=row[0],
            produced_at=_parsed_instant("produced_at", row[1]),
            detected_at=_parsed_instant("detected_at", row[2]),
            code_hash=row[3],
            tree_hash=row[4],
            alert_kind=row[5],
            status=row[6],
            marked_at=_parsed_instant("marked_at", row[7]),
            changed=changed,
        )


# -- The module-level spellings --------------------------------------------------


def _resolve_url(
    database_url: Optional[str], env: Optional[Mapping[str, str]]
) -> Optional[str]:
    """The URL a module-level call runs against, or ``None`` when none is named.

    An explicit ``database_url`` wins over the environment, so a caller with a
    URL in hand never depends on ambient state.
    """
    if database_url is not None:
        return database_url.strip() or None
    source = os.environ if env is None else env
    return source.get(DATABASE_URL_ENV, "").strip() or None


def void_scores_after_break(
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[VoidSweep]:
    """Sweep the pool for feature 144 — the nightly runner's spelling.

    The module-level form of :meth:`CanaryVoidMarkerStore.sweep`, for a caller
    that has just watched feature 143's canary break and wants the feature rather
    than an object.  A deployment that names no store is refused *by name* rather
    than silently doing nothing, for the reason
    :func:`canary.halt_dreaming` refuses one: a voiding that quietly skipped its
    write would leave the pool serving scores the break may have moved while the
    nightly runner believed it had refused them — which is the failure mode this
    whole feature exists to rule out.

    Returns the sweep, or ``None`` when the canary held (no break on record), so
    a nightly runner that ran green observes a quiet return and nothing else.
    """
    url = _resolve_url(database_url, env)
    if url is None:
        raise CanaryVoidMarkerError(
            "void_scores_after_break voids every score produced after a "
            f"determinism break and nothing names a store: {DATABASE_URL_ENV} is "
            "unset (and no database_url was supplied), so the markers could not "
            "be written down. Feature 144's whole point is that bad data must not "
            "age into good data — a voiding that silently went nowhere would "
            "leave the pool serving exactly the scores this feature refuses"
        )
    return CanaryVoidMarkerStore(url).sweep()


def unvoided_scores(
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> tuple[dict[str, Any], ...]:
    """The pool rows still usable — the replay path's spelling of the read.

    The shape a replay loop wants: it holds no store object, it needs the scores
    it may aggregate, and the refusal must be applied for it rather than left as
    an exercise.  A deployment that names no store is refused by name here too —
    a replay path that could not tell whether its scores were void would be
    aggregating numbers it had no business trusting.
    """
    url = _resolve_url(database_url, env)
    if url is None:
        raise CanaryVoidMarkerError(
            f"unvoided_scores cannot answer which scores are usable and nothing "
            f"names a store: {DATABASE_URL_ENV} is unset (and no database_url "
            "was supplied). An unconfigured deployment is not the same fact as "
            "one whose canary held, and a caller that mistook the two would "
            "aggregate scores a determinism break may have moved"
        )
    return CanaryVoidMarkerStore(url).unvoided_scores()


def require_score_usable(
    score_id: Any,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> None:
    """The guard, opening its own store — the caller-side spelling.

    Passes while a score may be used and raises
    :class:`CanaryVoidMarkerError` carrying the stored marker when it may not
    (see :meth:`CanaryVoidMarkerStore.require_score_usable`).  A deployment that
    names no store passes vacuously: with no relational store there is no
    reference pair, no nightly canary and no break to void anything, so there is
    no window this guard could be holding — the same "no store, no status"
    answer :func:`canary.require_dreaming_allowed` gives, kept distinct because a
    caller that mistook an unconfigured deployment for a checked one would
    aggregate scores believing the canary had run.
    """
    url = _resolve_url(database_url, env)
    if url is None:
        return None
    CanaryVoidMarkerStore(url).require_score_usable(score_id)


def mark_void_score(
    score_id: Any,
    produced_at: Any,
    *,
    database_url: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    marked_at: Optional[datetime] = None,
) -> VoidMarker:
    """Mark one score void — the explicit door, opening its own store.

    The module-level form of :meth:`CanaryVoidMarkerStore.mark`, for a caller
    that already holds a score and its instant rather than a pool to sweep.  A
    deployment that names no store is refused by name, as above: the marker is
    the feature, and one that silently went unwritten would leave the score
    being served as though the break had not happened.
    """
    url = _resolve_url(database_url, env)
    if url is None:
        raise CanaryVoidMarkerError(
            f"mark_void_score persists feature 144's marker and nothing names a "
            f"store: {DATABASE_URL_ENV} is unset (and no database_url was "
            "supplied), so the marker could not be written down"
        )
    return CanaryVoidMarkerStore(url).mark(
        score_id, produced_at, marked_at=marked_at
    )


def build_void_marker_store(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[CanaryVoidMarkerStore]:
    """Build the void-marker store the composed application carries.

    The one-shot convenience the component builder uses, kept beside the class so
    a test and the factory construct it the same way.  Deliberately resolves
    rather than strict: the factory builds this component on every
    ``create_app()``, so it must succeed without a ``DATABASE_URL`` and compose
    ``None`` where the deployment has no relational store — a discoverable state,
    not an exception — rather than taking composition down for every unrelated
    feature in the workspace.  A caller that wants the store pointed at a URL uses
    :class:`CanaryVoidMarkerStore` — this function is the composition spelling,
    not the operator's.
    """
    return CanaryVoidMarkerStore.resolve(env)
