"""The pool's train/holdout split — feature 278, and the ladder's top-rung tool.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 278: *System splits the
pool 70 to 30 into train and holdout, which returns selection on train with
reporting on holdout.*  docs/alpha-engine-prd.md §12.1 states the split as the
top rung's own regime — *"50+: Full dreaming, ``M = 30–40``, 70/30
train/holdout split on worlds, holdout rotated each cycle"* — and
docs/nullius-tech-architecture.md §10.3.1 states the call in code, with the
feature's own clause as its comment:

    train, holdout = pool.split(0.7, rotate_each_cycle=True)
    # select on train, report on holdout

**Why the split exists at all.**  §12.1's warning is the section's first
sentence: *"the dreaming loop **overfits its own replay pool**"*.  A cycle that
selects the argmax over ``M`` revisions (feature 274) and then *reports* on the
same worlds it selected over is grading its own homework — the winner's
advantage on the worlds that chose it is exactly the quantity selection
inflates, so the report would flatter the winner by construction and nothing in
it would look wrong.  The split moves the reporting half out of the selector's
reach: selection reads the train worlds' scores, reporting reads the holdout
worlds', and a holdout the selection never touched cannot be overfit to it.
§10.3.1's paired statistic (feature 281) and its ``√(2 ln M)`` bar (feature
280) both stand on that disjointness — *"same policy pair on the same worlds"*
is only an honest comparison when both halves exist and neither leaked into the
other — and the PRD's M3 exit criterion is evaluated *on worlds held out of the
dreaming loop*, which are these worlds.  The architecture's risk table names
the failure the split is the mitigation for — *"Dreaming overfits the pool …
Holdout-world score diverges from train-world score"* — and the divergence is
only observable because a holdout world was never a selection world.

What the split is
-----------------

Three spellings of one act, and the record they answer with:

* :func:`pool_worlds` — the pool's worlds as ids, read from the two tables
  this member already knows by name, **a world once** no matter how many score
  rows name it;
* :func:`split_pool` — the pure judgment: the world ids and a rotation in, the
  two halves out.  The shape of the ladder's other tools
  (:func:`dreaming.ladder.rejects_thin_pool`, :func:`dreaming.cap.revision_cap`
  and :func:`dreaming.ceiling.rejects_uncapped_sweep`): a pure function of what
  the caller already holds, which never opens a database, because a verdict is
  not a count and the count is the caller's to supply — here, generalised to
  the pool's *membership*, which the caller reads once and hands whole;
* :func:`split_replay_pool` — the feature's own call, the one §10.3.1 spells
  ``pool.split(0.7, ...)``: resolve the database the deployment names, read
  the pool's worlds, split them.  The same resolution order every store seam
  in this member takes — an explicit URL first, then ``DATABASE_URL``.

And the answer is a :class:`PoolSplit`: the two halves as tuples of world ids,
the rotation the split was taken at, and the fraction it was taken by — the
facts the split was decided over, carried the way a
:class:`~dreaming.cap.CapRecord` carries its ``world_count``, so an operator
reading a split can see *which* 70/30 it was rather than only *that* it was
one.  The record unpacks as ``(train, holdout)``, which is §10.3.1's own line
made to work, and answers :meth:`~PoolSplit.is_train` /
:meth:`~PoolSplit.is_holdout` for the caller that holds one world id and needs
to know which half a score row belongs to — the seam ``0109``'s
``replay_score.is_holdout`` flag exists to carry, and the seam feature 272's
evaluator will write.  A world the split does not hold is *refused* by both
predicates rather than answered ``False``: a world outside the pool is neither
train nor holdout, and an answer that let a caller mark an unseen world
``train`` by accident would be the leak the split exists to prevent.

The two halves of one figure
----------------------------

**The arithmetic is exact, and it is rational by construction.**
:data:`TRAIN_FRACTION` is :class:`fractions.Fraction` ``(7, 10)`` — §12.1's
"70/30" as an exact number, not ``0.7`` the float, because a floating-point
boundary would make the split's sizes process-accidental at exactly the pools
where the odd world matters (``0.1 + 0.2 != 0.3`` is the §12 determinism
contract's smallest example), and a split that could disagree with itself
between two processes is a split whose halves cannot be audited.  The caller
may hand its own fraction — the keyword is the §10.3.1 call's own argument —
and a ``float`` is read through its shortest textual form (``0.7`` becomes
``7/10`` exactly, never its binary tail), while anything a
:class:`~fractions.Fraction` cannot ground, or any fraction at or outside
``(0, 1)``, is refused: a split names two halves, and a fraction that empties
one names no split.

A finite pool cannot be cut at an exact seventh-tenths line, so the one odd
world at an indivisible pool size is apportioned by **largest remainder** —
each half's floor first, then the leftover seat to the half whose remainder is
larger — and when the remainders tie exactly (a pool of 25: ``17.5`` and
``7.5``), **the tie goes to the holdout**.  The rule is stated rather than
left to a rounding function because it is load-bearing: the holdout is the
half the split exists to protect, and a tie rule that rounded it down would
systematically under-fund the reporting half at every pool size the tie can
occur at — the exact failure §12.1's rung puts the split there to prevent.  So:
a pool of 20 splits 14/6, 50 splits 35/15, 53 splits 37/16 (the remainder
``0.9`` outbids ``0.1``), and 25 splits 17/8 (the tie, to the holdout).

Which worlds, and how they are chosen
-------------------------------------

**The assignment is a rank, and the rank is a digest.**  Every world id is
ranked by ``sha256`` over the rotation and the id together, and the holdout is
the first ``30%`` of that order.  Two properties follow, and both are the ones
the loop needs:

* **deterministic** — the same pool at the same rotation answers the same
  split in any process, which is §12's determinism contract restated for a
  partition; a holdout set that moved between the process that took it and the
  process that reported on it would be two different holdouts wearing one
  name; and
* **unbiased** — a cryptographic digest's order is uniform over the ids, so
  the holdout is a fair 30% sample that no world id can predict its way into
  or out of.  Sorting a pool's own ids and cutting the first 30% would be
  deterministic too, and would put the same worlds — the alphabetically first
  ones — in the holdout of every cycle forever, which is a holdout that never
  rotates even when feature 279 rotates it.

**``rotation`` is the seam feature 279 rotates, carried here because a split
that cannot rotate is a split 279 would have to re-implement.**  §12.1's rung
says *"holdout rotated each cycle"*, and §10.3.1's call says
``rotate_each_cycle=True``; feature 279's sentence (*"System rotates the
holdout split every cycle, persisting which worlds were held out per
iteration"*) is the per-cycle act and the record of it, and this module is the
mechanism it rotates — the rotation discriminator is folded into every world's
rank, so a different rotation answers a different holdout over the same pool,
deterministically, without this module knowing what a "cycle" is.  The default
rotation is the empty string: the split as first taken, over the pool as it
stands, which is feature 278's own sentence with feature 279's clause left to
feature 279.

The pool's worlds
-----------------

**A world is a world once, whatever the score rows say.**  The pool's two
tables hold the pool's two halves, and they name worlds differently:
``bootstrap_world`` holds one row per world it authors or ports, while
``replay_score`` holds one row per *(policy, world)* pair — a world that ``M``
revisions were replayed against is named by ``M`` score rows, and a plain
count of either table's rows is a count of replays, not of worlds.  So
:func:`pool_worlds` reads the **union**: every ``bootstrap_world.world_id``
and every distinct ``replay_score.world_id``, deduplicated across both, in one
total order.  A world the two halves share is one world — the census
(:mod:`bootstrap._census`, feature 186) reads the same membership law from the
other side of the member boundary, counting the financial half as the distinct
``replay_score`` worlds the bootstrap pool does not hold; the two spellings
are restatements of one law, pinned against each other by this member's
cross-member suite rather than imported, for the reason
:mod:`dreaming.layout` restates the pool's table names: no member in this
workspace imports another.

**The null guard is for a row a hand had been to.**  ``0109`` declares
``replay_score.world_id`` ``NOT NULL`` and ``DISTINCT`` treats ``NULL`` as a
value, so the union reads the guard the census reads — not because the
migration's shape admits the row, but because a read that would count a
phantom world into a holdout is a read that has stopped being careful at
exactly the table an operator bisecting a deployment is most likely to edit.

**The split's floor judges worlds, and that is not the hold's figure.**  A
feature-270 hold records ``world_count`` as its *commitment* counts it — the
pool's rows, score rows included — because the hold's subject is *did the pool
move*, and a score row moving is the pool moving.  This module's floor judges
the pool's *worlds*, because feature 275's sentence names worlds (*"fewer than
20 worlds"*) and a split over a pool of worlds is decided over how many worlds
there are.  The two figures agree on a pool with no scores and diverge the
moment one world is replayed, and both facts are kept rather than reconciled:
a caller reading a hold reads rows, a caller reading a split reads worlds, and
silently unifying them would make one of the two reads lie.  The judgment
itself is feature 275's own — :func:`dreaming.ladder.rejects_thin_pool`, in
the floor's word, with the ``floor`` keyword passed straight through as the
ladder's own ``gate``, the same delegation the cap's schedule and the band's
ceiling perform — because a pool too thin to dream on needs no train and no
holdout, and the refusal is the floor's to make.

What the split is not
---------------------

**It is not the rotator, the bar, the statistic, the evaluator or the
selector.**  Rotating the split per cycle and persisting which worlds were
held out per iteration is feature 279's sentence; the ``√(2 ln M)`` bar the
winning revision must clear on the holdout is feature 280's; the paired
continuous statistic over the same worlds is feature 281's; evaluating every
candidate against every world (feature 272) and selecting the argmax over the
train half (feature 274) are the loop's own acts.  This module answers *which
worlds are which half*, deterministically, and hands the answer to all of
them.

**It writes nothing, anywhere.**  The pool's two tables are read and never
touched — the split is a read-time judgment, the same restraint
:mod:`tripwires.excise` states for its read-time refusal — and the split
itself is not persisted here: feature 279's sentence is the one that
persists the holdout per iteration, and a split this module wrote would be a
record feature 279 already owns.  No new component, either: feature 270's
single ``"dreaming"`` component is the member's whole composition, and the
split is reached the way the floor, the cap and the ceiling are, as free
functions beside the store.  No seat edit, no migration, no third party:
``hashlib``, ``sqlite3``, ``os`` and ``fractions`` — the last new, and
stdlib's exact-rational arithmetic is the whole of the 70/30's exactness.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Iterable, Mapping
from contextlib import closing
from fractions import Fraction
from pathlib import Path
from typing import Any

from .cycle import sqlite_path
from .errors import FreezeRequestError, SplitRequestError, SplitStoreError
from .ladder import LADDER_FLOOR_WORLDS, rejects_thin_pool, validated_floor
from .layout import DATABASE_URL_ENV, POOL_TABLES, pool_tables_present

__all__ = [
    "TRAIN_FRACTION",
    "PoolSplit",
    "pool_worlds",
    "split_pool",
    "split_replay_pool",
]

#: The fraction of the pool the *train* half holds — §12.1's *"70/30
#: train/holdout split on worlds"* and §10.3.1's ``pool.split(0.7, ...)``, as
#: an exact rational rather than a float.  A float ``0.7`` is a binary
#: approximation whose tenths do not sum to one, and a split sized through it
#: could disagree with itself at exactly the pool sizes where the odd world
#: matters — the §12 determinism contract, violated by a spelling.  The
#: holdout holds the complement; the fraction is spelled as the train side
#: because the documents do.
TRAIN_FRACTION = Fraction(7, 10)

#: The pool's worlds, one query: every world either half names, each once.
#:
#: Three clauses, each argued in the module docstring and each load-bearing:
#:
#: * ``UNION`` rather than ``UNION ALL`` — the compound deduplicates *within*
#:   each half (``replay_score`` names a replayed world once per score row)
#:   and *across* the two (a world both halves hold is one world);
#: * the ``IS NOT NULL`` guard on the score side only — ``0109`` declares the
#:   column ``NOT NULL`` and ``bootstrap_world``'s id is its primary key, so
#:   the guard is for a row a hand had been to; ``DISTINCT``-shaped compound
#:   reads treat ``NULL`` as a value, and one stray empty row would join the
#:   holdout as a phantom world;
#: * ``ORDER BY`` over the compound — the enumeration answers a total order,
#:   the same discipline :func:`dreaming.cycle.pool_commitment` reads its
#:   membership in, so two reads of one pool return the same sequence
#:   whatever the storage engine's accident.
_WORLD_UNION = """
SELECT world_id FROM bootstrap_world WHERE world_id IS NOT NULL
UNION
SELECT world_id FROM replay_score WHERE world_id IS NOT NULL
ORDER BY world_id
"""


def pool_worlds(path: Path) -> tuple[str, ...]:
    """The pool's worlds as ids — every world either half names, each once.

    The membership read the split is taken over, and the one spelling of what
    a *world* is in this member: ``bootstrap_world``'s rows plus the distinct
    worlds ``replay_score`` names, deduplicated across both, in id order.  A
    world replayed by ``M`` revisions is one world here, not ``M`` — the score
    row is the cycle's output, and the split's subject is which *worlds* the
    tournament is held over, which is the same distinction the commitment
    draws when it hashes membership and refuses to fold scores in.

    A table the database does not hold is **refused by name**
    (:class:`~dreaming.errors.SplitStoreError`), not counted as empty, for the
    reason :func:`dreaming.cycle.pool_commitment` refuses one: a migrated
    deployment with no scores yet genuinely holds zero financial worlds,
    while a database without the tables holds no pool at all — and a split
    over a pool that is not there is a split of nothing, which the floor's
    own refusal would then misreport as a thin pool.  Takes a path rather
    than a URL, like the commitment does, so the two reads of one pool cost
    what one read costs; :func:`split_replay_pool` is the URL-taking seam.
    """
    with closing(sqlite3.connect(path)) as connection:
        present = pool_tables_present(connection)
        missing = [table for table in POOL_TABLES if table not in present]
        if missing:
            raise SplitStoreError(
                f"the database at {path} holds no "
                f"{' and no '.join(missing)} table, so there is no pool here "
                "to split — a train/holdout split partitions the worlds the "
                "two halves hold, and a split answered over a database "
                "without them would hand the cycle a train half to select on "
                "and a holdout half to report on that hold nothing. Point "
                f"{DATABASE_URL_ENV} at the database the replay pool lives "
                "in, or migrate it"
            )
        rows = connection.execute(_WORLD_UNION).fetchall()
    return tuple(row[0] for row in rows)


def _validated_world_ids(value: Any) -> tuple[str, ...]:
    """Check that ``value`` is the pool's worlds, or refuse it as the ask's own.

    The pool's worlds are non-empty text, each once.  A ``bool`` and a number
    are not text and are refused naming their type; blank text is refused
    because it names no world; and the same world twice is refused because the
    pool's enumeration is a union — a caller that hands one world twice has
    not enumerated the pool, and a split that quietly deduplicated it would
    answer a pool size the caller cannot reconcile with the one it read.

    A bare string is refused where many worlds belong, and the refusal is
    explicit rather than incidental: Python would iterate a string's
    characters, and a nine-character world id would silently become nine
    one-character worlds — a pool nobody holds, split into halves nobody can
    report on, with nothing in the result looking wrong.
    """
    if isinstance(value, (str, bytes)):
        raise SplitRequestError(
            f"the pool's worlds are many ids — got the single {type(value).__name__} "
            f"{value!r}; a bare string names one world, and iterating it would "
            "split its characters into a pool nobody holds. Pass the pool's "
            "world ids as an iterable of strings"
        )
    try:
        candidates = list(value)
    except TypeError as refusal:
        raise SplitRequestError(
            f"the pool's worlds are an iterable of ids — got {value!r} "
            f"({type(value).__name__}); a split partitions the pool's "
            "membership, and a value that cannot be walked names no pool to "
            "split"
        ) from refusal
    seen: dict[str, None] = {}
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate.strip():
            raise SplitRequestError(
                f"a world is named by a non-empty string — got {candidate!r} "
                f"({type(candidate).__name__}); the split's halves are made "
                "of the pool's world ids, and an id that names no world "
                "belongs in neither half"
            )
        if candidate in seen:
            raise SplitRequestError(
                f"the pool holds each world once — got {candidate!r} more "
                "than once; the pool's enumeration is a union of the two "
                "halves' ids, and a caller that hands one world twice has "
                "not enumerated the pool. A split that deduplicated silently "
                "would answer a pool size the caller cannot reconcile with "
                "the one it read"
            )
        seen[candidate] = None
    return tuple(candidates)


def _validated_rotation(value: Any) -> str:
    """Check that ``value`` is a rotation discriminator, or refuse it.

    Text, and any text — the empty string included, which is the default: the
    un-rotated split, taken over the pool as it stands, is feature 278's own
    sentence, and feature 279's per-cycle rotation is a discriminator this
    seam receives from its caller.  A non-string is refused because the
    discriminator is folded into a digest, and a digest over a value of
    shifting type would make the *same* rotation spell differently in
    different callers — ``1`` and ``"1"`` would rotate differently, and the
    split would be two splits wearing one name.
    """
    if not isinstance(value, str):
        raise SplitRequestError(
            f"a rotation is named by text — got {value!r} "
            f"({type(value).__name__}); the rotation is folded into every "
            "world's rank, and a discriminator of shifting type would make "
            "the same rotation answer different splits in different callers"
        )
    return value


def _validated_train_fraction(value: Any) -> Fraction:
    """Check that ``value`` names a two-halves split, or refuse it.

    Read through :class:`fractions.Fraction`, with a ``float`` read through
    its shortest textual form — ``0.7`` is exactly ``7/10``, never the binary
    tail a direct conversion would freeze in.  Refused outside the open
    interval ``(0, 1)``: the fraction names two halves of one pool, and a
    fraction that empties either half — all train, all holdout — names no
    split, because §10.3.1's *"select on train, report on holdout"* needs a
    half to select on and a half to report on.
    """
    if isinstance(value, bool):
        raise SplitRequestError(
            f"a split's fraction is a share of the pool — got {value!r} "
            f"({type(value).__name__}); ``True`` is ``1`` in Python, and a "
            "flag where a fraction belongs would name a pool with no holdout, "
            "which is the one split this member must not answer"
        )
    try:
        fraction = Fraction(str(value)) if isinstance(value, float) else Fraction(value)
    except (TypeError, ValueError, ArithmeticError) as refusal:
        raise SplitRequestError(
            f"a split's fraction is an exact share — got {value!r} "
            f"({type(value).__name__}); the 70/30 is rational arithmetic, and "
            "a value that names no exact share names no split"
        ) from refusal
    if not 0 < fraction < 1:
        raise SplitRequestError(
            f"a split names two halves, so its fraction lies strictly between "
            f"none of the pool and all of it — got {fraction}; a fraction at "
            "or outside the edges would empty a half, and §10.3.1's 'select "
            "on train, report on holdout' needs both halves to exist"
        )
    return fraction


def _rank(rotation: str, world_id: str) -> tuple[str, str]:
    """One world's place in the split's order — a digest, and the id itself.

    The rotation is folded in ahead of the id and both are framed with
    newlines, the discipline :func:`dreaming.cycle.pool_commitment` hashes
    membership in, so no id can shift its rank by prefixing the rotation (or
    vice versa).  The id is carried beside the digest as the tiebreak, which
    makes the order total even between two ids whose digests collide — an
    event nobody has ever arranged, and one a sort must still answer.
    """
    digest = hashlib.sha256(f"{rotation}\n{world_id}\n".encode()).hexdigest()
    return (digest, world_id)


def _holdout_size(world_count: int, train_fraction: Fraction) -> int:
    """The holdout half's size — exact largest remainder, ties to the holdout.

    Each half's floor first; the floors of two halves that sum to the pool
    hold every world but one at most, and the one leftover seat goes to the
    half with the larger remainder.  When the remainders tie exactly — which
    happens wherever ``train_fraction`` of the pool lands on a half — the seat
    goes to the holdout: the holdout is the half the split exists to protect,
    and a tie rule that rounded it down would under-fund the reporting half at
    every pool size the tie can occur at.  Spelled as subtraction on the
    complement so the two halves sum to the pool by construction, never by
    agreement of two roundings.
    """
    total = Fraction(world_count)
    train_exact = train_fraction * total
    holdout_exact = total - train_exact
    train_floor = train_exact.numerator // train_exact.denominator
    holdout_floor = holdout_exact.numerator // holdout_exact.denominator
    if train_floor + holdout_floor == world_count:
        return holdout_floor
    train_remainder = train_exact - train_floor
    holdout_remainder = holdout_exact - holdout_floor
    if holdout_remainder >= train_remainder:
        return holdout_floor + 1
    return holdout_floor


class PoolSplit:
    """One taken split — the pool's worlds in their two halves, feature 278's answer.

    The row's facts and nothing derived: the train half's ids (§10.3.1's
    *"select on train"* — the worlds whose scores feature 274's argmax runs
    over), the holdout half's (the *"report on holdout"* half — the worlds
    whose scores the selection never touched and the M3 exit criterion reads),
    the rotation the split was taken at and the fraction it was taken by.
    Both halves are carried in the split's own total order — the digest rank
    of :func:`_rank` — so the record is reproducible rather than incidental:
    the same pool at the same rotation constructs the same record in any
    process.

    Unpacks as ``(train, holdout)``, because §10.3.1 spells the call that way
    — ``train, holdout = pool.split(0.7, ...)`` — and the workspace's habit is
    to make the document's own line the one that runs.  Held as an immutable
    value rather than a live view for the reason
    :class:`dreaming.cycle.FreezeRecord` gives: a split is what selection and
    reporting are both made of, and a caller holding one must not be holding a
    handle a later split can move under it.
    """

    __slots__ = (
        "_holdout_set",
        "_train_set",
        "holdout",
        "rotation",
        "train",
        "train_fraction",
    )

    def __init__(
        self,
        *,
        train: Iterable[str],
        holdout: Iterable[str],
        rotation: Any = "",
        train_fraction: Fraction = TRAIN_FRACTION,
    ) -> None:
        train_tuple = tuple(train)
        holdout_tuple = tuple(holdout)
        train_set = frozenset(train_tuple)
        holdout_set = frozenset(holdout_tuple)
        overlap = train_set & holdout_set
        if overlap:
            raise SplitRequestError(
                f"the two halves hold the pool between them, disjointly — "
                f"got {min(overlap)!r} in both; a world selected on and "
                "reported on is the leak the split exists to prevent, and "
                "§10.3.1's paired statistic over 'the same worlds' is only "
                "honest when the halves never share one"
            )
        #: The selection half: the worlds whose scores the cycle's argmax
        #: (feature 274) runs over, in the split's rank order.
        self.train = train_tuple
        #: The reporting half: the worlds the selection never touched, in the
        #: same rank order — the M3 exit criterion's worlds.
        self.holdout = holdout_tuple
        #: The rotation the split was taken at — the empty string for the
        #: un-rotated split, feature 279's per-cycle discriminator otherwise.
        self.rotation = _validated_rotation(rotation)
        #: The fraction the train half was sized by, carried so the record
        #: says *which* 70/30 it was rather than only that it was one.
        self.train_fraction = _validated_train_fraction(train_fraction)
        # The membership sets the predicates answer from, precomputed once so
        # a caller marking a thousand score rows through :meth:`is_holdout`
        # pays a lookup per row rather than a rebuild.
        self._train_set = train_set
        self._holdout_set = holdout_set

    # -- The two faces --------------------------------------------------------

    @property
    def world_count(self) -> int:
        """How many worlds the split holds — both halves, the pool it split."""
        return len(self.train) + len(self.holdout)

    def is_train(self, world_id: Any) -> bool:
        """Whether ``world_id`` is one of the worlds selection runs on.

        A world the split does not hold is **refused** rather than answered
        ``False``: a world outside the pool is neither train nor holdout, and
        an answer that read as *train* would let a caller mark a world the
        cycle never saw — the leak the split exists to prevent, arriving as a
        return value instead of a write.
        """
        self._validated_member(world_id)
        return world_id in self._train_set

    def is_holdout(self, world_id: Any) -> bool:
        """Whether ``world_id`` is one of the worlds reporting runs on.

        The predicate feature 272's evaluator reads to mark a score row's
        ``is_holdout`` (``0109``'s own column, defaulted ``FALSE`` for exactly
        the row that never asked) — the same refusal for a world the split
        does not hold as :meth:`is_train` states, and for the same reason.
        """
        self._validated_member(world_id)
        return world_id in self._holdout_set

    def _validated_member(self, world_id: Any) -> str:
        """Check that ``world_id`` names a world this split holds, or refuse."""
        if not isinstance(world_id, str) or not world_id.strip():
            raise SplitRequestError(
                f"a world is named by a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the split's halves answer "
                "about the worlds they hold, and a value that names no world "
                "belongs to neither"
            )
        if world_id not in self._train_set and world_id not in self._holdout_set:
            raise SplitRequestError(
                f"the split holds {self.world_count} world(s) and {world_id!r} "
                "is not one of them — a world outside the pool is neither "
                "train nor holdout, and answering either would mark a world "
                "the cycle never saw. Split the pool the world was read from, "
                "or check the id"
            )
        return world_id

    # -- The value --------------------------------------------------------

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a report or a persistence seam (feature 279's) reads the
        split through: the two halves, the rotation and the fraction, under
        the names the record's own fields answer to.
        """
        return {
            "train": self.train,
            "holdout": self.holdout,
            "rotation": self.rotation,
            "train_fraction": self.train_fraction,
        }

    def __iter__(self):
        """Yield ``(train, holdout)`` — §10.3.1's own line, made to run.

        ``train, holdout = split_pool(...)`` is the architecture's spelling of
        the call, and the unpack is the record's one derived protocol: two
        values, the selection half first, in the order the document names
        them.
        """
        yield self.train
        yield self.holdout

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PoolSplit):
            return NotImplemented
        return (
            self.train,
            self.holdout,
            self.rotation,
            self.train_fraction,
        ) == (
            other.train,
            other.holdout,
            other.rotation,
            other.train_fraction,
        )

    def __hash__(self) -> int:
        return hash(
            (self.train, self.holdout, self.rotation, self.train_fraction)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"PoolSplit(train={len(self.train)} world(s), "
            f"holdout={len(self.holdout)} world(s), "
            f"rotation={self.rotation!r})"
        )


