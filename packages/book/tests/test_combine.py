"""The book combiner: IR-weighting, the composite, and every refusal.

This is feature 301's verb from the caller's side — the promoted signals go
in, the single composite target score per symbol comes out, weighted by
each signal's information ratio.  The act is pure arithmetic over the
signals it is handed: it writes no file, opens no database, reads no
environment variable and consults no clock, so no autouse fixture guards any
of its tests — what a test configures, it configures explicitly.

Three properties these tests pin, and each is the feature's own decision
rather than a knob:

* **the weight is the information ratio.**  Signal *i* enters the book with
  weight ``IR_i`` and the composite is the weighted average under those
  weights — so the fixtures' dyadic IRs (1.0, 2.0, 1.0) make every composite
  checkable with ``==``.
* **absence is not zero.**  A non-positive or non-finite information ratio
  is refused, not zero-weighted; a signal missing a symbol is refused, not
  zero-filled.  Each refusal is tested against a fixture that names it, not
  against a defaulted zero.
* **the composite is a check, not a claim.**  :class:`book.CompositeBook`
  carries the composite, the weights, the ratios and the contributions, and
  construction enforces that every composite equals its own weighted
  average — so a hand-built book that disagrees with itself is refused.
"""

from __future__ import annotations

import math
import typing
from dataclasses import FrozenInstanceError

import pytest
from book import BookConstructionError, CompositeBook, PromotedSignal, combine
from book._combine import _validate_number
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal


def test_combine_returns_one_composite_target_score_per_symbol(
    signals: list[PromotedSignal],
) -> None:
    """The sentence's answer: one composite target score per symbol."""
    book = combine(signals)
    assert sorted(book.scores) == [BTC, ETH, SOL]
    # IRs (1.0, 2.0, 1.0) → weights (¼, ½, ¼); the composites are the
    # weighted averages, dyadic, checkable with ==.
    assert book.scores[BTC] == 0.25 * 0.25 + 0.125 * 0.5 + 0.25 * 0.25
    assert book.scores[ETH] == 0.125 * 0.25 + 0.25 * 0.5 + 0.25 * 0.25
    assert book.scores[SOL] == 0.25 * 0.25 + 0.25 * 0.5 + 0.125 * 0.25
    assert book.scores[BTC] == 0.1875
    assert book.scores[ETH] == 0.21875
    assert book.scores[SOL] == 0.21875


def test_target_score_answers_the_composite_for_one_symbol(
    signals: list[PromotedSignal],
) -> None:
    """target_score(symbol) is the ranking's entry for that symbol."""
    book = combine(signals)
    assert book.target_score(BTC) == book.scores[BTC]
    assert book.target_score(ETH) == book.scores[ETH]
    assert book.target_score(SOL) == book.scores[SOL]


def test_target_score_refuses_a_symbol_the_book_does_not_cover(
    signals: list[PromotedSignal],
) -> None:
    """A symbol the composite holds no score for is refused, not zeroed."""
    book = combine(signals)
    with pytest.raises(BookConstructionError) as excinfo:
        book.target_score("DOGE")
    assert excinfo.value.args[0].startswith("uncovered_symbol")
    assert "DOGE" in excinfo.value.args[0]


def test_weights_sum_to_one_and_rank_by_information_ratio(
    signals: list[PromotedSignal],
) -> None:
    """The normalized weights sum to one and rank the signals by IR."""
    book = combine(signals)
    assert math.fsum(book.weights.values()) == pytest.approx(1.0)
    # SIGNAL_TWO carries IR 2.0, half the total weight; the two IR-1.0
    # signals carry a quarter each.
    assert book.weights[SIGNAL_ONE] == pytest.approx(0.25)
    assert book.weights[SIGNAL_TWO] == pytest.approx(0.5)
    assert book.weights[SIGNAL_THREE] == pytest.approx(0.25)
    assert book.weights[SIGNAL_TWO] > book.weights[SIGNAL_ONE]
    assert book.information_ratios[SIGNAL_TWO] == 2.0


def test_composite_is_the_weighted_average_of_the_contributing_scores(
    signals: list[PromotedSignal],
) -> None:
    """The record is a check: each composite equals its own weighted average."""
    book = combine(signals)
    for symbol in (BTC, ETH, SOL):
        recombinant = math.fsum(
            book.weights[sig.signal_id] * book.contributions[sig.signal_id][symbol]
            for sig in signals
        )
        assert book.scores[symbol] == recombinant


