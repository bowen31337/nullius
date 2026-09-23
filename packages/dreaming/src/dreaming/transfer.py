"""Leave-one-family-out transfer — feature 282, the holdout a family shapes.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 282: *System computes
leave-one-family-out transfer by holding an entire theme root out of the pool,
which returns the delta on that held-out theme.*  docs/alpha-engine-prd.md §4.5
states the metric as the second of its two enforcement requirements, and states
why it is a *requirement* rather than a preference:

    2. **Leave-one-family-out is a standing metric.**  Hold an entire theme
    root out of the dreaming pool, then evaluate on worlds from that theme.
    It measures transfer directly, costs almost nothing, and is the only
    honest way to tell learned research discipline from memorized family
    texture.

§11 carries it as one of the three primary metrics — *"Leave-one-family-out
transfer: ΔIR on a held-out theme root"* with target *"> 0"* — §12's M3 exit
criterion is met only when *"Leave-one-family-out transfer ΔIR > 0"*, §13's
risk table names it as the mitigation for the overfit signature being
family-specific, and §15's fifth resolved decision is the reason it has to be
a family-shaped measurement at all:

    Does the overfit signature transfer?  **Partially.**  Robustness features
    transfer; shape features do not and two of them invert sign across
    families.  Use partial pooling with family-conditional thresholds, enforce
    multi-theme campaigns, track leave-one-family-out.

docs/nullius-tech-architecture.md §11.1 spells the call in code, with the
feature's own clause as its comment:

    # Standing metric: hold an entire theme out of the dreaming pool, evaluate on it.
    lofo_delta_ir = evaluate(policy, worlds_of_theme(held_out_theme))

— and §16 lists ``leave-one-family-out transfer ΔIR`` among the research
metrics a campaign is observed by.  This module is that line, made to run:
:func:`family_transfer` answers the ``lofo_delta_ir`` of a held-out root, and
the record it returns carries the delta under the document's own name
(:attr:`FamilyTransfer.delta_ir`).

**Why the 70/30 holdout is not enough, and this one is.**  Feature 278's
split protects the *report* from the *selection*, but it samples worlds, not
families: a random 30% of the pool carries every family the pool carries,
very nearly in proportion.  So the holdout worlds of family ``F`` sat beside
train worlds of ``F`` in the pool the policy was selected over — the selection
*saw* ``F``'s texture, and a policy that had memorised it passes that holdout
with a ΔIR that is not transfer.  §4.5's finding is exactly that the failure
is family-shaped (*"shape features do not and two of them invert sign across
families"*), so the one leak a world-shaped holdout cannot catch is the
family-shaped one.  Holding the root out **entirely** — every world whose
theme root is ``F`` leaves the pool, none of its texture remains for a
selection to read — is the only holdout memorised family texture cannot
survive: anything that still reads well on ``F`` afterwards was carried there
by research discipline, which is the quantity the metric exists to measure and
the reason §4.5 calls it *"the only honest way to tell learned research
discipline from memorized family texture"*.

What this module is
-------------------

Three spellings of one act, and the records they answer with:

* :func:`leave_one_family_out` — the pure judgment: the pool's worlds with
  the family each belongs to, and the root to hold out, in; the two halves
  out.  The shape of the ladder's other tools
  (:func:`dreaming.ladder.rejects_thin_pool`,
  :func:`dreaming.cap.revision_cap`,
  :func:`dreaming.split.split_pool`): a pure function of what the caller
  already holds, which never opens a database, because a verdict is not a
  count and the pool is the caller's to enumerate;
* :func:`family_transfer` — the feature's own call, the one §11.1 spells
  ``lofo_delta_ir = evaluate(policy, worlds_of_theme(...))``: two arms'
  per-world out-of-sample IR readings, the pool's families and the held-out
  root in, and the paired delta **on that root's worlds alone** out;
* :func:`pooled_family_transfer` — the same judgment over the **store**: the
  arms read from the pool's own ``replay_score`` rows by policy version, the
  families the caller holds checked against the pool's membership before a
  figure is answered.

The answers are a :class:`FamilyPartition` — the pool with one family removed,
the family's worlds held out whole, every root the pool carried — and a
:class:`FamilyTransfer` — the held-out root, its worlds (the evidence the
delta is over), the count of worlds that remained (the pool the selection
runs over), and feature 281's :class:`~dreaming.paired.PairedDifference`
itself, carried rather than respelled: the delta on a held-out theme *is* a
paired comparison over that theme's worlds, and this feature's whole
arithmetic is §11.0's, reached through the seam the dependency declares.

The family is the caller's fact
-------------------------------

**``theme_root`` is not a column of the pool, and this module does not invent
one.**  The pool's two tables name worlds and score them; the family a world
belongs to is a fact about the *world*, carried by the question seam's
``meta()`` (architecture §11, feature 219's accessor — *"``theme_root`` used
only via ``meta()``"*) and reported by the adapters that wrap each pool's
worlds (a bootstrap world answers its domain on every cell; a financial
world's root is the theme its discovery tree was planted in, §9.1's
``node.theme_root``).  No member in this workspace imports another, so this
module cannot ask those members; instead the caller — the loop that walked
the pool and knows its worlds — hands the families in whole, as a mapping of
world id to theme root, the same stance :func:`dreaming.split.split_pool`
takes for the pool's ids: read once, handed whole, never re-derived here.

That makes the mapping a seam, and the seam validates what it reads: every
world non-empty text, every root non-empty text, a bare string refused where
a mapping belongs (Python would iterate its characters, and a pool nobody
holds would split into families nobody authored).  The store seam
(:func:`pooled_family_transfer`) goes one step further than the pure one,
because it can: it reads the pool's membership
(:func:`dreaming.split.pool_worlds` — the union law, a world once whichever
half names it) and **refuses a family census that disagrees with the store**,
in either direction.  A mapping that misses pool worlds would leave them in
no family — neither held out nor retained, invisible to a partition that
claims to be of the pool — and a mapping naming worlds the store does not
hold would ground a transfer figure partly on worlds that do not exist.
*"Holding an entire theme root out of the pool"* is a claim about the pool,
and at the store seam the pool is ground truth.

The delta, and whose law it is
------------------------------

**The delta is feature 281's statistic over the held-out root's worlds,
consumed and never respelled.**  §11.0's instruction — *"score each commit
continuously … and run the comparison paired — same policy pair, same
worlds"* — is the comparison this module restricts to one family: both arms'
readings are kept **only** for the worlds of the root asked out, and the
differences are tested over exactly those.  Readings for any other world are
not evaluated, which is the hold-out itself rather than a drop — the same
act the 70/30 split performs on worlds, performed on a family.  Everything
downstream of the restriction is delegated: a world only one arm carries is
refused by the pairing's own law in the pairing's own word
(:class:`~dreaming.errors.PairedComparisonError`), a family of one world is
refused by the same law (one difference has no spread), a non-finite reading
on a held-out world by the figure law, and the ``spread``/``delta``/``power``
keywords pass straight through to :func:`dreaming.paired.paired_ir_difference`
so the two spellings of the capacity arithmetic cannot disagree.  This module
mints no second arithmetic and no second pairing law — the same delegation
the split performs for the floor.

**The floor judges the pool that remains.**  Holding a root out is only
meaningful over a pool the ladder still admits: a retained pool below
§12.1's floor cannot be dreamed on at all (feature 275's own sentence), so a
transfer figure computed over a selection that could never have run would be
a number about nothing.  The judgment is the ladder's own, delegated —
:func:`dreaming.ladder.rejects_thin_pool` over the retained count, in the
floor's word — the identical delegation the cap, the ceiling and the split
perform, so the ladder has one spelling per rung and this module never speaks
for it.

What this module is not
-----------------------

**It is not the selector, the split, the bar or the campaign constraint.**
Running ``M`` revisions and selecting the argmax are features 271-274's acts,
and the honest use of this metric is *select over the retained half, then ask
for the delta on the held-out family* — the module supplies both halves of
that act and polices neither caller, because what the selection read is
feature 274's subject and the comparison's honesty is feature 281's.  The
70/30 train/holdout split (feature 278) is a *world-shaped* holdout that
rotates per cycle; this is the *family-shaped* one that stands — the two
answer different leaks and neither replaces the other.  The ``√(2 ln M)`` bar
is feature 280's, and multi-theme campaigns are planned by feature 229's
``plan_grid`` constraint (§11.1's *other* enforcement requirement); a pool
whose worlds all carry one root makes this module's retained half empty, and
that is refused by the delegated floor as the campaign-diversity failure it
is, not by a second law minted here.

**It writes nothing, anywhere.**  The pool's two tables are read and never
touched — the same read-time restraint :mod:`dreaming.split` and
:mod:`dreaming.paired` state, for the same reason: feature 270 holds the pool
fixed while a cycle walks it, and the transfer figure is one of the things
the cycle computes *during* that hold, so a read is what it must be.  No new
component: feature 270's single ``"dreaming"`` component is the member's
whole composition, and the metric is reached the way the floor, the cap, the
ceiling, the split and the comparison are, as free functions beside the
store.  No seat edit, no migration, no third party: ``os`` and the member's
own siblings — the arithmetic is feature 281's, the membership law is
feature 278's and the URL seam is feature 270's, all consumed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .cycle import sqlite_path
from .errors import (
    FreezeRequestError,
    SplitStoreError,
    TransferRequestError,
    TransferStoreError,
)
from .ladder import LADDER_FLOOR_WORLDS, rejects_thin_pool, validated_floor
from .layout import DATABASE_URL_ENV
from .paired import POWER, PairedDifference, _pool_arm, paired_ir_difference
from .split import pool_worlds

__all__ = [
    "FamilyPartition",
    "FamilyTransfer",
    "family_transfer",
    "leave_one_family_out",
    "pooled_family_transfer",
]


def _validated_themes(value: Any) -> dict[str, str]:
    """Check that ``value`` is the pool's families, or refuse it as the ask's own.

    The pool's families are a mapping of world id to the theme root that world
    belongs to — one family per world, because a world's root is a fact about
    the world (``meta()``'s own field) rather than a label a caller re-assigns.
    Both sides are non-empty text: a world is named by the same non-empty id
    every other seam in this member reads, and a root that names no theme
    belongs to no family — a world carrying it would sit in neither half of
    any partition, invisible to the very claim *"held out of the pool"* that
    the partition exists to make true.

    A bare string is refused where a mapping belongs, and the refusal is
    explicit rather than incidental: Python would iterate a string's
    *characters*, and a pool handed as one world's id would silently become
    as many one-character worlds as the string has letters — a pool nobody
    holds, divided into families nobody authored, with nothing in the
    partition looking wrong.
    """
    if isinstance(value, (str, bytes)):
        raise TransferRequestError(
            f"the pool's families are a mapping of world id to theme root — "
            f"got the single {type(value).__name__} {value!r}; a bare string "
            "names one world's family, and iterating it would read its "
            "characters as worlds nobody holds. Pass every pool world's root, "
            "keyed by world id"
        )
    if not isinstance(value, Mapping):
        raise TransferRequestError(
            f"the pool's families are a mapping of world id to theme root — "
            f"got {value!r} ({type(value).__name__}); a family is held out by "
            "collecting the worlds that belong to it, and a value that cannot "
            "be walked by world names no pool to hold a root out of"
        )
    families: dict[str, str] = {}
    for world_id, root in value.items():
        if not isinstance(world_id, str) or not world_id.strip():
            raise TransferRequestError(
                f"a world is named by a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the pool's families are keyed "
                "by the world ids every other seam in this member reads, and "
                "an id that names no world belongs to no family"
            )
        if not isinstance(root, str) or not root.strip():
            raise TransferRequestError(
                f"a theme root is named by non-empty text — got {root!r} "
                f"({type(root).__name__}) for world {world_id!r}; the root is "
                "the family the world belongs to (``meta()``'s own field), and "
                "a root that names no theme leaves the world in neither half "
                "of the partition"
            )
        families[world_id] = root
    return families


def _validated_theme(value: Any) -> str:
    """Check that ``value`` names a theme root, or refuse it.

    Non-empty text, the one spelling of what a root is everywhere the family
    dimension is spoken (§9.1's ``node.theme_root`` is ``TEXT NOT NULL``,
    :data:`bootstrap._question.BOOTSTRAP_THEME_ROOT` is a slug, feature 241's
    legal set is slugs).  Refused *before* any family is collected: an ask
    that names no root is the ask's own fault, and the repair is to name one.
    """
    if not isinstance(value, str) or not value.strip():
        raise TransferRequestError(
            f"the theme root held out is named by non-empty text — got "
            f"{value!r} ({type(value).__name__}); holding a family out of the "
            "pool starts by naming the family, and a value that names no "
            "theme names nothing to hold out"
        )
    return value


def _carried_root(families: Mapping[str, str], theme: str) -> str:
    """Check that the pool carries the root, or refuse it.

    §4.5's act is *"hold an entire theme root out of the dreaming pool"* — the
    root has to be in the pool for the holding out to remove anything.  A root
    the pool does not carry is refused rather than answered with an empty
    family: an empty hold-out would pair no worlds, and the paired statistic's
    own refusal would then describe a pairing failure where the fact is that
    the caller named a family the pool has none of.  The refusal states the
    roots the pool *does* carry, so an operator holding a stale census sees the
    drift rather than a refusal about statistics.
    """
    if theme not in set(families.values()):
        carried = sorted(set(families.values()))
        named = ", ".join(repr(root) for root in carried[:3]) + (
            ", …" if len(carried) > 3 else ""
        )
        raise TransferRequestError(
            f"the theme root {theme!r} is not one the pool carries — its "
            f"families are {named or 'none at all'}; holding a root out of "
            "the pool removes that root's worlds, and a root with no worlds "
            "removes nothing, so the transfer figure on it would be a delta "
            "over no evidence that still looked like a measurement. Hold a "
            "family the pool carries out, or re-read the pool's families"
        )
    return theme


def _validated_readings(value: Any, *, name: str) -> Mapping[str, Any]:
    """Check that ``value`` is one arm's readings, or refuse it — shape only.

    An arm is a mapping of world id to that arm's out-of-sample IR reading on
    the world, the shape §11.0's pairing needs.  Only the *container* is
    checked here: the worlds it may carry and the figures on them are
    feature 281's to judge, and this module says so by refusing exactly one
    thing — a value that cannot be walked by world, of which the dangerous
    case is a bare string (Python would iterate its characters, and one
    world's readings would silently become as many one-character worlds',
    restricted, paired and reported).  A non-finite figure or a world only
    one arm carries reaches :func:`dreaming.paired.paired_ir_difference` and
    is refused there, in the pairing's own vocabulary — the delegation this
    module states and does not re-spell.
    """
    if isinstance(value, (str, bytes)):
        raise TransferRequestError(
            f"the {name} arm's readings are a mapping of world id to figure — "
            f"got the single {type(value).__name__} {value!r}; a bare string "
            "names one world, and iterating it would read its characters as "
            "worlds nobody holds"
        )
    if not isinstance(value, Mapping):
        raise TransferRequestError(
            f"the {name} arm's readings are a mapping of world id to figure — "
            f"got {value!r} ({type(value).__name__}); §4.5's metric evaluates "
            "on the held-out family's worlds, and an arm that cannot be "
            "walked by world names no readings to evaluate"
        )
    return value


def _held_out_partition(
    families: Mapping[str, str], theme: str, floor: Any
) -> FamilyPartition:
    """The pool with ``theme`` held out, once the ask has been validated.

    The ladder's floor over the **retained** count, then the partition: the
    family's worlds held out whole, everything else retained, both in the id
    order :func:`dreaming.split.pool_worlds` answers (``ORDER BY world_id``),
    so the same families answer the same partition in any process whatever
    order the caller built the mapping in.  The floor is the ladder's own
    judgment in the ladder's own word — a retained pool too thin to dream on
    cannot ground a transfer figure, because the selection the figure
    presumes would itself be refused — and this private spelling exists so
    :func:`leave_one_family_out` and :func:`family_transfer` refuse in the
    same order without either re-deriving the other.
    """
    floor_count = validated_floor(floor)
    held_out = tuple(
        sorted(world for world, root in families.items() if root == theme)
    )
    retained = tuple(
        sorted(world for world, root in families.items() if root != theme)
    )
    rejects_thin_pool(len(retained), gate=floor_count)
    return FamilyPartition(
        theme=theme,
        held_out=held_out,
        retained=retained,
        roots=tuple(sorted(set(families.values()))),
    )


class FamilyPartition:
    """One held-out family and the pool it left — the split's family shape.

    The partition's facts and nothing derived: the root held out, the worlds
    of that root (held out *whole* — §4.5's *"an entire theme root"*), the
    worlds that remain (the pool the selection runs over), and every root the
    pool carried.  Both halves are carried in the pool's id order so the
    record is reproducible rather than incidental, the way a
    :class:`dreaming.split.PoolSplit` is: the same families and the same root
    construct the same partition in any process.

    Answers :meth:`is_held_out` / :meth:`is_retained` for the caller that
    holds one world id and needs to know which side of the hold-out a reading
    belongs to.  A world the partition does not hold is *refused* by both
    predicates rather than answered ``False``, for the reason the split's own
    predicates refuse: a world outside the pool is neither held out nor
    retained, and an answer that read as one side would let a caller mark a
    world the hold-out never saw — the leak the hold-out exists to prevent.
    """

    __slots__ = (
        "_held_out_set",
        "_retained_set",
        "held_out",
        "retained",
        "roots",
        "theme",
    )

    def __init__(
        self,
        *,
        theme: Any,
        held_out,
        retained,
        roots,
    ) -> None:
        held_out_tuple = tuple(held_out)
        retained_tuple = tuple(retained)
        held_out_set = frozenset(held_out_tuple)
        retained_set = frozenset(retained_tuple)
        overlap = held_out_set & retained_set
        if overlap:
            raise TransferRequestError(
                f"the two halves hold the pool between them, disjointly — "
                f"got {min(overlap)!r} in both; a world is of one family, so "
                "it is either held out with its root or retained with the "
                "rest, and a world in both would be evaluated on and selected "
                "over — the family-shaped leak this partition exists to "
                "prevent"
            )
        #: The theme root held out — §4.5's *"an entire theme root"*, named
        #: so the record says *which* family was the held-out one.
        self.theme = _validated_theme(theme)
        #: The held-out family's world ids, in the pool's id order — the
        #: worlds §11.1 evaluates on (``worlds_of_theme(held_out_theme)``).
        self.held_out = held_out_tuple
        #: The worlds that remain, in the same order — the pool the
        #: selection runs over once the family is out of it.
        self.retained = retained_tuple
        #: Every root the pool carried, sorted — the families the hold-out
        #: was chosen among, carried so an operator reading a partition sees
        #: the pool's breadth rather than only the one root asked out.
        self.roots = tuple(roots)
        # The membership sets the predicates answer from, precomputed once so
        # a caller marking a thousand score rows pays a lookup per row rather
        # than a rebuild.
        self._held_out_set = held_out_set
        self._retained_set = retained_set

    # -- The two faces --------------------------------------------------------

    @property
    def world_count(self) -> int:
        """How many worlds the partition holds — both halves, the pool it split."""
        return len(self.held_out) + len(self.retained)

    @property
    def family_count(self) -> int:
        """How many families the pool carried — the count §11.1's ``plan_grid``
        constraint keeps at three or more on the campaign side."""
        return len(self.roots)

    def is_held_out(self, world_id: Any) -> bool:
        """Whether ``world_id`` is one of the held-out family's worlds.

        The predicate the evaluation side reads — §11.1's
        ``worlds_of_theme(held_out_theme)`` answered per world.  A world the
        partition does not hold is **refused** rather than answered ``False``:
        a world outside the pool is in no family this partition knows, and an
        answer that read as *retained* would let a caller select over a world
        the hold-out never saw.
        """
        self._validated_member(world_id)
        return world_id in self._held_out_set

    def is_retained(self, world_id: Any) -> bool:
        """Whether ``world_id`` is one of the worlds the selection runs over.

        The predicate the selection side reads — the pool with the family out.
        The same refusal for a world the partition does not hold as
        :meth:`is_held_out` states, and for the same reason.
        """
        self._validated_member(world_id)
        return world_id in self._retained_set

    def _validated_member(self, world_id: Any) -> str:
        """Check that ``world_id`` names a world this partition holds, or refuse."""
        if not isinstance(world_id, str) or not world_id.strip():
            raise TransferRequestError(
                f"a world is named by a non-empty string — got {world_id!r} "
                f"({type(world_id).__name__}); the partition's halves answer "
                "about the worlds they hold, and a value that names no world "
                "belongs to neither"
            )
        if (
            world_id not in self._held_out_set
            and world_id not in self._retained_set
        ):
            raise TransferRequestError(
                f"the partition holds {self.world_count} world(s) and "
                f"{world_id!r} is not one of them — a world outside the pool "
                "is neither held out nor retained, and answering either would "
                "mark a world the hold-out never saw. Partition the pool the "
                "world was read from, or check the id"
            )
        return world_id

    # -- The value --------------------------------------------------------

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a report reads the partition through: the root, the two
        halves and the families, under the names the record's own fields
        answer to.
        """
        return {
            "theme": self.theme,
            "held_out": self.held_out,
            "retained": self.retained,
            "roots": self.roots,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FamilyPartition):
            return NotImplemented
        return (
            self.theme,
            self.held_out,
            self.retained,
            self.roots,
        ) == (other.theme, other.held_out, other.retained, other.roots)

    def __hash__(self) -> int:
        return hash((self.theme, self.held_out, self.retained, self.roots))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FamilyPartition(theme={self.theme!r}, "
            f"held_out={len(self.held_out)} world(s), "
            f"retained={len(self.retained)} world(s))"
        )


def leave_one_family_out(
    themes: Any,
    *,
    theme: Any,
    floor: Any = LADDER_FLOOR_WORLDS,
) -> FamilyPartition:
    """Hold one theme root out of the pool — feature 282's judgment.

    The pure half of the feature's act: the pool's families (a mapping of
    world id to theme root) and the root to hold out in, the two halves out.
    *Which* worlds leave is decided by nothing but their root — every world
    whose root is ``theme`` is held out, everything else is retained — so the
    hold-out is **entire** by construction: there is no parameter that could
    hold half a family out, and §4.5's sentence has no other spelling.

    ``themes`` are the pool's families — the caller reads them once (the
    question seam's ``meta()`` per world, or its own census) and hands them
    whole; passed in rather than read, so this function never opens a
    database, the verdict shape the ladder's other tools take.  ``theme`` is
    the root to hold out, and must be one the pool carries — a root with no
    worlds removes nothing.  ``floor`` is passed straight through to the
    ladder's judgment as its own ``gate`` keyword, so the two spellings of
    the bottom rung cannot disagree.

    Refuses, in this order, each naming what it is about:

    1. ``themes`` that are not a mapping of non-empty world ids to non-empty
       roots — a bare string, a non-mapping, a blank or non-text key or root
       (:class:`~dreaming.errors.TransferRequestError`);
    2. a ``theme`` that is not non-empty text, or a root the pool does not
       carry (:class:`~dreaming.errors.TransferRequestError`) — the ask's own
       facts, refused before any family is collected;
    3. a ``floor`` that is not a world count — refused by the ladder's own
       :func:`~dreaming.ladder.validated_floor`, in the ladder's vocabulary,
       because the floor is feature 275's fact;
    4. a retained pool below the floor — the family asked out carried so much
       of the pool that what remains is too thin to dream on, refused by the
       ladder in its own word and its own class
       (:class:`~dreaming.errors.PoolTooThinError`).
    """
    families = _validated_themes(themes)
    root = _carried_root(families, _validated_theme(theme))
    return _held_out_partition(families, root, floor)


class FamilyTransfer:
    """One taken leave-one-family-out transfer — feature 282's answer.

    The metric's facts and nothing derived: the root held out, its worlds
    (the evidence the delta is over — §11.1's ``worlds_of_theme(...)``), the
    count of worlds that remained (the pool the selection runs over, and the
    figure the delegated floor judged), and feature 281's
    :class:`~dreaming.paired.PairedDifference` itself — carried whole rather
    than flattened, because the delta on a held-out theme *is* a paired
    comparison and every figure §11.0's gate reads (the ``n``, the
    ``σ_diff``, the ``t``, the ``p``) is already spelled once, in the record
    this feature depends on.  An operator reading a transfer figure can see
    *which* family it was held out on and over *how many* worlds, not only
    that a delta came out — the same reason a
    :class:`dreaming.split.PoolSplit` carries its halves.

    Held as a value rather than a live view, for the reason the split's
    records give: a transfer figure is what an M3 decision is read from, and
    a caller holding one must not be holding a handle a later reading can
    move under it.
    """

    __slots__ = (
        "difference",
        "held_out",
        "retained_worlds",
        "theme",
    )

    def __init__(
        self,
        *,
        theme: Any,
        held_out,
        retained_worlds: int,
        difference: PairedDifference,
    ) -> None:
        #: The theme root the delta is on — §11's *"ΔIR on a held-out theme
        #: root"*, named so the figure says which family it transferred to.
        self.theme = _validated_theme(theme)
        #: The held-out family's world ids, in the pool's id order — the
        #: worlds the delta was taken over.
        self.held_out = tuple(held_out)
        #: How many worlds remained once the family was held out — the pool
        #: the selection ran over, carried as the count the delegated floor
        #: judged (a :class:`~dreaming.cap.CapRecord` carries its
        #: ``world_count`` for the same reason).
        self.retained_worlds = retained_worlds
        #: The paired comparison over the held-out family's worlds — feature
        #: 281's record, consumed rather than respelled.
        self.difference = difference

    # -- The metric's own figures --------------------------------------------

    @property
    def delta_ir(self) -> float:
        """The mean paired difference on the held-out family — the metric.

        §11.1's own variable name (``lofo_delta_ir``) for the figure §11's
        table states as *"Leave-one-family-out transfer: ΔIR on a held-out
        theme root"*: the candidate arm's mean reading minus the baseline
        arm's, over the held-out family's worlds, world by world.  A
        convenience over :attr:`difference`'s own field, not a second
        statistic.
        """
        return self.difference.mean_difference

    @property
    def transfers(self) -> bool:
        """Whether the held-out family reads better under the candidate.

        §11's target for this metric, *"ΔIR on a held-out theme root > 0"*
        (§12's M3 exit criterion states the same bar), read strictly: a delta
        of exactly zero is not transfer.  This answers only the direction —
        whether the M3 gate is met across the pool's families, and what to do
        about a family that did not transfer, is the gate's (§12), not this
        record's.
        """
        return self.delta_ir > 0.0

    # -- The value --------------------------------------------------------

    def row(self) -> dict[str, object]:
        """The record as a mapping — a fresh dict per call.

        The shape a report or a dashboard (§16's research metrics) reads the
        transfer through: the family, its worlds, the pool it left, and the
        whole paired comparison — evidence included, the same stance the
        split and the comparison's own records take toward their figures.
        """
        return {
            "theme": self.theme,
            "held_out": self.held_out,
            "retained_worlds": self.retained_worlds,
            "difference": self.difference.row(),
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FamilyTransfer):
            return NotImplemented
        return (
            self.theme,
            self.held_out,
            self.retained_worlds,
            self.difference,
        ) == (
            other.theme,
            other.held_out,
            other.retained_worlds,
            other.difference,
        )

    def __hash__(self) -> int:
        return hash(
            (self.theme, self.held_out, self.retained_worlds, self.difference)
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"FamilyTransfer(theme={self.theme!r}, "
            f"delta_ir={self.delta_ir!r}, "
            f"held_out={len(self.held_out)} world(s))"
        )


def family_transfer(
    candidate: Any,
    baseline: Any,
    *,
    themes: Any,
    theme: Any,
    floor: Any = LADDER_FLOOR_WORLDS,
    spread: Any | None = None,
    delta: Any = 0.0,
    power: Any = POWER,
) -> FamilyTransfer:
    """The delta on one held-out theme — feature 282's call.

    §11.1's line, made to run — ``lofo_delta_ir = evaluate(policy,
    worlds_of_theme(held_out_theme))`` — with the evaluation spelled as this
    member already spells it: both arms' readings are kept **only** for the
    worlds of ``theme``, and the differences over exactly those worlds are
    tested paired (:func:`dreaming.paired.paired_ir_difference`).  Readings
    for any other world are not evaluated — that is the hold-out, not a drop,
    and it is what makes the figure a *transfer* measurement: nothing the
    selection could have read on the held-out family is in the comparison.

    ``candidate`` and ``baseline`` are the two arms' per-world out-of-sample
    IR readings (mappings of world id to figure — §12's dreaming revision and
    its M2 fixed baseline, or any two policies); ``themes`` the pool's
    families as the caller holds them; ``theme`` the root to hold out; and
    ``spread``/``delta``/``power`` the capacity figures, passed straight
    through to the paired statistic so the two spellings of §11.0's arithmetic
    cannot disagree.  ``floor`` judges the *retained* pool, delegated to the
    ladder.

    Refuses, in this order, each naming what it is about:

    1. ``themes``/``theme`` ask facts, and the two arms' shapes — a mapping
       that is not a mapping, a blank id or root, a root the pool does not
       carry, a bare string where an arm belongs
       (:class:`~dreaming.errors.TransferRequestError`);
    2. a ``floor`` that is not a world count, or a retained pool below it —
       the ladder's own word
       (:class:`~dreaming.errors.PoolTooThinError`), because a selection that
       could not have run grounds no transfer figure;
    3. everything about the readings on the held-out family, in feature
       281's own vocabulary and by its own law: a world of the family only
       one arm carries, a family too small to spread, a non-finite figure, a
       degenerate pool, a sizing the capacity refuses
       (:class:`~dreaming.errors.PairedComparisonError`,
       :class:`~dreaming.errors.ProportionComparisonError`).
    """
    families = _validated_themes(themes)
    root = _carried_root(families, _validated_theme(theme))
    candidate_arm = _validated_readings(candidate, name="candidate")
    baseline_arm = _validated_readings(baseline, name="baseline")
    partition = _held_out_partition(families, root, floor)

    held = frozenset(partition.held_out)
    difference = paired_ir_difference(
        {world: figure for world, figure in candidate_arm.items() if world in held},
        {world: figure for world, figure in baseline_arm.items() if world in held},
        spread=spread,
        delta=delta,
        power=power,
    )
    return FamilyTransfer(
        theme=root,
        held_out=partition.held_out,
        retained_worlds=len(partition.retained),
        difference=difference,
    )


def _validated_policy(value: Any) -> str:
    """Check that ``value`` names a policy version, or refuse it.

    Non-empty text, the one spelling of what a policy version is in this
    workspace (``0109``'s ``policy_version`` column, ``TEXT NOT NULL
    UNIQUE``).  Refused in this module's own vocabulary and *before* any
    database is opened — an arm named by nothing is the ask's own fault, the
    same stance :func:`dreaming.paired._validated_policy` states, spelled
    here rather than imported so the refusal names the family metric's repair
    rather than the comparison's.
    """
    if not isinstance(value, str) or not value.strip():
        raise TransferRequestError(
            f"a policy version is named by a non-empty string — got "
            f"{value!r} ({type(value).__name__}); an arm of the transfer is a "
            "specific policy, and a value that names none names no arm to "
            "read the held-out family against"
        )
    return value


def _transfer_path(database_url: Any, env: Mapping[str, str] | None) -> Path:
    """Resolve the pool a transfer is taken over: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.split._split_path`,
    :func:`dreaming.cap._cap_path` and :func:`dreaming.paired._pool_path`
    take — an explicit URL first, then the deployment's ``DATABASE_URL`` —
    and the same refusal stance: an act that means to read the pool and
    resolves nothing is refused by name rather than answered with ``None``,
    because a transfer taken over no database would report a delta on a
    family of worlds that were never read.  A URL this member cannot speak is
    refused in this module's vocabulary, translated at the seam from the one
    spelling of what a ``sqlite:///`` URL names.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise TransferRequestError(
            f"taking a leave-one-family-out transfer needs the database the "
            f"pool lives in — pass it explicitly or set {DATABASE_URL_ENV}. "
            "A delta reported over no database would be a figure on worlds "
            "that were never read, and it would look exactly like one that "
            "had been"
        )
    try:
        return sqlite_path(url)
    except FreezeRequestError as refusal:
        raise TransferRequestError(
            f"the pool a family is held out of lives in the database the "
            f"replay pool lives in, and the URL given does not name one this "
            f"member can speak — see the refusal it raised: {refusal}. The "
            "transfer reads the pool's own rows rather than fetching two arms "
            "it could evaluate against nothing, because §11.1's standing "
            "metric is a claim about one pool and its families"
        ) from refusal


def pooled_family_transfer(
    candidate_policy: Any,
    baseline_policy: Any,
    *,
    themes: Any,
    theme: Any,
    database_url: str | None = None,
    floor: Any = LADDER_FLOOR_WORLDS,
    spread: Any | None = None,
    delta: Any = 0.0,
    power: Any = POWER,
    env: Mapping[str, str] | None = None,
) -> FamilyTransfer:
    """The delta on one held-out theme, over the pool's own rows — the store seam.

    The feature's own act against the store: name the two arms by their
    ``policy_version``, resolve the database the deployment names (an
    explicit URL first, then ``DATABASE_URL``, refused when neither names
    one), read the pool's membership (:func:`dreaming.split.pool_worlds` — a
    world once, whichever half names it), check the families given against
    it, read each arm's per-world readings from ``replay_score``
    (:func:`dreaming.paired._pool_arm` — the last row written per world,
    deterministically), and answer the transfer over them
    (:func:`family_transfer`).

    **The families must cover the pool, exactly.**  The pure seam takes the
    caller's census on trust; this seam has the store and does not.  A
    mapping that misses pool worlds leaves them in no family — invisible to
    a partition that claims to be *of the pool*, silently free to sit under
    a selection that believed its family was gone — and a mapping naming
    worlds the store does not hold grounds the figure partly on worlds that
    do not exist.  Both are refused (:class:`~dreaming.errors.
    TransferStoreError`) with the disagreement named, because *"holding an
    entire theme root out of the pool"* is a claim about the pool and at this
    seam the pool is ground truth.

    Refuses, in this order, each naming what it is about:

    1. a policy version that is not non-empty text, the same version named as
       both arms, or ``themes``/``theme`` ask facts
       (:class:`~dreaming.errors.TransferRequestError`) — refused before any
       database is opened;
    2. a URL that names no database or one this member cannot speak
       (:class:`~dreaming.errors.TransferRequestError`, translated at the
       seam);
    3. a database that holds no pool tables — no pool to hold a family out
       of (:class:`~dreaming.errors.TransferStoreError`, translated from the
       membership read's own refusal);
    4. families that disagree with the pool's membership, in either direction
       (:class:`~dreaming.errors.TransferStoreError`);
    5. the retained pool below the floor
       (:class:`~dreaming.errors.PoolTooThinError`), and the pairing laws
       (:class:`~dreaming.errors.PairedComparisonError`,
       :class:`~dreaming.errors.ProportionComparisonError`) — delegated, by
       :func:`family_transfer`.
    """
    candidate = _validated_policy(candidate_policy)
    baseline = _validated_policy(baseline_policy)
    if candidate == baseline:
        raise TransferRequestError(
            f"the two arms of a transfer are two policies — got {candidate!r} "
            "on both sides; a policy evaluated against itself reads the same "
            "figure on every world of the held-out family, so every "
            "difference is exactly zero and the delta would report no "
            "transfer while looking like a measurement of it. Name the arm "
            "this policy is to be transferred against"
        )
    families = _validated_themes(themes)
    root = _carried_root(families, _validated_theme(theme))

    path = _transfer_path(database_url, env)
    try:
        worlds = pool_worlds(path)
    except SplitStoreError as refusal:
        raise TransferStoreError(
            f"the database at {path} holds no pool to hold a family out of — "
            f"see the refusal the membership read raised: {refusal}. A "
            "transfer over a database without the pool's tables would report "
            "a delta on a family of worlds that were never read, and nothing "
            f"in the figure would look wrong. Point {DATABASE_URL_ENV} at the "
            "database the replay pool lives in, or migrate it"
        ) from refusal

    unnamed = sorted(set(worlds) - set(families))
    phantom = sorted(set(families) - set(worlds))
    if unnamed or phantom:
        missing = ", ".join(repr(world) for world in unnamed[:3]) + (
            ", …" if len(unnamed) > 3 else ""
        )
        invented = ", ".join(repr(world) for world in phantom[:3]) + (
            ", …" if len(phantom) > 3 else ""
        )
        raise TransferStoreError(
            f"the families given do not cover the pool at {path} — the pool "
            f"holds {len(worlds)} world(s) the mapping does not name"
            f" ({missing or 'none'})"
            if unnamed
            else (
                f"the families given name worlds the pool at {path} does not "
                f"hold — {invented or 'none'}; holding an entire theme root "
                "out of the pool is a claim about the pool, and a family "
                "census that disagrees with it leaves worlds in no family or "
                "grounds the figure on worlds that do not exist. Re-read the "
                "pool's families for every world it holds"
            )
        )
    return family_transfer(
        _pool_arm(path, candidate),
        _pool_arm(path, baseline),
        themes=families,
        theme=root,
        floor=floor,
        spread=spread,
        delta=delta,
        power=power,
    )
