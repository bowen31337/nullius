"""Feature 272, the sweep — every candidate revision against every stored world.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 272: *System evaluates
every candidate revision against every stored world, persisting one score per
pair.*  docs/alpha-engine-prd.md §C5 states the act as the middle clause of the
loop, between production and selection::

    Per outer iteration: hold the replay pool fixed, run ``M`` code revisions
    of ``π``, **evaluate each on every stored tree**, select the argmax under
    §7.

and docs/nullius-tech-architecture.md §10.3.1 spells the same clause as the
sentence the whole meta-level discipline is written around — *"every candidate
revision against every stored world"* — while §10.4 puts the figure on it:
*"200 worlds × 40 policy revisions … ~400 core-seconds per dreaming cycle,
embarrassingly parallel"*.  §C5's key interaction #3 states the order the loop
runs in: *"each replays across every stored world without touching the
evaluator"*.

**The coverage law is the feature.**  `M` candidates and `n` worlds is one
score per *pair* — ``M × n`` rows, no pair skipped and no pair taken twice —
and this module is the part of the system that makes that a fact rather than an
intention.  A sweep that quietly skipped a pair would leave a candidate whose
average is over a different world set than its rivals', and the argmax feature
274 takes over those averages would be comparing two tournaments while every
figure in the result looked like a score.  §12.1's *"The dreaming loop overfits
its own replay pool"* is the risk the discipline exists for: the guarantee
``V^{m★} ≥ V^0`` is a guarantee about a **fixed history**, and a history that
is fixed for one candidate and not for the next is not fixed.

Two halves, one act
-------------------

**The judgment is pure.**  :func:`plan_sweep` takes the candidates feature 271
produced, the pool's worlds, and (optionally) the split feature 278 took, and
answers the **plan**: one :class:`SweepPair` per ``(candidate, world)``, in a
total order, each carrying the two identities the evidence is filed under and
the half of the pool the world belongs to.  It reads no database, opens no
policy and runs nothing — the shape :func:`dreaming.split.split_pool`,
:func:`dreaming.ceiling.rejects_uncapped_sweep` and
:func:`dreaming.bar.selection_bar` all take, and for the same reason: the
coverage claim is checkable without doing the work, and a plan a caller can
hold is a plan a caller can audit against the rows that landed.

**The act is the store seam.**  :func:`sweep_candidates` is the feature's own
call: resolve the database the deployment names, read the pool's worlds, plan
the cross product, drive the caller's **evaluator** once per pair, and persist
each answer as one ``replay_score`` row — through the replay member's own
writer, reached through the composed application's seat rather than imported.
The evaluator is the one collaborator this member cannot supply, and the reason
is the workspace's oldest rule: **no member imports another.**  Running a
policy over a world's stored tree is the replay path's act (features 245-255 in
the ``replay`` member, which holds the tree, the transition, the scoring and
the row writer), so it arrives here as a callable — the same duck-typed seam
:func:`replay.rounds.run_replay` takes for its ``select`` and its ``question``,
and the same seam feature 281's comparison takes when it is handed readings
instead of computing them.

**The row is the replay member's, spelled once.**  ``replay_score`` and its
eight columns are migration ``0109``'s and the replay member's, and this module
needs two things about that table: its *name*, which it takes from
:mod:`dreaming.layout` — the member's one restatement of the pool's shape,
pinned against ``0109`` and against the bootstrap member by
``test_cross_member.py`` — and the fact that a row is written per
``(policy_version, world_id)`` at a ``beta``, which is feature 255's own
signature.  Neither is respelled as a write: the sweep hands the answer and the
four facts to the replay member's ``persist_replay_score`` and the row is
minted there, so ``0109``'s shape keeps one writer in this workspace rather
than two.

What it is not
--------------

**It is not the production, the incumbent's return, the argmax or the bar.**
``M`` revisions of ``π``'s source are feature 271's; putting ``π^0 = π_t`` back
into the candidate set so the selection can never fall below the current policy
is feature 273's; taking the argmax under §7's aggregated objective and
persisting the winner into ``policy_revision`` is feature 274's; and the
``√(2 ln M)`` bar the winner must clear on the holdout is feature 280's.  This
module *runs the tournament* — it produces the evidence those features read —
and it selects nothing, ranks nothing, averages nothing and keeps no incumbent.
It imports none of them and assumes none of them present; the three are
parallel siblings, and the only thing that crosses between them is rows in the
store.

**It is not the split, and it does not take one.**  Which worlds are train and
which are holdout is feature 278's judgment, rotated per cycle by feature 279;
this module reads that answer through the two predicates the split publishes
(:meth:`~dreaming.split.PoolSplit.is_holdout`, and its sibling) to mark each
row's ``is_holdout`` — the seam ``0109``'s column exists to carry, and the
reason :meth:`~dreaming.split.PoolSplit.is_holdout`'s own docstring names
feature 272's evaluator as its reader.  A split is **passed in**, never taken
here: taking one would be a second claimant to the cycle's reporting half, and
the rotation is a per-cycle fact this module has no cycle to derive.

**It is not the freeze, and it never writes around one.**  Feature 270 holds
the pool fixed for the whole of an outer iteration and its guards refuse every
insert, update and delete on the pool's two tables while a hold is open — and
``replay_score`` is one of those two tables.  So a sweep attempted under an
open hold is **refused**, and the refusal is where the loop's two clauses meet
rather than a limitation of this module: this module does not drop the guard,
does not write through a second connection, and does not re-open the hold to
slip a row underneath it.  The refusal arrives from the replay member's writer
wrapped in that member's own vocabulary (``ReplayScoreError``, chained to
SQLite's abort) and is **translated at this seam** into the dreaming member's
:class:`~dreaming.errors.PoolFrozenError`, naming the candidate and the world
that could not land — the one class a caller of *this* member can catch to
learn that the pool is held, which is the repair (*close the iteration*) rather
than a sweep fault.  Which iteration holds it is deliberately left to feature
270's own reading of the store: the trigger's literal is *an iteration*,
because a ``RAISE(ABORT, ...)`` cannot interpolate the holder, and the class's
message says so and points at
:meth:`dreaming.cycle.CycleFreeze.open_hold`, which answers the question
exactly — a translation that invented an id from a message that does not carry
one would be the sweep telling an operator who to blame.  The ordering
consequence is the caller's to arrange and is stated here rather than left to
be discovered: a cycle that means to write evidence must not hold the pool over
its own writes, so §C5's *hold* fixes the **input** — which worlds the
tournament is over — while the evidence the tournament produces is written when
the pool is free to take it.

Stdlib only, and import-cheap: :mod:`math`, :mod:`os`, :mod:`sqlite3` for the
one ``sqlite_master`` probe the store refusal makes (the writes themselves go
through the replay member), :mod:`importlib` for the one hyphen-free seat this
member resolves at call time, and the member's own modules.  No third-party
import at module scope, no new table, no new component, no migration, no seat
edit — feature 270's single ``"dreaming"`` component remains the member's whole
composition, and the sweep is reached the way the floor, the cap, the ceiling,
the split, the rotation, the bar, the comparison and the transfer are: as free
functions beside the store.
"""

