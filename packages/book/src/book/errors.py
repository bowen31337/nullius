"""The book combiner's refusal vocabulary — features 301 and 308.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  A combine can fail only because the
promoted signals it was handed cannot be weighted into a book, and this
module is the one place those failures are named.

app_spec.xml, feature 308 — this category's second sentence — is the sibling:
*System rejects a leverage target above one quarter of the Kelly fraction
implied by the book Sharpe and volatility.*  Its refusals live here beside
301's, for the reason 301's own docstring states this module exists at all:
one base class, so a caller can refuse the whole book surface with a single
``except``.  The two sentences' failures are different facts about different
figures — a *signal* that cannot be weighted (301) and a *leverage target*
the resulting book may not carry (308) — so the cap's classes are **named
siblings under :class:`BookConstructionError`** rather than additions to it:
a caller that must react differently to *your signals cannot be combined* and
*this book may not carry that leverage* distinguishes them by class, while a
caller that refuses book work wholesale goes on catching the one base — the
one-base-per-member shape the dreaming and regime members state for their own
vocabularies.

One base class, :class:`BookConstructionError`, so a caller — the order
layer, a seat, a test — can refuse the whole refusal surface with a single
``except``.  Every message opens with a greppable one-word code (the
``pool_frozen`` / ``unwalkable_tree`` precedent), so an operator greps one
word for the refusal; and every message names the signal (by ``signal_id``)
and, where a symbol is at issue, the symbol, so the refusal is actionable
without a stack trace.

The codes are the vocabulary of the act, and each names *what the caller
must do about it*:

* ``empty_book`` — no signals were handed, so there is nothing to weight;
* ``unnamed_signal`` — a signal carries no ``signal_id`` to attribute a
  weight to;
* ``duplicate_signal`` — two signals share a ``signal_id``;
* ``non_positive_ir`` — a signal's information ratio is zero or negative,
  so its standing to weight the book is undefined (refused, not
  zero-weighted, because silently dropping a losing signal would hide a
  portfolio decision);
* ``non_finite_ir`` — a signal's information ratio is NaN or ±inf;
* ``signal_without_scores`` — a signal carries no target scores;
* ``non_finite_score`` — a signal's score for a symbol is NaN or ±inf;
* ``uncovered_symbol`` — a signal carries no score for a symbol the book
  covers (refused, not zero-filled — absence is not a view).

The combiner raises these before it forms any composite, so a refused
combine leaves no value behind.

The leverage cap adds one code, and it is the only one an operator greps a
deployment log for on feature 308's path:

* ``leverage_above_quarter_kelly`` — the leverage target a caller means to
  hold sits above one quarter of the book's Kelly fraction: a long position
  on a book whose edge does not fund it (refused rather than scaled down,
  because lowering a target the caller asked for would be this member
  *sizing* a position, and sizing is the order layer's act rather than a
  bound's).

The cap's two faces are the pair of classes below — the ask's own facts
(:class:`LeverageRequestError`, no code, because a malformed ask names its
subject in its first words) and the one judgment the sentence mints
(:class:`LeverageTargetError`, carrying the code above).  Both are subclasses
of the base, so the caller that refuses the whole book surface still writes
one ``except``; and because they are *siblings of* rather than *aliases for*
:class:`BookConstructionError`, the caller that has to react differently to
*this book may not carry that leverage* and *your signals cannot be combined*
can still tell them apart — a leverage target is refusable for a book whose
signals weighted up perfectly, so the two facts are genuinely different and a
vocabulary that merged them would make a caller re-inspect something it
cannot tell apart.
"""

from __future__ import annotations

__all__ = [
    "BookConstructionError",
    "LeverageRequestError",
    "LeverageTargetError",
]


class BookConstructionError(Exception):
    """The book member's base refusal — a signal could not be weighted into a
    book, or a leverage target the resulting book may not carry.

    Raised directly by :func:`book.combine` (and by the construction of a
    :class:`book.PromotedSignal` or :class:`book.CompositeBook` that the
    combiner would not itself produce) when the promoted signals cannot be
    weighted into a composite.  Every message opens with a greppable
    one-word code — ``empty_book``, ``unnamed_signal``, ``duplicate_signal``,
    ``non_positive_ir``, ``non_finite_ir``, ``signal_without_scores``,
    ``non_finite_score`` or ``uncovered_symbol`` — and names the signal and,
    where relevant, the symbol.

    It is also the **base of the member's whole refusal surface**, which is
    the one-base-per-member shape the dreaming and regime members state for
    their own vocabularies: :class:`LeverageRequestError` (feature 308's ask)
    and :class:`LeverageTargetError` (feature 308's verdict) descend from it,
    so a caller that must refuse rather than rank catches this one class and
    catches the cap's failures with it.  A caller that has to *react*
    differently to *your signals cannot be combined* and *this book may not
    carry that leverage* catches the specific siblings instead — see each for
    why the distinction is worth a class.  The classes are siblings rather
    than aliases because the facts are genuinely different: a leverage target
    is refusable for a book whose signals weighted up perfectly.
    """


