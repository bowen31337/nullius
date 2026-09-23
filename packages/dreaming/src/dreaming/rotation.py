"""The holdout's per-cycle rotation, and the record of it — feature 279.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 279: *System rotates
the holdout split every cycle, persisting which worlds were held out per
iteration.*  docs/alpha-engine-prd.md §12.1 puts the rotation on the ladder's
top rung — *"50+: Full dreaming, ``M = 30–40``, 70/30 train/holdout split on
worlds, holdout rotated each cycle"* — and the section's risk table names the
failure the rotation is the mitigation for: *"Dreaming overfits the pool …
Cap ``M`` per §10.3.1; rotate the 70/30 split; block dreaming below 20
worlds."*  docs/nullius-tech-architecture.md §10.3.1 spells the call with the
clause as its own argument — ``train, holdout = pool.split(0.7,
rotate_each_cycle=True)`` — and §12 of the same document is why the argument
must be honoured rather than defaulted: *"Non-determinism does not announce
itself; it just slowly makes every conclusion wrong."*

**Why the holdout must rotate at all.**  Feature 278's split protects the
*report* from the *selection* — but only within one cycle.  Across cycles, a
holdout that never moves is a holdout the loop can *learn*: the winner of
every cycle is selected on the same 70% and reported on the same 30%, so
``M`` winners in a row each had the same worlds to flatter, and §12.1's
warning — *"the dreaming loop overfits its own replay pool … selecting the
max over ``M`` revisions … is the same multiple-testing problem one level
up"* — arrives one level up again, spread over time instead of over a single
tournament.  A holdout that cannot move also cannot be *audited for moving*:
the architecture's own detector for the risk table's failure is *"holdout-
world score diverges from train-world score"*, and a divergence over a fixed
30% is indistinguishable from a policy that memorised those worlds.
Rotation spreads every world across both halves over the cycles — no world
is the grader forever, none the graded forever — which is what makes the M3
exit criterion's reading (*"evaluated on worlds held out of the dreaming
loop"*) a claim about transfer rather than about tenancy.

What it is
----------

Two acts, one per clause of the sentence, and the record that joins them:

* :func:`cycle_rotation` — the *rotates* half, and the whole of this
  module's own law: **a cycle's rotation is its own name.**  The iteration
  id — the one identity every per-cycle record in this member already
  carries, the hold row's and the cap row's — is validated by the member's
  one iteration rule (translated into this module's vocabulary) and answered
  as the rotation discriminator feature 278's split folds into every world's
  rank.  ``split_pool(worlds, rotation=cycle_rotation("cycle-7"))`` is
  therefore *the* split of cycle 7, spelled through feature 278's own seam
  with no second spelling of the arithmetic;
* :func:`record_cycle_holdout` — the *persisting* half, the one act the
  sentence names: resolve the database the deployment names, read the pool's
  worlds (:func:`dreaming.split.pool_worlds`' union, reused), take the split
  at the cycle's own rotation, and write **one row per cycle** naming the
  iteration and carrying **which worlds were held out** — the holdout half
  in the split's own rank order, beside the pool's size and the fraction the
  split was taken by, so the row says *which* 70/30 of *which* pool it was
  rather than only that it was one.

And the audit read, :func:`cycle_holdouts` — every holdout this database
records, oldest first, the account an operator asks for after the fact:
*which worlds did each cycle report on?*

**Why the rotation is the iteration's own name, and not a counter or a
digest of one.**  Three properties, each load-bearing:

* **deterministic and recomputable** — the same cycle name answers the same
  holdout in any process (§12's determinism contract, restated for a
  partition), and an operator holding a recorded row can recompute its
  holdout from the row's own ``iteration_id`` and the pool, with nothing but
  feature 278's algorithm — a record that can only be believed, never
  checked, is not a record of a split;
* **free of the history it is recorded into** — a rotation derived from the
  *count* of prior rows would make every cycle's holdout a fact about its
  position in the table: a retried cycle would shift every later cycle's
  rotation, a restored backup would change holdouts yet to come, and the
  append-only history this member keeps would silently become an input to
  the splits it describes — a log that changes the future is not a log; and
* **one spelling with the split's own seam** — feature 278's ``rotation``
  keyword is any text, and the per-cycle discriminator this module answers
  is the cycle's name itself, so a caller taking the split directly during a
  cycle (to mark ``replay_score`` rows through :class:`~dreaming.split.
  PoolSplit.is_holdout`) and this module recording the cycle's holdout run
  *one* split, not two that merely agree.

Two cycle names could still collide on a holdout by digest accident — the
rank is uniform, not injective — but with six or more holdout seats over a
floor-sized pool the collision is an event no run of the loop arranges, and
the property the loop needs is not *never the same holdout twice* but *no
world held out or selected on by standing*, which the digest's uniformity
buys and §12.1's sentence asks for.

What is persisted, and what deliberately is not
-----------------------------------------------

**The holdout half, and only the holdout half.**  The sentence names it —
*which worlds were held out* — and feature 278's module states the division
in advance: the split writes nothing because *"feature 279's sentence is the
one that persists the holdout per iteration, and a split this module wrote
would be a record feature 279 already owns."*  The train half is not carried
beside it: the train half is the complement at the moment of the split, the
row's ``world_count`` says how large the pool it was complemented from was,
and a caller that needs the selection half recomputes it — from the pool, at
the row's own rotation, through feature 278's seam — rather than reading a
second list this member would have to keep agreeing with the first.

**The record is decided here, not accepted.**  A caller cannot hand in a
holdout, a split, or a rotation of its own spelling: the row's worlds are
always the split's answer at the row's own ``iteration_id`` over the pool as
the store holds it — the same stance :func:`dreaming.cap.record_cycle_cap`
takes for the cap ("the record cannot disagree with the ladder"), restated
for the halves: a record that could disagree with the split would be two
claimants to one cycle's reporting half.

**One row per cycle-occurrence, not per iteration name.**  §12.1's cycle may
legitimately open, close and open again, and the retried cycle is
re-decided — the pool may have grown between the attempts, so the retry's
split is a new fact with its own row, exactly as each hold window is its own
row in ``pool_freeze`` and each cap decision its own row in ``cycle_cap``.
Ids are minted per occurrence (:func:`_holdout_id`) so a retry recorded
inside the same second never collides on the primary key.  The table is
append-only with no unique index and no triggers: a holdout record is a
judgment's persistence, not a hold — there is nothing to guard and nothing
to close, only history to keep, ordered by ``(recorded_at, id)`` per the
§12 ordering rule every store in this workspace restates.

``cycle_holdout`` is this member's own table — member-owned, created lazily
beside the one module that writes it, never migrated in the shared chain,
for the same reason :data:`dreaming.cycle.FREEZE_TABLE` and
:data:`dreaming.cap.CYCLE_CAP_TABLE` are: the table has one writer, so its
shape is a fact about this feature rather than about the database's history,
and the shared migration chain is order-sensitive files this member does not
own.  The pool's own two tables are read and never touched, and the
``is_holdout`` flag ``0109`` carries on ``replay_score`` is written by the
evaluator's own writer, not by this module — the record names the worlds;
marking the rows is the replay path's act.

**The refusals are the rotation's own pair**, ask and store
(:class:`~dreaming.errors.HoldoutRequestError`,
:class:`~dreaming.errors.HoldoutRecordError`), under the one
:class:`~dreaming.errors.DreamingError` base — the split the cap, the
ceiling, the split, the comparison, the transfer and the bar all state, and
for the same reason: a caller that must react differently to *your cycle
could not be named* and *there is no pool here to hold worlds out of*
cannot catch one class and tell them apart.  The member's shared rules are
reused behind the vocabulary and *translated at this seam* — the iteration
rule and the URL translation from :mod:`dreaming.cycle`, the fraction rule
and the pool's membership query from :mod:`dreaming.split` — so a caller of
the rotation never meets the freeze's or the split's word for an act that
held and split nothing.  The one refusal this module never mints for itself
is the thin pool's: a pool below the ladder floor is feature 275's fact,
refused by the split's own judgment in the floor's own word, the same
delegation every rung of this member performs.

No new component — feature 270's single ``"dreaming"`` component is the
member's whole composition, and the rotation is reached the way the floor,
the cap, the ceiling, the split, the comparison, the transfer and the bar
are, as free functions beside the store.  No seat edit, no migration, no
third party: ``json``, ``hashlib``, ``secrets``, ``sqlite3``, ``datetime``
and ``os`` — ``json`` the one module of the set this member had not already
reached for, and stdlib's text encoding of a list of world ids is the whole
of the record's holdout half.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import secrets
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from typing import Any

from .cycle import _parsed_instant, _stamp, sqlite_path, validated_iteration_id
from .errors import (
    FreezeRequestError,
    HoldoutRecordError,
    HoldoutRequestError,
    PoolFrozenError,
    SplitRequestError,
)
from .ladder import LADDER_FLOOR_WORLDS, validated_floor
from .layout import DATABASE_URL_ENV, POOL_TABLES, pool_tables_present
from .split import (
    _WORLD_UNION,
    TRAIN_FRACTION,
    _validated_train_fraction,
    split_pool,
)

__all__ = [
    "CYCLE_HOLDOUT_TABLE",
    "HoldoutRecord",
    "cycle_holdout_schema",
    "cycle_holdouts",
    "cycle_rotation",
    "record_cycle_holdout",
]

#: The table this member's holdout record lives in — one row per cycle,
#: appended and never rewritten.  Member-owned and created lazily beside the
#: one module that writes it, on the same terms as
#: :data:`dreaming.cycle.FREEZE_TABLE` and :data:`dreaming.cap.CYCLE_CAP_TABLE`:
#: the table has one writer, so its shape is a fact about this feature rather
#: than about the database's history, and the shared migration chain is
#: order-sensitive files this member does not own.
CYCLE_HOLDOUT_TABLE = "cycle_holdout"

#: The row's column names, in declaration order — the one spelling of what a
#: holdout row is made of, shared by the DDL, the insert and the read-back so
#: the three cannot disagree on a column order, the failure a positional
#: ``SELECT *`` invites.
_ROW_COLUMNS = (
    "id",
    "iteration_id",
    "recorded_at",
    "world_count",
    "train_fraction",
    "holdout_worlds",
)

#: The record table's body.  Three columns beyond the identity pair are
#: load-bearing and are stated here rather than left to reader inference:
#:
#: * ``world_count`` is the pool's size the split was taken over — the same
#:   figure a feature-270 hold records at open and a cap record records at
#:   decision — carried so the row names the pool it was a share of, and a
#:   reader can tell a holdout of 6 from a pool of 20 against one of 15 from
#:   a pool of 50;
#: * ``train_fraction`` is the exact share the split was taken by, as the
#:   text of a :class:`~fractions.Fraction` (``7/10``) — the record says
#:   *which* 70/30 it was, the same reason :class:`~dreaming.split.PoolSplit`
#:   carries its fraction; and
#: * ``holdout_worlds`` is the held-out half itself — the worlds, in the
#:   split's own rank order, as a JSON array of ids — so the row is the
#:   sentence's own answer, *which worlds were held out*, readable by any
#:   process without re-running the split.
#:
#: No unique index and no triggers: the table is append-only history (a
#: retried cycle is a new occurrence with its own row), there is nothing to
#: guard — a holdout record is a judgment's persistence, not a hold — and
#: nothing to close.
_TABLE_BODY = """
(
    id              TEXT    NOT NULL PRIMARY KEY,
    iteration_id    TEXT    NOT NULL,
    recorded_at     TEXT    NOT NULL,
    world_count     INTEGER NOT NULL,
    train_fraction  TEXT    NOT NULL,
    holdout_worlds  TEXT    NOT NULL
)
"""

_SCHEMA = f"""
-- Feature 279: the worlds a dreaming cycle held out of selection, one row
-- per cycle.  The holdout rotates each cycle (PRD 12.1's top rung: "70/30
-- train/holdout split on worlds, holdout rotated each cycle"), and which
-- worlds each iteration held out is a fact the store holds rather than the
-- caller's memory: the M3 exit criterion is evaluated on worlds held out of
-- the dreaming loop, a holdout nobody recorded is a report over worlds
-- nobody can name, and a rotation nobody recorded is a claim the history
-- cannot check.  Append-only and never rewritten: a retried cycle is
-- re-decided over the pool as it stands, so it is a new occurrence with its
-- own row, and "which worlds did this cycle report on?" is a question the
-- table answers after the fact.
--
-- `holdout_worlds` carries the held-out half in the split's own rank order
-- (feature 278's digest rank at the cycle's own rotation -- the rotation IS
-- the iteration id, so the row carries it already and names no second
-- discriminator), and `world_count` and `train_fraction` name the pool and
-- the share the half was taken over, so an operator reading a row sees
-- which 70/30 of which pool it was rather than only that it was one.
CREATE TABLE IF NOT EXISTS {CYCLE_HOLDOUT_TABLE} {_TABLE_BODY};
"""

#: The insert a record performs.  A plain ``INSERT`` with no ``ON CONFLICT``
#: arm: the id is minted per occurrence, so there is nothing to conflict
#: with, and an upsert that rewrote an existing row would be the one history
#: rewrite this table exists not to perform.
_INSERT = f"""
INSERT INTO {CYCLE_HOLDOUT_TABLE} ({", ".join(_ROW_COLUMNS)})
VALUES (?, ?, ?, ?, ?, ?)
"""

#: The whole history, oldest first — the audit read, ordered by
#: ``(recorded_at, id)`` so two reads of one history return the same
#: sequence whatever the storage engine's accident.
_SELECT_ALL = (
    f"SELECT {', '.join(_ROW_COLUMNS)} FROM {CYCLE_HOLDOUT_TABLE} "
    "ORDER BY recorded_at, id"
)


def cycle_holdout_schema() -> str:
    """The DDL that brings a database to the holdout record's shape, idempotently.

    One statement: the table.  No guards — a holdout record is a judgment's
    persistence rather than a hold, so there is no pool write to refuse and
    no window to close — and no unique index — the history is append-only,
    and a retried cycle is a new occurrence whose row the table exists to
    keep.

    Returned as text rather than executed, for the reason
    :func:`dreaming.cycle.cycle_freeze_schema` and
    :func:`dreaming.cap.cycle_cap_schema` are: the DDL is then inspectable —
    a reader can see what the record is made of without opening a database,
    and a test can assert the shape without one.
    """
    return _SCHEMA


def cycle_rotation(iteration_id: Any) -> str:
    """The rotation a cycle's split is taken at — its own name, feature 279's law.

    The whole of this module's own judgment, and deliberately the identity
    over a validated id rather than a derivation: the iteration id is the
    one identity every per-cycle record in this member already carries, so
    folding it into feature 278's rank makes *the split of cycle N* a fact
    recomputable from the cycle's name alone, in any process, with nothing
    but the algorithm — §12's determinism contract, restated for a
    partition.  A rotation derived from the count of prior records would
    instead make each cycle's holdout a fact about its position in this
    table: a retry would shift every later cycle's worlds, and the
    append-only history would quietly become an input to the splits it
    describes.

    The id is validated by the member's one iteration rule
    (:func:`dreaming.cycle.validated_iteration_id`) and its refusal is
    *translated at this seam* into this module's vocabulary: a caller that
    asked for a cycle's rotation and caught feature 270's request class
    would read *your hold was malformed* about an act that held nothing.
    The returned text is the id verbatim — stripped, as the rule strips it —
    so ``split_pool(worlds, rotation=cycle_rotation(n))`` and this module's
    own record run one split, not two that merely agree.
    """
    try:
        return validated_iteration_id(iteration_id)
    except FreezeRequestError as refusal:
        raise HoldoutRequestError(
            f"a dreaming cycle is named by a non-empty string — got "
            f"{iteration_id!r} ({type(iteration_id).__name__}); the rotation a "
            "cycle's holdout is taken at is the cycle's own name, and a value "
            "that names no cycle rotates nothing — its record would be a "
            "holdout attributed to no tournament, and an operator reading the "
            "history could not say which cycle's worlds were held out"
        ) from refusal


class HoldoutRecord:
    """One recorded holdout — a row, as this member reads it.

    The row's six facts and nothing derived: which cycle held the worlds
    out, when its split was taken, how large the pool it was a share of was,
    the exact share the split was taken by, and the held-out half itself as
    the JSON text the row carries.  Held as an immutable value rather than a
    live cursor for the reason :class:`dreaming.cycle.FreezeRecord` and
    :class:`dreaming.cap.CapRecord` give: a record is what audits of the
    loop are made of, and a caller reading one must not be holding a handle
    a later record can move under it.

    The parsed faces are properties, and each refuses in this module's
    vocabulary rather than the freeze's or the split's: by the time a stamp,
    a world list or a fraction is being read back the row is in the store
    either way, but the caller asked the rotation's record, and a caller
    that met another feature's word here would read a *held pool* or a
    *malformed split* refusal out of a table that holds neither.
    """

    __slots__ = (
        "holdout_worlds",
        "id",
        "iteration_id",
        "recorded_at",
        "train_fraction",
        "world_count",
    )

    def __init__(
        self,
        *,
        id: str,
        iteration_id: str,
        recorded_at: str,
        world_count: int,
        train_fraction: str,
        holdout_worlds: str,
    ) -> None:
        self.id = id
        self.iteration_id = iteration_id
        self.recorded_at = recorded_at
        self.world_count = world_count
        self.train_fraction = train_fraction
        self.holdout_worlds = holdout_worlds

    # -- The parsed faces -----------------------------------------------------

    @property
    def recorded(self) -> dt.datetime:
        """When the cycle's split was taken, as the aware instant the row encodes.

        A stamp that will not parse is refused in this module's vocabulary
        (:class:`~dreaming.errors.HoldoutRecordError`) rather than the
        freeze's, for the reason :class:`dreaming.cap.CapRecord.recorded`
        states: the value is part of the cycle's own history, and a caller
        that met feature 270's word here would read a *held pool* refusal
        out of a table that holds nothing.
        """
        try:
            return _parsed_instant(self.recorded_at)
        except PoolFrozenError as refusal:
            raise HoldoutRecordError(
                f"a recorded holdout stamp must be ISO-8601 with a timezone "
                f"— got {self.recorded_at!r}; the stamp is part of the "
                "cycle's own history and a value that cannot be read back is "
                "one that was never written by this member"
            ) from refusal

    @property
    def fraction(self) -> Fraction:
        """The exact share the split was taken by — the row's fraction, parsed.

        :class:`fractions.Fraction` text (``7/10``), read back exactly; a
        value that names no exact share is refused in this module's
        vocabulary because it is a fact about the row, never written by this
        member, rather than a fact about the ask.
        """
        try:
            return Fraction(self.train_fraction)
        except (TypeError, ValueError, ZeroDivisionError) as refusal:
            raise HoldoutRecordError(
                f"a recorded train fraction is the exact text of a rational "
                f"— got {self.train_fraction!r}; the fraction names which "
                "70/30 the cycle's holdout was taken by, and a value that "
                "names no exact share is one that was never written by this "
                "member"
            ) from refusal

    @property
    def holdout(self) -> tuple[str, ...]:
        """Which worlds the cycle held out — the row's half, read back.

        A JSON array of world ids, answered as a tuple in the split's own
        rank order — the order the record was written in, so two reads of
        one row answer the same sequence.  A value that is not a list of
        non-empty strings is refused rather than coerced: the holdout half
        is made of the pool's world ids, and a row whose half reads back as
        numbers or blanks is a row this member never wrote.
        """
        try:
            worlds = json.loads(self.holdout_worlds)
        except (TypeError, ValueError) as refusal:
            raise HoldoutRecordError(
                f"a recorded holdout half is a JSON array of world ids — "
                f"got {self.holdout_worlds!r}; the row names which worlds "
                "the cycle held out of selection, and a value that cannot "
                "be read back is one that was never written by this member"
            ) from refusal
        if not isinstance(worlds, list) or not all(
            isinstance(world, str) and world.strip() for world in worlds
        ):
            raise HoldoutRecordError(
                f"a recorded holdout half is a JSON array of non-empty "
                f"world ids — got {self.holdout_worlds!r}; the row names "
                "which worlds the cycle held out of selection, and an "
                "element that names no world belongs in no cycle's half"
            )
        return tuple(worlds)

    # -- The value --------------------------------------------------------

    def row(self) -> dict[str, object]:
        """The record as a store-shaped mapping — a fresh dict per call."""
        return {
            "id": self.id,
            "iteration_id": self.iteration_id,
            "recorded_at": self.recorded_at,
            "world_count": self.world_count,
            "train_fraction": self.train_fraction,
            "holdout_worlds": self.holdout_worlds,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HoldoutRecord):
            return NotImplemented
        return self.row() == other.row()

    def __hash__(self) -> int:
        return hash(
            (
                self.id,
                self.iteration_id,
                self.recorded_at,
                self.world_count,
                self.train_fraction,
                self.holdout_worlds,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"HoldoutRecord(iteration_id={self.iteration_id!r}, "
            f"recorded_at={self.recorded_at!r}, "
            f"world_count={self.world_count!r})"
        )


def _record_from_row(row: tuple) -> HoldoutRecord:
    """Unpack one holdout row into the record it holds, in column order."""
    id_, iteration_id, recorded_at, world_count, train_fraction, worlds = row
    return HoldoutRecord(
        id=id_,
        iteration_id=iteration_id,
        recorded_at=recorded_at,
        world_count=int(world_count),
        train_fraction=train_fraction,
        holdout_worlds=worlds,
    )


def _holdout_id(iteration_id: str, recorded_at: str) -> str:
    """The id a holdout record is named by — iteration, instant, and a draw.

    Deterministic in the iteration and the instant and *distinct* for every
    call, which is the property a per-cycle table keyed by occurrence needs:
    §12.1's cycle may legitimately retry — release the hold, let the pool
    grow, open again — and the retried cycle is re-decided, so it is a new
    record even inside the same second, with its own row and its own id.
    Ids derived from ``(iteration, instant)`` alone would collide on the
    primary key for exactly that retry, and the collision would surface as
    an ``IntegrityError`` naming a constraint nobody violated — the failure
    mode :func:`dreaming.cycle._hold_id` states for holds, restated by
    :func:`dreaming.cap._cap_id` for caps before it can happen here.

    A sha256 hex string rather than a UUID for the reason the hold's id and
    the cap's are: the inputs are text of unbounded shape and a UUID's fixed
    layout would either truncate them or require a namespace this member has
    no use for.
    """
    digest = hashlib.sha256(
        f"{iteration_id}\n{recorded_at}\n{secrets.token_hex(16)}\n".encode()
    ).hexdigest()
    return f"holdout-{digest[:32]}"


def _validated_fraction(value: Any) -> Fraction:
    """The split's one fraction rule, translated into the rotation's word.

    :func:`dreaming.split._validated_train_fraction` is the one spelling of
    what a train fraction must be — an exact share strictly inside ``(0,
    1)``, a ``float`` read through its shortest text — and reusing it is
    what keeps a recorded rotation's fraction and a direct split's the same
    rule in the same database.  The refusal is translated at the seam: a
    caller recording a cycle's holdout must not meet the split's request
    class for an act that split nothing, the same seam discipline the cap
    and the split apply to the member's shared rules.
    """
    try:
        return _validated_train_fraction(value)
    except SplitRequestError as refusal:
        raise HoldoutRequestError(
            f"a split's fraction is an exact share strictly between none of "
            f"the pool and all of it — got {value!r}; the fraction names "
            "which 70/30 the cycle's holdout was taken by, and a value that "
            "names no exact share names no holdout to record. See the "
            f"refusal the split's own rule raised: {refusal}"
        ) from refusal


def _stamped_instant(value: Any) -> str:
    """The member's one stamp rule, translated into the rotation's word.

    :func:`dreaming.cycle._stamp` is the one spelling of what a recorded
    instant looks like — aware, UTC, second-truncated, ``Z``-suffixed — and
    reusing it is what keeps a holdout row's stamp, a hold row's and a cap
    row's the same shape in the same database.  A naive or non-datetime
    instant is refused here in the rotation's vocabulary for the reason the
    cap's is: the ask was the rotation's, not the freeze's.
    """
    try:
        return _stamp(value)
    except FreezeRequestError as refusal:
        raise HoldoutRequestError(
            f"the instant a cycle's holdout was recorded at is a "
            f"timezone-aware datetime — got {value!r} "
            f"({type(value).__name__}); a naive instant would place a "
            "cycle's split hours away from the process that took it, in "
            "whatever zone the host happens to keep, and nothing in the row "
            "would look wrong"
        ) from refusal


def _holdout_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the store a holdout is recorded in: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.cap._cap_path` and
    :func:`dreaming.split._split_path` take — an explicit URL first, then
    the deployment's ``DATABASE_URL`` — and the same refusal stance: an act
    that means to write and resolves nothing is refused by name rather than
    answered with ``None``, because a holdout "recorded" over no database is
    a holdout the store does not hold and the audit read would find nothing.
    A URL this member cannot speak is refused in the rotation's vocabulary,
    translated at the seam from the one spelling of what a ``sqlite:///``
    URL names.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise HoldoutRequestError(
            f"recording a cycle's holdout needs the database the replay pool "
            f"lives in — pass it explicitly or set {DATABASE_URL_ENV}. A "
            "holdout recorded over no database is a holdout the store does "
            "not hold: the M3 exit criterion is evaluated on worlds held out "
            "of the dreaming loop, and a criterion read over worlds nobody "
            "recorded is a criterion read over nothing"
        )
    try:
        return sqlite_path(url)
    except FreezeRequestError as refusal:
        raise HoldoutRequestError(
            f"the holdout record's store is the database the replay pool "
            f"lives in, and the URL given does not name one this member can "
            f"speak — see the refusal it raised: {refusal}. The rotation "
            "shares the pool's database rather than growing a second store a "
            "deployment could point at a different file, because a holdout "
            "taken over one pool and recorded in another would be a record "
            "about nothing"
        ) from refusal


def _refuses_poolless(connection: sqlite3.Connection, path: Path) -> None:
    """Refuse a database that holds no pool, before anything is created.

    The probe every store seam in this member performs, in this module's own
    vocabulary: a database that holds no ``replay_score`` and no
    ``bootstrap_world`` holds no pool to hold worlds out of, and a row
    written against it would name worlds that were never read while the
    cycle believed its reporting half existed.  Deliberately a probe of the
    pool's *presence* (:func:`dreaming.layout.pool_tables_present`), never
    of its rows — the worlds themselves are read once, whole, by the split's
    own membership query.
    """
    present = pool_tables_present(connection)
    missing = [table for table in POOL_TABLES if table not in present]
    if missing:
        raise HoldoutRecordError(
            f"the database at {path} holds no {' and no '.join(missing)} "
            "table, so there is no pool here to hold worlds out of — the "
            "holdout is a share of the pool's worlds, taken by the split at "
            "the cycle's own rotation, and a record written against a "
            "database with no pool would name worlds that were never read "
            "while the cycle believed its reporting half existed. Point "
            f"{DATABASE_URL_ENV} at the database the replay pool lives in, "
            "or migrate it"
        )


def record_cycle_holdout(
    iteration_id: Any,
    *,
    floor: Any = LADDER_FLOOR_WORLDS,
    train_fraction: Any = TRAIN_FRACTION,
    database_url: str | None = None,
    recorded_at: dt.datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> HoldoutRecord:
    """Rotate the split for one cycle and persist its holdout — feature 279's call.

    The one act the feature's sentence names, both clauses at once: take the
    cycle's rotation (:func:`cycle_rotation` — its own name), split the pool
    at that rotation (:func:`dreaming.split.split_pool`, feature 278's own
    arithmetic over :func:`dreaming.split.pool_worlds`' union), and write
    one row into ``cycle_holdout`` carrying **which worlds were held out**,
    beside the pool's size and the exact share the split was taken by.
    Returns the :class:`HoldoutRecord` written, so the caller that is about
    to select on the train half holds the holdout half its report will be
    read against, and the store holds the same fact for everyone after it.

    **The holdout is decided here, not accepted.**  The caller cannot hand
    in worlds, a split or a rotation of its own spelling; the row's worlds
    are always the split's answer at the row's own ``iteration_id`` over the
    pool as the store holds it, so the record cannot disagree with the split
    and an operator reading the table reads §12.1's rotation itself, cycle
    by cycle.  A caller that wants the selection half beside the record's
    reporting half takes the same split through feature 278's own seam —
    ``split_replay_pool(rotation=cycle_rotation(...))`` — which answers the
    identical halves over the pool feature 270 holds fixed for the cycle.

    Refuses, in this order, each naming what it is about:

    1. an ``iteration_id`` that is not non-empty text, a ``train_fraction``
       that names no exact share in ``(0, 1)``, or a ``floor`` that is not
       a world count — the ask's own facts, refused before anything is read
       or written (:class:`~dreaming.errors.HoldoutRequestError`, the first
       two translated at the seam from the member's one spellings of the
       rules, the floor refused by the ladder's own
       :func:`~dreaming.ladder.validated_floor` in the ladder's vocabulary,
       because the floor is feature 275's fact);
    2. a ``recorded_at`` that is not a timezone-aware datetime, or a URL
       that names no database or one this member cannot speak
       (:class:`~dreaming.errors.HoldoutRequestError`);
    3. a database that holds no pool tables — no pool to hold worlds out of
       (:class:`~dreaming.errors.HoldoutRecordError`) — and refused *before*
       the table is created, so a refused record leaves no trace;
    4. a pool below the ladder floor — too thin to dream on, so too thin to
       hold worlds out of, refused by the split's judgment in the ladder's
       own word (:class:`~dreaming.errors.PoolTooThinError`).  This refusal
       comes *after* the store's, like :func:`dreaming.split.
       split_replay_pool`'s and unlike :func:`dreaming.cap.
       record_cycle_cap`'s, because the figure the floor judges is the
       count this call has to read the pool to know.

    ``recorded_at`` defaults to the current UTC instant truncated to the
    second, and is a parameter so a test or a replayed script can stamp a
    deterministic instant — the same reason the hold's, the cap's and the
    split's callers take one.
    """
    turn = cycle_rotation(iteration_id)
    fraction = _validated_fraction(train_fraction)
    floor_count = validated_floor(floor)
    instant = _stamped_instant(
        recorded_at if recorded_at is not None else dt.datetime.now(dt.UTC)
    )
    path = _holdout_path(database_url, env)
    record_id = _holdout_id(turn, instant)
    with closing(sqlite3.connect(path)) as connection, connection:
        # The pool is probed, then read, then split, and only then is the
        # record's own table created: every refusal below this comment — no
        # pool, a thin pool — fires before a single DDL statement, so a
        # refused record leaves not even an empty table behind.
        _refuses_poolless(connection, path)
        worlds = tuple(row[0] for row in connection.execute(_WORLD_UNION))
        split = split_pool(
            worlds,
            rotation=turn,
            floor=floor_count,
            train_fraction=fraction,
        )
        connection.executescript(cycle_holdout_schema())
        connection.execute(
            _INSERT,
            (
                record_id,
                turn,
                instant,
                split.world_count,
                str(fraction),
                json.dumps(list(split.holdout)),
            ),
        )
    return HoldoutRecord(
        id=record_id,
        iteration_id=turn,
        recorded_at=instant,
        world_count=split.world_count,
        train_fraction=str(fraction),
        holdout_worlds=json.dumps(list(split.holdout)),
    )


def cycle_holdouts(
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[HoldoutRecord, ...]:
    """Every holdout this database records, oldest first — the audit read.

    The account an operator asks for after the fact: which worlds each cycle
    held out, over how large a pool, at which share, and when its split was
    taken.  Ordered by ``(recorded_at, id)`` so two reads of one history
    return the same sequence whatever the storage engine's accident — the
    §12 ordering rule every store in this workspace restates — with a
    retried cycle's re-decision standing beside the attempt it replaced,
    because both were true and the table is history, not a register.

    Resolves its store exactly as :func:`record_cycle_holdout` does and
    refuses the same two ways: no database named
    (:class:`~dreaming.errors.HoldoutRequestError`), and a database that
    holds no pool (:class:`~dreaming.errors.HoldoutRecordError`) — a
    database without the pool holds no dreaming cycles and so no holdouts,
    and answering ``()`` there would read *no cycle ever dreamed* off a
    store that never could.  A pool with no records yet answers ``()`` after
    creating the table lazily, which is the state between a migrated
    deployment and its first dreaming cycle.
    """
    path = _holdout_path(database_url, env)
    with closing(sqlite3.connect(path)) as connection:
        _refuses_poolless(connection, path)
        connection.executescript(cycle_holdout_schema())
        rows = connection.execute(_SELECT_ALL).fetchall()
    return tuple(_record_from_row(row) for row in rows)