def split_pool(
    world_ids: Any,
    *,
    rotation: Any = "",
    floor: Any = LADDER_FLOOR_WORLDS,
    train_fraction: Any = TRAIN_FRACTION,
) -> PoolSplit:
    """Split the pool's worlds into train and holdout — feature 278's judgment.

    The pure half of the feature's act: the pool's world ids and a rotation
    in, the two halves out.  *Which* worlds are holdout is decided by rank —
    every world's :func:`_rank` digest over the rotation and the id, the
    holdout the first ``30%`` of that order — so the same pool at the same
    rotation answers the same split in any process, and a different rotation
    answers a different split over the same pool, deterministically.  The
    sizes are exact rational largest-remainder arithmetic
    (:func:`_holdout_size`): 20 worlds split 14/6, 50 split 35/15, 53 split
    37/16, and a 25-world tie splits 17/8 with the odd world in the holdout.

    ``world_ids`` are the pool's worlds — the caller reads them once
    (:func:`pool_worlds`, or its own enumeration) and hands them whole; passed
    in rather than read, so this function never opens a database, the verdict
    shape the ladder's other tools take.  ``rotation`` is the discriminator
    feature 279 varies per cycle; the empty default is the split as first
    taken.  ``train_fraction`` is §10.3.1's ``0.7``, exact by default and read
    exactly when handed; ``floor`` is passed straight through to the ladder's
    judgment as its own ``gate`` keyword, so the two spellings of the bottom
    rung cannot disagree.

    Refuses, in this order, each naming what it is about:

    1. ``world_ids`` that are not many non-empty text ids — a bare string, a
       non-iterable, a blank or non-text member, or one world twice
       (:class:`~dreaming.errors.SplitRequestError`);
    2. a ``rotation`` that is not text, or a ``train_fraction`` that names no
       exact share in ``(0, 1)`` (:class:`~dreaming.errors.SplitRequestError`);
    3. a ``floor`` that is not a non-negative whole number — refused by the
       ladder's own :func:`~dreaming.ladder.validated_floor`, in the ladder's
       vocabulary, because the floor is feature 275's fact;
    4. a pool below the floor — too thin to dream on, so too thin to split,
       refused by the ladder in its own word and its own class
       (:class:`~dreaming.errors.PoolTooThinError`).
    """
    ids = _validated_world_ids(world_ids)
    turn = _validated_rotation(rotation)
    fraction = _validated_train_fraction(train_fraction)
    floor_count = validated_floor(floor)
    rejects_thin_pool(len(ids), gate=floor_count)
    ranked = sorted(ids, key=lambda world: _rank(turn, world))
    holdout_count = _holdout_size(len(ids), fraction)
    return PoolSplit(
        train=tuple(ranked[holdout_count:]),
        holdout=tuple(ranked[:holdout_count]),
        rotation=turn,
        train_fraction=fraction,
    )


