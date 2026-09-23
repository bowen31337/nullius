"""The revision cap's ladder rung, and the record of its use — feature 277.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 277: *System persists
the revision cap used per cycle, raising M to 40 once the pool holds 50 or more
worlds.*  docs/alpha-engine-prd.md §C5 puts ``M`` inside the loop this whole
member serves — *"Per outer iteration: hold the replay pool fixed, run ``M``
code revisions of ``π``, evaluate each on every stored tree, select the argmax
under §7"* — and §12.1's ladder table says what ``M`` is at each pool size:

    | 20–50 | Dreaming with ``M`` capped at 8–10 so the selection bar stays low |
    | 50+   | Full dreaming, ``M = 30–40``, 70/30 train/holdout split on worlds |

Feature 277's sentence takes the top rung — *raising M to 40 once the pool
holds 50 or more worlds* — and 40 is the figure §12.1 itself computes the bar
with (*"At ``M = 40`` (bar ≈ 2.72), ``σ_V ≈ 0.8`` and a target advantage of
0.3, this gives ``n > 53`` worlds"*), which is why the raise lands on 40 and
not somewhere inside the section's ``30–40``: the bar the ladder is calibrated
against is the bar at 40, and the M3 precondition's own threshold (*"≥ 50
worlds in the pool (§12.1)"*) is the boundary the raise fires on.

**The ladder's three rungs are three features, and this module states the
whole schedule without importing either sibling.**  The floor is feature
275's (``< 20``: do not run dreaming), and this module *delegates* to it —
:func:`revision_cap` calls :func:`dreaming.ladder.rejects_thin_pool`, so a
figure below the floor is refused in the floor's own word, ``pool_too_thin``,
by the floor's own one spelling of the rule.  The middle rung's ceiling is
feature 276's sentence (reject a revision count above 10 while the pool holds
between 20 and 50); this module spells the same 10 as the band's *cap* —
:data:`CAPPED_SWEEP_CAP` — because a schedule that answered no number below 50
would be a ladder with a missing rung, and the 10 is §12.1's own figure (the
*"capped at 8–10"* band at the count feature 276's refusal fixes).  The two
siblings do not import each other and are not imported here: the schedule
composes the floor because feature 277 depends on feature 275, and restates
the ceiling because a ladder is one thing spelled once.

**Why the cap is persisted — the half of the sentence a constant cannot
answer.**  Appendix B's meta-level selection bar is ``advantage > √(2 ln M) ·
σ_V / √n_worlds``, and feature 280 applies exactly that to the winning
revision.  The bar reads ``M``; a cycle that ran 40 revisions and was then
judged at a bar computed over 10 — or judged at a bar over an ``M`` nobody
could name — would have its multiple-testing width mis-stated by exactly the
factor the bar exists to control, and §12.1's whole warning (*"the dreaming
loop overfits its own replay pool … selecting the max over ``M`` revisions …
is the same multiple-testing problem one level up"*) is a warning about ``M``
growing unobserved.  So the cap a cycle used is a *fact about the store*
rather than a fact about the caller's memory: ``cycle_cap`` is this member's
own table — one row per cycle, append-only, the same member-owned stance
``pool_freeze`` takes — and the operator (or feature 280, reading ``M`` back)
asks the database, not the log.

**The schedule is a judgment over a count the caller already has.**
:func:`revision_cap` takes the pool's size and answers the cap — the same
verdict-gate shape :func:`dreaming.ladder.rejects_thin_pool` takes, and for
the same reason: a verdict is not a count, and the count is the caller's to
supply.  The figure is the one this member already computes —
:func:`dreaming.cycle.pool_commitment` returns it, and a feature-270 hold
records it as ``world_count`` at the moment it opened — so in the loop the
count is already in the caller's hand when it asks for the cap.

**The record takes the figure, and never counts the pool.**  The freeze's
``open()`` counts the pool because the *commitment* is its own subject; the
cap's record has no subject that needs a count — its subject is a decision
over a figure — so :func:`record_cycle_cap` takes the figure exactly as the
floor does, and the row carries ``world_count`` beside ``revision_cap`` so the
record says *what the cap was decided over* and not merely *what it decided*.
What the record does refuse is a database that holds no pool, for the reason
the freeze refuses one: a cap recorded against a database with no
``replay_score`` and no ``bootstrap_world`` caps nothing, and the row would
assert a tournament over a pool that is not there.  That refusal is a probe
of the pool's *presence* (:func:`dreaming.layout.pool_tables_present`), never
of its rows — the record does not read a single world.

**One row per cycle-occurrence, not per iteration name.**  §12.1's cycle may
legitimately open, close and open again — a retry after a failed sweep, an
operator releasing a stuck hold — and the retried cycle is *re-decided*: the
pool may have grown between the attempts, so the retry's cap is a new fact
with its own row, exactly as each hold window is its own row in
``pool_freeze``.  Ids are minted per occurrence (see :func:`_cap_id`) so a
retry recorded inside the same second never collides on the primary key —
the lesson ``_hold_id`` states for holds, restated for caps — and the table
is append-only with no unique index and no triggers: a cap is a judgment, not
a hold, so there is nothing to guard and nothing to close, only history to
keep, ordered by ``(recorded_at, id)`` per the §12 ordering rule every store
in this workspace restates.

**The vocabulary is the cap's own, and the member's one spellings are
reused behind it.**  Two new siblings under
:class:`~dreaming.errors.DreamingError`: :class:`~dreaming.errors.
CapRequestError` for the ask's own facts (an iteration id that names nothing,
an instant that is not timezone-aware, a URL this member cannot speak, or no
URL named at all) and :class:`~dreaming.errors.CapRecordError` for the
store's own facts (a database with no pool to cap; a recorded row whose stamp
will not read back).  What this module does *not* do is respell the rules it
shares with feature 270 — :func:`dreaming.cycle.validated_iteration_id`,
:func:`dreaming.cycle.sqlite_path` and the stamp pair ``_stamp`` /
``_parsed_instant`` are the member's one spellings of what an iteration id
is, what a ``sqlite:///`` URL names and what a row's instant looks like, and
a vocabulary spelled twice says two different things.  Their refusals are
*translated at this seam* into the cap's classes — the same discipline the
workspace states for error vocabularies across member boundaries, applied
inside the member — so a caller of the cap never meets a
:class:`~dreaming.errors.FreezeRequestError` for an act that held nothing.
Neither class carries a code word: feature 275's ``pool_too_thin`` is
mandated by its own sentence, and feature 270's codes name pool-facts; the
cap's refusals name their subject in their first words, and the thin-pool
refusal this module *does* mint is feature 275's, delegated, in feature
275's word.

No new component — feature 270's single ``"dreaming"`` component is the
member's whole composition, and the cap is reached the way the floor is, as
a free function beside the store.  No seat edit, no migration, no third
party: ``hashlib``, ``secrets``, ``sqlite3``, ``datetime`` and ``os``, so the
factory's scan — which imports this package to fire its ``@register`` — pays
nothing for the cap.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from .cycle import _parsed_instant, _stamp, sqlite_path, validated_iteration_id
from .errors import CapRecordError, CapRequestError, FreezeRequestError, PoolFrozenError
from .ladder import LADDER_FLOOR_WORLDS, rejects_thin_pool, validated_floor
from .layout import DATABASE_URL_ENV, POOL_TABLES, pool_tables_present

__all__ = [
    "CAPPED_SWEEP_CAP",
    "CYCLE_CAP_TABLE",
    "FULL_DREAMING_CAP",
    "FULL_DREAMING_WORLDS",
    "CapRecord",
    "cycle_cap_schema",
    "cycle_caps",
    "record_cycle_cap",
    "revision_cap",
]

#: The pool size the raise fires on — §12.1's ``50+`` rung, the M3
#: precondition's *"≥ 50 worlds in the pool (§12.1)"*, and feature 277's own
#: *"once the pool holds 50 or more worlds"*.  The edge is inclusive: 50
#: worlds is full dreaming, 49 is the capped sweep.
FULL_DREAMING_WORLDS = 50

#: The cap the raised rung runs at — §12.1's *"Full dreaming, ``M = 30–40``"*
#: at the figure the section's own bar calculation uses (*"At ``M = 40``
#: (bar ≈ 2.72) … this gives ``n > 53`` worlds"*).  40 rather than anywhere
#: else in the band because the ladder is calibrated at 40: the bar, the
#: ``n > 53`` and the raise are one calculation, and splitting them across
#: two figures would calibrate the bar against an ``M`` the loop never runs.
FULL_DREAMING_CAP = 40

#: The 20–50 rung's cap — §12.1's *"Dreaming with ``M`` capped at 8–10 so the
#: selection bar stays low"* at the count feature 276's refusal fixes
#: (*"rejects a revision count above 10"*).  Stated here so the ladder has
#: one spelling of the band's cap; the *refusal* that enforces the ceiling is
#: feature 276's sentence, not this module's — this module only answers what
#: a cycle on that rung runs under, and a schedule that answered no number
#: below 50 would be a ladder with a missing rung.
CAPPED_SWEEP_CAP = 10

#: The table this member's cap record lives in — one row per cycle, appended
#: and never rewritten.  Member-owned and created lazily beside the one
#: module that writes it, on the same terms as :data:`dreaming.cycle.
#: FREEZE_TABLE`: the table has one writer, so its shape is a fact about this
#: feature rather than about the database's history, and the shared migration
#: chain is order-sensitive files this member does not own.
CYCLE_CAP_TABLE = "cycle_cap"

#: The row's column names, in declaration order — the one spelling of what a
#: cap row is made of, shared by the DDL, the insert and the read-back so the
#: three cannot disagree on a column order, the failure a positional
#: ``SELECT *`` invites.
_ROW_COLUMNS = (
    "id",
    "iteration_id",
    "recorded_at",
    "world_count",
    "revision_cap",
)

#: The record table's body.  ``world_count`` is carried beside
#: ``revision_cap`` deliberately — the row says *what the cap was decided
#: over*, not merely *what it decided*, so an operator reading a cycle's
#: record can see the rung the cycle was on and not just the cap it ran
#: under.  No unique index and no triggers: the table is append-only history
#: (a retried cycle is a new occurrence with its own row), there is nothing
#: to guard — a cap is a judgment, not a hold — and nothing to close.
_TABLE_BODY = """
(
    id           TEXT    NOT NULL PRIMARY KEY,
    iteration_id TEXT    NOT NULL,
    recorded_at  TEXT    NOT NULL,
    world_count  INTEGER NOT NULL,
    revision_cap INTEGER NOT NULL
)
"""

_SCHEMA = f"""
-- Feature 277: the revision cap a dreaming cycle ran under, one row per
-- cycle.  Append-only and never rewritten: a retried cycle is re-decided
-- over the pool as it stands, so it is a new occurrence with its own row,
-- and "what cap did this cycle run under?" is a question the table answers
-- after the fact -- which is the whole reason the cap is persisted rather
-- than remembered.  Appendix B's selection bar reads M, and a bar computed
-- over an M nobody recorded is a bar over a number nobody ran.
--
-- `world_count` is the pool's size the cap was decided over -- the same
-- figure a feature-270 hold records as `world_count` -- carried beside the
-- cap so the record names its own rung of §12.1's ladder.
CREATE TABLE IF NOT EXISTS {CYCLE_CAP_TABLE} {_TABLE_BODY};
"""

#: The insert a record performs.  A plain ``INSERT`` with no ``ON CONFLICT``
#: arm: the id is minted per occurrence, so there is nothing to conflict
#: with, and an upsert that rewrote an existing row would be the one history
#: rewrite this table exists not to perform.
_INSERT = f"""
INSERT INTO {CYCLE_CAP_TABLE} ({", ".join(_ROW_COLUMNS)})
VALUES (?, ?, ?, ?, ?)
"""

#: The whole history, oldest first — the audit read, ordered by
#: ``(recorded_at, id)`` so two reads of one history return the same
#: sequence whatever the storage engine's accident.
_SELECT_ALL = (
    f"SELECT {', '.join(_ROW_COLUMNS)} FROM {CYCLE_CAP_TABLE} "
    "ORDER BY recorded_at, id"
)


def cycle_cap_schema() -> str:
    """The DDL that brings a database to the cap record's shape, idempotently.

    One statement: the table.  No guards — a cap is a judgment rather than a
    hold, so there is no pool write to refuse and no window to close — and no
    unique index — the history is append-only, and a retried cycle is a new
    occurrence whose row the table exists to keep.

    Returned as text rather than executed, for the reason
    :func:`dreaming.cycle.cycle_freeze_schema` is: the DDL is then
    inspectable — a reader can see what the record is made of without
    opening a database, and a test can assert the shape without one.
    """
    return _SCHEMA


def _validated_world_count(value: Any) -> int:
    """Check that ``value`` is a pool size, or refuse it as the cap's own ask.

    The same rule :func:`dreaming.ladder._validated_figure` states for the
    floor — a pool's size is a non-negative whole number, and a ``bool`` is
    refused where a count belongs because ``True`` is ``1`` in Python — but
    refused in *this* module's vocabulary rather than the ladder's: the
    figure arrives here as part of a record's ask, and a caller of the cap
    must not meet the floor's word for a malformed ask of its own.  The two
    spellings agree on the rule and split on the vocabulary, which is the
    seam discipline the workspace states for error classes.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapRequestError(
            f"a pool's size is a world count — got {value!r} "
            f"({type(value).__name__}); the cap is decided over the pool a "
            "cycle is about to walk, and a value that is not a whole number "
            "names no pool a cap can be decided over"
        )
    if value < 0:
        raise CapRequestError(
            f"a pool's size is a non-negative world count — got {value!r}; "
            "a pool holds zero worlds or more, and a negative figure names "
            "no pool a cap can be decided over"
        )
    return value