def test_combine_is_order_independent(signals: list[PromotedSignal]) -> None:
    """The composite is a sum over signals, so order does not move it."""
    forward = combine(signals)
    reversed_signals = list(reversed(signals))
    backward = combine(reversed_signals)
    assert backward.scores == forward.scores
    assert backward.weights == forward.weights
    assert backward.information_ratios == forward.information_ratios


def test_combine_accepts_duck_typed_signals() -> None:
    """The seam reads the surface, not the type — a stand-in combines."""
    stand_ins = [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.2, ETH: 0.1, SOL: 0.3}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.1, ETH: 0.3, SOL: 0.2}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.3, ETH: 0.2, SOL: 0.1}),
    ]
    book = combine(stand_ins)
    assert book.scores[BTC] == pytest.approx(0.175)


def test_empty_book_is_refused() -> None:
    """A book of zero signals has no composite."""
    with pytest.raises(BookConstructionError) as excinfo:
        combine([])
    assert excinfo.value.args[0].startswith("empty_book")


def test_none_signals_is_refused() -> None:
    """None is not an empty iterable — it is no book at all."""
    with pytest.raises(BookConstructionError) as excinfo:
        combine(None)  # type: ignore[arg-type]
    assert excinfo.value.args[0].startswith("empty_book")


def test_non_iterable_signals_is_refused() -> None:
    """A bare signal is not a book of signals."""
    with pytest.raises(BookConstructionError) as excinfo:
        combine(PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 0.2}))  # type: ignore[arg-type]
    assert excinfo.value.args[0].startswith("empty_book")


def test_unnamed_signal_is_refused() -> None:
    """A signal that names no id cannot have a weight attributed to it.

    Read off a duck-typed stand-in, not a ``PromotedSignal``: construction of
    a real signal would refuse a blank id first, so the seam's own
    ``unnamed_signal`` check — the one that also covers an *absent* ``signal_id``
    attribute — is exercised by handing ``combine`` a value that never went
    through construction.  That is the point of the duck-typed seam: it
    validates what it reads, not the type it was handed.
    """
    signals = [
        StandInSignal("  ", 1.0, {BTC: 0.2, ETH: 0.1, SOL: 0.3}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.1, ETH: 0.3, SOL: 0.2}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.3, ETH: 0.2, SOL: 0.1}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("unnamed_signal")


def test_unnamed_signal_with_absent_attribute_is_refused() -> None:
    """An absent ``signal_id`` attribute is refused exactly as a blank one.

    A bare object exposing only the two other attributes — no ``signal_id`` at
    all — so the ``getattr(..., _MISSING)`` default is the branch under test.
    """

    class _BareSignal:
        information_ratio: typing.ClassVar[float] = 1.0
        target_scores: typing.ClassVar[dict[str, float]] = {
            BTC: 0.2,
            ETH: 0.1,
            SOL: 0.3,
        }

    signals = [
        _BareSignal(),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.1, ETH: 0.3, SOL: 0.2}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.3, ETH: 0.2, SOL: 0.1}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("unnamed_signal")