def _split_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the pool a split is taken over: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.cap._cap_path` takes — an
    explicit URL first, then the deployment's ``DATABASE_URL`` — and the same
    refusal stance: an act that means to read the pool and resolves nothing is
    refused by name rather than answered with ``None``, because a split taken
    over no database is a split of a pool that does not exist.  A URL this
    member cannot speak is refused in the split's vocabulary, translated at
    the seam from the one spelling of what a ``sqlite:///`` URL names.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise SplitRequestError(
            f"splitting the replay pool needs the database it lives in — "
            f"pass it explicitly or set {DATABASE_URL_ENV}. A split taken "
            "over no database would hand the cycle a train half to select on "
            "and a holdout half to report on that hold nothing, and §10.3.1's "
            "'select on train, report on holdout' would be a claim about "
            "worlds that do not exist"
        )
    try:
        return sqlite_path(url)
    except FreezeRequestError as refusal:
        raise SplitRequestError(
            f"the pool a split is taken over lives in the database the "
            f"replay pool lives in, and the URL given does not name one this "
            f"member can speak — see the refusal it raised: {refusal}. The "
            "split reads the pool's two tables rather than growing a second "
            "store a deployment could point at a different file, because a "
            "split over one pool and a hold reported from another would be "
            "two pools wearing one name"
        ) from refusal


def split_replay_pool(
    *,
    database_url: str | None = None,
    rotation: Any = "",
    floor: Any = LADDER_FLOOR_WORLDS,
    train_fraction: Any = TRAIN_FRACTION,
    env: Mapping[str, str] | None = None,
) -> PoolSplit:
    """Split the replay pool 70 to 30 — feature 278's call, over the store.

    The one act the feature's sentence names, spelled the way §10.3.1 spells
    it — ``train, holdout = pool.split(0.7, ...)``: resolve the database the
    deployment names (an explicit URL first, then ``DATABASE_URL``, refused
    when neither names one), read the pool's worlds
    (:func:`pool_worlds`), and split them (:func:`split_pool`).  The two
    halves come back as one :class:`PoolSplit`, and the caller that only
    wants the document's own line unpacks it: ``train, holdout =
    split_replay_pool()``.

    Refuses, in this order, each naming what it is about:

    1. a ``rotation`` that is not text, a ``train_fraction`` that names no
       exact share in ``(0, 1)``, or a ``floor`` that is not a world count —
       the ask's own facts, refused before any database is opened (the first
       two :class:`~dreaming.errors.SplitRequestError`, the floor by the
       ladder's own :func:`~dreaming.ladder.validated_floor` in the ladder's
       vocabulary, because the floor is feature 275's fact);
    2. a URL that names no database or one this member cannot speak
       (:class:`~dreaming.errors.SplitRequestError`, translated at the seam);
    3. a database that holds no pool tables — no pool to split
       (:class:`~dreaming.errors.SplitStoreError`);
    4. a pool below the ladder floor — refused by the ladder in its own word
       (:class:`~dreaming.errors.PoolTooThinError`).  This refusal comes
       *after* the store's here rather than before it, unlike
       :func:`dreaming.cap.record_cycle_cap`'s ordering, because the figure
       the floor judges is the count this call has to read the pool to know:
       the cap's caller held its figure already, and this call's does not.
    """
    turn = _validated_rotation(rotation)
    fraction = _validated_train_fraction(train_fraction)
    floor_count = validated_floor(floor)
    path = _split_path(database_url, env)
    return split_pool(
        pool_worlds(path),
        rotation=turn,
        floor=floor_count,
        train_fraction=fraction,
    )
