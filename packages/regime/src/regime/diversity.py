"""The diversity claim's verdict — feature 289.

app_spec.xml, "Regime Coverage Strata", feature 289: *System rejects a
regime-diverse claim while fewer than three strata hold stored worlds.*
Its declared parent is feature 284 — the ledger read — and the dependency
is the whole shape: the claim is judged over a *reading*, the very
:class:`~regime.ledger.CoverageLedger` :meth:`~regime.coverage.
RegimeCoverage.ledger` answers, and this module adds to that reading the
one thing it declines to do itself.  docs/alpha-engine-prd.md §C7 states
the danger the sentence exists to keep a claim from papering over:

    The paper's replay pool grows monotonically and that is fine when
    outcomes are ground truth.  Yours is indexed by calendar time.  Run
    six months in low-vol chop and your entire pool is low-vol chop;
    the meta-policy learns a chop-optimal search policy and you find
    out when the regime breaks.

A *regime-diverse claim* is the report that says the pool is past that
danger — that it spans regimes, that a policy selected over it was not
selected over one regime wearing a pool's clothes.  And §C7's own example
ledger is the claim's worst case written down: ``{high-vol trend: 2,
low-vol chop: 14, crash: 0, …}`` is two strata holding worlds and one
named and empty, published beside a zero nobody acted on.  This module
is the acting: while fewer than three strata hold stored worlds, the
claim does not leave the room.

**A judgment over the counts already made, never a third count.**  The
category's division of labour is stated from feature 283 onward and this
module is the last piece of it: :mod:`regime.coverage` persists one
count per stratum, :mod:`regime.ledger` reads them all back,
:mod:`regime.census` makes the numbers, and :mod:`regime.origins`
records where backfilled worlds came from.  Every one of those is a
*fact about the pool*; a verdict over them is a different act, and a
module that counted *and* judged would be answering a question about a
report from inside a count.  So this module counts nothing (the figure
is the reading's own), persists nothing (a verdict is not evidence —
the ledger's rows are), and registers no component
(:mod:`regime.__init__`'s own argument: feature 289's refusal *"is a
threshold applied to counts the caller read through this store"* — a
free function beside the store, the way :func:`~bootstrap.
rejects_dreaming_claim` sits beside the census it judges).  The shape is
the dreaming ladder's verdicts exactly
(:func:`~dreaming.ladder.rejects_thin_pool`,
:func:`~dreaming.bar.rejects_unbarred_winner`): figures the caller
already holds in, and either the claim proceeds or it is refused.

**What the figure is — strata that hold worlds, and nothing else.**
:attr:`~regime.ledger.CoverageLedger.covered` is the view the ledger
ships *for this feature* (*"the figure feature 289's diversity claim is
refused against"*), and this module honors its definition rather than
recomputing it: a stratum counts when its row holds at least one stored
world.  Two neighbors the figure deliberately is not.  It is not
``len(ledger)`` — naming is not covering, and a ledger that names three
strata and holds worlds in none of them is §C7's ``crash: 0`` drawn
three times over.  It is not the sum of the counts — worlds are not
strata, and fourteen worlds in low-volatility chop *is* the one-regime
pool §C7's opening sentence describes, whatever fourteen counts.  And
``0107`` detail 1 holds at this seam as everywhere else in the member:
a stratum named and empty and a stratum never named are different facts
(feature 286's ``empty_stratum`` warning fires on the first and must not
fire on the second), but they are the same *non-figure* here — neither
holds a stored world, and the claim is not diverse on either's account.

**Why three, and why the floor is a keyword.**  The sentence's own
number, and the number the member's default vocabulary arrives at on
its own: :data:`~regime.coverage.DEFAULT_STRATA` names three strata, the
labeler's :data:`~feature_store.regime_labeler.DEFAULT_K` carves three
(the agreement ``packages/regime/tests/test_cross_member.py`` pins, since
no member imports another), and a pool diverse in fewer than the
vocabulary's own size is diverse in a minority of the regimes the
deployment counts.  :data:`REGIME_DIVERSITY_FLOOR` is that three, and
the member's suite pins it to ``len(DEFAULT_STRATA)`` so a future edit
that widens the default vocabulary has to look at the floor too.  The
floor is a keyword — the precedent :func:`~dreaming.ladder.
rejects_thin_pool`'s ``gate`` and :func:`~bootstrap.
rejects_dreaming_claim`'s ``gate`` set, and the openness
:meth:`~regime.ledger.CoverageLedger.holes`'s vocabulary argument states
for this member: a deployment whose labeler carves five strata asks the
diversity question with its own figure, and nothing here refuses one.
The boundary is the sentence's own word: the claim is rejected *while
fewer than* the floor's strata hold worlds, so at exactly the floor the
claim stands, and there is no upper edge — more strata holding worlds
only strengthens a diversity claim, the same asymmetry a power floor
has.

**The refusal raises, and that is the point.**  A claim that survives
judgment returns ``None``; a claim that does not **raises**
:class:`~regime.errors.DiversityClaimError`, because the shape that
protects a published report is the caller calling this on its last
line — the stop has to be the function's own act, not a boolean every
caller must remember to branch on, and the caller that forgets is
precisely the report §C7 exists to prevent.  The class is the sibling
:mod:`regime.errors` reserved for this feature when it argued that
*"a well-formed ask that runs into … a judged threshold is not a
malformed one"*: a caller catching :class:`~regime.errors.CoverageError`
for a refused persist must not find a refused *claim* behind the same
``except``, because the repairs differ — the persist's repair is a
corrected re-ask, and the claim's repair is a decision about evidence
(withdraw the claim, or grow the coverage it leans on).

**The seam is the reading, and it is duck-typed.**  The judgment takes
the ledger value — reached through either of feature 284's spellings,
:meth:`~regime.coverage.RegimeCoverage.ledger` for the caller that holds
a store, :func:`~regime.ledger.read_ledger` for the caller that holds a
URL — and never the store itself: a verdict over a live store would be
a verdict about a moving pool, and the dreaming ladder's law holds here
too (*"a verdict is not a count, and the count is the caller's to
supply"*).  A store handed in by mistake is refused with its repair
named — read first, then judge.  The reading is duck-read on its
``covered`` view rather than ``isinstance``-gated, for the reason every
seam in this workspace duck-reads: the module loader imports each member
under a synthetic name, so the ledger a composed store hands back is
structurally identical to a direct import's without being the same
class object, and a type gate would refuse the very reading composition
serves.  What is read is validated — each covered row's name, through
feature 283's own validator imported rather than re-written, with its
:class:`~regime.errors.CoverageError` translated into this module's
class at the seam so a caller's ``except DiversityClaimError`` is never
defeated by the count-persist vocabulary for an act that persisted
nothing.

**A value is a reading, and the verdict rules on the one it was handed.**
The judgment does not re-read the table behind the ledger's back: §C6's
tripwires excise worlds, the census and the backfill land counts, and
another process may have moved the pool since the caller took its
reading.  A claim judged over a stale reading gets that reading's
verdict — which is the honest behaviour for a caller that *claims over
what it read* — and the caller claiming diversity *now* reads again and
judges the new reading.  The suite pins both halves.

**The message names everything an operator needs.**  It opens with
:data:`NOT_REGIME_DIVERSE_CODE` — ``not_regime_diverse``, the greppable
one word in the family ``pool_too_thin``, ``full_history_fit``,
``no_origin`` and ``illegal_theme`` already establish — then states the
figure, names the strata that hold worlds, states the floor, names §C7,
and states the repair: withdraw the claim, or raise the figure.  The
acts that raise it are the category's own — the census (feature 290)
that counts the pool into the ledger and the backfill (feature 287)
that replays stored trees against epochs they never saw — and the
refusal says so, because a gate whose message does not name the door
out is a dead end rather than a finding.

**Stdlib only, and import-cheap.**  No ``sqlite3``, no third-party
import at module scope — the factory's scan imports this package to
fire its ``@register``, and a judgment that never opens a database
should never make composition pay for one.  This module holds no state,
registers nothing, and adds no second component: the member's registered
surface stays feature 283's one store, reached exactly as
:mod:`regime.__init__` documents.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .coverage import _validated_stratum
from .errors import CoverageError, DiversityClaimError

__all__ = [
    "NOT_REGIME_DIVERSE_CODE",
    "REGIME_DIVERSITY_FLOOR",
    "rejects_regime_diverse_claim",
]

#: The one word that names the refusal — ``not_regime_diverse`` — opening
#: every verdict this module raises so it is greppable by the word an
#: operator would search for, the convention ``pool_too_thin`` (feature
#: 275), ``full_history_fit`` (feature 290) and ``no_origin`` (feature
#: 288) already follow in this workspace.  The word names the *finding*,
#: not the act: the claim said regime-diverse, and the pool is not.
NOT_REGIME_DIVERSE_CODE = "not_regime_diverse"

#: How many strata must hold stored worlds before a regime-diverse claim
#: stands — the feature's own sentence (*"fewer than three strata"*) and
#: the default vocabulary's own size in one number: ``DEFAULT_STRATA``
#: names three, the labeler's ``DEFAULT_K`` carves three, and a claim of
#: diversity over fewer than the vocabulary's own count of regimes is
#: diverse in a minority of what the deployment counts.  The member's
#: suite pins ``REGIME_DIVERSITY_FLOOR == len(DEFAULT_STRATA)`` so a
#: future edit that widens the vocabulary has to look at the floor too.
#: The default of the ``floor`` keyword, not a law: a deployment asking
#: the diversity question over a wider vocabulary passes its own figure.
REGIME_DIVERSITY_FLOOR = 3


def _validated_floor(floor: Any) -> int:
    """Check that ``floor`` is a count of strata, or refuse it.

    The one spelling of what the floor must be, shared by
    :func:`rejects_regime_diverse_claim`.  A floor is a count of strata —
    the feature's sentence's *three* — so it is a positive whole number,
    and a value that is not one would silently admit or block a claim on
    a number that is not a count of anything.  A ``bool`` is refused
    where a count belongs for the reason every count validator in this
    workspace refuses one: ``True`` is ``1`` in Python, so a flag where
    a floor belongs would name a pool of one covered stratum as diverse
    enough, which no reading of §C7 supports.

    Zero is refused rather than allowed: a diversity floor of zero
    admits every claim — including one over a pool no stratum of which
    holds a single world — which is the exact blindness §C7's ledger
    exists to cure, legislated back in through the configuration.  A
    floor of one is *degenerate* but honest (``covered >= 1`` still
    refuses an empty pool's claim) and is not this module's to refuse.
    """
    if isinstance(floor, bool) or not isinstance(floor, int):
        raise DiversityClaimError(
            f"{NOT_REGIME_DIVERSE_CODE}: the regime-diversity floor is a "
            f"count of strata — got {floor!r} ({type(floor).__name__}); "
            "feature 289's sentence refuses a claim while fewer than three "
            "strata hold stored worlds, and a value that is not a whole "
            "number names no floor a claim can be judged against (a truthy "
            "flag is not a count of strata, and a fractional stratum is "
            "not a stratum)"
        )
    if floor < 1:
        raise DiversityClaimError(
            f"{NOT_REGIME_DIVERSE_CODE}: the regime-diversity floor is at "
            f"least one stratum — got {floor!r}; a floor below one admits "
            "every claim, including one over a pool no stratum of which "
            "holds a single stored world, and the one thing this feature "
            "exists to keep shut is the claim §C7's ledger says the pool "
            "cannot carry"
        )
    return floor


def _covered_strata(ledger: Any) -> tuple[str, ...]:
    """Read the covered figure off ``ledger``, or refuse what carries none.

    The judgment's whole evidence, gathered in one place: the names of
    the strata the reading says hold at least one stored world, in the
    reading's own order.  The figure is the length of the answer and the
    message is built from the names — the two things this seam reads —
    and nothing else on the ledger is consulted, because the covered view
    is the ledger's own named spelling of exactly this figure and a
    judgment that re-derived it from ``rows`` would be the drift that
    view exists to prevent.

    Duck-typed on ``covered`` (the loader's synthetic-name copies make
    ``isinstance`` refuse the very reading composition serves), and each
    covered row's name goes through feature 283's own validator —
    imported, not re-written — with its refusal translated into this
    module's class at the seam: an ask refused here must not surface as
    a count-persist refusal a caller's ``except DiversityClaimError``
    can miss.
    """
    covered = getattr(ledger, "covered", None)
    if covered is None:
        # The store carries its own read verb and no covered view, so a
        # store handed in where the reading belongs is refusable *by its
        # repair*: read first (feature 284's verb), then judge.  Spelled
        # duck-shaped rather than as an isinstance for the composed-copy
        # reason above — the loader's RegimeCoverage is a second class
        # object too.
        if callable(getattr(ledger, "ledger", None)):
            raise DiversityClaimError(
                f"{NOT_REGIME_DIVERSE_CODE}: a regime-diverse claim is "
                f"judged over a reading, and {ledger!r} is the store — "
                "call its ``ledger()`` verb (feature 284's read, either "
                "spelling) and hand the judgment the CoverageLedger it "
                "answers with; a verdict over a live store would be a "
                "verdict about a pool that can move under it"
            )
        raise DiversityClaimError(
            f"{NOT_REGIME_DIVERSE_CODE}: a regime-diverse claim is judged "
            f"over a coverage ledger — got {ledger!r} "
            f"({type(ledger).__name__}), which carries no ``covered`` "
            "figure; the reading feature 284's verb answers with is the "
            "evidence the claim is refused against, and something that "
            "is not that reading names no figure to judge a claim on"
        )
    if isinstance(covered, (str, bytes)) or not isinstance(covered, Iterable):
        raise DiversityClaimError(
            f"{NOT_REGIME_DIVERSE_CODE}: a ledger's ``covered`` view is a "
            f"collection of the rows that hold stored worlds — got "
            f"{covered!r} ({type(covered).__name__}); the figure the "
            "diversity claim is judged on is how many strata that view "
            "counts, and something that cannot be counted names no figure"
        )
    names: list[str] = []
    for row in covered:
        try:
            names.append(_validated_stratum(getattr(row, "stratum", None)))
        except CoverageError as exc:
            raise DiversityClaimError(
                f"{NOT_REGIME_DIVERSE_CODE}: a covered row could not be "
                f"read as a stratum — got {row!r}: {exc}"
            ) from exc
    return tuple(names)


def rejects_regime_diverse_claim(
    ledger: Any,
    *,
    floor: int = REGIME_DIVERSITY_FLOOR,
) -> None:
    """Refuse a regime-diverse claim the pool's coverage does not carry.

    The one judgment for feature 289's sentence: a coverage ledger in —
    the reading feature 284's verb answers with — and either the claim
    proceeds or it is refused.  It decides whether the strata that hold
    stored worlds reach the floor — *"rejects a regime-diverse claim
    while fewer than three strata hold stored worlds"* — and **raises**
    :class:`~regime.errors.DiversityClaimError` when they do not, so the
    caller that calls it on its last line is stopped before the claim is
    published.  A claim over a pool whose covered strata meet the floor
    returns without raising — at exactly the floor the claim stands,
    because the sentence rejects *while fewer than*, and there is no
    upper edge: more strata holding worlds only strengthens the claim.

    The figure is the reading's own :attr:`~regime.ledger.
    CoverageLedger.covered` view — the strata holding at least one
    stored world, honored rather than recomputed.  Not ``len(ledger)``:
    naming a stratum is not covering it, and §C7's own example ledger
    (``crash: 0`` beside two covered strata) is a two-figure pool.  Not
    the sum of the counts: worlds are not strata, and fourteen worlds in
    one regime is the one-regime pool §C7's ledger exists to expose.  A
    stratum named and empty and a stratum never named are different
    facts (``0107`` detail 1, and feature 286's business) and the same
    non-figure here — neither holds a stored world.

    The judgment rules on the reading it was handed and never re-reads
    the table behind it: a claim over a stale reading gets that
    reading's verdict, and the caller claiming diversity *now* reads
    again and judges the new reading.  It writes nothing — a verdict is
    not a persist, and the table is exactly what it was whether the
    claim stands or falls.

    Refuses, in this order, each naming what it is about:

    1. a ledger carrying no readable figure — nothing handed in, a
       string, a ``covered`` view that cannot be counted, a covered row
       with no usable stratum name; a store handed in where the reading
       belongs is refused with its repair named (call ``ledger()`` on it
       first — feature 284's verb);
    2. a ``floor`` that is not a positive whole count of strata — a
       floor that is not a count cannot judge a claim, and a floor below
       one admits every claim, which is the gate this feature exists to
       keep shut;
    3. the verdict — fewer than ``floor`` strata hold stored worlds,
       refused with a message that opens with ``not_regime_diverse``,
       states the figure and names the covered strata, names the floor,
       names §C7, and states the repair: withdraw the claim, or raise
       the figure — the census (feature 290) and the backfill
       (feature 287) are the acts that do.
    """
    covered = _covered_strata(ledger)
    minimum = _validated_floor(floor)
    if len(covered) >= minimum:
        return
    if covered:
        noun, verb = (
            ("stratum", "holds") if len(covered) == 1 else ("strata", "hold")
        )
        named = ", ".join(repr(name) for name in sorted(covered))
        finding = (
            f"{len(covered)} {noun} {verb} stored worlds ({named}), below "
            f"the regime-diversity floor of {minimum}"
        )
    else:
        finding = (
            f"no stratum holds a stored world, below the regime-diversity "
            f"floor of {minimum}"
        )
    raise DiversityClaimError(
        f"{NOT_REGIME_DIVERSE_CODE}: {finding}; docs/alpha-engine-prd.md "
        "§C7 refuses a regime-diverse claim while fewer than that many "
        "strata hold stored worlds, because the replay pool grows "
        "monotone with calendar time — run six months in low-vol chop and "
        "the entire pool is low-vol chop — and a claim of diversity the "
        "pool does not carry publishes the skew §C7's ledger exists to "
        "make visible. Withdraw the claim, or raise the figure: the "
        "census (feature 290) and the backfill (feature 287) are the acts "
        "that bring more strata to hold stored worlds, and the claim "
        "stands over the reading that follows"
    )
