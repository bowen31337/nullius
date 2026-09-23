"""The dreaming ladder's floor — feature 275, and this member's second sentence.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 275: *System rejects a
dreaming run when the pool holds fewer than 20 worlds, which returns a
``pool_too_thin`` error message.*  docs/alpha-engine-prd.md §12.1 states the
rule this module enforces, and states it as a precondition *on a run that has
not started* rather than as a caveat on one that is going:

    Below 20 worlds: **do not run dreaming.** Fixed exploration; accumulate
    history.

The ladder has three rungs, and only the top one dreams.  §12.1's table reads
``< 20 worlds`` as *do not run dreaming at all*; ``20–50`` as a capped,
low-bar sweep (feature 276 caps the revision count, feature 277 raises it once
the pool clears 50); and ``50+`` as full dreaming with the 70/30 split.  This
module is the floor of that ladder — the refusal that keeps a cycle from
starting over a pool too small to dream on — and it is the rung feature 276 and
feature 277 build on.

**Why the floor is a refusal rather than a recommendation.**  A dreaming cycle
over a handful of worlds has no statistical power: §10.3.1's selection bar is a
*paired* continuous statistic over holdout worlds, and a pair that small cannot
clear it with any confidence, while selecting the max over ``M`` revisions
scored on them is the multiple-testing problem one level up with nothing to
average it out — the same overfitting §12.1 names in its *"the dreaming loop
overfits its own replay pool"* and the reason feature 270 holds the pool fixed
in the first place.  A pool below the floor does not make the bar *hard to
clear*; it makes the bar *meaningless*, so the run is refused rather than
advised.  The refusal is the M3 gate's younger sibling: where the gate
(feature 187, §10.3.1's ``n > 53``) judges whether a *financial* claim has
enough worlds to dream *honestly*, this floor judges whether there are enough
worlds to dream *at all*.

**What this module is, and what it is not.**  It is a *judgment over a count the
caller already has*, and nothing more — the shape :func:`bootstrap.
rejects_dreaming_claim` takes for feature 187's own verdict, and for the same
reason: a verdict is not a count, and a count is not the verdict.  The count the
judgment reads is the pool's size, which this member already computes —
:func:`dreaming.cycle.pool_commitment` returns ``(digest, world_count)``, and a
feature-270 hold records ``world_count`` at the moment it opened — so a caller
obtains the figure from the same member it asks to judge, and this module never
opens a database or reads the pool itself.  A module that counted the pool would
be answering a question about a store from inside a verdict, and would couple a
judgment to a connection it does not need.  The judgment is spoken as a
refusal: :func:`rejects_thin_pool` raises when the pool is thin and returns
otherwise, so a caller that calls it on its last line is stopped before it
begins, the way a caller of :func:`bootstrap.rejects_dreaming_claim` would
guard its own proceeding.

**The floor is a parameter, and it is not hard-wired to §12.1's 20.**  The
precondition a dreaming run must meet is the ladder floor's own world count,
which §12.1 states as 20 but which a deployment may set differently.  The floor
is therefore a keyword of the refusal, defaulting to the §12.1 figure the
feature was written against, validated to be a non-negative whole number so a
floor that is not a world count cannot silently admit or block a run.  A run is
refused when the figure is below the floor; it is admitted when it meets the
floor — there is no upper edge, because the floor is a power precondition and
more worlds only strengthen the comparison.

**Why this is a second sentence and not a third face of feature 270.**  Feature
270's subject is a cycle that is *already running* and must not have its pool
moved underneath it; its code is ``pool_frozen`` and its repair is *stop
writing, or close the iteration*.  This module's subject is a run that *has not
begun*; its code is ``pool_too_thin`` and its repair is *grow the pool, or run
fixed exploration*.  The two sentences have different repairs, so the workspace's
error-vocabulary discipline — a shared helper that raises another feature's
error type defeats the caller's ``except`` — forbids this module from borrowing
feature 270's :class:`~dreaming.errors.PoolFrozenError`, and the two live as
siblings under the one :class:`~dreaming.errors.DreamingError` base.  This
module carries the floor's code and raises the floor's class; it deliberately
carries none of feature 270's words.

Stdlib only, and import-cheap: no ``sqlite3``, no third-party import at module
scope, so the factory's scan — which imports this package to fire its
``@register`` — pays nothing for the floor.
"""

from __future__ import annotations

from typing import Any

from .errors import PoolTooThinError

__all__ = [
    "LADDER_FLOOR_WORLDS",
    "POOL_TOO_THIN_CODE",
    "rejects_thin_pool",
    "validated_floor",
]

#: The code a *thin-pool* refusal opens with — the pool fell short of the ladder
#: floor — so the rejection is greppable by the word that names it.  Deliberately
#: feature 275's word and not feature 270's ``pool_frozen``: this module's
#: subject is a run that has not started and should not start, and the ladder's
#: floor is a precondition on that run, not a cycle that is running and must not
#: have its pool moved.
POOL_TOO_THIN_CODE = "pool_too_thin"

