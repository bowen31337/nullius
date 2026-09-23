"""The middle rung's ceiling — feature 276, and the ladder's second rung.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 276: *System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds, so the
selection bar stays low.*  docs/alpha-engine-prd.md §12.1 states the rule as
the middle row of the ladder this member spells rung by rung:

    | Pool size | Operating regime |
    |-----------|---|
    | < 20 worlds | **Do not run dreaming.** Fixed exploration; accumulate history |
    | 20–50 | Dreaming with ``M`` capped at 8–10 so the selection bar stays low. Cap policy complexity |
    | 50+ | Full dreaming, ``M = 30–40``, 70/30 train/holdout split on worlds |

Features 275 and 277 are the other two rows: the floor refuses a run below 20
worlds, and the schedule raises ``M`` to 40 once the pool holds 50 or more.
This module is the row *between* them, and it is the only one of the three that
is a **ceiling** — a refusal of a count the caller asked for, rather than a
figure the system answers with.  The band is not merely *admissible*; it is
admissible **at a bounded ``M``**, and a cycle that runs a wider sweep on it is
stopped before it runs rather than warned after it has selected.

**Why the ceiling exists — the selection bar, which is the reason feature 276's
own sentence carries.**  §12.1's warning is that the dreaming loop *"overfits
its own replay pool"*: the paper's guarantee ``V^{m★} ≥ V^0`` holds on the
*fixed history*, and selecting the max over ``M`` revisions scored on a handful
of worlds is the same multiple-testing problem one level up.  Appendix B's
meta-level bar is exactly the width of that problem —

    true_advantage  >  √(2 ln M) · σ_V / √n_worlds

— and ``M`` enters it, so a sweep wider than the band's cap widens the bar the
*selected* revision will later be judged against.  The two figures §12.1
computes are the whole argument: at ``M = 40`` with ``σ_V ≈ 0.8`` and a target
advantage of 0.3 it needs **n > 53 worlds**, and a pool of 20–50 is by
construction short of that.  Nor is the dependence on ``M`` the small term — a
bar at ``M = 40`` is ``√(ln 40 / ln 10) ≈ 1.27`` times the bar at ``M = 10``
— so running the raised cap on the thin rung would judge the winner against a
bar ~27% wider than the rung can afford, and the ``n > 53`` it needs is exactly
what the *next* rung waits for.  §12.1's "cap policy complexity" is the same
sentence from the other side: the band trades sweep width for a bar low enough
to clear, and the trade is not the caller's to decline.

**The 10 is feature 277's, and this module consumes it rather than respelling
it.**  Feature 277's schedule *answers* the band's cap — :data:`dreaming.cap.
CAPPED_SWEEP_CAP`, §12.1's *"capped at 8–10"* at the count this feature's
sentence fixes — and feature 277's own module says why the refusal that
enforces it is not its business: *"this module only answers what a cycle on
that rung runs under"*.  So the number a cycle is *entitled to* and the number
it is *refused above* are one constant, imported from the one module that
states it, and the two features cannot drift apart: :func:`rejects_uncapped_
sweep` with its default ceiling admits exactly what :func:`dreaming.cap.
revision_cap` answers, for every pool size, by construction rather than by
agreement.  The band's edges come from the same place — ``floor`` is feature
275's :data:`~dreaming.ladder.LADDER_FLOOR_WORLDS` and ``full_dreaming`` is
feature 277's :data:`~dreaming.cap.FULL_DREAMING_WORLDS` — so this module
*spells no ladder figure of its own at all*.  A ladder is one thing spelled
once, and a third spelling of the 10 here would be a second thing to keep in
sync at the one place a disagreement costs a cycle its statistical honesty.

**What this module is: a verdict over counts the caller already has.**  The
shape is feature 275's :func:`~dreaming.ladder.rejects_thin_pool` exactly, and
for the same reason it gives — a verdict is not a count, and the count is the
caller's to supply.  :func:`rejects_uncapped_sweep` takes the revision count
the caller is about to run and the pool's size, and **raises** when the count
exceeds the band's ceiling while the pool sits in the band, so a caller that
calls it on its last line is stopped before it begins a sweep §12.1 does not
fund.  Both figures are already in the caller's hand at that point: §C5's loop
holds the pool's size from the hold it opened (a feature-270 :class:`~dreaming.
cycle.FreezeRecord` records ``world_count``) and the revision count is its own
intent.  A module that counted the pool would be answering a question about a
store from inside a verdict; this one opens no database, reads no row, takes no
path and imports nothing that could — it is a pure function of integers, and
:mod:`dreaming.cap`'s schedule is the same kind of thing one rung up.

**Above the band there is no ceiling, and below it there is no answer to
give.**  Both edges are load-bearing and neither is a formality:

* ``world_count >= full_dreaming`` — the pool has cleared 50, §12.1's raise
  has fired, and ``M`` is feature 277's to answer at 40.  This module returns
  without raising *whatever* the count is: the ceiling is the middle rung's
  rule and it does not follow the cycle up the ladder.  Refusing 40 there
  would leave the top rung refusing the very figure §12.1's bar calculation is
  written at.
* ``world_count < floor`` — the pool may not dream at all, so a cap on its
  sweep is not the caller's problem.  The refusal is feature 275's, delegated
  to :func:`~dreaming.ladder.rejects_thin_pool` in the floor's own word
  (``pool_too_thin``) by the floor's own one spelling of the rule, which is
  what ``depends_on="275"`` means in code and the same delegation feature 277's
  schedule performs.

**The vocabulary is this feature's own, and the member's one spellings are
reused behind it.**  One new sibling under
:class:`~dreaming.errors.DreamingError`: :class:`~dreaming.errors.
RevisionCeilingError`, for the refusal this sentence mints.  It is a new class
rather than a borrowed one because its **repair** is its own — *lower ``M`` to
the band's ceiling, or grow the pool until the raise applies* — and the two
classes a caller could otherwise catch it as name repairs that are wrong here:
:class:`~dreaming.errors.PoolTooThinError` means *grow the pool before dreaming
at all* (this pool may dream, just not that widely), and feature 277's
:class:`~dreaming.errors.CapRequestError` means *your ask was malformed* (a
count of 40 is perfectly well formed and legal one rung up).  The floor's own
keyword ``gate`` is passed straight through to the ladder's judgment, so the
two spellings of the bottom rung cannot disagree, and the ladder's
:func:`~dreaming.ladder.validated_floor` refuses a malformed floor in the
ladder's vocabulary because the floor is feature 275's fact.  What this module
does *not* borrow is any of the member's other four classes: a caller that
catches a ceiling refusal catches nothing else, and a caller that catches
anything else catches no ceiling refusal.

**No code word, and deliberately.**  Feature 275's ``pool_too_thin`` is
mandated by its own sentence (*"which returns a ``pool_too_thin`` error
message"*), and this feature's sentence mandates none: *"System rejects a
revision count above 10 while the pool holds between 20 and 50 worlds"* names
its subject in prose.  So the refusal opens with its subject — the count, the
ceiling and the band — which is the shape feature 277's :class:`~dreaming.
errors.CapRequestError` states for its own pair, and the reason a reader of a
ceiling refusal is told *what to lower* rather than handed a token to grep for.

No new component — feature 270's single ``"dreaming"`` component is the
member's whole composition, and the ceiling is reached the way the floor is, as
a free function beside the store.  No seat edit, no table, no migration, no
third party: this module imports ``typing``, the member's own ``.cap``,
``.errors`` and ``.ladder``, and nothing else, so the factory's scan — which
imports this package to fire its ``@register`` — pays nothing for the ceiling.
"""

