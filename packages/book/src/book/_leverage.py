"""The leverage cap — feature 308: one quarter of the book's Kelly fraction.

app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects a
leverage target above one quarter of the Kelly fraction implied by the book
Sharpe and volatility.*  docs/alpha-engine-prd.md states both figures the
sentence is built from.  Appendix B's reference-formula table — the same table
that carries §7.3's null max-Sharpe bar and the meta-level selection bar —
states the fraction:

    Kelly fraction, Sharpe S, vol σ          f* = S/σ   (use ≤ ¼ Kelly)

so the sentence's two inputs are the table's two inputs (the book's Sharpe
``S`` and its volatility ``σ``), the fraction it names is the table's
``f* = S/σ``, and the quarter it bounds a target by is the parenthetical's own
*"use ≤ ¼ Kelly"*.  §C8 puts the rule where the category's features do —
*"Signal book → IR-weighted combination with shrinkage → volatility targeting
→ position and concentration limits → orders.  Version-controlled,
human-authored, explicitly outside the search space."* — and §1's non-goals
line (*"No position sizing, no stop-loss, no entry timing, no leverage.  Those
live downstream."*) is the same division from the other side: the research
loop never sizes a position, and this member is where sizing is bounded.

This module applies Appendix B's line verbatim, in three spellings of one act:

* :func:`kelly_fraction` — the arithmetic itself: the book's Sharpe and
  volatility in, ``f* = S/σ`` out.  The shape
  :func:`dreaming.bar.selection_bar` takes for its own figure — a pure
  function over figures the caller already holds, which never opens a
  database, because the figures are the *caller's* to supply and a member
  never re-derives a measurement it was handed;
* :func:`leverage_cap` — the sentence's *one quarter of* that fraction, and
  the figure a target is judged against;
* :func:`rejects_overleveraged_target` — the **rejects** of the sentence, the
  verdict shape the workspace's other refusals-of-a-figure take
  (:func:`dreaming.ceiling.rejects_uncapped_sweep`,
  :func:`dreaming.bar.rejects_unbarred_winner`): it **raises** when the target
  sits above the cap, so a caller that calls it on its last line is stopped
  before it hands an over-bet book to the order layer.

**Why the quarter is there, and why it is not a knob.**  The fraction is
estimated from a Sharpe, and §1.2 states exactly what a Sharpe measured on
history is worth: *"A backtest Sharpe of 4.0 is a noisy, biased,
adversarially exploitable estimate.  Port Dream-RSI naively and the cheapness
of replay becomes a liability"* — the estimate is a measurement with error, so
betting the full ``f*`` bets the point estimate as though it were the truth,
and the errors of a maximum-selected figure are one-sided.  The quarter is the
document's own discount against that error, which is why it is a **constant of
this module rather than a parameter of it**: :data:`KELLY_FRACTION` is
Appendix B's *"use ≤ ¼ Kelly"* spelled once, and neither the arithmetic nor the
verdict accepts another.  The contrast is feature 303's, one feature over:
*"weights scaled to a configured annualized volatility"* is a deployment's
figure and arrives as a parameter; the quarter is the document's figure and
arrives as nothing.  The cap is also a **ceiling, not a target** — it never
raises what the caller asked for, only refuses what sits above it, so a
deployment that chooses to run at half-Kelly is admitted at every figure this
module answers.

**The fraction is the table's line, applied, not a formula re-derived.**  The
continuous-Kelly literature writes a single asset's optimal exposure as
``μ/σ²``; Appendix B writes ``S/σ``, and the difference is not this module's
to settle: a feature that "implies the Kelly fraction from the book Sharpe and
volatility" means the table's two named inputs and the table's one expression
over them.  So ``f*`` is ``S/σ`` to the bit, and a caller that reaches for the
other spelling reaches for a different document.

**Non-positive Sharpe is answered, not refused — and that is this member's
301 stance read on a different figure.**  Feature 301 refuses a non-positive
*information ratio* because a signal's *standing to weight the book* is
undefined without one (absence is not zero).  A book's *Sharpe* is not a
standing but a measurement, and a losing book's measured Sharpe is negative —
well defined, and the honest reading of it is not an error: the Kelly fraction
is negative, so :func:`leverage_cap` answers a cap at or below zero, and
:func:`rejects_overleveraged_target` then refuses every target **above the
flat book** — i.e. every long leverage — naming the negative cap and the
Sharpe behind it.  The answer a caller gets is "a long position on this book
is not admissible", which is the sentence's own outcome; an error would hide
the book's figure behind the refusal and leave the caller unable to tell *no
long leverage is admissible* from *your ask was malformed*.

**The admissible set is the cap intersected with the target's own domain.**
A leverage target is a **gross exposure of zero or more** (a negative one is
a position's direction, refused as the ask's own fact), so the set
:func:`rejects_overleveraged_target` admits is ``0 ≤ target ≤ cap`` — and on a
cap at or below zero that set is the single point ``0``.  Holding the book
*flat* is therefore admitted even on a book whose measured edge is negative,
which is the honest reading: a trader who does not like a book holds nothing,
and refusing the flat book as "above the cap" would be an arithmetic that read
the sentence's *above* without reading the domain the target lives in.  The
refusal states the repair that is actually available in each case — lower the
target, for a positive cap; hold the book flat, for a non-positive one — and
:func:`_overshoot` is where the two spellings live.

**The edge is the word "above", and it is strict.**  The sentence rejects a
target *above* one quarter Kelly, so a target exactly at the cap is admitted
and one float over it is refused — the same inclusive-on-the-admitted-side
edge :func:`dreaming.ceiling.rejects_uncapped_sweep` states for the band's
ceiling (*"``ceiling`` itself runs, ``ceiling + 1`` does not"*), and the
opposite reading to the strict *"only when"* edge feature 280 enforces on its
own verdict, because the two sentences say different words: "below the bar",
"above the cap".  The strictness is not decoration — the cap is a budget, and
spending it exactly is spending within it.

**Two refusal classes, because the repairs differ.**  The ask's own facts — a
Sharpe that is not a finite real, a volatility that is not a finite
*strictly positive* real (a zero volatility makes ``S/σ`` a division by
exactly nothing, and a negative one is a scale that is not a measurement), a
target that is not a finite real of zero or more (a leverage is a gross
exposure; a negative one is a direction, not a leverage) — are refused with
:class:`~book.errors.LeverageRequestError` *before anything is computed*, the
ordering every store and verdict in this workspace states.  The one judgment
the sentence mints — a well-formed target above a well-formed cap — is refused
with :class:`~book.errors.LeverageTargetError`, opening with
:data:`OVERLEVERAGE_CODE` and naming the target, the cap, the fraction, the
Sharpe and the volatility.  Both are subclasses of feature 301's
:class:`~book.errors.BookConstructionError`, so the caller that already
refuses the whole book surface with a single ``except`` goes on doing exactly
that, and a caller that must react differently to *your book may not carry
that leverage* and *your ask named no figure* can still tell them apart.

**What this module does not do.**  It applies no leverage, sizes no position,
persists no target and reads no store — feature 304's per-position and
concentration limits are the bound on the *size* of a position and this cap is
the bound on the *book's* exposure, and neither subsumes the other; feature
305's final target weights are what the order layer consumes.  It shrinks no
covariance (302's), chooses no volatility target (303's), re-opens no
information-ratio weight (301's) and measures neither of its own two inputs:
the Sharpe and the volatility arrive as figures, because a verdict is a
judgment over figures the caller already holds and the measurement of a book's
Sharpe is the evaluator's business, not this module's.

**No new component, and the layering note.**  Feature 301's single ``book``
component is the member's whole composition — the cap is reached the way
feature 276's ceiling is reached beside feature 270's freeze, as a free
function in its own module, and the composed ``book`` component goes on
answering exactly one question, *what is the composed book combiner?*  No
table, no endpoint, no migration, no new component, and no third-party import:
``math`` and the member's own ``.errors``, so the factory's scan — which
imports this package to fire its ``@register`` — pays nothing for the cap and
the replay path stays import-cheap.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import LeverageRequestError, LeverageTargetError

__all__ = [
    "KELLY_FRACTION",
    "OVERLEVERAGE_CODE",
    "kelly_fraction",
    "leverage_cap",
    "rejects_overleveraged_target",
]

#: Appendix B's *"use ≤ ¼ Kelly"* — the fraction of the Kelly fraction a
#: leverage target may reach.  Spelled as a binary-exact literal (a quarter is
#: exactly representable), so the cap is ``S/σ`` scaled by a factor no rounding
#: touches and the arithmetic is checkable with ``==``.  A constant of this
#: module rather than a parameter of it, for the reason the module docstring
#: gives: it is the document's stated discount against a Sharpe the document
#: itself calls a noisy estimate, not a deployment's preference — the knob
#: one feature over is feature 303's configured volatility target.
KELLY_FRACTION = 0.25

#: The code an *over-leveraged* refusal opens with — the target sits above one
#: quarter of the book's Kelly fraction — so the rejection is greppable by the
#: word that names it.  Feature 308's sentence mandates no token (it names its
#: subject in prose), so the code is this module's own, minted on the
#: ``pool_too_thin`` / ``advantage_below_bar`` / ``not_regime_diverse``
#: convention the workspace states for the one refusal an operator greps a
#: deployment log for: *why was this leverage target refused?*  The ask's own
#: facts carry no code, for the reason
#: :class:`~book.errors.LeverageRequestError` gives — a malformed ask names its
#: subject in its first words, and a token there would hand a reader a
#: developer's word for a fact they can simply fix.
OVERLEVERAGE_CODE = "leverage_above_quarter_kelly"


def _validated_sharpe(value: Any) -> float:
    """Check that ``value`` is a finite real Sharpe, or refuse it.

    Appendix B's ``S`` — the book's Sharpe, the numerator of the fraction the
    sentence is built on.  A finite real: a ``bool`` is refused where a figure
    belongs because ``True`` is ``1`` in Python and a flag where a Sharpe
    belongs would read as a full unit of risk-adjusted return, and ``nan`` /
    ``±inf`` are refused because they are not readings — a ``nan`` Sharpe
    answers a ``nan`` fraction, which is neither below nor above any cap, and
    a verdict compared against it would decide nothing while looking like it
    had decided.

    **A non-positive Sharpe is admitted**, and deliberately: see the module
    docstring.  It is a measurement a book can carry (a losing book), not a
    standing that needs to be positive to mean anything — the refusal
    :func:`book._combine.combine` applies to a non-positive *information
    ratio* is about a signal's standing to weight the book, which is a
    different fact about a different figure.  The answer to a non-positive
    Sharpe is a fraction at or below zero, and it is returned rather than
    withheld.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LeverageRequestError(
            f"a book's Sharpe is a number — got {value!r} "
            f"({type(value).__name__}); the leverage cap is one quarter of "
            "the Kelly fraction f* = S/sigma implied by the book's Sharpe and "
            "volatility (docs/alpha-engine-prd.md Appendix B), and a value "
            "that is not one names no Sharpe this cap can be computed from"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise LeverageRequestError(
            f"a book's Sharpe is a finite number — got {value!r}; a "
            "non-finite numerator answers a non-finite cap, and a leverage "
            "target compared against a cap that is not a number is neither "
            "above it nor below it — a verdict that decided nothing while "
            "looking like it decided one. Note that a *negative* Sharpe is "
            "admitted: a losing book's Kelly fraction is negative, and the "
            "cap that follows honestly admits no positive leverage"
        )
    return figure


def _validated_volatility(value: Any) -> float:
    """Check that ``value`` is a finite, strictly positive volatility.

    Appendix B's ``σ`` — the denominator of ``f* = S/σ``.  Strictly positive
    on the terms :func:`dreaming.bar._validated_score_deviation` states for
    its own scale, and for the sharper reason here: a volatility of zero makes
    the fraction a division by exactly nothing, so a book with no volatility
    has no Kelly fraction at all — the ratio is undefined, not infinite, and
    an infinite cap would admit every target as signal on the strength of a
    scale the evidence does not carry.  A negative volatility is a scale that
    is not a measurement: it would flip the sign of the fraction and turn a
    losing book's cap positive.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LeverageRequestError(
            f"a book's volatility is a number — got {value!r} "
            f"({type(value).__name__}); f* = S/sigma divides the book's "
            "Sharpe by its volatility, and a value that is not one names no "
            "scale this fraction can be stated in"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise LeverageRequestError(
            f"a book's volatility is a finite number — got {value!r}; a "
            "non-finite scale answers a fraction that is not a number, and a "
            "leverage target compared against a cap that is not a number is "
            "neither above it nor below it"
        )
    if figure <= 0.0:
        raise LeverageRequestError(
            f"a book's volatility is strictly positive — got {value!r}; a "
            "volatility of zero leaves f* = S/sigma a division by exactly "
            "nothing, so a book with no volatility has no Kelly fraction at "
            "all rather than an infinite one, and a negative volatility is a "
            "scale that is not a measurement — it would turn a losing book's "
            "cap positive"
        )
    return figure


def _validated_target(value: Any) -> float:
    """Check that ``value`` is a leverage target, or refuse it as the ask's own.

    The figure the sentence judges: a finite real **of zero or more**.  Zero
    is admitted and is the honest floor — a book held at no leverage is not
    above any cap this module can answer, except a negative one (a losing
    book's, whose refusal names the Sharpe behind it).  A *negative* target is
    refused because a leverage is a gross exposure and a negative one is a
    direction instead: ``-2`` would sit below a negative cap and be admitted
    by an arithmetic that read it as leverage, when what the caller meant was
    a short position, which this module does not size.  A ``bool`` and a
    non-finite real are refused for the reasons the other two validators give.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LeverageRequestError(
            f"a leverage target is a number — got {value!r} "
            f"({type(value).__name__}); the target is the multiple of the "
            "book the caller means to hold, and a value that is not one is "
            "not a leverage this cap can judge"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise LeverageRequestError(
            f"a leverage target is a finite number — got {value!r}; a "
            "non-finite target is neither above nor below the cap, and a "
            "verdict on it would decide nothing while looking like it "
            "decided one"
        )
    if figure < 0.0:
        raise LeverageRequestError(
            f"a leverage target is zero or more — got {value!r}; a leverage "
            "is a gross exposure, and a negative one is a position's "
            "direction rather than its size. A short book is not this "
            "module's to size: hand the target the book is held at, and let "
            "the order layer carry the direction"
        )
    return figure


def _fraction(sharpe: float, volatility: float) -> float:
    """Appendix B's line — the one spelling of ``f* = S/σ``.

    Over figures the callers have already validated, so :func:`kelly_fraction`,
    :func:`leverage_cap` and :func:`rejects_overleveraged_target` cannot
    disagree about what the fraction is — the discipline
    :func:`dreaming.bar._bar` states for keeping one module's arithmetic from
    drifting, applied to the one expression this module exists to apply.
    """
    return sharpe / volatility


def _cap(sharpe: float, volatility: float) -> float:
    """The sentence's *one quarter of* that fraction — spelled once.

    ``f* · KELLY_FRACTION``, and it is deliberately the *fraction scaled*
    rather than a second division (``S / (4σ)``): the cap the arithmetic
    answers and the cap the verdict judges are one expression, so no caller
    can be refused by a figure a hair different from the one it was shown.
    """
    return _fraction(sharpe, volatility) * KELLY_FRACTION


def kelly_fraction(sharpe: Any, *, volatility: Any) -> float:
    """The book's Kelly fraction, ``f* = S/σ`` — Appendix B's line.

    The figure feature 308's sentence takes one quarter of: the book's Sharpe
    ``S`` over its volatility ``σ``, exactly as docs/alpha-engine-prd.md
    Appendix B's reference table states it (*"Kelly fraction, Sharpe S, vol σ
    → f* = S/σ"*).  Pure arithmetic over figures the caller already holds — no
    database is opened, no row is read, and neither figure is re-derived here:
    the shape :func:`dreaming.bar.selection_bar` takes for its own answer, for
    the same reason (a verdict is not a measurement, and the measurement is
    the caller's to supply).

    The two figures are the **book's** — the Sharpe and volatility measured on
    the composite feature 301 answers — and they arrive as numbers because a
    member never re-derives a figure it was handed: the measurement of a
    book's Sharpe is the evaluator's business, and this module's whole subject
    is the one quarter of the fraction that follows from it.

    Answers a **negative** fraction when the Sharpe is negative, and answers
    rather than refuses, for the reason the module docstring gives: a losing
    book's Kelly fraction is a measured fact, and the cap that follows from it
    is the honest *no positive leverage is admissible*, not an error.

    Refuses, in this order, each naming what it is about: a ``sharpe`` that is
    not a finite real, and a ``volatility`` that is not a finite strictly
    positive real (:class:`~book.errors.LeverageRequestError`).  Both are the
    ask's own facts, refused before any fraction is formed.
    """
    lead = _validated_sharpe(sharpe)
    scale = _validated_volatility(volatility)
    return _fraction(lead, scale)


def leverage_cap(sharpe: Any, *, volatility: Any) -> float:
    """One quarter of the book's Kelly fraction — feature 308's cap.

    The figure the sentence's *rejects* turns on: ``f* · ¼``, computed from
    Appendix B's ``f* = S/σ`` and :data:`KELLY_FRACTION`, which is the table's
    own *"use ≤ ¼ Kelly"* spelled once.  It is the largest leverage target the
    book may be held at, and it is a **ceiling rather than a target**: it
    never raises what a caller asked for, only refuses what sits above it.

    The quarter is not a parameter, and that is the sentence's own design
    rather than a simplification: the discount exists because a Sharpe
    measured on history is a noisy estimate (§1.2's *"A backtest Sharpe of 4.0
    is a noisy, biased, adversarially exploitable estimate"*), the document
    states the discount at a quarter, and a cap a deployment could set
    anywhere would be a cap that had stopped being the document's rule.  A
    deployment that wants less leverage than the cap simply asks for less —
    anything at or below this figure is admitted.

    Answers a value at or below zero for a non-positive Sharpe, and answers
    rather than refuses: the figure is a measurement's consequence, and
    :func:`rejects_overleveraged_target` is where the consequence becomes a
    verdict.

    Refuses what :func:`kelly_fraction` refuses, in the same order, with the
    same class: the ask's own facts, before anything is computed.
    """
    lead = _validated_sharpe(sharpe)
    scale = _validated_volatility(volatility)
    return _cap(lead, scale)


def _overshoot(
    held: float, sharpe: float, volatility: float, fraction: float, cap: float
) -> str:
    """The refusal's own sentence — the figures, and the repair that is real.

    Spelled once so :func:`rejects_overleveraged_target` raises one message,
    and every branch of it states the same figures the same way.  The two
    branches are the two *repairs*, and only one of them is achievable as a
    non-zero book: a positive cap is lowered to, while a non-positive cap —
    a book whose measured Sharpe is itself non-positive, so its Kelly
    fraction is not positive either — leaves nothing above zero to lower to,
    and the caller's only admissible target on it is flat.  A message
    prescribing "lower the target to the cap" there would be telling the
    caller to hold the book short, which is a position this module does not
    size (a negative leverage is refused as the ask's own fact).

    * ``cap > 0`` — *lower the target to one quarter Kelly or below*, which
      is feature 308's *"above one quarter"* read as the budget it is.
    * ``cap <= 0`` — *hold the book flat, and re-ask once the measured Sharpe
      is positive*.  That is the true statement about the admissible set, not
      the module editorialising: ``f* = S/σ`` at a non-positive ``S`` says
      the book's measured edge does not support a long position, so the
      intersection with leverage zero-and-up is the single point zero.  The
      message names the Sharpe, so the caller can tell *this book's measured
      edge is the problem* from *my ask was malformed* — the distinction the
      two classes exist to keep.
    """
    prefix = (
        f"{OVERLEVERAGE_CODE}: a leverage target of {held!r} is above one "
        f"quarter of the book's Kelly fraction — Appendix B's cap is "
        f"f* . 1/4 = ({sharpe!r} / {volatility!r}) * {KELLY_FRACTION!r} = "
        f"{cap!r} at a book Sharpe of {sharpe!r} and a book volatility of "
        f"{volatility!r}, where f* = {fraction!r} and "
        "docs/alpha-engine-prd.md Appendix B states the rule as \"Kelly "
        "fraction, Sharpe S, vol sigma  ->  f* = S/sigma  (use <= 1/4 "
        "Kelly)\". The fraction is estimated from a Sharpe the document "
        "itself calls a noisy estimate (\"A backtest Sharpe of 4.0 is a "
        "noisy, biased, adversarially exploitable estimate\" — PRD §1.2), so "
        "betting the full f* bets a point estimate as though it were the "
        "truth, and the quarter is the document's own discount against that "
        "error. "
    )
    if cap > 0.0:
        return (
            prefix + "Lower the target to one quarter Kelly or below; the cap "
            "is a ceiling and never raises what the caller asked for, so any "
            "figure at or under it is admitted"
        )
    return (
        prefix + f"The cap is {cap!r} — not positive — because the book's own "
        f"measured Sharpe of {sharpe!r} is not positive, so f* = S/sigma "
        "says the book's measured edge does not support a long position and "
        "one quarter of it says so a quarter as loudly. A leverage target is "
        "a gross exposure of zero or more, so the only target at or below "
        "this cap is flat: hold the book at no leverage, and re-ask once its "
        "measured Sharpe is positive. A target the caller means to hold is "
        "what is refused here — a malformed ask is refused as a "
        "LeverageRequestError before this verdict is reached"
    )


def rejects_overleveraged_target(
    target: Any,
    *,
    sharpe: Any,
    volatility: Any,
) -> None:
    """Refuse an over-bet book — feature 308's call.

    The one judgment for feature 308's sentence: the leverage target the
    caller means to hold and the book's two figures in, and either the book
    proceeds or it is refused.  It computes the cap
    (:func:`leverage_cap`) and **raises**
    :class:`~book.errors.LeverageTargetError` when the target sits above it,
    so a caller that calls it on its last line is stopped before it hands an
    over-bet book to the order layer.  A target at or below the cap returns
    without raising.

    **The edge is the sentence's own word, and it is strict.**  Feature 308
    rejects a target *above* one quarter Kelly, so a target exactly at the cap
    is admitted — Appendix B's *"use ≤ ¼ Kelly"* is inclusive on the admitted
    side, and the cap is a budget: spending it exactly is spending within it.
    One float above is refused.  This is the edge
    :func:`dreaming.ceiling.rejects_uncapped_sweep` states for its own band
    (*"``ceiling`` itself runs, ``ceiling + 1`` does not"*), and it is
    deliberately *not* the strict-inequality edge feature 280 enforces on the
    selection bar, because the two sentences say different words ("below the
    bar" against "above the cap") and a module that copied one edge onto the
    other's words would refuse a book that is exactly at the document's own
    bound.

    The shape is the workspace's other verdicts exactly
    (:func:`dreaming.ceiling.rejects_uncapped_sweep`,
    :func:`dreaming.bar.rejects_unbarred_winner`,
    :func:`dreaming.ladder.rejects_thin_pool`): a judgment over figures the
    caller already holds, which never opens a database, never counts anything
    and never re-measures either figure.  A judge that measured the book's
    Sharpe itself would be answering a question about the evaluator from
    inside a verdict.

    Refuses, in this order, each naming what it is about:

    1. a ``target`` that is not a finite real of zero or more, a ``sharpe``
       that is not a finite real, or a ``volatility`` that is not a finite
       strictly positive real — the ask's own facts, refused before anything
       is judged (:class:`~book.errors.LeverageRequestError`);
    2. a target above the cap — the one refusal this sentence mints
       (:class:`~book.errors.LeverageTargetError`), opening with
       :data:`OVERLEVERAGE_CODE`, stating the target, the cap, the fraction
       and the two figures behind it, naming Appendix B and the sentence's
       *"use ≤ ¼ Kelly"*, and stating the repair.  A target at the cap, and
       any target below it, is not refused.

    **The repair has two spellings, and the message picks the achievable
    one.**  A positive cap is lowered to (*lower the target to one quarter
    Kelly or below*).  A cap at or below zero — a book whose measured Sharpe
    is itself non-positive, so ``f* = S/σ`` is not positive either — leaves
    nothing above zero to lower to, and the message says the true thing
    instead: *hold the book flat, and re-ask once the measured Sharpe is
    positive*, naming the Sharpe that put the cap there.  That is not the
    module editorialising.  The admissible set is the target's own domain
    (a gross exposure of zero or more) intersected with the cap, so on a
    non-positive cap it is the single point ``0``: the flat book is admitted
    and every long leverage refused, and the message must let the caller tell
    *this book's measured edge is the problem* from *my ask was malformed* —
    the distinction the two classes exist to keep.
    """
    held = _validated_target(target)
    lead = _validated_sharpe(sharpe)
    scale = _validated_volatility(volatility)
    fraction = _fraction(lead, scale)
    cap = _cap(lead, scale)
    # The admissible set is the target's own domain — zero or more, a
    # leverage being a gross exposure — intersected with "at or below the
    # cap".  On a positive cap the intersection is just the cap and the bound
    # below is a no-op; on a non-positive one (a book whose measured Sharpe
    # is itself non-positive) the cap lies below the domain's floor, the
    # intersection is the single point 0, and holding the book *flat* is
    # admitted while any long leverage is refused.  Refusing 0 there as
    # "above the cap" would be an arithmetic that read the sentence's
    # *"above"* without reading the domain it is stated over — and would tell
    # a caller its flat book was over-bet.
    if held > max(cap, 0.0):
        raise LeverageTargetError(_overshoot(held, lead, scale, fraction, cap))