from __future__ import annotations

import math
import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from .cycle import FREEZE_CODE, sqlite_path
from .errors import (
    FreezeRequestError,
    PoolFrozenError,
    SplitRequestError,
    SplitStoreError,
    SweepRequestError,
    SweepStoreError,
)
from .layout import (
    DATABASE_URL_ENV,
    POOL_TABLES,
    REPLAY_SCORE_TABLE,
    pool_tables_present,
)
from .split import pool_worlds

__all__ = [
    "SweepPair",
    "SweepReport",
    "plan_sweep",
    "sweep_candidates",
]

#: The code the sweep opens every *ask* refusal with — a greppable word naming
#: what was refused, the convention feature 270's ``pool_frozen`` states for
#: this member's refusals.  Feature 272's verb is *evaluates*: the sentence
#: mandates no outcome word (unlike feature 275's ``pool_too_thin`` or feature
#: 280's ``advantage_below_bar``), so this prefix is the module's own — it says
#: *the sweep's ask* rather than naming a tournament outcome, and a caller
#: grepping a deployment log for the sweep's malformed calls finds exactly the
#: ones that never ran.
SWEEP_CODE = "sweep_malformed"

#: The code the sweep's *store* refusals open with — the other half of the same
#: convention.  ``sweep_ungrounded`` names the fact the two store refusals
#: share: the sweep was planned or begun and the **store** could not ground it
#: — no pool here to sweep over, or a pair's evidence that measured but never
#: landed.  Spelled apart from :data:`SWEEP_CODE` because the two fail
#: differently and are repaired differently (*re-send the ask* against *point
#: at the pool, or repair the store*), which is the split every pair of classes
#: in this member's vocabulary makes.
SWEEP_STORE_CODE = "sweep_ungrounded"

#: The substring feature 270's trigger writes into SQLite's abort, and the one
#: word that identifies a refusal as *the pool is held* rather than as some
#: other store fault.  **Imported, not restated**: it is feature 270's own
#: constant (the module beside this one, which this member already imports
#: ``sqlite_path`` from), and the code is a *contract between two of this
#: module's functions* — the trigger writes it and :func:`_hold_refusal` reads
#: it inside a string a *sibling member* wrapped (the replay member's
#: ``ReplayScoreError`` chains SQLite's ``IntegrityError``, whose message
#: carries the trigger's literal).  A second spelling here would be a second
#: thing to keep in sync at exactly the seam where drifting apart means an
#: operator is told *the store is broken* about a pool a cycle is holding.
_FREEZE_MARK = FREEZE_CODE

#: What a candidate must answer to be swept, spelled once so the plan's
#: validation and the report's prose cannot disagree about it.
_CANDIDATE_FACTS = ("code_hash", "module_id")


def _candidate_of(value: Any) -> tuple[str, str, int | None]:
    """Read one candidate module's identity — ``(module_id, code_hash, revision_index)``.

    Duck-typed, deliberately.  Feature 271's :class:`~dreaming.reviser.
    CandidateModule` is the value this loop produces, and the three facts read
    here are the three the sweeps's evidence is filed under: ``module_id`` (the
    version string the ``replay_score`` row carries as ``policy_version`` — the
    spelling feature 274 later persists as ``policy_revision.policy_version``),
    ``code_hash`` (the candidate's identity, and the thing feature 274 writes
    to ``policy_revision.code_hash``) and ``revision_index`` (which of the ``M``
    revisions this candidate is, carried into the plan so a report can order
    the sweep the way the sweep was produced).

    It is read rather than ``isinstance``-checked for the reason every seam in
    this workspace is duck-typed: a member never imports another, so a type
    check would be a second spelling of what a candidate is, and 273's
    incumbent — put back into the candidate set by a *sibling* feature — may
    well arrive as a different class carrying the same facts.

    Refused as :class:`~dreaming.errors.SweepRequestError` before any world is
    read, naming the fact that was missing, because a candidate whose identity
    cannot be read names no revision and its evidence could not be filed.
    """
    missing = [name for name in _CANDIDATE_FACTS if not getattr(value, name, None)]
    if missing:
        raise SweepRequestError(
            f"{SWEEP_CODE}: a swept candidate is a candidate module carrying a "
            f"``module_id`` and a ``code_hash`` — got {value!r} "
            f"({type(value).__name__}), missing "
            f"{' and '.join(repr(name) for name in missing)}. The two are how "
            "one pair's evidence is filed: the row carries the module_id as "
            "its policy_version and feature 274 persists the code_hash beside "
            "it, so a candidate that cannot be named contributes scores nobody "
            "could attribute to a revision (feature 272)"
        )
    module_id = value.module_id
    code_hash = value.code_hash
    for name, read in (("module_id", module_id), ("code_hash", code_hash)):
        if not isinstance(read, str) or not read.strip():
            raise SweepRequestError(
                f"{SWEEP_CODE}: a candidate's {name} is non-empty text — got "
                f"{read!r} ({type(read).__name__}) on {value!r}; the field is "
                "how the sweep's evidence is attributed, and a value that is "
                "not text attributes none (feature 272)"
            )
    index = getattr(value, "revision_index", None)
    if index is not None and (
        isinstance(index, bool) or not isinstance(index, int) or index < 1
    ):
        raise SweepRequestError(
            f"{SWEEP_CODE}: a candidate's revision_index is a genuine "
            f"positive integer or absent — got {index!r} "
            f"({type(index).__name__}) on {value!r}; it is which of the ``M`` "
            "revisions this candidate is, and a value that is not an index "
            "misplaces the candidate in the sweep the report orders (feature "
            "272)"
        )
    return module_id, code_hash, index