from __future__ import annotations

from typing import Any

from .cap import CAPPED_SWEEP_CAP, FULL_DREAMING_WORLDS
from .errors import RevisionCeilingError
from .ladder import LADDER_FLOOR_WORLDS, rejects_thin_pool, validated_floor

__all__ = ["rejects_uncapped_sweep"]


def _validated_revision_count(value: Any) -> int:
    """Check that ``value`` is a revision count, or refuse it as the ask's own.

    A revision count is what §C5's loop runs — *"run ``M`` code revisions of
    ``π``"* — so it is a non-negative whole number, and a ``bool`` is refused
    where a count belongs because ``True`` is ``1`` in Python: a flag where a
    revision count belongs would name a sweep of one revision, which is a
    sweep nobody intended rather than a malformed ask.  Zero is admitted and
    never refused by the ceiling: *do not run any revision* is a caller's own
    business and the ceiling exists to bound a sweep that happens, not to
    require one.

    Spelled here rather than borrowed from :func:`dreaming.cap.
    revision_cap`'s own figure validation for the reason that module gives for
    spelling its own: the *rule* is one rule, and the *vocabulary* splits by
    who was asked.  A caller of the ceiling that handed in a malformed count
    must not meet feature 277's request class for a judgment feature 277 never
    made — the seam discipline the whole workspace states for error
    vocabularies, applied inside the member.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RevisionCeilingError(
            f"a revision count is a whole number — got {value!r} "
            f"({type(value).__name__}); §C5's loop runs M code revisions of "
            "the exploration policy, and a value that is not a whole number "
            "names no sweep this ceiling can measure"
        )
    if value < 0:
        raise RevisionCeilingError(
            f"a revision count is a non-negative whole number — got {value!r}; "
            "a sweep runs zero revisions or more, and a negative figure names "
            "no sweep this ceiling can measure"
        )
    return value


def _validated_world_count(value: Any) -> int:
    """Check that ``value`` is a pool size, or refuse it as the ask's own.

    The same rule :func:`dreaming.cap._validated_world_count` and the ladder's
    own ``_validated_figure`` state — a pool's size is a non-negative whole
    number, ``bool`` refused — and refused in *this* module's vocabulary for
    the reason that pair gives: the figure arrives here as part of the ask, and
    a malformed one must not be answered with the ladder's ``pool_too_thin``
    word.  A pool size that is not a count is a **malformed ask** (repair:
    re-send it), never a **thin pool** (repair: grow it), and the two repairs
    are the entire reason this member splits its error classes the way it does.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RevisionCeilingError(
            f"a pool's size is a world count — got {value!r} "
            f"({type(value).__name__}); this ceiling is decided over the pool a "
            "cycle is about to walk, and a value that is not a whole number "
            "names no band the ceiling applies to"
        )
    if value < 0:
        raise RevisionCeilingError(
            f"a pool's size is a non-negative world count — got {value!r}; a "
            "pool holds zero worlds or more, and a negative figure names no "
            "band the ceiling applies to"
        )
    return value