#: The world count the ladder floor's paired comparison needs — §12.1's
#: *"below 20 worlds: do not run dreaming"*, the floor a dreaming run must meet.
#: The default the refusal judges against; a deployment that sets its own floor
#: passes it as the ``gate`` keyword of :func:`rejects_thin_pool`.
LADDER_FLOOR_WORLDS = 20


def validated_floor(value: Any) -> int:
    """Check that ``value`` is a world count, or refuse it.

    The one spelling of what the floor must be, shared by
    :func:`rejects_thin_pool`.  A floor is the ladder precondition's world
    count — §12.1's 20 — so it is a non-negative whole number, and a value that
    is not one would silently admit or block a dreaming run on a number that is
    not a world count.  A ``bool`` is refused where a count belongs: ``True`` is
    ``1`` in Python, so a flag where a floor belongs would name a pool of one
    world as the floor, which no ladder has.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PoolTooThinError(
            f"{POOL_TOO_THIN_CODE}: the ladder floor is a world count — got "
            f"{value!r} ({type(value).__name__}); §12.1's precondition is a "
            "number of worlds the pool must hold before dreaming may begin, "
            "and a value that is not a whole number names no floor a run can "
            "be measured against"
        )
    if value < 0:
        raise PoolTooThinError(
            f"{POOL_TOO_THIN_CODE}: the ladder floor is a non-negative world "
            f"count — got {value!r}; the paired comparison needs zero worlds "
            "or more, and a negative floor would admit every dreaming run, "
            "which is the floor §12.1 exists to keep shut"
        )
    return value


def _validated_figure(value: Any) -> int:
    """Check that ``value`` is a pool size, or refuse it.

    The figure the judgment reads is the pool's size — the same count a
    feature-270 hold records as ``world_count`` — so it is a non-negative whole
    number, and a value that is not one names no pool this judgment can measure.
    A ``bool`` is refused where a count belongs for the reason the floor is:
    ``True`` is ``1`` in Python, so a flag where a figure belongs would name a
    pool of one world, which is below any floor and would be refused for the
    wrong reason.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise PoolTooThinError(
            f"{POOL_TOO_THIN_CODE}: a pool's size is a world count — got "
            f"{value!r} ({type(value).__name__}); the floor judges the number "
            "of worlds the pool holds, and a value that is not a whole number "
            "names no pool a run can be measured against"
        )
    if value < 0:
        raise PoolTooThinError(
            f"{POOL_TOO_THIN_CODE}: a pool's size is a non-negative world "
            f"count — got {value!r}; a pool holds zero worlds or more, and a "
            "negative figure names no pool this judgment can measure"
        )
    return value


def rejects_thin_pool(world_count: Any, *, gate: int = LADDER_FLOOR_WORLDS) -> None:
    """Refuse a dreaming run whose pool is too thin to dream on — feature 275's call.

    The one judgment for feature 275's sentence: a pool size and a floor in,
    and either the run proceeds or it is refused.  It decides whether the pool
    clears the ladder floor — *"below 20 worlds: do not run dreaming"* — and
    **raises** :class:`~dreaming.errors.PoolTooThinError` when it does not, so
    the caller that calls it on its last line is stopped before it begins a run
    over a pool too small to dream on.  A pool that meets the floor returns
    without raising — ``20`` worlds with the default floor of ``20`` is
    admitted, because the floor is a power precondition and meeting it is
    enough; there is no upper edge.

    The figure is the pool's size — the count this member already computes
    (:func:`dreaming.cycle.pool_commitment` returns it, and a feature-270 hold
    records it as ``world_count``) — passed in rather than read, so this module
    never opens a database or counts the pool itself: a verdict is not a count,
    and the count is the caller's to supply.  ``gate`` is the ladder floor's
    world count, §12.1's 20 by default.

    Refuses, in this order, each naming what it is about:

    1. a ``world_count`` that is not a non-negative whole number — a pool's size
       is a world count, and a value that is not one names no pool a run can be
       measured against;
    2. a ``gate`` that is not a non-negative whole number — the floor is a world
       count, and a floor that is not one cannot measure a pool;
    3. a figure below the floor — the pool holds fewer worlds than the ladder
       floor, so the run is refused with a message that opens with
       ``pool_too_thin``, states the figure and the floor, names §12.1, and
       states the repair (grow the pool, or run fixed exploration).

    A malformed figure or floor is refused rather than answered, so a run whose
    inputs are wrong is never silently admitted or blocked on a number that is
    not a world count — the caller corrects the inputs and calls again.
    """
    figure = _validated_figure(world_count)
    floor = validated_floor(gate)
    if figure < floor:
        raise PoolTooThinError(
            f"{POOL_TOO_THIN_CODE}: the pool holds {figure} world(s), below the "
            f"ladder floor of {floor}; docs/alpha-engine-prd.md §12.1 refuses "
            f"a dreaming run below {floor} worlds — the paired comparison has "
            "no power and selecting the max over M revisions overfits the pool. "
            "Do not run dreaming: grow the pool, or run fixed exploration and "
            "accumulate history until the pool clears the floor"
        )