class LeverageRequestError(BookConstructionError):
    """The leverage cap could not be asked for as the caller asked for it.

    app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects
    a leverage target above one quarter of the Kelly fraction implied by the
    book Sharpe and volatility.*  This class is the *ask* face of that
    sentence and never the judgment: it refuses a leverage target that is not
    a finite real of zero or more, a book Sharpe that is not a finite real, or
    a book volatility that is not a finite strictly positive real — the
    figures :func:`book.leverage_cap` and
    :func:`book.rejects_overleveraged_target` are computed from — **before**
    any fraction is formed, the ordering every verdict and store in this
    workspace states.

    **What it deliberately does not refuse: a non-positive Sharpe.**  A
    losing book's Sharpe is a measurement, not a malformed ask, and the
    honest consequence — a Kelly fraction at or below zero, and therefore a
    cap that admits no *long* leverage (though it still admits the flat book,
    the admissible set being the cap intersected with leverage zero-and-up) —
    is the answer :func:`book.leverage_cap` returns and the refusal
    :class:`LeverageTargetError` states in the book's own terms.  Refusing
    the Sharpe here would hide the book's figure behind a validation and
    leave a caller unable to tell *no long leverage is admissible* from
    *your ask named no figure*.

    **No code word, and deliberately.**  Feature 308's sentence mandates no
    token (it names its subject in prose), and every message here opens with
    its subject — the figure, its type and what it is for — the shape
    :class:`dreaming.errors.CapRequestError` states for its own pair, so a
    reader is told *what to fix* rather than handed a token to grep for.  The
    one code the sentence's path carries is
    :class:`LeverageTargetError`'s, on the verdict alone.

    **Why it is its own class rather than the base alone.**  The repair
    differs.  A bare :class:`BookConstructionError` means *your signals
    cannot be combined — fix the signals*; this one means *your ask named no
    figure the cap can be computed from — fix the ask*, and the two are not
    the same instruction.  A caller that must react differently to them can
    tell them apart by class; a caller that refuses book work wholesale still
    catches one class, the base this descends from.
    """


class LeverageTargetError(BookConstructionError):
    """The leverage target is above one quarter of the book's Kelly fraction.

    app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects
    a leverage target above one quarter of the Kelly fraction implied by the
    book Sharpe and volatility.*  This class is the judgment that sentence
    mints — the one refusal on the cap's path that is a *verdict* rather than
    a validation — and it is raised by
    :func:`book.rejects_overleveraged_target` when a well-formed target sits
    above a well-formed cap.  Its message opens with the greppable code
    :data:`book.OVERLEVERAGE_CODE` (``leverage_above_quarter_kelly``).

    **Why the quarter, stated where the refusal is caught.**  The Kelly
    fraction ``f* = S/σ`` is Appendix B's line and is estimated from a Sharpe
    — a figure docs/alpha-engine-prd.md §1.2 states the worth of exactly:
    *"A backtest Sharpe of 4.0 is a noisy, biased, adversarially exploitable
    estimate."*  Betting the full ``f*`` bets a point estimate as though it
    were the truth, so the table states the discount itself — *"use ≤ ¼
    Kelly"* — and this class is the refusal that enforces it.

    **Its repair is its own, which is why it is its own class.**  *Lower the
    target to one quarter Kelly or below* — or, where the cap itself is not
    positive (a book whose measured Sharpe is non-positive), the repair is
    the only one that exists on it: *hold the book flat, and re-ask once the
    measured Sharpe is positive*.  The two classes a caller could otherwise
    catch this as both name repairs that are wrong here:
    :class:`LeverageRequestError` means *your ask named no figure* (the
    target is perfectly well formed and the cap is perfectly well defined —
    it is simply smaller), and the bare :class:`BookConstructionError` means
    *your signals cannot be combined* (they combined; the resulting book is
    real and its Sharpe is what capped it).  Folding these together would
    make a caller that must react differently to *this book may not carry
    that leverage* and *your ask was malformed* catch one class and
    re-inspect something it cannot tell apart, which is the failure this
    vocabulary is split to prevent.

    **The edge is the sentence's own word.**  A target *at* the cap is
    admitted — Appendix B's *"use ≤ ¼ Kelly"* is inclusive on the admitted
    side — so this class is raised strictly above it.
    """