def test_duplicate_signal_is_refused() -> None:
    """Two signals sharing an id cannot both carry a weight."""
    signals = [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_ONE, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("duplicate_signal")
    assert SIGNAL_ONE in excinfo.value.args[0]


def test_non_positive_ir_is_refused_not_zero_weighted() -> None:
    """A losing signal is refused, not silently dropped from the book."""
    signals = [
        StandInSignal(SIGNAL_ONE, 0.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("non_positive_ir")
    assert SIGNAL_ONE in excinfo.value.args[0]


def test_negative_ir_is_refused() -> None:
    """A negative standing is refused exactly as a zero one is."""
    signals = [
        StandInSignal(SIGNAL_ONE, -0.5, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("non_positive_ir")


def test_non_finite_ir_is_refused() -> None:
    """A NaN standing would reach the composite dressed as a measurement."""
    signals = [
        StandInSignal(SIGNAL_ONE, float("nan"), {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("non_finite_ir")


def test_signal_without_scores_is_refused() -> None:
    """A signal that expresses no view contributes nothing."""
    signals = [
        StandInSignal(SIGNAL_ONE, 1.0, {}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("signal_without_scores")


def test_non_finite_score_is_refused() -> None:
    """A non-finite score would reach the composite dressed as a view."""
    signals = [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: float("inf"), ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("non_finite_score")
    assert BTC in excinfo.value.args[0]


def test_uncovered_symbol_is_refused_not_zero_filled() -> None:
    """A signal missing a covered symbol is refused — absence is not a view."""
    signals = [
        StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125}),  # no SOL
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError) as excinfo:
        combine(signals)
    assert excinfo.value.args[0].startswith("uncovered_symbol")
    assert SIGNAL_ONE in excinfo.value.args[0]
    assert SOL in excinfo.value.args[0]


def test_refused_combine_forms_no_value() -> None:
    """A refused combine leaves no composite behind."""
    signals = [
        StandInSignal(SIGNAL_ONE, 0.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
        StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
        StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
    ]
    with pytest.raises(BookConstructionError):
        combine(signals)


def test_validate_number_rejects_bool() -> None:
    """A bool is a flag, not a measurement — refused on the numeric seam."""
    with pytest.raises(BookConstructionError):
        _validate_number(True, "a score")


def test_promoted_signal_freezes_after_construction() -> None:
    """A promoted signal is a recorded fact — a later edit must not move it."""
    signal = PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 0.2, ETH: 0.1, SOL: 0.3})
    with pytest.raises(FrozenInstanceError):
        signal.information_ratio = 9.0  # type: ignore[misc]


def test_promoted_signal_rejects_blank_id() -> None:
    """The value admits only what the combiner can score."""
    with pytest.raises(BookConstructionError) as excinfo:
        PromotedSignal("", 1.0, {BTC: 0.2})
    assert excinfo.value.args[0].startswith("unnamed_signal")


def test_promoted_signal_rejects_nan_ratio_at_construction() -> None:
    """A non-finite ratio is caught where the signal is built."""
    with pytest.raises(BookConstructionError):
        PromotedSignal(SIGNAL_ONE, float("nan"), {BTC: 0.2})


def test_promoted_signal_rejects_non_finite_score_at_construction() -> None:
    """A non-finite score is caught where the signal is built."""
    with pytest.raises(BookConstructionError):
        PromotedSignal(SIGNAL_ONE, 1.0, {BTC: float("inf")})


def test_promoted_signal_rejects_empty_scores_at_construction() -> None:
    """A signal that expresses no view is caught where it is built."""
    with pytest.raises(BookConstructionError):
        PromotedSignal(SIGNAL_ONE, 1.0, {})


def test_composite_book_rejects_self_inconsistent_composite() -> None:
    """A hand-built book whose composite is not its own weighted average is
    refused — the record is a check, not a claim."""
    with pytest.raises(BookConstructionError):
        CompositeBook(
            scores={BTC: 0.999},  # not the weighted average below
            weights={SIGNAL_ONE: 0.5, SIGNAL_TWO: 0.5},
            information_ratios={SIGNAL_ONE: 1.0, SIGNAL_TWO: 1.0},
            contributions={
                SIGNAL_ONE: {BTC: 0.2},
                SIGNAL_TWO: {BTC: 0.4},
            },
        )


def test_composite_book_rejects_self_inconsistent_weight() -> None:
    """A hand-built book whose weight is not IR_i / Σ_j IR_j is refused."""
    with pytest.raises(BookConstructionError):
        CompositeBook(
            scores={BTC: 0.3},
            weights={SIGNAL_ONE: 0.9, SIGNAL_TWO: 0.1},  # not 0.5 / 0.5
            information_ratios={SIGNAL_ONE: 1.0, SIGNAL_TWO: 1.0},
            contributions={
                SIGNAL_ONE: {BTC: 0.2},
                SIGNAL_TWO: {BTC: 0.4},
            },
        )


def test_composite_book_rejects_non_finite_score() -> None:
    """A non-finite composite score would rank above an honest one."""
    with pytest.raises(BookConstructionError):
        CompositeBook(
            scores={BTC: float("nan")},
            weights={SIGNAL_ONE: 0.5, SIGNAL_TWO: 0.5},
            information_ratios={SIGNAL_ONE: 1.0, SIGNAL_TWO: 1.0},
            contributions={
                SIGNAL_ONE: {BTC: 0.2},
                SIGNAL_TWO: {BTC: 0.4},
            },
        )
