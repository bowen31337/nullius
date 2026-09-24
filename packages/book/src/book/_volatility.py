"""The volatility target — feature 303: weights scaled to a configured volatility.

app_spec.xml, "Portfolio Book Construction", feature 303: *System applies
volatility targeting to the combined book, which returns weights scaled to a
configured annualized volatility.*  This module is that act.  It takes the
combined book feature 301 answers — the composite target score per symbol —
and the book's own annualized volatility, and answers the book's **target
weights**: the composite normalized into a book and scaled by the one factor
that puts the book's annualized volatility on the configured target::

    scale  = target_volatility / volatility
    w_raw  = score_s / Σ_t |score_t|        (the book at one unit of gross)
    w_s    = w_raw · scale                  (the scaled book)

**The composite is a score, so it is normalized before it can be a book.**  A
node's target score carries free sign and scale — docs/alpha-engine-prd.md §3
states it of the searched object itself (*"Returns: index=symbol,
value=cross-sectional score.  Sign and scale are free; the evaluator ranks and
normalizes."*) — and feature 301's composite is the weighted average of such
scores, so its *absolute* magnitude is an artifact of the signals' own units
rather than an exposure.  A weight is not free that way: the order layer
cannot hold ``0.1875`` of a symbol.  So the act's first step turns the
composite into a book — one symbol's score relative to the rest, normalized to
**one unit of gross exposure**, ``w_raw = score_s / Σ_t |score_t|`` — and only
then scales it.  Gross rather than net because the composite is
cross-sectional: a z-scored score is roughly half negative, so a book built
from one is long *and* short, and a net normalization (``score_s / Σ_t
score_t``) would be a division by whatever the signals happened to net out to
— zero for the market-neutral book the cross-section usually produces.  Gross
normalization instead preserves every sign, keeps the book's own direction
(§3's *"sign and scale are free"* read on the composite: the sign is the view
and this act does not re-open it, and re-centering a book here would be
re-ranking what feature 301 ranked).

**The configured annualized volatility is a parameter — the one knob in this
category, and this is its feature.**  §C8's chain — *"Signal book →
IR-weighted combination with shrinkage → volatility targeting → position and
concentration limits → orders.  Version-controlled, human-authored, explicitly
outside the search space."* — names volatility targeting between the
combination and the limits, and docs/alpha-engine-prd.md states no figure for
it: the document states a *discount* on a Kelly fraction (Appendix B's *"use ≤
¼ Kelly"*, feature 308's constant) and the *form* of a bar, but nowhere a risk
level.  A target volatility is a deployment's own decision — how much risk the
book is to be held at — so it arrives as a required keyword, ``target_volatility``,
and deliberately with **no default**: a module-chosen fallback would be a
risk level no document states, silently applied to every deployment that never
configured one.  Feature 308 states the same boundary from the other side of
the category (*"the knob in this neighbourhood is feature 303's configured
volatility target, and it is a different feature's"*), and its quarter is its
contrast: the document's figure arrives as nothing, the deployment's arrives as
a parameter.

**The book's volatility arrives as a figure the caller already holds.**  The
act is a scaling, not a measurement: it never re-derives the volatility of the
book it is handed, because a workspace member never re-derives a measurement
it was handed and the measurement of a book's volatility is the evaluator's
business (feature 308's stance on the same member's other figure, and
:func:`dreaming.bar.selection_bar`'s on its own).  The figure is *the book the
normalized weights describe* — the book at one unit of gross exposure — so the
scaling is exact: gross exposure enters a book's volatility linearly, so the
scaled book's annualized volatility is ``scale · volatility``, which is
``target_volatility`` by construction, which is the sentence's own claim
("weights scaled to a configured annualized volatility") and the identity
:class:`TargetWeights` enforces on itself.

**Annualized means the two figures share one basis, and this module applies
none.**  The sentence's target is *annualized* and the book's volatility
arrives on whatever basis it was measured on — crypto's year is 365 calendar
days, the basis feature 55's realized volatility annualizes on
(``sqrt(365)``).  The act divides one by the other, so an annualization factor
applied here would be this module *re-deriving* a measurement's units rather
than scaling a book, and it would be wrong whenever the two figures arrived
already annualized — which they do.  Both figures must therefore be stated on
the same annualized basis; the module neither knows nor needs to know which.

**Absence is not zero, and the flat composite is a division by exactly
nothing.**  A book whose composite scores are all zero — every symbol scored
at no view — has a gross score of exactly zero, so ``score_s / Σ_t
|score_t|`` is undefined rather than zero: there is no book whose weights
could be scaled to any target, and answering an all-zero weight set would
counterfeit a book from no view (feature 301's stance on absence, read on this
act's own divisor).  It is refused with :class:`VolatilityTargetError` naming
the code :data:`FLAT_BOOK_CODE`, and it is the *only* judgment the sentence
mints — the one refusal an operator greps a deployment log for on this path.
A *configured target of zero* is the different fact and is **answered**, the
way feature 308 answers a zero Sharpe: "no risk is to be taken" is a
well-formed configuration whose honest consequence is a flat book — ``scale =
0``, every weight zero — and refusing it would report a deployment's risk
appetite as a malformed ask.

**This act sets exposure; it does not bound it.**  The scale may exceed one —
a book quieter than its target is levered up to it, which is the whole point
of targeting — so this module refuses no leverage and clamps nothing: feature
308's cap is the bound on the book's exposure and feature 304's limits are the
bound on a position's size, and both are applied by their own callers to the
weights this act answers (:attr:`TargetWeights.gross_exposure` is the figure
the cap judges, exposed so the two features meet without either importing the
other).  A module that refused leverage here would be a bound wearing a
scaling's name, and a book refused for reaching its configured risk would
report the configuration as the fault.

**The record is a check rather than a claim.**  :class:`TargetWeights` carries
the scaled weights, the gross-normalized book they came from, the scale, and
the two volatility figures, and construction enforces what the act claims:
every weight equals its gross weight times the scale, the scale equals
``target_volatility / volatility``, the gross weights are a book at one unit
of gross exposure, and the two mappings cover the same symbols.  That is the
self-consistency :class:`book.CompositeBook` enforces on its own composite and
:class:`evaluator.MarginalIR` on its ratios: a hand-built target-weight set
whose weights are not its own gross book scaled is refused.

**What this module does not do.**  It shrinks no covariance (feature 302's),
re-opens no information-ratio weight (feature 301's), measures no volatility,
demeans or re-ranks the composite, applies no per-position or concentration
limit (feature 304's), bounds no leverage (feature 308's), persists no
rebalance (feature 309's) and reaches no order layer.  It takes the combined
book and its volatility and answers exactly one question: *what are the
book's target weights when its annualized volatility is the configured
target?*

**No new component, and the layering note.**  The act is a free function
beside the combiner, the way feature 306's guard, feature 307's companion and
feature 308's cap sit: its whole input is a value and two figures the caller
already holds, so there is nothing for the factory to compose and nothing for
a deployment to configure *through the registry* — the one thing a deployment
configures here is the target, and it hands that to the call rather than to
the composition.  No ``@register``, no table, no endpoint, no migration, no
seat edit, and no third-party import — ``math``, ``dataclasses``,
``collections``, ``types``, ``typing`` and the member's own ``.errors`` — so
the factory's scan, which imports this package on every ``create_app()`` to
fire its ``@register``, pays nothing for the act beyond the import it already
paid for the combiner, and the replay path stays import-cheap.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import (
    BookConstructionError,
    VolatilityTargetError,
    VolatilityTargetRequestError,
)

__all__ = [
    "FLAT_BOOK_CODE",
    "TargetWeights",
    "apply_volatility_target",
]

#: The code a *flat-book* refusal opens with — the combined book's composite
#: expresses no view anywhere, so there is no book whose weights could be
#: scaled to a volatility target — so the refusal is greppable by the word
#: that names it.  Feature 303's sentence mandates no token (it names its
#: subject in prose), so the code is this module's own, minted on the
#: ``leverage_above_quarter_kelly`` / ``missing_changelog_entry`` convention
#: the workspace states for the one refusal an operator greps a deployment log
#: for: *why was this book not sized?*  The ask's own facts carry no code, for
#: the reason :class:`~book.errors.VolatilityTargetRequestError` gives — a
#: malformed ask names its subject in its first words, and a token there would
#: hand a reader a developer's word for a fact they can simply fix.  The word
#: is the member's own: feature 308's refusal already calls a book at no
#: exposure *the flat book*, and this is the same book seen one step earlier —
#: a composite with no direction to normalize.
FLAT_BOOK_CODE = "flat_book"

#: Sentinel for "attribute not present" when reading the book's surface, so a
#: value that carries no ``scores`` is distinguished from one that carries
#: ``scores=None`` — a book that omits its scores entirely is not a book,
#: which is a different report from a book that stated its scores as nothing.
#: The combiner's, the guard's and the companion's own ``_MISSING``
#: discipline, read on this act's book.
_MISSING = object()


def _validated_volatility(value: Any) -> float:
    """Check that ``value`` is the book's annualized volatility, or refuse it.

    The book's scale, and the divisor of the act's one factor: a finite real
    **strictly positive**.  Strictly positive on the terms
    :func:`book._leverage._validated_volatility` states for feature 308's own
    figure, and for the identical reason read on the other side of the
    division — a book with no volatility has no scale to target, so ``target /
    volatility`` is a division by exactly nothing rather than an infinite
    scale, and a module that answered an infinite scale would lever every
    target on the strength of a measurement the evidence does not carry.  A
    *negative* volatility is a scale that is not a measurement: it would flip
    the sign of the scale and turn a long book into a short one, which is a
    direction this act does not take.

    The boundary with feature 308 is exact and deliberate: that feature
    validates the same kind of figure for its Kelly fraction, this one for its
    scaling, and each refuses it with **its own** class — a shared helper
    raising another feature's error type would defeat the caller's ``except``,
    which is why the two validators are two spellings rather than one import.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VolatilityTargetRequestError(
            f"a book's annualized volatility is a number — got {value!r} "
            f"({type(value).__name__}); volatility targeting scales the "
            "combined book by the configured annualized volatility over the "
            "book's own, and a value that is not one names no scale this act "
            "can divide by"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise VolatilityTargetRequestError(
            f"a book's annualized volatility is a finite number — got "
            f"{value!r}; a non-finite scale answers a scale factor that is not "
            "a number, and every weight scaled by it would be a weight that is "
            "not a weight"
        )
    if figure <= 0.0:
        raise VolatilityTargetRequestError(
            f"a book's annualized volatility is strictly positive — got "
            f"{value!r}; the act's one factor is the configured annualized "
            "volatility over the book's own, and a book volatility of zero "
            "leaves that a division by exactly nothing — a book with no scale "
            "has no target weights at all rather than infinitely many, and a "
            "negative volatility is a scale that is not a measurement: it "
            "would flip the sign of the scale and turn the book short"
        )
    return figure


def _validated_target_volatility(value: Any) -> float:
    """Check that ``value`` is the configured annualized target, or refuse it.

    The deployment's one figure in this category (§C8's chain names the step;
    the document states no risk level), and the numerator of the act's one
    factor: a finite real **of zero or more**.  Zero is admitted and is the
    honest floor — *take no risk* is a well-formed configuration whose
    consequence is a flat book (``scale = 0``), the reading feature 308 gives
    a zero Sharpe (*"a zero Sharpe answers a zero cap and admits only the flat
    book"*), and refusing it would report a deployment's risk appetite as a
    malformed ask.

    A *negative* target is refused, and it is the ask's own fact rather than a
    judgment: a volatility target is a **scale**, and a negative one is a
    direction — ``-0.20`` would flip every weight's sign, turning a long book
    into a short one through an arithmetic that read a risk level as a view.
    A ``bool`` is refused where a figure belongs because ``True`` is ``1`` in
    Python and a flag where a risk level belongs would read as *one hundred
    percent annualized*; ``nan``/``±inf`` are refused because they are not
    levels — a ``nan`` target answers a ``nan`` scale, and a book scaled by it
    would be a book of ``nan`` weights that no limit could bound.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VolatilityTargetRequestError(
            f"a configured volatility target is a number — got {value!r} "
            f"({type(value).__name__}); the target is the annualized "
            "volatility the book is to be held at, and a value that is not one "
            "names no risk level this act can scale to"
        )
    figure = float(value)
    if not math.isfinite(figure):
        raise VolatilityTargetRequestError(
            f"a configured volatility target is a finite number — got "
            f"{value!r}; a non-finite target answers a non-finite scale and "
            "every weight scaled by it would be a weight no bound can judge"
        )
    if figure < 0.0:
        raise VolatilityTargetRequestError(
            f"a configured volatility target is zero or more — got {value!r}; "
            "a volatility target is a scale, and a negative one is a "
            "direction: it would flip the sign of every weight and turn a long "
            "book short through an arithmetic that read a risk level as a "
            "view. A deployment that wants the opposite book asks feature "
            "301's composite to express it"
        )
    return figure


def _scale(volatility: float, target_volatility: float) -> float:
    """The act's one factor — the one spelling of ``target / volatility``.

    Over figures the callers have already validated, so
    :func:`apply_volatility_target`, the record's own self-check and any
    reader of the record cannot disagree about what the scale is — the
    discipline :func:`book._leverage._cap` states for keeping one module's
    arithmetic from drifting (and :func:`dreaming.bar._bar` before it),
    applied to the one expression this module exists to apply.  It is the
    *ratio of the two figures* and nothing else: no annualization factor, no
    clamping to one, no floor — an act that silently capped its own scale
    would be a leverage bound wearing a scaling's name (feature 308's job),
    and one that annualized would be re-deriving the units of a measurement it
    was handed.
    """
    return target_volatility / volatility


def _scores_of(book: Any) -> Mapping[str, float]:
    """Read the combined book's composite scores, or refuse it as the ask's own.

    The surface feature 301's :class:`~book.CompositeBook` carries and this
    act needs — one composite target score per symbol.  Read duck-typed, so a
    value that exposes ``scores`` is a book here whatever class composed it
    (a member never isinstance-gates the value a composition seam hands out),
    and a value that carries no ``scores`` is refused rather than treated as
    an empty book: *this is not a book* and *this book covers no symbols* are
    different reports, and the sentinel keeps them apart.
    """
    scores = getattr(book, "scores", _MISSING)
    if scores is _MISSING:
        raise VolatilityTargetRequestError(
            "volatility targeting takes the combined book — got "
            f"{book!r} ({type(book).__name__}), which carries no ``scores``; "
            "hand the composite feature 301's combine answers (or any value "
            "exposing the same ``scores`` mapping of symbol to composite "
            "target score), and this act will scale its weights to the "
            "configured annualized volatility"
        )
    if not isinstance(scores, Mapping):
        raise VolatilityTargetRequestError(
            "the combined book's scores are a mapping of symbol to composite "
            f"target score — got {type(scores).__name__}; a book's scores are "
            "read one symbol at a time and a value that is not a mapping names "
            "no book"
        )
    if not scores:
        raise VolatilityTargetRequestError(
            "the combined book covers at least one symbol — got a book whose "
            "``scores`` are empty; a book that covers no symbols has no "
            "weights to scale, and an empty weight set would be a book "
            "presented to the order layer as if it were a decision"
        )
    validated: dict[str, float] = {}
    for symbol, score in scores.items():
        if not isinstance(symbol, str) or not symbol.strip():
            raise VolatilityTargetRequestError(
                "the combined book's scores must be keyed by non-empty symbol "
                f"names — got {symbol!r}; a weight cannot be attributed to a "
                "symbol the book does not name"
            )
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise VolatilityTargetRequestError(
                "the combined book's composite target score for symbol "
                f"{symbol!r} must be a finite real — got {score!r} "
                f"({type(score).__name__}); a book whose score is not a number "
                "has no weight this act could scale"
            )
        number = float(score)
        if not math.isfinite(number):
            raise VolatilityTargetRequestError(
                "the combined book's composite target score for symbol "
                f"{symbol!r} is not finite ({score!r}); a NaN or ±inf would "
                "reach the weights dressed as a measurement, and every weight "
                "scaled from it would be unboundable"
            )
        validated[symbol] = number
    return validated


def _flat_refusal(scores: Mapping[str, float]) -> str:
    """The refusal's own sentence for a composite that expresses no view.

    Spelled once so :func:`apply_volatility_target` raises one message, and it
    states the figures the caller needs to see the arithmetic rather than take
    it on faith: the symbols the book covers (all of them scored at zero), the
    gross score the normalization would divide by, and the one repair that
    exists — *hand a composite that expresses a view*, because this module
    fabricates no view to fill the gap and holds no weight to fall back on.
    The message names the divisor, because that is the fact that makes this a
    refusal rather than a zero answer: ``Σ_t |score_t|`` is exactly nothing
    here, so the weights are undefined, not flat.
    """
    return (
        f"{FLAT_BOOK_CODE}: the combined book expresses no view — every one of "
        f"its composite target scores is zero (it covers "
        f"{sorted(scores)} and they are all at 0.0), so its gross score "
        "Σ_t |score_t| is exactly 0.0 and volatility targeting would divide "
        "the book by it. There is no book of weights to scale: normalizing a "
        "flat composite is a division by exactly nothing, not a book held "
        "flat, and answering an all-zero weight set would counterfeit a book "
        "from no view (absence is not zero — the stance feature 301 takes on a "
        "signal that misses a symbol, read on this act's own divisor). The "
        "repair is the one that exists: hand a composite that expresses a "
        "view — signals whose combined target scores are not all zero — and "
        "this act will normalize it and scale it to the configured annualized "
        "volatility. A *configured target of zero* is a different fact and is "
        "not this refusal: that is a deployment asking for no risk, and it is "
        "answered with a flat book (scale 0.0, every weight 0.0)"
    )


@dataclass(frozen=True)
class TargetWeights:
    """The scaled book — feature 303's answer.

    The weights the sentence's act answers: the combined book normalized into
    a book and scaled to the configured annualized volatility.  Frozen for the
    reason :class:`book.CompositeBook`, :class:`book.PromotedSignal` and
    :class:`scoring.WorldScore` are: these are the weights the order layer
    holds, and a value that could move after it was read would be a book that
    changed beneath the instruction that consumes it — feature 305's *"final
    target weights as the only output consumed by the order layer"* is this
    value, and a target set that a later edit could re-scale would be a
    rebalance nobody decided.

    The record is a check rather than a claim.  Construction enforces the
    act's own terms:

    * every :attr:`weights` entry equals its :attr:`gross_weights` entry times
      :attr:`scale` — the scaled book is its own gross book scaled;
    * :attr:`scale` equals ``target_volatility / volatility`` — the factor the
      figures behind it imply, so a hand-built record cannot carry one pair of
      figures and another factor;
    * :attr:`gross_weights` is a book at **one unit of gross exposure**,
      ``Σ_s |w_s| = 1`` — the normalization the act's first step performs, and
      the property that makes the volatility figure interpretable at all (a
      caller's volatility is the volatility of *that* book);
    * the two mappings cover the same symbols, so a symbol is never weighed
      without the gross weight its scaling is checked against.

    The gross-one law is the one comparison this module makes with a
    tolerance rather than with ``==``, and deliberately:
    ``Σ_s |score_s / Σ_t |score_t||`` is not exactly one in binary arithmetic
    for an arbitrary composite (each division rounds), so an exact test would
    refuse honest books.  The tolerance is far below any weight a book
    carries and is stated here so the exception is not mistaken for slack:
    the identities that tie the record's *own* fields together stay exact,
    because the verb computes them with these same operations.
    """

    #: The scaled weights — the book held at the configured annualized
    #: volatility, keyed by symbol in sorted order so two calls over the same
    #: book and figures answer identical values.
    weights: Mapping[str, float]
    #: The combined book normalized to one unit of gross exposure — the book
    #: the caller's volatility figure describes, and the value every scaled
    #: weight is checked against.
    gross_weights: Mapping[str, float]
    #: The factor the book was scaled by — ``target_volatility / volatility``.
    scale: float
    #: The book's own annualized volatility, as the caller measured it.
    volatility: float
    #: The configured annualized volatility the book is held at.
    target_volatility: float

    def weight(self, symbol: str) -> float:
        """The scaled weight for one symbol — the order layer's figure for it.

        Refuses with :class:`~book.errors.BookConstructionError` a symbol the
        book does not cover, rather than answering a fabricated zero: a symbol
        the weights hold no entry for is not a symbol this book holds, and a
        zero would read to the order layer as *hold none of it* — a position
        decision this act never made.  The message opens with the same
        ``uncovered_symbol`` word feature 301's ``CompositeBook.target_score``
        answers with, because it is the same fact about the same surface.
        """
        try:
            return self.weights[symbol]
        except KeyError:
            raise BookConstructionError(
                f"uncovered_symbol: the target weights hold no weight for "
                f"symbol {symbol!r}; the book covers {sorted(self.weights)}"
            ) from None

    @property
    def gross_exposure(self) -> float:
        """The gross exposure the scaled book is held at — ``Σ_s |w_s|``.

        Derived from :attr:`weights` rather than stored, so it can never
        disagree with the weights it summarises (the discipline
        :class:`replay.ReplayDuration` states for its own derived flags), and
        exposed because it is the figure **feature 308's cap judges**: that
        feature rejects a leverage target above one quarter of the book's
        Kelly fraction, and the leverage a caller would hand it *is* this
        number.  The two features meet here without either importing the
        other — the cap takes figures, and this is the figure its caller needs
        from this act.

        It is also the sentence's *scaled* made legible: on a book whose
        volatility sits below the target the exposure is above one (the book
        is levered up to its risk level, which is what targeting is for), and
        on one above the target it is below one.  This act does not bound it —
        see the module docstring.
        """
        return math.fsum(abs(weight) for weight in self.weights.values())

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize:
        # this value validates and freezes, like CompositeBook and
        # PromotedSignal.  The order is the ask's own facts first — a field
        # that is not what it must be is refused before any identity between
        # fields is checked — the ordering every verdict and record in this
        # workspace states.
        weights = self._captured(self.weights, "weights")
        gross = self._captured(self.gross_weights, "gross_weights")
        object.__setattr__(self, "weights", MappingProxyType(weights))
        object.__setattr__(self, "gross_weights", MappingProxyType(gross))

        volatility = _validated_volatility(self.volatility)
        target = _validated_target_volatility(self.target_volatility)
        object.__setattr__(self, "volatility", volatility)
        object.__setattr__(self, "target_volatility", target)
        if isinstance(self.scale, bool) or not isinstance(self.scale, (int, float)):
            raise VolatilityTargetRequestError(
                "the target weights' scale must be a finite real — got "
                f"{self.scale!r} ({type(self.scale).__name__}); the scale is "
                "the factor the combined book was scaled by, and a record that "
                "states it as anything else states no book"
            )
        scale = float(self.scale)
        if not math.isfinite(scale):
            raise VolatilityTargetRequestError(
                f"the target weights' scale must be finite — got {self.scale!r}"
            )
        object.__setattr__(self, "scale", scale)

        # The two mappings are one book read twice: a symbol weighed without
        # the gross weight its scaling is checked against would make the check
        # below vacuous, so the coverage is settled before it runs.
        if set(weights) != set(gross):
            missing = sorted(set(gross) - set(weights))
            extra = sorted(set(weights) - set(gross))
            raise VolatilityTargetRequestError(
                "the target weights and their gross weights cover the same "
                f"symbols — the scaled book misses {missing} and adds {extra}; "
                "a weight is its gross weight scaled, so the one book's two "
                "readings must name the same symbols"
            )

        # The act's own terms, in the order they reduce: the factor from the
        # two figures, the book at one unit of gross, then every weight from
        # its gross weight and that factor.  The identities the verb computes
        # are checked with `==` — same operations, same results — and the
        # gross-one law alone carries a tolerance; see the class docstring.
        expected_scale = _scale(volatility, target)
        if scale != expected_scale:
            raise VolatilityTargetRequestError(
                f"the target weights say the book was scaled by {scale!r} but "
                f"the two figures it carries give {target!r} / {volatility!r} "
                f"= {expected_scale!r}; the record disagrees with itself — the "
                "scale is the configured annualized volatility over the book's "
                "own"
            )
        gross_exposure = math.fsum(abs(weight) for weight in gross.values())
        if not math.isclose(gross_exposure, 1.0, rel_tol=1e-9, abs_tol=1e-12):
            raise VolatilityTargetRequestError(
                "the target weights' gross weights are a book at one unit of "
                f"gross exposure — they sum in absolute value to "
                f"{gross_exposure!r}, not 1.0; the book is normalized to unit "
                "gross before it is scaled, because the combined book is a "
                "score whose absolute scale is free and the caller's "
                "volatility figure describes the normalized book"
            )
        for symbol, gross_weight in gross.items():
            expected = gross_weight * scale
            if weights[symbol] != expected:
                raise VolatilityTargetRequestError(
                    f"the target weights say the weight for symbol {symbol!r} "
                    f"is {weights[symbol]!r} but its own gross weight "
                    f"{gross_weight!r} scaled by {scale!r} gives {expected!r}; "
                    "the record disagrees with itself — a weight is its gross "
                    "weight times the scale"
                )

    @staticmethod
    def _captured(values: Any, field: str) -> dict[str, float]:
        """Read one of the record's two symbol mappings, or refuse it.

        Both mappings are the same shape — non-empty symbols to finite reals,
        one entry per symbol — so they are read by one helper, and the
        messages name which of the two was ill-stated.  The scalar checks are
        the same :func:`_validated_volatility` discipline read on a weight: a
        ``bool`` is a flag where a magnitude belongs, and a ``nan`` / ``inf``
        weight is not a position any limit could bound.
        """
        if not isinstance(values, Mapping):
            raise VolatilityTargetRequestError(
                f"the target weights' {field} must be a mapping of symbol to "
                f"weight — got {type(values).__name__}"
            )
        if not values:
            raise VolatilityTargetRequestError(
                f"the target weights' {field} must cover at least one symbol — "
                "got none; a book that holds no symbol is not a book the order "
                "layer can be handed"
            )
        captured: dict[str, float] = {}
        for symbol, value in values.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise VolatilityTargetRequestError(
                    f"the target weights' {field} must be keyed by non-empty "
                    f"symbol names — got {symbol!r}"
                )
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise VolatilityTargetRequestError(
                    f"the target weights' {field} for symbol {symbol!r} must "
                    f"be a finite real — got {value!r} ({type(value).__name__})"
                )
            number = float(value)
            if not math.isfinite(number):
                raise VolatilityTargetRequestError(
                    f"the target weights' {field} for symbol {symbol!r} is not "
                    f"finite ({value!r}); a NaN or ±inf weight is not a "
                    "position, and no limit downstream could bound it"
                )
            captured[symbol] = number
        return captured


def apply_volatility_target(
    book: Any,
    *,
    volatility: Any,
    target_volatility: Any,
) -> TargetWeights:
    """Scale the combined book to a configured annualized volatility — 303's act.

    Feature 303's verb, in the order the refusals must fire.  ``book`` is the
    combined book feature 301 answers — a :class:`book.CompositeBook`, or any
    value exposing the same ``scores`` mapping of symbol to composite target
    score; a member never isinstance-gates the value a composition seam hands
    out, so the surface is read, not the type — ``volatility`` is the book's
    own annualized volatility (of the book its scores normalize to: the book
    at one unit of gross exposure), and ``target_volatility`` is the
    configured annualized volatility the book is to be held at.  The answer is
    a frozen :class:`TargetWeights` carrying the scaled weights, the
    gross-normalized book, the scale and the two figures.

    The steps, in the order they must happen, each refusal leaving no value:

    (1) read the book's ``scores``, refusing a value that carries none, a
    non-mapping, and a book covering no symbols — the ask's own facts;
    (2) read each symbol and score, refusing a blank symbol name and a score
    that is not a finite real;
    (3) validate the two figures — ``volatility`` a finite strictly positive
    real, ``target_volatility`` a finite real of zero or more — refused with
    :class:`~book.errors.VolatilityTargetRequestError` **before any book is
    judged**, the ordering every verdict and act in this workspace states: a
    caller that mis-stated a figure is told *what to fix*, never told its
    composite is flat;
    (4) normalize the composite to the book at one unit of gross exposure,
    ``w_raw = score_s / Σ_t |score_t|``, refusing a gross score of exactly
    zero with :class:`~book.errors.VolatilityTargetError` opening with
    :data:`FLAT_BOOK_CODE` — the one judgment this sentence mints: a flat
    composite has no book to scale, and the denominator is nothing;
    (5) form the one factor ``scale = target_volatility / volatility`` and
    answer the :class:`TargetWeights`, whose construction re-checks that every
    weight is its gross weight times that factor.

    Deterministic and order-independent: the normalization is a sum over the
    book and the scaling is one factor over it, so symbols are emitted sorted
    and two calls over the same book and figures answer an identical record.

    **The target may exceed the book's volatility, and that is answered.**  A
    scale above one is a book levered up to its configured risk level, which
    is what volatility targeting is for; this act refuses no leverage and
    clamps nothing, because the bound on a book's exposure is feature 308's
    and the bound on a position's size is feature 304's — both applied by
    their own callers to the weights answered here (:attr:`TargetWeights.gross_exposure`
    is the figure the cap judges).  A *zero* target is answered too: it is a
    deployment asking for no risk, and the honest book for it is flat
    (``scale = 0``, every weight zero), the reading feature 308 gives a zero
    Sharpe.  Only a *malformed* figure — a negative target, a zero or negative
    or non-finite book volatility — is refused, and as the ask's own fact.
    """
    scores = _scores_of(book)
    lead = _validated_volatility(volatility)
    target = _validated_target_volatility(target_volatility)

    gross_score = math.fsum(abs(score) for score in scores.values())
    if gross_score == 0.0:
        raise VolatilityTargetError(_flat_refusal(scores))

    scale = _scale(lead, target)
    gross_weights = {symbol: score / gross_score for symbol, score in scores.items()}
    weights = {
        symbol: gross_weights[symbol] * scale for symbol in sorted(gross_weights)
    }

    return TargetWeights(
        weights=weights,
        gross_weights=gross_weights,
        scale=scale,
        volatility=lead,
        target_volatility=target,
    )
