"""The meta-level selection bar — feature 280, and the tournament's own verdict.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 280: *System rejects a
winning revision whose advantage falls below the square root of twice the log
of M scaled by score deviation.*  docs/alpha-engine-prd.md §12.1 states the
rule the sentence exists to enforce, and states it as the answer to the
question §C5's loop ends on — *"select the argmax under §7"* — because the
argmax is not the last word about a tournament, it is the first word about a
maximum:

    Applying the ``√(2 ln M)`` bar at the meta level, with ``SE(V) ≈
    σ_V/√n_worlds``, the selected policy's true advantage survives selection
    noise only when:

        true_advantage  >  √(2 ln M) · σ_V / √n_worlds

    At ``M = 40`` (bar ≈ 2.72), ``σ_V ≈ 0.8`` and a target advantage of 0.3,
    this gives **n > 53 worlds** — independently reproducing the ~56 from the
    paired-power calculation in §11.0.

docs/nullius-tech-architecture.md §10.3.1 carries the same line under its own
heading — *Meta-level selection discipline* — and states the stance this
module takes: *"The orchestrator enforces this as a hard precondition, not a
guideline."*  Appendix B lists the formula among its reference forms.

**Why the winner needs a bar at all — because a max is biased.**  §7.3 states
the statistic one level down and states it exactly: *"Expected maximum Sharpe
under the null across ``K`` trials grows like ``√(2 ln K)``, in units of
``SE(Sharpe)``"* — 10 trials at 2.15, 100 at 3.03, 1,000 at 3.72, 10,000 at
4.29.  §12.1's warning is that the dreaming loop is *"the same
multiple-testing problem one level up"*: selecting the max over ``M``
revisions scored on a fixed pool selects **upward noise**, and the noise a max
selects is precisely §7.3's figure — the expected maximum of ``M`` scores that
carry *no* advantage at all is ``√(2 ln M)`` standard errors.  So a winner
whose advantage sits below that many standard errors is indistinguishable from
the best of ``M`` nulls, and persisting it (feature 274's write into
``policy_revision``) would enshrine selection noise as improvement while every
figure in the record looked like a measurement.

**The repair is the incumbent, and that is what makes the refusal safe.**  The
paper's guarantee ``V^{m★} ≥ V^0`` holds *by construction* once the incumbent
is in the candidate set (feature 273's sentence): when nothing clears the bar,
the incumbent *is* the argmax.  A refused winner is not a lost cycle — it is
the guarantee holding, which is why this refusal raises and answers nothing
rather than returning a score the caller might act on.

What this module is
-------------------

Three spellings of one act:

* :func:`selection_bar` — the arithmetic itself: ``M``, the score deviation
  and the world count in, Appendix B's bar out.  The shape
  :func:`dreaming.cap.revision_cap` takes for its own figure — a pure
  function over counts the caller already holds, which never opens a
  database, because a verdict is not a count and the count is the caller's
  to supply;
* :func:`rejects_unbarred_winner` — the **rejects** of the sentence, and the
  shape the ladder's other verdicts take
  (:func:`dreaming.ladder.rejects_thin_pool`,
  :func:`dreaming.ceiling.rejects_uncapped_sweep`,
  :func:`dreaming.paired.rejects_proportion_comparison`): the winner's
  advantage and the figures the bar is computed over in, and either the
  winner proceeds or it is refused;
* :func:`cycle_bar` — the store seam: ``M`` read back from feature 277's
  record, and the winner's advantage judged at it.  This is the half of the
  feature the record exists for — cap.py's own statement of why the cap is
  persisted is that *"Appendix B's selection bar … reads ``M`` back, and a
  bar computed over an ``M`` nobody recorded is a bar over a number nobody
  ran"*, and this is the code that does the reading.

The figures the bar is computed over are feature 281's, carried not respelled
--------------------------------------------------------------------------

§12.1's ``σ_V ≈ 0.8`` and §11.0's ``σ_diff ≈ 0.8`` are one figure — the two
sections' ``n > 53`` and ``~56`` are two derivations of the same pool, which
is §12.1's own claim (*"independently reproducing"*) — so the advantage the
bar judges is the mean paired difference, the deviation it is scaled by is
the sample deviation of those differences, and the world count it is divided
by is the pair's world count: three figures one
:class:`~dreaming.paired.PairedDifference` already carries, which is why the
store seam takes the comparison whole rather than three loose numbers.  A
caller holding loose figures (a report, a test, a pool measured another way)
reaches :func:`rejects_unbarred_winner`; a caller holding the comparison the
holdout produced reaches :func:`cycle_bar`; the two spell the same verdict
over the same arithmetic and cannot disagree.

The bar does not choose the worlds the advantage was measured over — feature
278's split does, and §10.3.1's discipline is that the winner is *reported*
on holdout worlds.  :func:`cycle_bar` judges whatever comparison it is handed,
for the same reason :func:`dreaming.paired.paired_ir_difference` does: the
honesty of the world set is the split's sentence, not the bar's.

The ``M`` is read back, and the record in force is the newest
-------------------------------------------------------------

:func:`cycle_bar` reads the cycle's ``M`` from ``cycle_cap`` — feature 277's
append-only history, one row per cycle-occurrence — and takes the **newest**
row naming the iteration, because a retried cycle is re-decided over the pool
as it stands and the decision in force when the sweep ran is the last one
written.  A cycle that holds no record for the iteration is refused rather
than guessed at: that is the *"a bar over a number nobody ran"* refusal, and
it is this module's own store face rather than the cap's, because the caller
asked for a bar and must not be told the cap could not be *recorded*.

The ``M`` read back is the recorded **cap** — the bound the cycle ran under —
not a count of the revisions that happened to complete, and that is the
conservative direction by the arithmetic's own monotonicity: the bar grows
with ``M`` (``√(2 ln M)`` is increasing), so a cycle that ran fewer revisions
than its cap is judged against a bar at least as wide as the one its actual
sweep earned.  A bar that under-counts ``M`` is the one failure this seam
cannot produce.

The edge, and the one candidate that carries no selection noise
---------------------------------------------------------------

**The edge is strict, and it is §12.1's own word.**  *"Survives selection
noise **only when** ``true_advantage > √(2 ln M) · σ_V / √n_worlds``"* — an
advantage exactly at the bar has not exceeded it, exactly as
:meth:`~dreaming.paired.PairedDifference.clears` states the strict edges of
the gate's own criterion (*"a ``ΔIR`` exactly equal to the bar is not
*greater* than it"*).  A winner one float above clears; a winner at the bar
does not.

**``M = 1`` answers a bar of zero, and that is the arithmetic's own value.**
``ln 1 = 0``: the expected maximum of one null score is that score, and the
multiple-testing width begins with the second candidate.  A tournament of one
revision carries no selection noise to survive, so any positive advantage
clears and the module does not refuse the figure — §12.1's ladder caps far
above one, and a refusal here would be editorialising rather than judging.

What this module is not
-----------------------

**It is not the selector, and it does not persist anything.**  Feature 274
selects the argmax and writes the winner into ``policy_revision``; this
module *refuses* a winner, and the act of refusing one is not the act of
crowning it.  It reads ``cycle_cap`` and writes no row, no table and no
column — the same read-time discipline :mod:`dreaming.paired` and
:mod:`dreaming.split` state for the pool, and a bar taken under feature 270's
hold is permitted because it is a read.

**It is not the ceiling.**  Feature 276 refuses a *sweep* — before it runs,
for the width the pool's rung cannot fund; this module refuses a *winner* —
after the sweep ran, for the selection noise the sweep earned.  The two share
Appendix B's line and nothing else: the ceiling's repair is to lower ``M``
before running, the bar's is to keep the incumbent after winning, and a
caller that caught one as the other would lower a cap that was legal or
re-run a sweep that was noise.

**It is not the gate.**  :meth:`~dreaming.paired.PairedDifference.clears` is
the M3 deployment criterion (``ΔIR > 0.3`` with ``p < 0.05``); the bar is the
in-loop selection criterion (advantage beyond ``√(2 ln M)`` standard errors).
A winner can clear the bar and fail the gate, and clear the gate's figures
while failing the bar — the two answer different questions, and the bar
states no verdict about deployment.

No new component — feature 270's single ``"dreaming"`` component is the
member's whole composition, and the bar is reached the way the floor, the
cap, the ceiling, the split and the comparison are, as free functions beside
the store.  No seat edit, no migration, no table, no third party: ``math``
and the member's own ``.cap``, ``.cycle``, ``.errors``, ``.layout`` and
``.paired``, so the factory's scan — which imports this package to fire its
``@register`` — pays nothing for the bar.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .cap import CapRecordError, CapRequestError, cycle_caps
from .cycle import FreezeRequestError, validated_iteration_id
from .errors import BarRecordError, BarRequestError, SelectionBarError
from .layout import DATABASE_URL_ENV
from .paired import PairedDifference

__all__ = [
    "SELECTION_BAR_CODE",
    "cycle_bar",
    "rejects_unbarred_winner",
    "selection_bar",
]

#: The code a *below-bar* refusal opens with — the winning revision's
#: advantage did not survive the selection noise its own tournament earned —
#: so the rejection is greppable by the word that names it.  Feature 280's
#: sentence mandates no token (*"rejects a winning revision whose advantage
#: falls below …"* names its subject in prose), so the code is this module's
#: own, minted on the ``pool_frozen`` / ``pool_too_thin`` /
#: ``proportion_comparison`` convention the workspace states for the one
#: refusal an operator greps a deployment log for: *why did this cycle keep
#: the incumbent?*  The ask and store faces carry no code, for the reason
#: :class:`~dreaming.errors.CapRequestError` gives — they name their subjects
#: in their first words and a reader is told *what to fix* rather than handed
#: a token for a developer fact.
SELECTION_BAR_CODE = "advantage_below_bar"


def _validated_advantage(value: Any) -> float:
    """Check that ``value`` is a finite real advantage, or refuse it.

    The figure the whole verdict turns on — §12.1's ``true_advantage``, in
    the paired spelling the mean difference feature 281 answers — so it is a
    finite real, and a ``bool`` is refused where a figure belongs because
    ``True`` is ``1`` in Python: a flag where an advantage belongs would read
    as a full unit of IR, which no advantage is.  ``nan`` and ``inf`` are
    refused because they are not readings at all: a ``nan`` advantage
    compared against the bar answers ``nan``, which is neither below it nor
    above it, and a verdict that answered nothing while looking like it had
    decided would be the failure this member's vocabulary exists to prevent.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BarRequestError(
            f"a winner's advantage is a number — got {value!r} "
            f"({type(value).__name__}); the bar judges §12.1's "
            "true_advantage, the mean paired difference the comparison "
            "answered, and a value that is not one names no advantage this "
            "verdict can measure"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise BarRequestError(
            f"a winner's advantage is a finite number — got {value!r}; a "
            "non-finite figure compared against the bar answers neither "
            "below nor above it, which is a verdict that decided nothing "
            "while looking like it decided one"
        )
    return figure