def _validated_boundary(value: Any) -> int:
    """Check that ``value`` is the raise boundary, or refuse it.

    The boundary is a world count like the floor is — a non-negative whole
    number, ``bool`` refused — validated in this module's vocabulary because
    it is this module's own rung edge: §12.1's ``50+``, the count at which
    the capped sweep becomes full dreaming.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CapRequestError(
            f"the raised rung begins at a world count — got {value!r} "
            f"({type(value).__name__}); §12.1's ladder raises M once the "
            "pool holds a count of worlds, and a value that is not a whole "
            "number names no rung the raise can begin at"
        )
    if value < 0:
        raise CapRequestError(
            f"the raised rung begins at a non-negative world count — got "
            f"{value!r}; a negative boundary would place full dreaming "
            "below the ladder's floor, which is no ladder at all"
        )
    return value


def revision_cap(
    world_count: Any,
    *,
    floor: Any = LADDER_FLOOR_WORLDS,
    full_dreaming: Any = FULL_DREAMING_WORLDS,
) -> int:
    """The revision cap a cycle runs under — feature 277's judgment.

    A pure function of the pool's size: 40 once the pool holds 50 or more
    worlds, 10 on the rung between the floor and 50, and a refusal below the
    floor.  Three rungs, one ladder, §12.1's table in one answer:

    * ``world_count < floor`` — **refused**, by
      :func:`dreaming.ladder.rejects_thin_pool` in the ladder's own word
      (``pool_too_thin``): a pool below the floor is feature 275's refusal,
      and a cycle that cannot run needs no cap;
    * ``floor <= world_count < full_dreaming`` —
      :data:`CAPPED_SWEEP_CAP`, §12.1's *"M capped at 8–10 so the selection
      bar stays low"*;
    * ``world_count >= full_dreaming`` — :data:`FULL_DREAMING_CAP`,
      §12.1's *"full dreaming, M = 30–40"* at the 40 its own bar
      calculation uses.

    ``floor`` is passed straight through to the ladder's judgment (the
    keyword is the floor's own ``gate``), so the two spellings of the
    bottom rung cannot disagree; ``full_dreaming`` is the raise's edge,
    §12.1's 50 by default, refused when it falls below the floor — a
    boundary under the floor leaves no rung between them and would hand
    every admissible pool the cap §12.1 reserves for a pool of 50 or more.

    Refuses, in this order, each naming what it is about:

    1. a ``world_count`` that is not a non-negative whole number — a pool's
       size is a world count, and a value that is not one names no pool a
       cap can be decided over (:class:`~dreaming.errors.CapRequestError`);
    2. a ``floor`` that is not a non-negative whole number — refused by the
       ladder's own :func:`~dreaming.ladder.validated_floor`, in the
       ladder's vocabulary, because the floor is feature 275's fact;
    3. a ``full_dreaming`` that is not a non-negative whole number, or one
       below the floor — the first names no rung and the second erases the
       rung between them (:class:`~dreaming.errors.CapRequestError`);
    4. a figure below the floor — the pool is too thin to dream on, and the
       refusal is feature 275's own, delegated, in its own word
       (:class:`~dreaming.errors.PoolTooThinError`).
    """
    figure = _validated_world_count(world_count)
    floor_count = validated_floor(floor)
    boundary = _validated_boundary(full_dreaming)
    if boundary < floor_count:
        raise CapRequestError(
            f"the raised rung begins at or above the ladder floor — got a "
            f"boundary of {boundary} under a floor of {floor_count}; "
            "§12.1's ladder holds a capped sweep between the two, and a "
            "boundary below the floor leaves no rung between them, handing "
            "every admissible pool the raised cap the section reserves for "
            f"a pool of {boundary} or more"
        )
    rejects_thin_pool(figure, gate=floor_count)
    if figure >= boundary:
        return FULL_DREAMING_CAP
    return CAPPED_SWEEP_CAP


class CapRecord:
    """One recorded revision cap — a row, as this member reads it.

    The row's five facts and nothing derived: which cycle ran under the cap,
    when its cap was decided, the pool's size the cap was decided over, and
    the cap itself.  Held as an immutable value rather than a live cursor
    for the reason :class:`dreaming.cycle.FreezeRecord` gives: a record is
    what audits of the loop are made of, and a caller reading one must not
    be holding a handle a later record can move under it.
    """

    __slots__ = (
        "id",
        "iteration_id",
        "recorded_at",
        "revision_cap",
        "world_count",
    )

    def __init__(
        self,
        *,
        id: str,
        iteration_id: str,
        recorded_at: str,
        world_count: int,
        revision_cap: int,
    ) -> None:
        self.id = id
        self.iteration_id = iteration_id
        self.recorded_at = recorded_at
        self.world_count = world_count
        self.revision_cap = revision_cap

    @property
    def recorded(self) -> dt.datetime:
        """When the cap was decided, as the aware instant the row encodes.

        A stamp that will not parse is refused in this module's vocabulary
        (:class:`~dreaming.errors.CapRecordError`) rather than the freeze's:
        by the time it is read the row is in the store either way, but the
        caller asked the cap's record, and a caller that met feature 270's
        word here would read a *held pool* refusal out of a table that holds
        nothing.
        """
        try:
            return _parsed_instant(self.recorded_at)
        except PoolFrozenError as refusal:
            raise CapRecordError(
                f"a recorded cap stamp must be ISO-8601 with a timezone — "
                f"got {self.recorded_at!r}; the stamp is part of the "
                "cycle's own history and a value that cannot be read back "
                "is one that was never written by this member"
            ) from refusal

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call."""
        return {
            "id": self.id,
            "iteration_id": self.iteration_id,
            "recorded_at": self.recorded_at,
            "world_count": self.world_count,
            "revision_cap": self.revision_cap,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CapRecord):
            return NotImplemented
        return self.row() == other.row()

    def __hash__(self) -> int:
        return hash(
            (
                self.id,
                self.iteration_id,
                self.recorded_at,
                self.world_count,
                self.revision_cap,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CapRecord(iteration_id={self.iteration_id!r}, "
            f"recorded_at={self.recorded_at!r}, "
            f"world_count={self.world_count!r}, "
            f"revision_cap={self.revision_cap!r})"
        )


def _record_from_row(row: tuple) -> CapRecord:
    """Unpack one cap row into the record it holds, in column order."""
    id_, iteration_id, recorded_at, world_count, revision_cap = row
    return CapRecord(
        id=id_,
        iteration_id=iteration_id,
        recorded_at=recorded_at,
        world_count=int(world_count),
        revision_cap=int(revision_cap),
    )


def _cap_id(iteration_id: str, recorded_at: str) -> str:
    """The id a cap record is named by — iteration, instant, and a draw.

    Deterministic in the iteration and the instant and *distinct* for every
    call, which is the property a per-cycle table keyed by occurrence needs:
    §12.1's cycle may legitimately retry — release the hold, let the pool
    grow, open again — and the retried cycle is re-decided, so it is a new
    record even inside the same second, with its own row and its own id.
    Ids derived from ``(iteration, instant)`` alone would collide on the
    primary key for exactly that retry, and the collision would surface as
    an ``IntegrityError`` naming a constraint nobody violated — the failure
    mode :func:`dreaming.cycle._hold_id` states for holds, restated here
    before it can happen for caps.

    A sha256 hex string rather than a UUID for the reason the hold's id is:
    the inputs are text of unbounded shape and a UUID's fixed layout would
    either truncate them or require a namespace this member has no use for.
    """
    digest = hashlib.sha256(
        f"{iteration_id}\n{recorded_at}\n{secrets.token_hex(16)}\n".encode()
    ).hexdigest()
    return f"cap-{digest[:32]}"


def _validated_iteration(value: Any) -> str:
    """The member's one iteration-id rule, translated into the cap's word.

    :func:`dreaming.cycle.validated_iteration_id` is the one spelling of
    what names a dreaming iteration — an id is text and not blank — and this
    module reuses it rather than restating the rule, translating its refusal
    at the seam: a caller recording a cap that handed a bad id must not meet
    feature 270's request class for an act that held nothing, the same seam
    discipline the workspace states for error vocabularies across members.
    """
    try:
        return validated_iteration_id(value)
    except FreezeRequestError as refusal:
        raise CapRequestError(
            f"a dreaming iteration is named by a non-empty string — got "
            f"{value!r} ({type(value).__name__}); the iteration id is how a "
            "cycle's cap record is attributed, and a record that cannot say "
            "which cycle it was decided for would leave an operator with a "
            "cap nobody could place"
        ) from refusal


def _stamped_instant(value: Any) -> str:
    """The member's one stamp rule, translated into the cap's word.

    :func:`dreaming.cycle._stamp` is the one spelling of what a recorded
    instant looks like — aware, UTC, second-truncated, ``Z``-suffixed — and
    reusing it is what keeps a cap row's stamp and a hold row's stamp the
    same shape in the same database.  A naive or non-datetime instant is
    refused here in the cap's vocabulary for the reason the id above is: the
    ask was the cap's, not the freeze's.
    """
    try:
        return _stamp(value)
    except FreezeRequestError as refusal:
        raise CapRequestError(
            f"the instant a cap was recorded at is a timezone-aware "
            f"datetime — got {value!r} ({type(value).__name__}); a naive "
            "instant would place a cycle's decision hours away from the "
            "process that made it, in whatever zone the host happens to "
            "keep, and nothing in the row would look wrong"
        ) from refusal


def _cap_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the store a cap is recorded in: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.cycle.open_cycle_freeze` takes
    — an explicit URL first, then the deployment's ``DATABASE_URL`` — and
    the same refusal stance: an act that means to write and resolves nothing
    is refused by name rather than answered with ``None``, because a cap
    "recorded" over no database is a cap the store does not hold and the bar
    reading it back would find nothing.  A URL this member cannot speak is
    refused in the cap's vocabulary, translated at the seam from the one
    spelling of what a ``sqlite:///`` URL names.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise CapRequestError(
            f"recording a cycle's revision cap needs the database the replay "
            f"pool lives in — pass it explicitly or set {DATABASE_URL_ENV}. "
            "A cap recorded over no database is a cap the store does not "
            "hold: Appendix B's selection bar reads M back from the record, "
            "and a bar computed over an M nobody recorded is a bar over a "
            "number nobody ran"
        )
    try:
        return sqlite_path(url)
    except FreezeRequestError as refusal:
        raise CapRequestError(
            f"the revision cap's store is the database the replay pool "
            f"lives in, and the URL given does not name one this member can "
            f"speak — see the refusal it raised: {refusal}. The cap shares "
            "the pool's database rather than growing a second store a "
            "deployment could point at a different file, because a cap "
            "decided over one pool and recorded in another is a record "
            "about nothing"
        ) from refusal


def _ensure_schema(connection: sqlite3.Connection, path: Path) -> None:
    """Bring the database to the record's shape, over a pool that is there.

    The pool-presence probe comes **before** the DDL, so a refused record
    leaves no trace: a database that holds no pool gets no ``cycle_cap``
    table, exactly as :meth:`dreaming.cycle.CycleFreeze.ensure_schema` refuses
    before creating ``pool_freeze`` over nothing.  The refusal is the cap's
    own (:class:`~dreaming.errors.CapRecordError`) rather than the freeze's,
    for the reason every translation in this module gives: the caller asked
    about a cap, and *the pool is frozen* names a fact about a hold this act
    never took.

    The probe reads ``sqlite_master`` and never a pool row — the record
    never counts the pool, it only refuses to record over a pool that is not
    there.
    """
    present = pool_tables_present(connection)
    missing = [table for table in POOL_TABLES if table not in present]
    if missing:
        raise CapRecordError(
            f"the database at {path} holds no {' and no '.join(missing)} "
            "table, so there is no pool here to cap — a revision cap is "
            "decided over the pool a cycle is about to walk, and a record "
            "written against a database with no pool would assert a "
            "tournament over nothing while the cycle believed its ladder "
            f"rung was measured. Point {DATABASE_URL_ENV} at the database "
            "the replay pool lives in, or migrate it"
        )
    connection.executescript(cycle_cap_schema())


def record_cycle_cap(
    iteration_id: Any,
    world_count: Any,
    *,
    floor: Any = LADDER_FLOOR_WORLDS,
    full_dreaming: Any = FULL_DREAMING_WORLDS,
    database_url: str | None = None,
    recorded_at: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> CapRecord:
    """Decide the cap and persist it as this cycle's record — feature 277's call.

    The one act the feature's sentence names: take the iteration the cycle
    is named by and the pool's size (the figure the caller already holds —
    the same count a feature-270 open records as ``world_count``), decide
    the cap by the ladder (:func:`revision_cap`), and write one row into
    ``cycle_cap`` carrying both.  Returns the :class:`CapRecord` written, so
    the caller that is about to run ``M`` revisions holds the ``M`` it is
    entitled to and the store holds the same fact for everyone after it.

    **The cap is decided here, not accepted.**  The caller cannot hand in a
    cap of its own; the row's ``revision_cap`` is always the schedule's
    answer over the row's ``world_count``, so the record cannot disagree
    with the ladder and an operator reading the table reads §12.1 itself,
    rung by rung, cycle by cycle.

    Refuses, in this order, each naming what it is about:

    1. an ``iteration_id`` that is not non-empty text, a ``world_count``
       that is not a non-negative whole number, a ``floor`` or
       ``full_dreaming`` that is not a world count, or a boundary below the
       floor — the ask's own facts, refused before anything is read or
       written (:class:`~dreaming.errors.CapRequestError`, and the floor in
       the ladder's own word);
    2. a ``world_count`` below the floor — the pool is too thin to dream
       on, refused by the ladder in its own word
       (:class:`~dreaming.errors.PoolTooThinError`), before any database is
       opened;
    3. a ``recorded_at`` that is not a timezone-aware datetime, or a URL
       that names no database or one this member cannot speak
       (:class:`~dreaming.errors.CapRequestError`);
    4. a database that holds no pool
       (:class:`~dreaming.errors.CapRecordError`) — and refused *before*
       the table is created, so a refused record leaves no trace.

    ``recorded_at`` defaults to the current UTC instant truncated to the
    second, and is a parameter so a test or a replayed script can stamp a
    deterministic instant — the same reason the pool's own authoring takes
    one.
    """
    iteration = _validated_iteration(iteration_id)
    figure = _validated_world_count(world_count)
    cap = revision_cap(figure, floor=floor, full_dreaming=full_dreaming)
    instant = _stamped_instant(recorded_at if recorded_at is not None else dt.datetime.now(dt.UTC))
    path = _cap_path(database_url, env)
    record_id = _cap_id(iteration, instant)
    with closing(sqlite3.connect(path)) as connection, connection:
        _ensure_schema(connection, path)
        connection.execute(_INSERT, (record_id, iteration, instant, figure, cap))
    return CapRecord(
        id=record_id,
        iteration_id=iteration,
        recorded_at=instant,
        world_count=figure,
        revision_cap=cap,
    )


def cycle_caps(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[CapRecord, ...]:
    """Every cap this database records, oldest first — the audit read.

    The account an operator (or feature 280's bar, reading ``M`` back) asks
    for: which cycle ran under which cap, over how large a pool, and when it
    was decided.  Ordered by ``(recorded_at, id)`` so two reads of one
    history return the same sequence whatever the storage engine's accident
    — the §12 ordering rule every store in this workspace restates — with a
    retried cycle's re-decision standing beside the attempt it replaced,
    because both were true and the table is history, not a register.

    Resolves its store exactly as :func:`record_cycle_cap` does and refuses
    the same two ways: no database named
    (:class:`~dreaming.errors.CapRequestError`), and a database that holds
    no pool (:class:`~dreaming.errors.CapRecordError`) — a database without
    the pool holds no dreaming cycles and so no caps, and answering ``()``
    there would read *no cycle ever dreamed* off a store that never could.
    A pool with no records yet answers ``()`` after creating the table
    lazily, which is the state between a migrated deployment and its first
    dreaming cycle.
    """
    path = _cap_path(database_url, env)
    with closing(sqlite3.connect(path)) as connection:
        _ensure_schema(connection, path)
        rows = connection.execute(_SELECT_ALL).fetchall()
    return tuple(_record_from_row(row) for row in rows)