def _validated_boundary(value: Any) -> int:
    """Check that ``value`` is the band's upper edge, or refuse it.

    The edge is a world count like the floor is — a non-negative whole number,
    ``bool`` refused — validated in this module's vocabulary because it is the
    edge of the band this module enforces.  §12.1's ``50``, the point at which
    the capped sweep becomes full dreaming and this ceiling stops applying.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RevisionCeilingError(
            f"the band's upper edge is a world count — got {value!r} "
            f"({type(value).__name__}); §12.1's ladder runs the capped sweep "
            "below a count of worlds, and a value that is not a whole number "
            "names no edge the band can end at"
        )
    if value < 0:
        raise RevisionCeilingError(
            f"the band's upper edge is a non-negative world count — got "
            f"{value!r}; a negative edge would place the capped sweep below "
            "the ladder's floor, which is no ladder at all"
        )
    return value


def _validated_ceiling(value: Any) -> int:
    """Check that ``value`` is a revision ceiling, or refuse it.

    The ceiling is a revision count that bounds a revision count, so it is a
    non-negative whole number on the same terms as the count it judges —
    ``bool`` refused for the reason every count in this member refuses one.
    Zero is a coherent ceiling: a deployment that answers *no sweep on this
    band* is applying the floor's own advice one rung up, and it is admitted
    rather than refused because the ladder does not forbid a narrow band, only
    an unmeasured one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RevisionCeilingError(
            f"the band's ceiling is a revision count — got {value!r} "
            f"({type(value).__name__}); the ceiling bounds how wide a sweep "
            "the band may run, and a value that is not a whole number names no "
            "bound a caller could lower M to"
        )
    if value < 0:
        raise RevisionCeilingError(
            f"the band's ceiling is a non-negative revision count — got "
            f"{value!r}; a sweep runs zero revisions or more, and a negative "
            "ceiling would refuse every sweep the band could run, which is "
            "the thin-pool rung's refusal spoken from the wrong rung"
        )
    return value