def _validated_revision_count(value: Any) -> int:
    """Check that ``value`` is a revision count, or refuse it as the ask's own.

    ``M`` is what §C5's loop runs — *"run ``M`` code revisions of ``π``"* —
    and the bar is the width of the maximum over them, so it is a whole
    number of **one or more**: the maximum of no scores is a figure no
    tournament produced, and ``√(2 ln M)`` at ``M = 0`` is the logarithm's
    own refusal rather than this member's.  A ``bool`` is refused where a
    count belongs for the reason every count in this member refuses one.
    One is admitted and answers a bar of zero — see
    :func:`selection_bar`.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise BarRequestError(
            f"a revision count is a whole number — got {value!r} "
            f"({type(value).__name__}); the bar is the width of the maximum "
            "over M revisions (§7.3's null maximum, one level up), and a "
            "value that is not a whole number names no tournament this "
            "verdict can measure"
        )
    if value < 1:
        raise BarRequestError(
            f"a revision count is a whole number of one or more — got "
            f"{value!r}; the expected maximum of no scores is a figure no "
            "tournament produced, and a bar over an M of none would judge a "
            "winner nobody ran. §12.1's ladder caps far above one, and the "
            "one-revision tournament is admitted — it carries no selection "
            "noise to survive"
        )
    return value


def _validated_score_deviation(value: Any) -> float:
    """Check that ``value`` is a positive score deviation, or refuse it.

    The scale the whole bar is measured in — §12.1's ``σ_V``, which is
    §11.0's ``σ_diff`` (both ≈ 0.8 in the documents' own arithmetic) — so it
    is a finite real and **strictly positive**, on the terms
    :func:`dreaming.paired._validated_spread` states for its own figure: a
    deviation of zero is a pool on which every difference is identical, the
    degenerate pool the paired statistic refuses in its own word, and a bar
    of zero would admit every positive advantage as signal on the strength
    of a spread the evidence does not carry.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BarRequestError(
            f"the score deviation a bar is scaled by is a number — got "
            f"{value!r} ({type(value).__name__}); σ_V is the spread the "
            "advantage is measured against (§12.1's σ_V, §11.0's σ_diff), "
            "and a value that is not one names no scale this bar can be "
            "stated in"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise BarRequestError(
            f"the score deviation a bar is scaled by is a finite number — "
            f"got {value!r}; a non-finite scale would answer a bar that is "
            "not a number, and a verdict compared against it would decide "
            "nothing while looking like it decided one"
        )
    if figure <= 0.0:
        raise BarRequestError(
            f"the score deviation a bar is scaled by is strictly positive — "
            f"got {value!r}; a deviation of zero is a pool whose every "
            "difference is identical, and a bar of zero would admit every "
            "positive advantage as signal on the strength of a spread the "
            "evidence does not carry — the degenerate pool the paired "
            "statistic refuses in its own word"
        )
    return figure


def _validated_world_count(value: Any) -> int:
    """Check that ``value`` is a world count, or refuse it as the ask's own.

    The ``n_worlds`` of Appendix B's line — the count the deviation is
    divided by the square root of, ``SE(V) ≈ σ_V/√n_worlds`` — so it is a
    whole number of **one or more**: the standard error over no worlds is a
    division by exactly nothing, and a Python ``ZeroDivisionError`` about
    floats would be the interpreter's vocabulary for a refusal that is this
    member's to state.  A ``bool`` is refused where a count belongs for the
    reason every count in this member refuses one.  This is the comparison's
    own world count — the pair's worlds, not the pool's — so it is not the
    ladder floor's figure and is never judged against it: feature 275's
    floor refuses the *pool* before a cycle runs, and feature 278's holdout
    may legitimately carry fewer worlds than the pool it came from.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise BarRequestError(
            f"the world count a bar is divided by is a whole number — got "
            f"{value!r} ({type(value).__name__}); SE(V) ≈ σ_V/√n_worlds is "
            "the standard error of the mean score, and a value that is not "
            "a count names no worlds this bar can be narrowed by"
        )
    if value < 1:
        raise BarRequestError(
            f"the world count a bar is divided by is a whole number of one "
            f"or more — got {value!r}; a standard error over no worlds is a "
            "division by exactly nothing, and a bar stated over none would "
            "be infinite in every figure but its own"
        )
    return value


def _bar(count: int, deviation: float, worlds: int) -> float:
    """Appendix B's line — the one spelling of the arithmetic.

    ``√(2 ln M) · σ_V / √n_worlds``, over figures the callers have already
    validated, so :func:`selection_bar`, :func:`rejects_unbarred_winner` and
    :func:`cycle_bar` cannot disagree on what the bar is — the same discipline
    :data:`dreaming.paired._Z_ALPHA` states for keeping one module's levels
    from drifting, applied to the one expression this module exists to apply.
    """
    return math.sqrt(2.0 * math.log(count)) * deviation / math.sqrt(worlds)


def selection_bar(m: Any, *, spread: Any, worlds: Any) -> float:
    """Appendix B's meta-level selection bar — the arithmetic itself.

    For ``M`` revisions, a score deviation ``σ_V`` and ``n_worlds`` worlds:

        bar  =  √(2 ln M) · σ_V / √n_worlds

    — the width, in standard errors of the mean score, that a winner's
    advantage must *exceed* before it survives the selection noise of being
    the best of ``M`` (§7.3's null maximum, one level up).  Pure arithmetic
    over figures the caller already holds: no database is opened, no row is
    read, and the figures are never re-derived here — the shape
    :func:`dreaming.cap.revision_cap` takes for its own answer.

    The documents' own figures fall out of it rather than being quoted into
    it: ``selection_bar(40, spread=1.0, worlds=1)`` is ≈ 2.72 — §12.1's
    *"bar ≈ 2.72"* at ``M = 40``, stated in SE units — and the same call at
    ``K`` revisions reproduces §7.3's whole null max-Sharpe table (2.15 at
    10, 3.03 at 100, 3.72 at 1,000, 4.29 at 10,000).  At ``σ_V = 0.8`` and a
    target advantage of 0.3 the bar crosses 0.3 between 52 and 53 worlds,
    which is §12.1's *"n > 53"*.

    ``M = 1`` answers ``0.0`` and is not refused: ``ln 1 = 0``, the expected
    maximum of one null score is that score, and a tournament of one carries
    no selection noise to survive.  The bar grows with ``M`` from there —
    monotonically, which is what makes judging a cycle at its recorded *cap*
    the conservative direction.

    Refuses, in this order, each naming what it is about: an ``m`` that is
    not a whole number of one or more, a ``spread`` that is not a finite
    strictly-positive real, or a ``worlds`` that is not a whole number of
    one or more (:class:`~dreaming.errors.BarRequestError`) — the ask's own
    facts, refused before anything is computed.
    """
    count = _validated_revision_count(m)
    deviation = _validated_score_deviation(spread)
    worlds_count = _validated_world_count(worlds)
    return _bar(count, deviation, worlds_count)


def rejects_unbarred_winner(
    advantage: Any,
    *,
    m: Any,
    spread: Any,
    worlds: Any,
) -> None:
    """Refuse a winner whose advantage does not survive selection noise.

    The one judgment for feature 280's sentence: the winner's advantage and
    the three figures the bar is computed over in, and either the winner
    proceeds or it is refused.  It decides §12.1's inequality —
    *``true_advantage > √(2 ln M) · σ_V / √n_worlds``* — and **raises**
    :class:`~dreaming.errors.SelectionBarError` when the advantage does not
    exceed the bar, so the caller that calls it on its last line is stopped
    before it persists a winner that is indistinguishable from the best of
    ``M`` nulls.  A winner above the bar returns without raising.

    **The edge is strict.**  §12.1 says the advantage survives *"only when"*
    it *exceeds* the bar, so an advantage exactly at it does not clear —
    the same strict edge :meth:`~dreaming.paired.PairedDifference.clears`
    states for the gate's own criterion — and a negative advantage is not
    refused as a malformed ask but by the bar itself: it falls below any bar
    the arithmetic can state, and the refusal that names it is a verdict,
    not a validation.

    The shape is the ladder's other verdicts exactly
    (:func:`dreaming.ladder.rejects_thin_pool`,
    :func:`dreaming.ceiling.rejects_uncapped_sweep`,
    :func:`dreaming.paired.rejects_proportion_comparison`): a verdict over
    figures the caller already holds, which never opens a database.  In the
    loop those figures are the comparison's own — the advantage, the
    deviation and the world count one
    :class:`~dreaming.paired.PairedDifference` carries — and the caller that
    holds the comparison *and* the cycle's record reaches
    :func:`cycle_bar`, which reads ``M`` back and spells this verdict over
    the record's figure.

    Refuses, in this order, each naming what it is about:

    1. an ``advantage`` that is not a finite real, an ``m`` that is not a
       whole number of one or more, a ``spread`` that is not a finite
       strictly-positive real, or a ``worlds`` that is not a whole number of
       one or more — the ask's own facts
       (:class:`~dreaming.errors.BarRequestError`);
    2. an advantage at or below the bar — the one refusal this sentence
       mints (:class:`~dreaming.errors.SelectionBarError`), opening with
       :data:`SELECTION_BAR_CODE`, stating the advantage, the bar and the
       three figures behind it, naming §12.1, and stating the repair:
       *keep the incumbent* — ``V^{m★} ≥ V^0`` holds by selecting it when
       nothing clears, and the winner is not persisted.
    """
    lead = _validated_advantage(advantage)
    count = _validated_revision_count(m)
    deviation = _validated_score_deviation(spread)
    worlds_count = _validated_world_count(worlds)
    bar = _bar(count, deviation, worlds_count)
    if lead <= bar:
        raise SelectionBarError(
            f"{SELECTION_BAR_CODE}: a winning revision's advantage of "
            f"{lead!r} does not survive the selection noise of its own "
            f"tournament — Appendix B's meta-level bar is sqrt(2 ln M) . "
            f"sigma_V / sqrt(n_worlds) = {bar!r} at M = {count}, a score "
            f"deviation of {deviation!r} and {worlds_count} world(s), and "
            "docs/alpha-engine-prd.md §12.1 states the winner survives only "
            "when its advantage exceeds that bar. The expected maximum of M "
            "scores carrying no advantage at all is sqrt(2 ln M) standard "
            "errors (§7.3's null max-Sharpe bar, the same multiple-testing "
            "problem one level up), so a winner at or below the bar is "
            "indistinguishable from the best of M nulls — \"the dreaming "
            "loop overfits its own replay pool\". Keep the incumbent: with "
            "it in the candidate set (feature 273) V^m* >= V^0 holds by "
            "selecting it when nothing clears, and a winner below the bar "
            "is not persisted"
        )


def _validated_iteration(value: Any) -> str:
    """The member's one iteration-id rule, translated into the bar's word.

    :func:`dreaming.cycle.validated_iteration_id` is the one spelling of
    what names a dreaming iteration — an id is text and not blank — and this
    module reuses it rather than restating the rule, translating its refusal
    at the seam: a caller judging a winner that handed a bad id must not
    meet feature 270's request class for an act that held nothing, the seam
    discipline the workspace states for error vocabularies and this member
    applies at every one of its own.
    """
    try:
        return validated_iteration_id(value)
    except FreezeRequestError as refusal:
        raise BarRequestError(
            f"a dreaming iteration is named by a non-empty string — got "
            f"{value!r} ({type(value).__name__}); the bar reads the cycle's "
            "recorded M back by its iteration id, and a name that names no "
            "cycle reads no record"
        ) from refusal


def _validated_difference(value: Any) -> PairedDifference:
    """Check that ``value`` is a taken comparison, or refuse it.

    The advantage, the deviation and the world count the bar is computed
    over are the three figures one :class:`~dreaming.paired.PairedDifference`
    already carries — §12.1's ``σ_V`` is §11.0's ``σ_diff``, and the section
    that states the bar is the section whose ``n > 53`` independently
    reproduces §11.0's ``~56`` — so the store seam takes the comparison
    whole rather than three loose numbers that could come from three
    different measurements.  The record's figures are still validated at
    this module's own seam before the store is read, because a record is a
    value any caller can construct and the ask's own facts are refused
    before anything is opened.
    """
    if not isinstance(value, PairedDifference):
        raise BarRequestError(
            f"the advantage a cycle's winner is judged on is carried by a "
            f"PairedDifference — got {value!r} ({type(value).__name__}); "
            "§12.1's advantage, σ_V and n_worlds are the mean difference, "
            "the spread and the paired world count of one comparison "
            "(feature 281's), and three loose figures could come from three "
            "different measurements. Compare the arms first with "
            "dreaming.paired.paired_ir_difference, or judge loose figures "
            "with dreaming.bar.rejects_unbarred_winner"
        )
    return value


def cycle_bar(
    iteration_id: Any,
    difference: Any,
    *,
    database_url: str | None = None,
    env: Mapping[str, str] | None = None,
) -> float:
    """Judge a cycle's winner at the bar its recorded ``M`` sets.

    The store seam of feature 280's sentence, and the half the cap's record
    exists for: resolve the database the deployment names (an explicit URL
    first, then ``DATABASE_URL``, refused when neither names one), read the
    cycle's revision cap back from feature 277's ``cycle_cap`` history, and
    judge the winner's :class:`~dreaming.paired.PairedDifference` at the bar
    that cap sets — :func:`rejects_unbarred_winner`'s one verdict, spelled
    over the record's ``M`` and the comparison's own advantage, deviation
    and world count.  Returns the bar the winner cleared, so the caller that
    persists a winner (feature 274's ``policy_revision``) can carry beside
    it *what* it cleared — the same figure :func:`selection_bar` answers
    over the same figures, recomputed rather than cached so the verdict and
    the answer cannot disagree.

    **The record in force is the newest one naming the iteration.**  A
    retried cycle is re-decided over the pool as it stands — feature 277's
    own law, one row per occurrence — so the ``M`` a winner is judged at is
    the last cap recorded for its cycle: the decision that was in force when
    the sweep ran.  Judging at the recorded cap rather than a hand-counted
    actual is the conservative direction, because the bar grows with ``M``:
    a cycle that ran fewer revisions than its cap is judged against a bar at
    least as wide as the one its sweep earned, and this seam cannot
    under-state the multiple-testing width.

    Refuses, in this order, each naming what it is about:

    1. an ``iteration_id`` that is not non-empty text, a ``difference`` that
       is not a :class:`~dreaming.paired.PairedDifference`, or figures
       inside the comparison that are not a finite advantage, a strictly
       positive deviation and a world count of one or more — the ask's own
       facts, refused before anything is read
       (:class:`~dreaming.errors.BarRequestError`);
    2. no database named, or a URL this member cannot speak
       (:class:`~dreaming.errors.BarRequestError`, translated at the seam
       from the cap's own request class — the caller asked for a bar, and
       must not be told the cap could not be *recorded*);
    3. a database that holds no pool
       (:class:`~dreaming.errors.BarRecordError`, translated at the seam —
       a store without the pool holds no dreaming cycles, and so no caps to
       read);
    4. no recorded cap naming the iteration — the *"a bar computed over an
       ``M`` nobody recorded is a bar over a number nobody ran"* refusal
       (:class:`~dreaming.errors.BarRecordError`): record the cycle's cap
       (feature 277's :func:`~dreaming.cap.record_cycle_cap`) before judging
       its winner;
    5. an advantage at or below the bar — :func:`rejects_unbarred_winner`'s
       own refusal, in its own word
       (:class:`~dreaming.errors.SelectionBarError`), spelling the verdict
       over the record's ``M``.

    Reads ``cycle_cap`` and writes nothing — no row, no table, no column —
    so a bar taken under feature 270's hold is permitted because it is a
    read.
    """
    iteration = _validated_iteration(iteration_id)
    compared = _validated_difference(difference)
    lead = _validated_advantage(compared.mean_difference)
    deviation = _validated_score_deviation(compared.spread)
    worlds = _validated_world_count(compared.paired_worlds)
    try:
        records = cycle_caps(database_url=database_url, env=env)
    except CapRequestError as refusal:
        raise BarRequestError(
            f"judging a cycle's winner needs the database its revision cap "
            f"is recorded in — pass it explicitly or set {DATABASE_URL_ENV}. "
            "Appendix B's bar reads M back from feature 277's record "
            "(dreaming.cap), and without the store there is no M to read: "
            "the figures the caller holds name an advantage, not the sweep "
            "that won it. See the refusal the record's own seam raised: "
            f"{refusal}"
        ) from refusal
    except CapRecordError as refusal:
        raise BarRecordError(
            f"the bar reads M back from a database that holds no replay "
            f"pool — see the refusal the record's own seam raised: "
            f"{refusal}. A store without the pool holds no dreaming cycles "
            "and so no caps to read, and a bar computed over an M nobody "
            f"recorded is a bar over a number nobody ran. Point "
            f"{DATABASE_URL_ENV} at the database the replay pool lives in, "
            "or migrate it"
        ) from refusal
    occurrences = [
        record for record in records if record.iteration_id == iteration
    ]
    if not occurrences:
        raise BarRecordError(
            f"the dreaming iteration {iteration!r} has no recorded revision "
            "cap, so there is no M to set this winner's bar — Appendix B's "
            "selection bar reads M back from feature 277's record "
            "(dreaming.cap), and a bar computed over an M nobody recorded "
            "is a bar over a number nobody ran. Record the cycle's cap "
            "before judging its winner (dreaming.record_cycle_cap), or "
            "judge loose figures with dreaming.bar.rejects_unbarred_winner"
        )
    # ``cycle_caps`` answers oldest-first, so the newest occurrence — the
    # re-decision in force when the sweep ran — is the last row naming the
    # iteration.
    in_force = occurrences[-1]
    rejects_unbarred_winner(
        lead,
        m=in_force.revision_cap,
        spread=deviation,
        worlds=worlds,
    )
    return selection_bar(
        in_force.revision_cap,
        spread=deviation,
        worlds=worlds,
    )