def _candidates_of(value: Any) -> tuple[tuple[str, str, int | None], ...]:
    """Read the candidate set the sweep runs over — many candidates, or refuse.

    A bare candidate module is refused where a sequence of them belongs, and
    with it every other shape that is not a non-empty sequence: a ``str`` (a
    bare candidate's source would iterate its characters), a single
    ``CandidateModule``, ``None``, an empty sequence.  The candidate set is the
    *cross product's* first axis, and a sweep of no candidates is
    ``M × n = 0`` pairs — a tournament nobody entered, which would report as a
    clean sweep with nothing to select from.

    Feature 271's :func:`~dreaming.reviser.revise_policy` already refuses a
    production shortfall, so an empty set reaching here is a caller's own
    construction rather than a policy that could not fund ``M``; the refusal
    says so rather than repeating the production's verdict in this module's
    word.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise SweepRequestError(
            f"{SWEEP_CODE}: the sweep runs over the candidate set feature 271 "
            f"produced — a sequence of candidate modules — got {value!r} "
            f"({type(value).__name__}). A sweep is one score per "
            "(candidate, world) pair, and a value that is not a sequence of "
            "candidates names no cross product to take (feature 272)"
        )
    candidates = tuple(_candidate_of(candidate) for candidate in value)
    if not candidates:
        raise SweepRequestError(
            f"{SWEEP_CODE}: the sweep runs over a non-empty candidate set — "
            "got an empty one. ``M × n`` pairs over no candidates is a "
            "tournament nobody entered, and §C5's argmax over nothing would "
            "read as a clean sweep rather than as the missing production it is "
            "(feature 272)"
        )
    seen: dict[str, str] = {}
    for module_id, _, _ in candidates:
        if module_id in seen:
            raise SweepRequestError(
                f"{SWEEP_CODE}: a candidate set names each revision once — "
                f"{module_id!r} arrives twice. Two pairs filing evidence under "
                "one policy_version are two rows no reader can tell apart, and "
                "the average feature 274 takes over one candidate's worlds "
                "would be taken over two revisions' evidence (feature 272)"
            )
        seen[module_id] = module_id
    return candidates


def _worlds_of(value: Any) -> tuple[str, ...]:
    """Read the worlds a sweep covers — many non-empty world ids, or refuse.

    The cross product's second axis, validated the way
    :func:`dreaming.split._validated_world_ids` validates the split's input:
    a bare string is refused where a sequence of ids belongs (Python would
    iterate its characters as worlds), a blank or non-text member is refused
    because it names no world, and the same world twice is refused because one
    world is one column of the sweep — a world appearing twice would write two
    rows for one pair while the coverage claim said ``M × n``.
    """
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep's worlds are many world ids — got "
            f"{value!r} ({type(value).__name__}). A bare string is a single "
            "name, not a set of worlds, and iterating its characters would "
            "sweep candidates against worlds nobody has (feature 272)"
        )
    worlds = tuple(value)
    if not worlds:
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep covers a non-empty set of worlds — got an "
            "empty one. ``M × n`` pairs over no worlds is a tournament held "
            "nowhere, and §10.3.1's bar divided by ``√n_worlds`` would divide "
            "by zero (feature 272)"
        )
    for world_id in worlds:
        if not isinstance(world_id, str) or not world_id.strip():
            raise SweepRequestError(
                f"{SWEEP_CODE}: a world is named by a non-empty string — got "
                f"{world_id!r} ({type(world_id).__name__}). A pair's row names "
                "the world its score is about, and a value that names no world "
                "files evidence against nothing (feature 272)"
            )
    # Counted in one pass rather than by ``set`` arithmetic: a pool is 200
    # worlds at the documents' own scale but a caller's enumeration is theirs,
    # and the refusal wants the *names* that doubled rather than only the fact
    # that some did.  Order preserved so the message reads in the pool's order.
    counts: dict[str, int] = {}
    for world_id in worlds:
        counts[world_id] = counts.get(world_id, 0) + 1
    doubled = [world for world, times in counts.items() if times > 1]
    if doubled:
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep covers each world once — "
            f"{', '.join(repr(world) for world in doubled)} arrive(s) twice. "
            "The coverage law is one score per pair, and a world on both sides "
            "of the cross product writes two rows for one pair while the plan "
            "still claimed ``M × n`` (feature 272)"
        )
    return worlds


def _validated_beta(value: Any) -> float:
    """The beta the sweep scores at — a finite number, required.

    §7.4's single scalar, *"fixed within an episode"*, so it is one value for
    the whole sweep rather than one per pair: a sweep whose rows carried
    different betas would be a set of scores measured under different
    explore/exploit settings, and the argmax over them would compare two
    regimes while every figure looked like a score.  Required and with no
    default, following feature 238's ``width`` and :meth:`replay.ReplayEngine.
    persist_replay_score`'s own ``beta``: the caller holds it, this module does
    not decide it.

    Refused as :class:`~dreaming.errors.SweepRequestError` before the store is
    touched — a ``bool``, a non-number, or a non-finite figure (an infinity is
    not a hyperparameter, it is a value outside the space the scoring was made
    in).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep is scored at a beta — a finite number — "
            f"got {value!r} ({type(value).__name__}). The beta is §7.4's "
            "single scalar, fixed within an episode, and a value that is not a "
            "number names no scoring a reader could reproduce (feature 272)"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep is scored at a finite beta — got "
            f"{figure!r}. An infinity is not a hyperparameter: it is a value "
            "outside the space the scoring was made in, and every row in the "
            "sweep would claim to have been measured under a setting no reader "
            "could reproduce (feature 272)"
        )
    return figure


def _validated_split(value: Any) -> Any:
    """The split the evidence is marked with — a :class:`PoolSplit`, or ``None``.

    ``None`` is a real answer and not a missing argument: it is a sweep taken
    with **no split taken**, in which case every row is written with
    ``is_holdout`` ``False`` — the value ``0109``'s column defaults to *"for
    exactly the row that never asked"*, which is the honest reading of a sweep
    whose caller never asked.  A caller that holds a split must pass it, and
    the marking then comes from the split's own predicate rather than from a
    second derivation of the 70/30 rule here.

    A value that is neither is refused as
    :class:`~dreaming.errors.SweepRequestError` naming what arrived, before any
    world is read: a split-shaped object without the predicate the marking
    reads would let every row land ``False`` while the caller believed the
    holdout half was marked, which is the leak feature 278 exists to prevent
    arriving through the sweep's own signature.
    """
    if value is None:
        return None
    if not callable(getattr(value, "is_holdout", None)):
        raise SweepRequestError(
            f"{SWEEP_CODE}: a sweep's split is feature 278's PoolSplit — an "
            f"object answering ``is_holdout(world_id)`` — got {value!r} "
            f"({type(value).__name__}). The split is what marks each row's "
            "``is_holdout`` (``0109``'s column), and a split-shaped value the "
            "marking cannot ask would write every row ``False`` while the "
            "caller believed the holdout half was recorded. Pass the split the "
            "cycle took, or pass nothing for a sweep with no split taken "
            "(feature 272)"
        )
    return value


def _validated_evaluator(value: Any) -> Callable[..., Any]:
    """The collaborator that replays one candidate against one world — callable.

    The one thing this member cannot supply, validated before anything is read
    or written: the replay path lives in another member, so the evaluator
    arrives as a callable taking ``(candidate, world_id)`` and answering the
    terminal pick carrier feature 255's writer reads.  A non-callable is
    refused by name here rather than at the first pair, so a malformed seam
    fails before any row is planned — the stance
    :func:`replay.rounds.run_replay` takes for its own ``select``.
    """
    if not callable(value):
        raise SweepRequestError(
            f"{SWEEP_CODE}: the evaluator that replays a candidate against a "
            f"world is callable — got {value!r} ({type(value).__name__}). This "
            "member never runs a policy: the replay path is the replay "
            "member's (features 245-255), and it arrives here as one callable "
            "per pair. A seam that cannot be called is a wiring fault, and it "
            "is named before any pair is planned rather than at the first one "
            "(feature 272)"
        )
    return value


class SweepPair:
    """One ``(candidate, world)`` pair — a cell of the cross product, as a value.

    The two identities the pair's evidence is filed under and the half of the
    pool the world belongs to, and nothing derived:

    * **``module_id``** — the candidate's version string, written as the row's
      ``policy_version`` (feature 271's ``CandidateModule.module_id``, and the
      spelling feature 274 persists as ``policy_revision.policy_version``);
    * **``code_hash``** — the candidate's identity, the sha256 of its source;
    * **``world_id``** — the world the candidate was replayed against;
    * **``is_holdout``** — whether the world sits in the split's reporting half
      (§10.3.1's *"select on train, report on holdout"*), read from the split's
      own predicate and defaulted ``False`` for a sweep taken with no split;
    * **``revision_index``** — which of the ``M`` revisions the candidate is,
      or ``None`` when the candidate does not carry one.  Carried so a report
      can order the sweep the way feature 271 produced it; it is *not* part of
      the row, which is why it is a fact beside the four the store takes.

    Frozen with hand-written ``__slots__``, the member's
    :class:`~dreaming.cycle.FreezeRecord` stance, so a caller holding a plan
    cannot have it moved under it by the sweep it describes.  Two pairs are
    equal exactly when their five facts are, so a plan compared against a
    report's pairs answers the coverage claim directly.
    """

    __slots__ = ("code_hash", "is_holdout", "module_id", "revision_index", "world_id")

    def __init__(
        self,
        *,
        module_id: str,
        code_hash: str,
        world_id: str,
        is_holdout: bool = False,
        revision_index: int | None = None,
    ) -> None:
        self.module_id = module_id
        self.code_hash = code_hash
        self.world_id = world_id
        self.is_holdout = is_holdout
        self.revision_index = revision_index

    @property
    def policy_version(self) -> str:
        """The pair's policy version — the row's own name for the candidate.

        An alias rather than a second field: ``replay_score.policy_version`` is
        the column and ``module_id`` is the candidate's field, and this member
        states the two agree here, once, so a caller that has read feature 255's
        docstring and a caller that has read feature 271's reach the same
        string.
        """
        return self.module_id

    def row(self) -> dict[str, object]:
        """The pair as a mapping — a fresh dict per call.

        The shape a report, a log line or a later feature reads one cell
        through: the four facts the store's row carries, plus the revision
        index beside them.
        """
        return {
            "policy_version": self.module_id,
            "code_hash": self.code_hash,
            "world_id": self.world_id,
            "is_holdout": self.is_holdout,
            "revision_index": self.revision_index,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SweepPair):
            return NotImplemented
        return (
            self.module_id,
            self.code_hash,
            self.world_id,
            self.is_holdout,
            self.revision_index,
        ) == (
            other.module_id,
            other.code_hash,
            other.world_id,
            other.is_holdout,
            other.revision_index,
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.module_id,
                self.code_hash,
                self.world_id,
                self.is_holdout,
                self.revision_index,
            )
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SweepPair(module_id={self.module_id!r}, "
            f"world_id={self.world_id!r}, is_holdout={self.is_holdout!r})"
        )


def plan_sweep(
    candidates: Any,
    worlds: Any,
    *,
    split: Any = None,
) -> tuple[SweepPair, ...]:
    """Every candidate against every world — feature 272's judgment, pure.

    The whole of the coverage law as one pure function: the candidate set
    feature 271 produced, the pool's worlds, and (optionally) the split feature
    278 took in; one :class:`SweepPair` per ``(candidate, world)`` out, in the
    candidates' own order and, within each candidate, in the order the worlds
    were handed.  ``M`` candidates and ``n`` worlds answer exactly ``M × n``
    pairs — no pair skipped, none taken twice — and the plan is what makes that
    checkable *before* ``M × n`` replays are paid for: a caller compares the
    report's pairs against this tuple and either matches to the last element or
    finds the difference.

    Reads no database, opens no policy, runs nothing — the shape
    :func:`dreaming.split.split_pool` and :func:`dreaming.ceiling.
    rejects_uncapped_sweep` take, and the honest division between a verdict and
    an act: a caller that only wants to know *what the cycle will evaluate*,
    or a test pinning the cross product, asks this and pays for nothing.

    ``split`` is feature 278's :class:`~dreaming.split.PoolSplit` when the cycle
    took one, and ``None`` when it did not; each pair's ``is_holdout`` is read
    from the split's own predicate, so the marking comes from the one place the
    70/30 rule lives rather than from a second derivation here.  A world the
    split does not hold is **refused** rather than marked ``False``: a world
    outside the pool the split was taken over is neither half, and a plan that
    called it train would write a row the reporting never sees while the
    cycle believed the world was accounted for — the leak the split's own
    predicates refuse at their seam, translated here into the sweep's word
    because a caller sweeping worlds has asked the *sweep* about them.

    Refuses, in this order, each naming what it is about
    (:class:`~dreaming.errors.SweepRequestError` throughout, because every one
    is a fact about the **ask** and nothing has been read): candidates that are
    not a non-empty sequence of candidate modules, an identity on a candidate
    that is not text, two candidates under one ``policy_version``, worlds that
    are not a non-empty sequence of distinct non-empty ids, a split without the
    predicate the marking reads, and a world the split does not hold.
    """
    swept = _candidates_of(candidates)
    worlds = _worlds_of(worlds)
    held = _validated_split(split)
    plan: list[SweepPair] = []
    for module_id, code_hash, index in swept:
        for world_id in worlds:
            plan.append(
                SweepPair(
                    module_id=module_id,
                    code_hash=code_hash,
                    world_id=world_id,
                    is_holdout=False if held is None else _holdout_of(held, world_id),
                    revision_index=index,
                )
            )
    return tuple(plan)


def _holdout_of(split: Any, world_id: str) -> bool:
    """Whether the split puts ``world_id`` in the reporting half — its own word.

    The read is the split's :meth:`~dreaming.split.PoolSplit.is_holdout`, asked
    once per pair, and its refusal for a world the split does not hold is
    **translated at this seam** into this module's ask vocabulary: a caller
    that swept a world the pool's split never saw has asked the *sweep* about
    that world, and reading feature 278's ``SplitRequestError`` out of a sweep
    would tell it the split was malformed about an act that swept nothing.  The
    discipline the workspace states for error vocabularies, applied here the
    way :mod:`dreaming.rotation` applies it to the same predicate.
    """
    try:
        return bool(split.is_holdout(world_id))
    except SplitRequestError as refusal:
        raise SweepRequestError(
            f"{SWEEP_CODE}: the sweep covers each world once and the split it "
            f"is marked with must hold every one of them — {world_id!r} is not "
            f"in the split's pool; see the refusal it raised: {refusal}. A "
            "world outside the split is neither train nor holdout, and marking "
            "it either would file evidence about a world the rotated "
            "reporting half never accounted for (feature 272)"
        ) from refusal


class SweepReport:
    """One sweep, as it ran — the plan and the rows that landed.

    What :func:`sweep_candidates` answers: the pairs the sweep covered (the
    :func:`plan_sweep` it ran, in the same order), the ``replay_score`` row ids
    those pairs wrote, one per pair and in the plan's order, and the worlds the
    pool held when the sweep began.  The whole of it is *the evidence*, and
    nothing here is a verdict: no average, no argmax, no ranking and no
    winner — those are features 274 and 280, and a report that carried a
    favourite would be this module taking the selection it exists to serve.

    ``rows`` and ``pairs`` are equal in length by construction — one row per
    pair, and the sweep refuses rather than continuing when a row does not land
    — so ``len(report)`` is the cross product's size and the coverage claim is
    readable off the report itself.  Held as an immutable value for the reason
    :class:`~dreaming.cycle.FreezeRecord` gives: a report is what a selection
    is made of, and a caller holding one must not be holding a handle a later
    sweep can move under it.
    """

    __slots__ = ("pairs", "rows", "worlds")

    def __init__(
        self,
        *,
        pairs: Sequence[SweepPair],
        rows: Sequence[str],
        worlds: Sequence[str],
    ) -> None:
        self.pairs = tuple(pairs)
        self.rows = tuple(rows)
        self.worlds = tuple(worlds)

    @property
    def pair_count(self) -> int:
        """How many ``(candidate, world)`` pairs the sweep covered."""
        return len(self.pairs)

    @property
    def world_count(self) -> int:
        """How many worlds the sweep was taken over — the pool it crossed."""
        return len(self.worlds)

    @property
    def candidate_count(self) -> int:
        """How many distinct candidate revisions the sweep crossed the pool with.

        Counted from the plan rather than stored beside it, so the figure
        cannot disagree with the pairs it is a fact about: a report whose
        ``candidate_count`` was carried separately would be a second claimant
        to the cross product's first axis.
        """
        return len({pair.module_id for pair in self.pairs})

    def scores_for(self, module_id: Any) -> tuple[SweepPair, ...]:
        """Every pair one candidate ran — the column of the cross product.

        The read feature 274 takes before it aggregates: one candidate's
        evidence, in the pool's order, with each pair naming the world it is
        about.  Refused as :class:`~dreaming.errors.SweepRequestError` for a
        revision the sweep does not hold, because a caller that asked for a
        column the sweep never ran has asked about a candidate the tournament
        did not contain, and an empty answer would read as *this revision
        scored nothing* rather than as *no such revision ran*.
        """
        if not isinstance(module_id, str) or not module_id.strip():
            raise SweepRequestError(
                f"{SWEEP_CODE}: a swept revision is named by a non-empty "
                f"string — got {module_id!r} ({type(module_id).__name__}); a "
                "column of the cross product is asked for by the version the "
                "rows were filed under (feature 272)"
            )
        column = tuple(
            pair for pair in self.pairs if pair.module_id == module_id
        )
        if not column:
            ran = sorted({pair.module_id for pair in self.pairs})
            raise SweepRequestError(
                f"{SWEEP_CODE}: the sweep ran {self.candidate_count} "
                f"revision(s) and {module_id!r} is not one of them "
                f"({', '.join(repr(name) for name in ran)}) — an empty answer "
                "would read as a revision that scored nothing rather than as "
                "one the tournament never contained (feature 272)"
            )
        return column

    def row(self) -> dict[str, object]:
        """The report as a mapping — a fresh dict per call, with fresh lists.

        A summary shape for a log line or a later feature's own record: the
        counts, the worlds and the pairs.  The rows themselves are deliberately
        *not* listed — a report read back as a mapping is a summary, and the
        row ids are one per pair, so a caller that wants them has
        :attr:`rows` already and a caller reading a summary does not.
        """
        return {
            "candidate_count": self.candidate_count,
            "world_count": self.world_count,
            "pair_count": self.pair_count,
            "worlds": list(self.worlds),
            "pairs": [pair.row() for pair in self.pairs],
        }

    def __len__(self) -> int:
        """How many pairs the sweep covered — ``M × n``, made readable."""
        return len(self.pairs)

    def __iter__(self):
        """Yield the pairs the sweep covered, in the plan's order."""
        return iter(self.pairs)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SweepReport):
            return NotImplemented
        return (self.pairs, self.rows, self.worlds) == (
            other.pairs,
            other.rows,
            other.worlds,
        )

    def __hash__(self) -> int:
        return hash((self.pairs, self.rows, self.worlds))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"SweepReport({self.candidate_count} candidate(s) × "
            f"{self.world_count} world(s) = {self.pair_count} pair(s))"
        )


def sweep_candidates(
    candidates: Any,
    *,
    evaluator: Any,
    beta: Any,
    worlds: Any = None,
    split: Any = None,
    database_url: str | None = None,
    replay: Any = None,
    env: Mapping[str, str] | None = None,
) -> SweepReport:
    """Evaluate every candidate against every stored world — feature 272's call.

    The one act the feature's sentence names: read the pool's worlds, plan the
    ``M × n`` cross product, drive ``evaluator(candidate, world_id)`` once per
    pair, and persist each answer as one ``replay_score`` row through the
    replay member's own writer.  Returns the :class:`SweepReport` — the pairs,
    the row ids in the plan's order, and the worlds the pool held.

    ``worlds`` is the pool's world ids; ``None`` reads them from the store
    (:func:`dreaming.split.pool_worlds`), which is the feature's own sentence —
    *every **stored** world* — and the reason a sweep cannot be run over a
    caller's private list without saying so.  A caller that has the enumeration
    already (one read of the pool, shared with the cycle's split) hands it in
    and the store is not read twice.

    ``evaluator`` is the one collaborator this member cannot supply: a callable
    taking ``(candidate, world_id)`` — the candidate module feature 271
    produced and the world id — and answering the terminal pick carrier
    feature 255's writer reads (a carrier with a ``score``, and optionally a
    ``pick``).  This is the replay path, which lives in the ``replay`` member;
    a member never imports another, so it arrives as a callable — the seam
    :func:`replay.rounds.run_replay` takes for its ``select``, and the same
    seam feature 281's comparison takes for readings it did not compute.  A
    **miss** is a score and not a refusal: an evaluator answering the
    non-committing score persists it like any other, because the row is the
    record of a completed scoring (feature 249's ``−∞``, feature 255's own
    stance).

    ``replay`` is the composed replay component — the object
    ``application.get("replay")`` answers — reached without importing the
    member.  ``None`` reads it by name from the composed application
    (``create_app().get("replay")``) at call time, exactly as
    :func:`replay.transition.resolve_tree` resolves its campaign through the
    composed ``policy-runtime`` component and for the same reason: the
    member's module stays
    free of a hard dependency on a sibling, and a composed application carries
    the object the deployment actually built.  No composed replay path is a
    refusal rather than a silent success — a sweep whose evidence had nowhere
    to land would report as a sweep.

    Refuses, in this order, each naming what it is about.  Every one of the
    first five is a fact about the **request** and is refused before it can
    touch anything that is not the caller's own arguments — which is the
    ordering that matters here more than elsewhere, because a sweep's asks are
    ``M × n`` of them and one that is wrong is the same wrong however often it
    is re-sent:

    1. ``candidates`` that are not a non-empty sequence of candidate modules,
       and a candidate whose identity cannot be read
       (:class:`~dreaming.errors.SweepRequestError`);
    2. a ``beta`` that is not a finite number — a ``bool``, a string, an
       infinity, a NaN (:class:`~dreaming.errors.SweepRequestError`);
    3. a ``split`` that is neither ``None`` nor an object answering
       ``is_holdout`` (:class:`~dreaming.errors.SweepRequestError`);
    4. an ``evaluator`` that is not callable
       (:class:`~dreaming.errors.SweepRequestError`);
    5. ``worlds`` that were handed over and are not a non-empty sequence of
       distinct non-empty ids (:class:`~dreaming.errors.SweepRequestError`);
    6. a URL that names no database, or one this member cannot speak
       (:class:`~dreaming.errors.SweepRequestError`, translated at the seam
       from :func:`dreaming.cycle.sqlite_path`'s own refusal by name);
    7. no composed replay path to persist through
       (:class:`~dreaming.errors.SweepStoreError`), because the evidence has
       nowhere to land;
    8. a database that holds no pool tables — no pool to sweep over
       (:class:`~dreaming.errors.SweepStoreError`, translated at the seam from
       the split's own store refusal, and raised before the plan is built, so a
       refused sweep leaves not even a plan behind);
    9. a world the split does not hold, or two candidates under one version
       (:class:`~dreaming.errors.SweepRequestError`, by :func:`plan_sweep`);
    10. **while the sweep runs**, a pair whose row did not land
        (:class:`~dreaming.errors.SweepStoreError`), and a pair refused because
        an iteration holds the pool fixed
        (:class:`~dreaming.errors.PoolFrozenError`, translated at this seam
        from the replay member's own wrapper — see :func:`_hold_refusal`).

    Refusal 10 is where §C5's first clause and this feature's sentence meet, and
    the translation rather than the swallowing is the point: feature 270's
    guards refuse every write to the pool's two tables while a cycle holds it,
    so a sweep attempted under an open hold is refused **in feature 270's word**
    — the repair is *close the iteration*, which is the holder's decision and
    not a sweep this module could re-run differently.  Nothing here weakens
    that rule: the sweep does not drop a guard, open a second connection, or
    re-hold the pool to slip a row underneath it, and a row that was refused
    leaves the pool exactly as it was found.

    **A fault inside ``evaluator`` is deliberately none of the ten.**  The
    evaluator is another member's code — the replay path — so a ``raise`` from
    inside it is that member's error and **propagates untouched**: this module
    does not catch it, does not translate it into :class:`SweepStoreError`
    (nothing was stored), and does not absorb it into a shorter
    :class:`SweepReport`, because a report answered at that point would be a
    coverage claim for a tournament that did not finish.  The rows that landed
    before the fault stay: the sweep does not roll back a writer it does not
    own, and the caller's own refusal is what says the run is incomplete.  The
    distinction is the one refusal 10 turns on — *the store would not take a
    score we measured* is a sweep fact, *the scorer fell over* is not.
    """
    _candidates_of(candidates)
    figure = _validated_beta(beta)
    held = _validated_split(split)
    evaluate = _validated_evaluator(evaluator)
    if worlds is not None:
        listed = _worlds_of(worlds)
    else:
        listed = None
    # One URL for the read *and* the write: the worlds the plan crosses and the
    # store the evidence lands in are the same pool by construction, so *every
    # stored world* is a claim about one deployment rather than two.
    url = _sweep_url(database_url, env)
    connection = _replay_of(replay)
    if listed is None:
        listed = _stored_worlds(sqlite_path(url))
    plan = plan_sweep(candidates, listed, split=held)
    values = tuple(candidates)
    # One value per pair, in the plan's own order: the plan crosses candidates
    # outer and worlds inner, so repeating each candidate once per world gives
    # the sequence the loop below indexes, and the two orders agree by
    # construction rather than by a second sort.
    run: list[str] = []
    for index, pair in enumerate(plan):
        answer = evaluate(values[index // len(listed)], pair.world_id)
        run.append(_persist(connection, answer, pair, figure, url))
    return SweepReport(pairs=plan, rows=run, worlds=listed)


def _persist(
    replay: Any,
    answer: Any,
    pair: SweepPair,
    beta: float,
    database_url: str,
) -> str:
    """Write one pair's row through the replay member's writer, or translate.

    The seam itself: the answer and the pair's four facts go to
    :meth:`replay.ReplayEngine.persist_replay_score` — the composed spelling of
    feature 255's writer — and the row id comes back.  Both failures a store
    can raise on the way are read apart rather than merged, because they mean
    different things and are repaired differently:

    * **the pool is held** — feature 270's trigger aborts the insert, and the
      replay member wraps SQLite's ``IntegrityError`` in its own
      ``ReplayScoreError``, whose message and whose ``__cause__`` both carry
      the trigger's literal.  Recognised by that mark
      (:data:`_FREEZE_MARK`) and raised as
      :class:`~dreaming.errors.PoolFrozenError`, naming the world and the
      candidate, because the fact a caller of *this* member must be able to
      catch is *the pool is fixed and my evidence cannot land*, and its repair
      is feature 270's — close the iteration — not the sweep's.  A caller that
      swept and caught the replay member's class would be reading another
      member's word for an act this one performed.
    * **anything else** — the row measured but did not land, which is a fact
      about the **store**: raised as
      :class:`~dreaming.errors.SweepStoreError`, with the store's own refusal
      chained so the operator still sees the database's words.  It is a
      refusal rather than a skipped pair on purpose: §C5's coverage law is one
      score per pair, and a sweep that continued past a lost row would answer a
      report whose pairs outnumber its rows while nothing in the result looked
      wrong.

    The two classes are told apart by reading the *cause*, and by reading it
    through the replay member's own wrapper rather than by catching SQLite
    here: this module never opens the pool's database for writing, so the only
    evidence it has of the trigger is the message the writer carried out — the
    same one-word probe feature 270's own ``guard`` performs on the abort it
    translates, applied one member up.
    """
    try:
        return replay.persist_replay_score(
            answer,
            pair.module_id,
            pair.world_id,
            beta,
            is_holdout=pair.is_holdout,
            database_url=database_url,
        )
    except Exception as refusal:
        held = _hold_refusal(refusal, pair)
        if held is not None:
            raise held from refusal
        raise SweepStoreError(
            f"{SWEEP_STORE_CODE}: the evidence for policy "
            f"{pair.module_id!r} against world {pair.world_id!r} measured but "
            f"never landed — the replay member's writer refused the row: "
            f"{refusal}. §C5's coverage law is one score per pair and the "
            "sweep is refused rather than continued, because a report whose "
            "pairs outnumber its rows is a tournament one candidate partly sat "
            "out while every figure in the result still looked like a score. "
            "The repair is the store's (the original refusal is chained), "
            "never a re-run over evidence that already measured (feature 272)"
        ) from refusal


def _hold_refusal(refusal: BaseException, pair: SweepPair) -> PoolFrozenError | None:
    """Whether a store refusal is feature 270's hold, spelled in this member's word.

    ``None`` when the refusal is anything else — the caller then reports it as
    the store fault it is.  A :class:`~dreaming.errors.PoolFrozenError` when
    the replay member's wrapper (or SQLite beneath it) carries the trigger's
    literal, naming the candidate and the world that could not land and
    directing the caller to feature 270's own reading of *which* iteration
    holds the pool — a ``RAISE(ABORT, ...)`` literal cannot interpolate the
    holder, so an id invented from the message would be this module guessing.

    **Why the cause is read rather than caught.**  The refusal arrives from
    another member, wrapped in that member's own class
    (``replay.ReplayScoreError``), which this module may not import and could
    not catch by name even if it wanted to — the workspace's rule that no
    member imports another, stated by
    :func:`discovery.persist._published_bytes` for its own broad guard.  So the
    probe is the *text* feature 270 writes into its trigger, which is the same
    discriminator :meth:`dreaming.cycle.CycleFreeze.guard` uses on the abort it
    translates: one code, spelled once in the database and read at every seam
    that has to tell *the pool is held* from *the store is broken*.

    The chain is walked rather than only the outermost message, because a
    writer is free to wrap (and this one does: ``raise ReplayScoreError(...)
    from exc``) — the cause is where the literal lives.  ``__cause__`` only:
    the walk does **not** follow ``__context__``, because a writer's
    ``__context__`` may point at an unrelated failure being handled in the same
    ``except`` block, and reading *that* as the hold would report a cycle that
    is not holding anything.  A chain that loops (a refusal chained to itself,
    which ``raise x from x`` can produce) is walked once per object rather than
    forever.  A refusal whose text merely *mentions* ``pool_frozen`` — a
    message about a pool that is held, raised by something else — is still
    reported as the hold, which is the safe direction: the alternative would
    report *the store is broken* about a pool that a cycle is holding, and an
    operator would go looking for a fault that does not exist.
    """
    held: BaseException | None = refusal
    seen: set[int] = set()
    while held is not None and id(held) not in seen:
        seen.add(id(held))
        if _FREEZE_MARK in str(held):
            return PoolFrozenError(
                f"{_FREEZE_MARK}: the sweep of policy {pair.module_id!r} "
                f"against world {pair.world_id!r} could not persist its score "
                "— an iteration holds the replay pool fixed for the cycle, and "
                "feature 270's guards refuse every write to "
                f"{REPLAY_SCORE_TABLE} while it does (feature 270's own word "
                "for the holder is *an iteration*, which is the whole of what "
                f"a trigger can say), chained to: {refusal}. This is §C5's "
                "first clause meeting its middle one: the hold fixes the "
                "history the tournament is over, and the evidence the "
                "tournament produces has to reach the store while the pool is "
                "free to take it — the loop's ordering to arrange, not a rule "
                "this member bends. Close the iteration (the dreaming member's "
                "CycleFreeze.release — and CycleFreeze.open_hold names the "
                "iteration holding it) and write the sweep's evidence between "
                "cycles (feature 272)"
            )
        held = held.__cause__
    return None


def _replay_of(value: Any) -> Any:
    """The composed replay component — the value handed in, or the app's.

    Read by name from the composed application (``create_app().get("replay")``)
    when none is handed over, the same call-time resolution
    :func:`replay.transition.resolve_tree` performs for the ``policy-runtime``
    component: a member reaches a sibling through ``app.*`` and never through
    its import name, and the resolution happens inside the function so this
    module stays import-cheap and free of a hard dependency at composition
    time.

    ``None`` from the app is a refusal, not a silent success: a deployment
    with no composed replay path has nowhere for evidence to land, and a sweep
    that reported a clean run over rows nobody wrote is the failure mode
    :func:`discovery.campaign`'s own builder warns about for its store — the
    degrade-don't-break stance belongs at *composition*, where an absent
    component is a discovery, and never at an act that must write.
    """
    if value is not None:
        writer = getattr(value, "persist_replay_score", None)
        if not callable(writer):
            raise SweepStoreError(
                f"{SWEEP_STORE_CODE}: a sweep persists through the replay "
                "member's own writer — an object answering "
                "``persist_replay_score(pick, policy_version, world_id, beta, "
                f"*, is_holdout=…, database_url=…)`` — got {value!r} "
                f"({type(value).__name__}). The row is feature 255's and "
                "``0109``'s, and this member writes none of it itself; a "
                "carrier without the writer names no store the evidence could "
                "reach (feature 272)"
            )
        return value
    from app.module_loader import create_app

    # "replay" is the replay member's own component name (replay.COMPONENT_NAME).
    component = create_app().get("replay")
    if component is None:
        raise SweepStoreError(
            f"{SWEEP_STORE_CODE}: no replay component is composed, so a "
            "sweep's evidence has nowhere to land — the sweep persists one "
            "``replay_score`` row per pair through the replay member's own "
            "writer, and a deployment that composed none would report a clean "
            "sweep over rows nobody wrote (feature 272)"
        )
    return component


def _sweep_url(database_url: Any, env: Mapping[str, str] | None) -> str:
    """Resolve the store a sweep is taken over: the URL, then ``DATABASE_URL``.

    The same resolution order :func:`dreaming.split._split_path` and
    :func:`dreaming.paired._pool_path` take, and the same refusal stance: an
    act that means to read the pool and resolves nothing is refused by name
    rather than answered with ``None``, because a sweep over no database would
    cross the candidates with worlds that do not exist.  A URL this member
    cannot speak is refused in the sweep's vocabulary, translated at the seam
    from the one spelling of what a ``sqlite:///`` URL names — so a caller
    sweeping never meets feature 270's
    :class:`~dreaming.errors.FreezeRequestError` for an act that held nothing.

    **Returns the URL, not the path**, and the caller derives the path and
    hands the URL to the writer: one resolution feeding both the read and the
    write is what makes *the worlds were read from the pool the evidence
    landed in* a fact rather than a hope.  A sweep that resolved the pool
    through ``env`` and the row's store through ``os.environ`` would file
    evidence against one tournament's worlds while the cycle read another's —
    the failure mode this module's own refusal message names.
    """
    url = (
        database_url
        if database_url is not None
        else (os.environ if env is None else env).get(DATABASE_URL_ENV, "")
    )
    if not isinstance(url, str) or not url.strip():
        raise SweepRequestError(
            f"{SWEEP_CODE}: sweeping the replay pool needs the database it "
            f"lives in — pass it explicitly or set {DATABASE_URL_ENV}. A "
            "sweep taken over no database would cross the candidates with "
            "worlds that do not exist, and §C5's *every stored world* is a "
            "claim about a store (feature 272)"
        )
    try:
        sqlite_path(url)
    except FreezeRequestError as refusal:
        raise SweepRequestError(
            f"{SWEEP_CODE}: the worlds a sweep covers are read from the "
            f"database the replay pool lives in, and the URL given does not "
            f"name one this member can speak — see the refusal it raised: "
            f"{refusal}. The sweep reads the pool's own tables rather than "
            "growing a second store a deployment could point at a different "
            "file, because evidence filed against one pool and read from "
            "another would be two tournaments wearing one name (feature 272)"
        ) from refusal
    return url


def _stored_worlds(path: Path) -> tuple[str, ...]:
    """The pool's worlds as the store holds them — the sweep's second axis.

    :func:`dreaming.split.pool_worlds`'s read, with its refusal **translated at
    this seam**: a database holding no pool tables is refused by the split in
    the split's word (``SplitStoreError``), and a caller sweeping would read
    *your split was malformed* about an act that split nothing.  The refusal is
    this module's store face
    (:class:`~dreaming.errors.SweepStoreError`) and it is raised **before any
    pair is planned or any row written**, so a refused sweep leaves not even a
    plan behind.

    ``REPLAY_SCORE_TABLE`` is named in the message because it is the table the
    evidence lands in: a database without the pool has nowhere for a sweep's
    rows either, and saying which table was missing is what tells an operator
    whether to migrate or whether they pointed at the wrong file.  The absent
    tables are read with :func:`dreaming.layout.pool_tables_present` rather
    than inferred from the refusal, so the message names what is *actually*
    missing instead of assuming the whole pool is.
    """
    try:
        return tuple(pool_worlds(path))
    except SplitStoreError as refusal:
        raise SweepStoreError(
            f"{SWEEP_STORE_CODE}: the database at {path} holds no "
            f"{' and no '.join(_absent_pool_tables(path))} table, so there is "
            "no pool here to sweep over — §C5 evaluates every candidate "
            "against every *stored* world, and "
            f"{REPLAY_SCORE_TABLE} is where each pair's one score lands, so a "
            "sweep over a database without the pool would cross the candidates "
            "with worlds that do not exist and write rows nowhere. Point "
            f"{DATABASE_URL_ENV} at the database the replay pool lives in, or "
            f"migrate it; the store's own refusal follows: {refusal}"
        ) from refusal


def _absent_pool_tables(path: Path) -> list[str]:
    """Which of the pool's two tables the database at ``path`` is missing.

    The ``sqlite_master`` probe :func:`dreaming.layout.pool_tables_present`
    performs, spelled here so the sweep's store refusal can name the absent
    tables rather than assuming both.  A database that cannot be opened
    propagates the driver's own error untouched — the refusal this feeds is
    already being raised, and a fault in *asking* about the pool must not
    replace the fact that there is no pool to sweep over.
    """
    try:
        with closing(sqlite3.connect(path)) as connection:
            present = pool_tables_present(connection)
    except sqlite3.Error:  # pragma: no cover - the refusal already names the store
        return list(POOL_TABLES)
    return [table for table in POOL_TABLES if table not in present]
