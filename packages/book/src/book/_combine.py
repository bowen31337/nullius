"""Combine promoted signals by information-ratio weighting — feature 301.

app_spec.xml, "Portfolio Book Construction", feature 301: *System combines
promoted signals by information-ratio weighting, which returns a single
composite target score per symbol.*  This module is that act.  It takes the
promoted signals — each a :class:`PromotedSignal` carrying its out-of-sample
information ratio and one target score per symbol — weights signal *i* by
``w_i = IR_i`` (the information-ratio weighting the sentence names), and
answers a single :class:`CompositeBook` holding one composite target score
per symbol, the weighted average of that symbol's scores across the signals
that carry it::

    composite[s] = Σ_i w_i · score_i[s] / Σ_i w_i

Four decisions carry the feature, and each is a pin rather than a knob:

*the weight is the information ratio, and that is a convention, not a knob.*
    Signal *i* enters the book with weight ``IR_i`` and the composite is the
    weighted average under those weights — the information-ratio weighting
    feature 301's sentence names, verbatim.  It is not a caller's parameter:
    a weight is a portfolio decision the combiner applies rather than
    accepts, and a composite computed under an ad-hoc weighting would not be
    comparable across deployments, which is what a ranking that becomes an
    order must be.  (Downstream features — covariance shrinkage, volatility
    targeting — take this composite and rescale it; they do not re-open this
    weight.)  The weighting is restated here in this member's own terms
    rather than borrowed from the evaluator or scoring member, because a
    workspace member never imports another workspace member.

*the information ratio is a signal's standing to weight the book, and a
standing that is not positive is refused, not zero-weighted.*
    A signal presenting a zero, negative or non-finite information ratio is
    refused with :class:`BookConstructionError` — never silently dropped and
    never zero-weighted, because discarding a losing signal would hide a
    portfolio decision behind an arithmetic that looks like agreement.  This
    is the same stance the marginal-IR step takes on a book signal that
    misses a priced date: refuse rather than let an absence read as a view.

*absence is not zero, for the scores too.*
    Every signal must carry a score for every symbol the book covers — the
    union of the signals' symbol sets — so the composite over a symbol is the
    weighted average across *all* the signals.  A signal that carries no
    score for a covered symbol is refused as ``uncovered_symbol``, not
    zero-filled: a zero is a view (a maximally negative one), and a signal
    that expresses no view on a symbol must not be read as expressing the
    worst one.

*the composite is checkable against its own terms.*
    :class:`CompositeBook` carries the composite score per symbol, the
    normalized weight each signal carried (summing to one), each signal's
    information ratio, and the per-signal per-symbol scores the composite
    reduces from — and construction enforces that every composite score
    equals the weighted average of its contributing scores under the carried
    weights, and every weight equals ``IR_i / Σ_j IR_j``.  That is the
    self-consistency :class:`evaluator.MarginalIR` enforces on its ratios and
    the node-metrics store on its ``ic_mean``: the record is a check rather
    than a claim, so a hand-built composite whose composite is not its own
    weighted average is refused.

**What this module does not do.**  It chooses no weights beyond the
information-ratio weighting, applies no volatility target, shrinks no
covariance, persists no rebalance, and reaches no order layer — those are the
category's later features (302 through 309).  It takes the promoted signals
and answers exactly one question: *what is the single composite target score
per symbol when these signals are weighted by their information ratios?*

**The layering note.**  This module is stdlib-only — dataclasses, mappings,
square-free arithmetic; no polars, no pyarrow, no lake, no environment, no
HTTP, and no import of any other member.  The signals arrive as values, so
the Polars boundary stays at the edge of the package where every other member
keeps it, which is what makes importing this member cost composition — and
the replay path forbids from reaching the book — nothing at all.  It depends
on no other member: the information-ratio weighting it uses is pinned here
rather than borrowed.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .errors import BookConstructionError

__all__ = ["CompositeBook", "PromotedSignal", "combine"]

#: Sentinel for "attribute not present" when reading a signal's surface, so a
#: missing field is distinguished from one present-and-``None`` — a signal
#: that omits ``signal_id`` entirely is ``unnamed_signal``, not a signal that
#: named itself ``None``.
_MISSING = object()


def _validate_number(value: object, what: str) -> float:
    """A finite real, narrowed to ``float`` — the unit a score or ratio must be.

    Refuses what cannot be a measurement: a ``bool`` (a flag is not a number),
    a non-numeric type, or a NaN / ±inf (an infinity would rank above an
    honest score and a NaN would eat the ordering the composite exists to
    feed).  Returns the value as a ``float`` so the arithmetic downstream has
    one type.  ``int`` readings are accepted, because a caller whose scores
    are whole numbers has measured the same fact a fractional panel has.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BookConstructionError(
            f"{what} must be a finite real number, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number):
        raise BookConstructionError(f"{what} is not finite ({value!r})")
    return number


@dataclass(frozen=True)
class PromotedSignal:
    """A promoted signal's recorded fact — feature 301's input value.

    The signal the promotion gate admitted, as the combiner needs it: its
    out-of-sample information ratio (the scalar it was promoted on, and the
    weight it will carry) and one target score per symbol (the signal's
    per-symbol view).  Frozen, for the same reason
    :class:`scoring.WorldScore` and :class:`evaluator.MarginalIR` are: a
    promoted signal is the record of a decision, and a caller who could edit
    its ratio or its scores in memory could re-weight the book without
    re-running the promotion that earned the signal its place.

    Construction admits only what the combiner can score — the value is a
    plain record, and the *policy* (a ratio must be strictly positive) lives
    in the verb, :func:`combine`, which refuses a non-positive ratio rather
    than zero-weighting it — so construction validates only the shape: a
    non-empty name, a finite information ratio, and a non-empty mapping of
    symbol to finite score.  A malformed signal is thereby caught where it is
    built, not where it is combined.
    """

    #: The signal's non-empty name — the promotion record's identity for it.
    signal_id: str
    #: The signal's out-of-sample information ratio — a finite real, and the
    #: weight it will carry; validated strictly positive by :func:`combine`.
    information_ratio: float
    #: The signal's per-symbol target scores — symbol to score, each finite.
    target_scores: Mapping[str, float]

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize:
        # this value validates and freezes, like MarginalIR and WorldScore.
        if not isinstance(self.signal_id, str) or not self.signal_id.strip():
            raise BookConstructionError(
                "unnamed_signal: a promoted signal must carry a non-empty "
                f"signal_id to attribute a weight to, got {self.signal_id!r}"
            )
        object.__setattr__(
            self,
            "information_ratio",
            _validate_number(
                self.information_ratio, "a promoted signal's information_ratio"
            ),
        )
        if not isinstance(self.target_scores, Mapping):
            raise BookConstructionError(
                "signal_without_scores: a promoted signal must carry a mapping "
                f"of symbol to target score, got {type(self.target_scores).__name__}"
            )
        if not self.target_scores:
            raise BookConstructionError(
                "signal_without_scores: a promoted signal must carry at least "
                f"one target score, got none for signal {self.signal_id!r}"
            )
        validated: dict[str, float] = {}
        for symbol, score in self.target_scores.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise BookConstructionError(
                    "signal_without_scores: a promoted signal's target scores "
                    f"must be keyed by non-empty symbol names, got {symbol!r} "
                    f"for signal {self.signal_id!r}"
                )
            if symbol in validated:
                raise BookConstructionError(
                    "signal_without_scores: a promoted signal names symbol "
                    f"{symbol!r} twice in its target scores; one symbol, one score"
                )
            validated[symbol] = _validate_number(
                score,
                f"a promoted signal's target score for symbol {symbol!r}",
            )
        object.__setattr__(self, "target_scores", MappingProxyType(validated))


@dataclass(frozen=True)
class CompositeBook:
    """The single composite ranking — feature 301's answer.

    The one ranking :func:`combine` returns: the composite target score per
    symbol, the normalized weight each signal carried, each signal's
    information ratio, and the per-signal per-symbol scores the composite
    reduces from.  Frozen, because the composite is the order layer's ranking
    and a value that could move after it was read would be a ranking that
    changed beneath the instruction that consumes it — the same guarantee
    :class:`scoring.WorldScore` makes for a world's score.

    The record is a check rather than a claim: construction enforces that
    every :attr:`scores` entry equals the weighted average of its contributing
    :attr:`contributions` under the carried :attr:`weights`, and every weight
    equals ``IR_i / Σ_j IR_j`` — the self-consistency
    :class:`evaluator.MarginalIR` enforces on its ratios.  A hand-built
    composite whose composite is not its own weighted average is refused.
    """

    #: The composite target score per symbol — the weighted average of that
    #: symbol's scores across the signals, keyed by symbol in sorted order so
    #: two calls over the same signals answer identical values.
    scores: Mapping[str, float]
    #: The normalized weight each signal carried — ``IR_i / Σ_j IR_j`` — keyed
    #: by signal_id, summing to one.
    weights: Mapping[str, float]
    #: Each signal's information ratio — the raw standing the normalized
    #: weight reduces from — keyed by signal_id.
    information_ratios: Mapping[str, float]
    #: The per-signal per-symbol scores the composite reduces from — keyed by
    #: signal_id then symbol — carried so the composite is checkable.
    contributions: Mapping[str, Mapping[str, float]]

    def target_score(self, symbol: str) -> float:
        """The composite target score for one symbol — the ranking's entry for it.

        Refuses with :class:`BookConstructionError` a symbol the book does not
        cover, rather than answering a fabricated zero: a symbol the composite
        holds no score for is not a symbol this book ranks.
        """
        try:
            return self.scores[symbol]
        except KeyError:
            raise BookConstructionError(
                f"uncovered_symbol: the composite book holds no target score "
                f"for symbol {symbol!r}; it covers {sorted(self.scores)}"
            ) from None

    def __post_init__(self) -> None:
        # object.__setattr__ where the frozen constructor would normalize;
        # this value validates and freezes, like MarginalIR and WorldScore.
        captured_scores: dict[str, float] = {}
        for symbol, score in self.scores.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise BookConstructionError(
                    "the composite book's scores must be keyed by non-empty "
                    f"symbol names, got {symbol!r}"
                )
            captured_scores[symbol] = _validate_number(
                score, f"the composite book's target score for symbol {symbol!r}"
            )
        object.__setattr__(self, "scores", MappingProxyType(captured_scores))

        captured_weights: dict[str, float] = {}
        captured_irs: dict[str, float] = {}
        captured_contrib: dict[str, Mapping[str, float]] = {}
        for signal_id, ir in self.information_ratios.items():
            if not isinstance(signal_id, str) or not signal_id.strip():
                raise BookConstructionError(
                    "the composite book's information_ratios must be keyed by "
                    f"non-empty signal ids, got {signal_id!r}"
                )
            captured_irs[signal_id] = _validate_number(
                ir, f"the composite book's information ratio for signal {signal_id!r}"
            )
        for signal_id, weight in self.weights.items():
            if not isinstance(signal_id, str) or not signal_id.strip():
                raise BookConstructionError(
                    "the composite book's weights must be keyed by non-empty "
                    f"signal ids, got {signal_id!r}"
                )
            captured_weights[signal_id] = _validate_number(
                weight, f"the composite book's weight for signal {signal_id!r}"
            )
        for signal_id, per_symbol in self.contributions.items():
            if not isinstance(signal_id, str) or not signal_id.strip():
                raise BookConstructionError(
                    "the composite book's contributions must be keyed by "
                    f"non-empty signal ids, got {signal_id!r}"
                )
            if not isinstance(per_symbol, Mapping):
                raise BookConstructionError(
                    "the composite book's contributions for signal "
                    f"{signal_id!r} must map symbol to score, got "
                    f"{type(per_symbol).__name__}"
                )
            row: dict[str, float] = {}
            for symbol, score in per_symbol.items():
                if not isinstance(symbol, str) or not symbol.strip():
                    raise BookConstructionError(
                        "the composite book's contribution for signal "
                        f"{signal_id!r} must be keyed by a non-empty symbol, got "
                        f"{symbol!r}"
                    )
                row[symbol] = _validate_number(
                    score,
                    f"the composite book's contribution for signal {signal_id!r} "
                    f"and symbol {symbol!r}",
                )
            captured_contrib[signal_id] = MappingProxyType(row)
        object.__setattr__(self, "information_ratios", MappingProxyType(captured_irs))
        object.__setattr__(self, "weights", MappingProxyType(captured_weights))
        object.__setattr__(self, "contributions", captured_contrib)

        # Every signal that carries a weight must carry its scores, and every
        # symbol the book covers must be scored by every signal — the coverage
        # the composite's own arithmetic requires.
        symbols = captured_scores.keys()
        for signal_id in captured_irs:
            if signal_id not in captured_weights:
                raise BookConstructionError(
                    "the composite book carries an information ratio for signal "
                    f"{signal_id!r} but no weight for it; a weight and a ratio "
                    "belong to one signal"
                )
            contribution = captured_contrib.get(signal_id)
            if contribution is None:
                raise BookConstructionError(
                    "the composite book carries a weight for signal "
                    f"{signal_id!r} but no scores for it; a weighted signal must "
                    "contribute a score per symbol"
                )
            for symbol in symbols:
                if symbol not in contribution:
                    raise BookConstructionError(
                        f"uncovered_symbol: the composite book's signal "
                        f"{signal_id!r} carries no score for symbol {symbol!r}, "
                        "which the book covers; every signal must score every "
                        "symbol the book covers"
                    )

        # The total weight the ratios reduce from, and the self-consistency the
        # record exists to enforce: each weight is IR_i / Σ_j IR_j, and each
        # composite score is the weighted average of its contributing scores.
        total = math.fsum(captured_irs.values())
        if total == 0.0:
            raise BookConstructionError(
                "the composite book's signals sum to zero information ratio, so "
                "no signal has a standing to weight the book; a book of "
                "zero-standing signals has no composite"
            )
        for signal_id, ir in captured_irs.items():
            expected = ir / total
            if captured_weights[signal_id] != expected:
                raise BookConstructionError(
                    f"the composite book says the weight for signal {signal_id!r} "
                    f"is {captured_weights[signal_id]!r} but its information "
                    f"ratio {ir!r} over the total {total!r} gives {expected!r}; "
                    "the record disagrees with itself — a weight is IR_i / Σ_j IR_j"
                )
        for symbol in symbols:
            recombinant = math.fsum(
                captured_weights[signal_id] * captured_contrib[signal_id][symbol]
                for signal_id in captured_irs
            )
            if captured_scores[symbol] != recombinant:
                raise BookConstructionError(
                    f"the composite book says the target score for symbol "
                    f"{symbol!r} is {captured_scores[symbol]!r} but its own "
                    "weighted average of the contributing scores gives "
                    f"{recombinant!r}; the record disagrees with itself — a "
                    "composite score is the weighted average of its contributing "
                    "scores under the carried weights"
                )


def combine(signals: Iterable[object]) -> CompositeBook:
    """Combine the promoted signals by information-ratio weighting — 301's answer.

    Feature 301's verb, in the order the refusals must fire.  ``signals`` is
    the promoted signals — each a :class:`PromotedSignal` (or any object
    exposing the same ``signal_id`` / ``information_ratio`` / ``target_scores``
    surface; a member never isinstance-gates the value a composition seam
    hands out, so the surface is read, not the type) — and the answer is a
    frozen :class:`CompositeBook` holding one composite target score per
    symbol, weighted by each signal's information ratio.

    The steps, in the order they must happen, each refusal leaving no value:
    (1) collect the signals, refusing an empty set as ``empty_book``; (2) read
    each signal's ``signal_id``, refusing a blank or absent one as
    ``unnamed_signal`` and a ``signal_id`` already seen as
    ``duplicate_signal``; (3) read each ``information_ratio``, refusing a
    non-finite one as ``non_finite_ir`` and a non-positive one as
    ``non_positive_ir`` — a ratio that is not a positive standing is refused,
    not zero-weighted; (4) read each signal's ``target_scores``, refusing an
    empty or malformed mapping as ``signal_without_scores`` and a non-finite
    score as ``non_finite_score``; (5) resolve the symbol set as the union of
    the signals' symbols and require every signal to carry a score for every
    symbol in it, refusing a gap as ``uncovered_symbol``; (6) form the total
    weight ``W = Σ_i IR_i`` and each normalized weight ``w_i = IR_i / W``;
    (7) form each symbol's composite as the weighted average of its scores
    under the normalized weights and answer the :class:`CompositeBook`, whose
    construction re-checks that every composite equals its own weighted
    average.

    Refuses with :class:`BookConstructionError`, each with its greppable code
    and the signal (and symbol, where relevant) named.  Deterministic and
    order-independent: the composite is a sum over signals, so a re-run over
    the same signals in a different order answers an identical book, and
    symbols are emitted sorted.
    """
    if signals is None:
        raise BookConstructionError(
            "empty_book: combine takes the promoted signals to weight into a "
            "book, got None; hand the promoted signals, or an empty iterable "
            "to be refused as empty_book"
        )
    if isinstance(signals, (str, bytes)) or not isinstance(signals, Iterable):
        raise BookConstructionError(
            "empty_book: combine takes an iterable of promoted signals, got "
            f"{type(signals).__name__}; the signals are the book"
        )
    collected = list(signals)
    if not collected:
        raise BookConstructionError(
            "empty_book: combine was handed no promoted signals, so there is "
            "nothing to weight into a composite; a book of zero signals has no "
            "composite"
        )

    information_ratios: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    for signal in collected:
        raw_id = getattr(signal, "signal_id", _MISSING)
        if raw_id is _MISSING or not isinstance(raw_id, str) or not raw_id.strip():
            raise BookConstructionError(
                "unnamed_signal: a promoted signal carries no signal_id to "
                f"attribute a weight to, got {raw_id!r}"
            )
        signal_id = raw_id.strip()
        if signal_id in information_ratios:
            raise BookConstructionError(
                f"duplicate_signal: two promoted signals carry signal_id "
                f"{signal_id!r}, so a weight could not be attributed to one "
                "signal; one signal, one id"
            )
        raw_ir = getattr(signal, "information_ratio", _MISSING)
        if raw_ir is _MISSING:
            raise BookConstructionError(
                f"non_finite_ir: promoted signal {signal_id!r} carries no "
                "information_ratio; a signal that states no standing cannot "
                "weight the book"
            )
        if isinstance(raw_ir, bool) or not isinstance(raw_ir, (int, float)):
            raise BookConstructionError(
                f"non_finite_ir: promoted signal {signal_id!r}'s "
                f"information_ratio must be a finite real, got {raw_ir!r}"
            )
        ir = float(raw_ir)
        if not math.isfinite(ir):
            raise BookConstructionError(
                f"non_finite_ir: promoted signal {signal_id!r}'s "
                f"information_ratio is not finite ({raw_ir!r}); a NaN or ±inf "
                "would reach the composite dressed as a standing"
            )
        if ir <= 0.0:
            raise BookConstructionError(
                f"non_positive_ir: promoted signal {signal_id!r}'s "
                f"information_ratio is {ir!r}, so its standing to weight the "
                "book is undefined; a non-positive ratio is refused rather than "
                "zero-weighted, because silently dropping a losing signal would "
                "hide a portfolio decision"
            )

        raw_scores = getattr(signal, "target_scores", _MISSING)
        if raw_scores is _MISSING or not isinstance(raw_scores, Mapping):
            raise BookConstructionError(
                f"signal_without_scores: promoted signal {signal_id!r} carries "
                "no target_scores mapping; a signal that expresses no view "
                "contributes nothing"
            )
        if not raw_scores:
            raise BookConstructionError(
                f"signal_without_scores: promoted signal {signal_id!r} carries "
                "an empty target_scores; a signal that expresses no view "
                "contributes nothing"
            )
        scores: dict[str, float] = {}
        for symbol, score in raw_scores.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise BookConstructionError(
                    f"signal_without_scores: promoted signal {signal_id!r}'s "
                    f"target_scores must be keyed by non-empty symbols, got "
                    f"{symbol!r}"
                )
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise BookConstructionError(
                    f"non_finite_score: promoted signal {signal_id!r}'s score "
                    f"for symbol {symbol!r} must be a finite real, got {score!r}"
                )
            number = float(score)
            if not math.isfinite(number):
                raise BookConstructionError(
                    f"non_finite_score: promoted signal {signal_id!r}'s score "
                    f"for symbol {symbol!r} is not finite ({score!r}); a NaN or "
                    "±inf would reach the composite dressed as a measurement"
                )
            scores[symbol] = number

        information_ratios[signal_id] = ir
        contributions[signal_id] = scores

    # Full coverage: every signal must score every symbol the book covers —
    # the union of the signals' symbol sets — so the composite over a symbol
    # is the weighted average across all the signals, not a partial one.
    symbols: set[str] = set()
    for per_symbol in contributions.values():
        symbols.update(per_symbol)
    for signal_id, per_symbol in contributions.items():
        for symbol in sorted(symbols):
            if symbol not in per_symbol:
                raise BookConstructionError(
                    f"uncovered_symbol: promoted signal {signal_id!r} carries "
                    f"no target score for symbol {symbol!r}, which the book "
                    "covers; every signal must score every symbol the book "
                    "covers — a signal that expresses no view on a symbol must "
                    "not be read as expressing the worst one"
                )

    # Information-ratio weighting: w_i = IR_i / Σ_j IR_j, and the composite is
    # the weighted average of each symbol's scores under those weights.  A sum
    # over signals, so it is order-independent; symbols are emitted sorted.
    total = math.fsum(information_ratios.values())
    weights = {signal_id: ir / total for signal_id, ir in information_ratios.items()}
    composite = {
        symbol: math.fsum(
            weights[signal_id] * contributions[signal_id][symbol]
            for signal_id in information_ratios
        )
        for symbol in sorted(symbols)
    }

    return CompositeBook(
        scores=composite,
        weights=weights,
        information_ratios=information_ratios,
        contributions=contributions,
    )