def rejects_uncapped_sweep(
    revision_count: Any,
    world_count: Any,
    *,
    floor: Any = LADDER_FLOOR_WORLDS,
    full_dreaming: Any = FULL_DREAMING_WORLDS,
    ceiling: Any = CAPPED_SWEEP_CAP,
) -> None:
    """Refuse a sweep wider than the band's ceiling — feature 276's call.

    The one judgment for feature 276's sentence: the revision count a cycle
    means to run and the pool's size in, and either the sweep proceeds or it is
    refused.  It decides whether the pool sits in §12.1's ``20–50`` band and,
    if it does, whether the count stays within the band's cap — *"dreaming with
    ``M`` capped at 8–10 so the selection bar stays low"* — and **raises**
    :class:`~dreaming.errors.RevisionCeilingError` when it does not, so a
    caller that calls it on its last line is stopped before it begins a sweep
    whose selection bar is wider than the pool can carry.

    Three regions, and the ceiling applies to exactly one of them:

    * ``world_count >= full_dreaming`` — **admitted, whatever the count**.  The
      pool has cleared §12.1's ``50``, feature 277's raise has fired, and ``M``
      is that feature's to answer at 40 (:func:`dreaming.cap.revision_cap`
      returns it).  The ceiling is the middle rung's rule and does not follow a
      cycle up the ladder — refusing 40 here would leave the top rung refusing
      the figure §12.1's own bar calculation is written at.
    * ``floor <= world_count < full_dreaming`` — the band.  A count **above**
      ``ceiling`` is refused; a count at or below it is admitted.  The edge is
      inclusive on the admitted side: ``ceiling`` itself runs, ``ceiling + 1``
      does not.
    * ``world_count < floor`` — **refused by the ladder**, in
      :func:`~dreaming.ladder.rejects_thin_pool`'s own word (``pool_too_thin``)
      and its own class: a pool that may not dream at all needs no cap on its
      sweep, and the refusal is feature 275's because the fact is.

    ``ceiling`` defaults to :data:`dreaming.cap.CAPPED_SWEEP_CAP` — the very
    figure feature 277's schedule answers on this band — so the default
    judgment and the schedule agree by construction: **this function never
    refuses the cap** :func:`dreaming.cap.revision_cap` **answers**, at any
    pool size.  ``floor`` is passed straight through to the ladder's judgment
    (the keyword is the floor's own ``gate``), so the two spellings of the
    bottom rung cannot disagree; ``full_dreaming`` is the band's upper edge and
    is refused when it falls below the floor, because an edge under the floor
    leaves no band between them and every admissible pool would escape the
    ceiling §12.1 keeps shut on the thin rung.

    Both figures are counts the caller already has — the pool's size from the
    hold it opened (§C5's loop holds one per outer iteration, and a feature-270
    :class:`~dreaming.cycle.FreezeRecord` records ``world_count``) and the
    revision count from its own intent.  Passed in rather than read, so this
    module never opens a database or counts the pool itself: a verdict is not a
    count, and the count is the caller's to supply.

    Refuses, in this order, each naming what it is about:

    1. a ``revision_count`` that is not a non-negative whole number, or a
       ``world_count`` that is not one — the ask's own facts, refused before
       anything else is judged (:class:`~dreaming.errors.
       RevisionCeilingError`);
    2. a ``floor`` that is not a non-negative whole number — refused by the
       ladder's own :func:`~dreaming.ladder.validated_floor`, in the ladder's
       vocabulary, because the floor is feature 275's fact;
    3. a ``full_dreaming`` that is not a non-negative whole number, or one
       below the floor — the first names no edge and the second erases the band
       (:class:`~dreaming.errors.RevisionCeilingError`);
    4. a ``ceiling`` that is not a non-negative whole number — the bound the
       caller asked for is part of the ask
       (:class:`~dreaming.errors.RevisionCeilingError`);
    5. a pool below the floor — too thin to dream on at all, refused by the
       ladder in its own word and its own class
       (:class:`~dreaming.errors.PoolTooThinError`);
    6. a count above the ceiling while the pool sits in the band — the one
       refusal this sentence mints
       (:class:`~dreaming.errors.RevisionCeilingError`).

    A malformed count, edge or ceiling is refused rather than answered, so a
    cycle whose inputs are wrong is never silently admitted or blocked on a
    number that is not a count — the caller corrects the inputs and calls
    again.
    """
    count = _validated_revision_count(revision_count)
    figure = _validated_world_count(world_count)
    floor_count = validated_floor(floor)
    boundary = _validated_boundary(full_dreaming)
    if boundary < floor_count:
        raise RevisionCeilingError(
            f"the band ends at or above the ladder floor — got an upper edge "
            f"of {boundary} under a floor of {floor_count}; §12.1's ladder "
            "holds a capped sweep between the two, and an edge below the floor "
            "leaves no band between them, so every admissible pool would run "
            "the uncapped sweep this ceiling exists to refuse"
        )
    cap = _validated_ceiling(ceiling)
    rejects_thin_pool(figure, gate=floor_count)
    if figure >= boundary:
        return
    if count > cap:
        raise RevisionCeilingError(
            f"a dreaming sweep over a pool of {figure} world(s) runs at most "
            f"{cap} revision(s) — got {count}; docs/alpha-engine-prd.md §12.1 "
            f"caps M at 8-10 on the {floor_count}-{boundary} band so the "
            "selection bar stays low, and Appendix B's bar "
            "(true_advantage > sqrt(2 ln M) . sigma_V / sqrt(n_worlds)) widens "
            f"with M: the section computes n > 53 worlds for M = 40, so a "
            f"wider sweep is available only once the pool clears {boundary} "
            "worlds. Lower M to the band's cap, or grow the pool until the "
            "raise applies"
        )
