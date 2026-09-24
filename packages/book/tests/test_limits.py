"""Feature 304's claim, stated as tests: the two bounds.

app_spec.xml, "Portfolio Book Construction", feature 304: *System applies
per-position and concentration limits, which rejects a target weight breaching
either bound.*  docs/alpha-engine-prd.md §C8 puts the step in the
construction's own chain — *"Signal book → IR-weighted combination with
shrinkage → volatility targeting → position and concentration limits →
orders.  Version-controlled, human-authored, explicitly outside the search
space."* — and docs/nullius-tech-architecture.md §13.1 states it as the live
path's book manager, one step before the target weights the order layer
consumes.  Neither document states a figure for either bound, so both figures
are a deployment's and this suite pins the act that applies them.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the two bounds are different facts about the same book** — a *position's
  size* (``|w_s| ≤ per_position_limit``) and the book's *shape*
  (``max_s |w_s| / Σ_t |w_t| ≤ concentration_limit``) — and neither subsumes
  the other, because feature 303's scaling multiplies every weight by one
  factor and therefore moves the first while leaving the second exactly where
  feature 301's ranking put it.  The scale-invariance of the concentration is
  the load-bearing half of that claim;
* **the bounds reject, they never reshape** — a breaching book is refused
  rather than scaled down, re-weighted or clamped, because reshaping a
  caller's book would be this member sizing it rather than bounding it, and a
  caller told its book passed would be handed a book nobody chose;
* **both limits are the deployment's figures** — required keywords with no
  defaults, on both the predicate and the verdict, so no module and no
  composition carries a fallback risk bound;
* **absence is not zero, and the two zeros are different facts** — a *zero
  limit* is answered (it admits exactly the flat book, the appetite's own
  consequence), while a target weight that is not a finite real is refused;
  and the flat book's *concentration* is answered as ``0.0`` rather than
  refused, because a book that holds nothing is genuinely not concentrated;
* **the edge is inclusive on the admitted side** — a weight exactly at a limit
  is admitted, one float above it is refused;
* **the ask settles before the judgment** — a malformed limit is refused
  before any book is judged, however breaching that book meant to be, and a
  value that is not a target-weight set is refused as the ask's own fact;
* **the vocabulary is the act's own two classes** — the ask
  (:class:`book.LimitRequestError`) and the one judgment the sentence mints
  (:class:`book.LimitBreachError`), both under the member's
  :class:`book.BookConstructionError`, and a caller must be able to catch one
  without catching the other.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
from pathlib import Path

import pytest
from book import (
    CONCENTRATION_LIMIT_CODE,
    PER_POSITION_LIMIT_CODE,
    BookConstructionError,
    CompositeBook,
    LimitBreachError,
    LimitRequestError,
    PromotedSignal,
    apply_volatility_target,
    combine,
    concentration,
    is_breaching_limits,
    rejects_breaching_target_weights,
)
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal

#: The module the layering pin at the foot of this file parses — anchored to
#: the file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_limits.py"

#: The figures the conftest's three signals answer under feature 303's act, all
#: dyadic so every one is checkable with ``==``.  The composites are 0.1875 /
#: 0.21875 / 0.21875 and sum in absolute value to 0.625, so at a book
#: volatility of 0.5 and a configured target of 0.2 the gross weights are
#: 0.3 / 0.35 / 0.35 and the scaled weights are 0.12 / 0.14 / 0.14.
BOOK_VOLATILITY = 0.5
TARGET_VOLATILITY = 0.2
SCALE = TARGET_VOLATILITY / BOOK_VOLATILITY
BTC_WEIGHT = 0.12
MAJOR_WEIGHT = 0.14
GROSS_EXPOSURE = 0.4

#: The book's concentration at those figures — the largest position (ETH and
#: SOL, tied) over the gross exposure.  The module computes it as
#: ``math.fsum(0.14, 0.14, 0.12)`` over ``0.14 / 0.39999999999999997``, and
#: that lands **exactly** on ``0.35`` — which is why this suite can pin both
#: bounds' edges with ``==`` and ``math.nextafter``.  (The *abstract* quotient
#: ``MAJOR_WEIGHT / GROSS_EXPOSURE`` is ``0.35000000000000003``, one float
#: above: the same operation performed on rounded inputs, and not the figure.)
BOOK_CONCENTRATION = 0.35


def _book() -> CompositeBook:
    """The combined book the conftest's three signals answer."""
    return combine(
        [
            PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
            PromotedSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
            PromotedSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
        ]
    )


def _weights():
    """Feature 303's answer for that book at the suite's two figures."""
    return apply_volatility_target(
        _book(), volatility=BOOK_VOLATILITY, target_volatility=TARGET_VOLATILITY
    )


@dataclasses.dataclass(frozen=True)
class _StandInWeights:
    """A stand-in for the target weights.

    The act reads the ``weights`` mapping duck-typed — the loader imports
    members under synthetic names and re-executes them, so a value this process
    composed may be a second class object — and this is the shape that proves
    it: exactly one attribute, ``weights``, nothing else.  Feature 303's record
    enforces its own internal consistency (its gross book, its scale, its
    figures), which makes it the wrong tool for probing *one* bound in
    isolation; a stand-in carrying only the positions exercises the seam the
    act actually depends on, and nothing more.
    """

    weights: dict[str, float]


def _limits(
    weights: dict[str, float],
    *,
    per_position: float = 1.0,
    concentration_limit: float = 1.0,
) -> None:
    """Run the verdict over a bare weight set — the suite's one call shape."""
    rejects_breaching_target_weights(
        _StandInWeights(weights),
        per_position_limit=per_position,
        concentration_limit=concentration_limit,
    )


class TestThePerPositionBoundIsAPositionSize:
    """``|w_s| ≤ per_position_limit`` — a magnitude, not a direction."""

    def test_a_book_inside_the_bound_is_admitted(self):
        """The ordinary case: every position under the limit."""
        assert (
            rejects_breaching_target_weights(
                _weights(), per_position_limit=0.2, concentration_limit=1.0
            )
            is None
        )

    def test_a_position_above_the_bound_is_refused(self):
        """One oversized position is the whole refusal."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.3, ETH: 0.1}, per_position=0.2)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_a_large_short_breaches_exactly_as_a_large_long_does(self):
        """The bound is a *size*, so the sign cannot be a route around it.

        A book that held arbitrary exposure by flipping signs would not be
        bounded at all, and §C8's chain applies the bound to the weights
        feature 303 returned — magnitudes — rather than to the views behind
        them.
        """
        with pytest.raises(LimitBreachError) as short:
            _limits({BTC: -0.3, ETH: 0.1}, per_position=0.2)
        with pytest.raises(LimitBreachError) as long:
            _limits({BTC: 0.3, ETH: 0.1}, per_position=0.2)
        assert str(short.value).startswith(PER_POSITION_LIMIT_CODE)
        assert str(long.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_a_weight_exactly_at_the_bound_is_admitted(self):
        """The edge is inclusive: a limit is a budget, not a floor.

        ``0.14`` at a ``0.14`` limit runs — the same edge feature 308 states
        for its cap (*"``ceiling`` itself runs, ``ceiling + 1`` does not"*) and
        Appendix B's *"use ≤ ¼ Kelly"* states for the quarter.
        """
        _limits(
            {BTC: MAJOR_WEIGHT, ETH: BTC_WEIGHT, SOL: MAJOR_WEIGHT},
            per_position=MAJOR_WEIGHT,
        )
        assert (
            rejects_breaching_target_weights(
                _weights(), per_position_limit=MAJOR_WEIGHT, concentration_limit=1.0
            )
            is None
        )

    def test_one_float_above_the_bound_is_refused(self):
        """The strictness is the sentence's word: *breaching*, not reaching."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: math.nextafter(0.3, math.inf), ETH: 0.1}, per_position=0.3)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_the_refusal_names_every_position_above_the_bound(self):
        """Every offender is stated, because they share one repair.

        A caller told only about the first would lower it and come back to the
        same refusal — the message names the symbols and the weights the
        caller has to fix.
        """
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.4, ETH: 0.3, SOL: 0.05}, per_position=0.2)
        message = str(caught.value)
        assert "'BTC' at 0.4" in message
        assert "'ETH' at 0.3" in message
        assert "2 of the book's positions" in message

    def test_the_refusal_states_that_a_short_breaches_too(self):
        """The message carries the reading, not just the verdict."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: -0.3, ETH: 0.1}, per_position=0.2)
        assert "a short at -0.30 breaches a 0.20 limit" in str(caught.value)


class TestTheConcentrationBoundIsTheBooksShape:
    """``max_s |w_s| / Σ_t |w_t| ≤ concentration_limit`` — a scale-free share."""

    def test_the_figure_is_the_largest_positions_share_of_gross(self):
        """The one arithmetic the sentence's second bound is stated over.

        The exposure figure itself is ``math.fsum`` of three dividends that are
        not exact in binary — ``0.39999999999999997`` — so the chain's own
        figures are read with ``pytest.approx`` while the *concentration* is
        read with ``==``: it is one division of one sum by another, the same
        operations feature 303 performed, and that lands exactly on ``0.35``
        (the abstract quotient ``0.14 / 0.4`` is ``0.35000000000000003``, one
        float above — the same operation on rounded inputs, and not the
        figure).  The edges this suite pins are exact for that reason.
        """
        target = _weights()
        assert concentration(target) == BOOK_CONCENTRATION
        assert concentration(target) == max(abs(w) for w in target.weights.values()) / math.fsum(
            abs(w) for w in target.weights.values()
        )
        assert target.gross_exposure == pytest.approx(GROSS_EXPOSURE)

    def test_a_book_inside_the_bound_is_admitted(self):
        assert (
            rejects_breaching_target_weights(
                _weights(), per_position_limit=1.0, concentration_limit=0.4
            )
            is None
        )

    def test_a_book_above_the_bound_is_refused(self):
        """A share above the limit is the refusal, and names the share."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.1, ETH: 0.4}, concentration_limit=0.5)
        assert str(caught.value).startswith(CONCENTRATION_LIMIT_CODE)

    def test_a_book_inside_the_position_bound_can_breach_this_one(self):
        """The two bounds are orthogonal, and this is the shape that shows it.

        Every position is ``0.3`` — comfortably inside a ``0.5`` per-position
        limit — but the largest is half the book's gross exposure, above a
        ``0.25`` concentration limit.  Nowhere for the position bound to fire,
        so the whole refusal is the book's shape.
        """
        assert is_breaching_limits(
            _StandInWeights({BTC: 0.3, ETH: 0.3}),
            per_position_limit=0.5,
            concentration_limit=0.25,
        )
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.3, ETH: 0.3}, per_position=0.5, concentration_limit=0.25)
        assert str(caught.value).startswith(CONCENTRATION_LIMIT_CODE)

    def test_a_book_inside_the_concentration_bound_can_breach_the_other(self):
        """And the other way round — neither bound subsumes the other."""
        weights = {BTC: 0.4, ETH: 0.2, SOL: 0.2, "ADA": 0.2}
        # Largest share is 0.4 / 1.0 = 0.4, inside a 0.5 concentration limit;
        # the position itself is above a 0.3 per-position limit.
        assert concentration(_StandInWeights(weights)) == 0.4
        with pytest.raises(LimitBreachError) as caught:
            _limits(weights, per_position=0.3, concentration_limit=0.5)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_the_per_position_bound_fires_first_when_both_are_breached(self):
        """The sentence's own order — *"per-position and concentration"*.

        A book that breaches both is refused over its positions, which is the
        local repair: a caller told about the position is never left believing
        the whole shape was the fault.
        """
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.6, ETH: 0.4}, per_position=0.5, concentration_limit=0.5)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_a_weight_exactly_at_the_bound_is_admitted(self):
        """Inclusive on the admitted side, like the position bound."""
        assert (
            rejects_breaching_target_weights(
                _weights(),
                per_position_limit=1.0,
                concentration_limit=BOOK_CONCENTRATION,
            )
            is None
        )
        with pytest.raises(LimitBreachError):
            _limits(
                {BTC: BTC_WEIGHT, ETH: MAJOR_WEIGHT, SOL: MAJOR_WEIGHT},
                concentration_limit=math.nextafter(BOOK_CONCENTRATION, 0.0),
            )

    def test_the_refusal_states_the_largest_position_the_gross_and_the_share(self):
        """The figures a caller needs to see the arithmetic, not take it on faith."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.2, ETH: 0.8}, concentration_limit=0.5)
        message = str(caught.value)
        assert "'ETH' at 0.8" in message
        assert "Σ_s |w_s| = 1.0" in message
        assert "0.8" in message
        assert "2 symbols the book covers" in message

    def test_the_refusal_states_the_repair_and_what_this_module_will_not_do(self):
        """*Hold more names* — and neither a re-weighting nor a rescaling."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.2, ETH: 0.8}, concentration_limit=0.5)
        message = str(caught.value)
        assert "hold more names" in message
        assert "neither re-weights the book" in message
        assert "nor scales it down" in message

    def test_the_largest_position_is_named_even_when_several_tie(self):
        """A tie is named in full, so the refusal is not arbitrary."""
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.5, ETH: 0.5}, concentration_limit=0.4)
        message = str(caught.value)
        assert "'BTC' at 0.5" in message
        assert "'ETH' at 0.5" in message


class TestTheConcentrationIsScaleFreeAndThatIsWhyItIsASecondBound:
    """Feature 303's scaling moves the size bound and not this one."""

    def test_scaling_the_book_leaves_the_concentration_where_the_ranking_put_it(self):
        """The property that makes the two bounds genuinely different.

        A book scaled to a higher volatility target has larger positions and
        the same shape: the concentration is invariant under the act one step
        before this one, which is what lets §C8's chain apply this bound after
        that act rather than before it.
        """
        book = _book()
        gentle = apply_volatility_target(
            book, volatility=0.5, target_volatility=0.2
        )
        levered = apply_volatility_target(
            book, volatility=0.1, target_volatility=0.2
        )
        assert concentration(gentle) == concentration(levered)
        assert levered.gross_exposure > gentle.gross_exposure
        # The size bound, by contrast, is exactly what the scaling moves: the
        # same book passes it at one target and breaches it at the other.
        assert (
            rejects_breaching_target_weights(
                gentle, per_position_limit=MAJOR_WEIGHT, concentration_limit=1.0
            )
            is None
        )
        with pytest.raises(LimitBreachError) as caught:
            rejects_breaching_target_weights(
                levered, per_position_limit=MAJOR_WEIGHT, concentration_limit=1.0
            )
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_concentration_is_invariant_over_a_scaled_stand_in(self):
        """The same fact read without the member's own record."""
        base = {BTC: 0.3, ETH: 0.35, SOL: 0.35}
        assert concentration(_StandInWeights(base)) == concentration(
            _StandInWeights({symbol: 4.0 * weight for symbol, weight in base.items()})
        )

    def test_a_one_name_book_is_maximally_concentrated(self):
        """The figure's ceiling is exactly 1.0, so a limit of 1.0 is a bound.

        ``1.0`` admits every book, and a limit just below it admits none but
        the perfectly spread ones — which is what makes the configured figure
        legible rather than an arbitrary index.
        """
        assert concentration(_StandInWeights({BTC: 0.4})) == 1.0
        assert (
            rejects_breaching_target_weights(
                _StandInWeights({BTC: 0.4}),
                per_position_limit=1.0,
                concentration_limit=1.0,
            )
            is None
        )

    def test_a_spread_book_has_a_small_concentration(self):
        """And the figure falls toward zero as the book spreads."""
        wide = {symbol: 0.1 for symbol in ("A", "B", "C", "D", "E")}
        assert concentration(_StandInWeights(wide)) == pytest.approx(0.2)
        assert concentration(_StandInWeights(wide)) < concentration(
            _StandInWeights({BTC: 0.4, ETH: 0.6})
        )


class TestTheFlatBookIsNotConcentrated:
    """A book at no exposure holds nothing, so it is not spread oddly either."""

    def test_the_flat_books_concentration_is_zero(self):
        """``0/0`` would be a division by nothing; the answer is the floor.

        Feature 303 refuses a flat *composite* because the weights it would
        have to invent are a decision nobody made.  This is the different
        fact: the target weights exist — feature 303 answers exactly this set
        for a configured target of zero — and a book that holds nothing is
        genuinely not concentrated, so ``0.0`` is a description rather than a
        fabrication.
        """
        flat = apply_volatility_target(
            _book(), volatility=BOOK_VOLATILITY, target_volatility=0.0
        )
        assert all(weight == 0.0 for weight in flat.weights.values())
        assert concentration(flat) == 0.0

    def test_the_flat_book_is_admitted_by_both_bounds_at_every_limit(self):
        """Feature 303's zero-target book is the appetite's own consequence."""
        flat = apply_volatility_target(
            _book(), volatility=BOOK_VOLATILITY, target_volatility=0.0
        )
        assert (
            rejects_breaching_target_weights(
                flat, per_position_limit=0.0, concentration_limit=0.0
            )
            is None
        )
        assert (
            rejects_breaching_target_weights(
                flat, per_position_limit=1.0, concentration_limit=1.0
            )
            is None
        )
        assert not is_breaching_limits(
            flat, per_position_limit=0.0, concentration_limit=0.0
        )

    def test_no_other_book_answers_a_zero_concentration(self):
        """So ``0.0`` means exactly one thing, and a zero limit means one thing.

        Every book that holds something has a largest position and a gross
        exposure, both strictly positive, so a zero concentration limit admits
        exactly the flat book — and this is that reading, exercised.
        """
        for weights in (
            {BTC: 0.1},
            {BTC: 0.1, ETH: -0.1},
            {BTC: -0.5, ETH: 0.5},
            {BTC: 0.0001, ETH: 0.0002},
        ):
            assert concentration(_StandInWeights(weights)) > 0.0
            with pytest.raises(LimitBreachError) as caught:
                _limits(weights, per_position=1.0, concentration_limit=0.0)
            assert str(caught.value).startswith(CONCENTRATION_LIMIT_CODE)

    def test_a_zero_position_limit_admits_only_the_flat_book(self):
        """The same edge on the first bound, read the same way."""
        _limits({BTC: 0.0, ETH: 0.0}, per_position=0.0, concentration_limit=1.0)
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.01, ETH: 0.0}, per_position=0.0, concentration_limit=1.0)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)


class TestTheTwoLimitsAreTheDeploymentsFigures:
    """Required keywords, no defaults, on both the predicate and the verdict."""

    @pytest.mark.parametrize(
        "call", [is_breaching_limits, rejects_breaching_target_weights]
    )
    def test_both_figures_are_required_keywords_with_no_default(self, call):
        """A module-chosen fallback would be a risk bound no document states.

        §C8 and §13.1 name the step and state no figure for either bound, so
        the figures are the deployment's and arrive at the call — the boundary
        feature 303 states for its target, read on the two bounds one step
        after it.
        """
        parameters = inspect.signature(call).parameters
        assert set(parameters) == {
            "target_weights",
            "per_position_limit",
            "concentration_limit",
        }
        for name in ("per_position_limit", "concentration_limit"):
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert parameters[name].default is inspect.Parameter.empty

    def test_the_figures_cannot_cross_composition(self):
        """The factory's protocol takes no arguments, so no component carries one.

        Pinned through the builder's signature rather than this module's source,
        because the claim is about composition: a builder that had grown a
        limit keyword would be a deployment knob on the one component whose
        whole configuration is supposed to be the arithmetic.
        """
        import book as member

        assert not inspect.signature(member.build_book_combiner).parameters

    def test_the_same_book_is_judged_differently_at_different_limits(self):
        """The figures are the deployment's because they decide the verdict."""
        target = _weights()
        assert not is_breaching_limits(
            target, per_position_limit=MAJOR_WEIGHT, concentration_limit=0.4
        )
        assert is_breaching_limits(
            target, per_position_limit=0.13, concentration_limit=0.4
        )
        assert is_breaching_limits(
            target, per_position_limit=MAJOR_WEIGHT, concentration_limit=0.3
        )


class TestTheAskSettlesBeforeTheJudgment:
    """A malformed ask is refused before any book is judged."""

    def test_a_malformed_limit_is_refused_before_a_breaching_book_is_judged(self):
        """The ordering every verdict in this workspace states.

        The book here breaches both bounds at the well-formed figures, and the
        ask's class is still what fires — a caller that mis-stated a limit is
        told *what to fix*, never told its book is too concentrated.
        """
        oversized = _StandInWeights({BTC: 0.9, ETH: 0.9})
        for limits in (
            {"per_position_limit": -0.1, "concentration_limit": 1.0},
            {"per_position_limit": 0.1, "concentration_limit": -0.1},
        ):
            with pytest.raises(LimitRequestError):
                rejects_breaching_target_weights(oversized, **limits)
            with pytest.raises(LimitRequestError):
                is_breaching_limits(oversized, **limits)

    @pytest.mark.parametrize(
        "limit",
        [
            -1.0,
            -0.0001,
            float("nan"),
            float("inf"),
            float("-inf"),
            True,
            "0.2",
            None,
            [0.2],
        ],
    )
    def test_a_limit_that_is_not_a_bound_is_refused(self, limit):
        """A ``bool`` is a flag where a magnitude belongs; a ``nan`` is no bound."""
        with pytest.raises(LimitRequestError):
            _limits({BTC: 0.1}, per_position=limit)
        with pytest.raises(LimitRequestError):
            _limits({BTC: 0.1}, concentration_limit=limit)

    def test_a_zero_limit_is_answered_rather_than_refused(self):
        """*Take no position* is a level, not a malformed ask."""
        assert not is_breaching_limits(
            _StandInWeights({BTC: 0.0}), per_position_limit=0, concentration_limit=0
        )
        assert not is_breaching_limits(
            _StandInWeights({BTC: 0.0}),
            per_position_limit=0.0,
            concentration_limit=0.0,
        )

    def test_an_integer_limit_is_a_bound(self):
        """A caller whose limits are whole numbers has stated the same fact."""
        _limits({BTC: 0.5, ETH: 0.5}, per_position=1, concentration_limit=1)

    def test_a_value_that_is_not_a_target_weight_set_is_refused(self):
        """*This is not a book* and *this book holds nothing* are different."""
        for value in (None, 0.3, {BTC: 0.1}, ["BTC"], "BTC"):
            with pytest.raises(LimitRequestError):
                rejects_breaching_target_weights(
                    value, per_position_limit=1.0, concentration_limit=1.0
                )
            with pytest.raises(LimitRequestError):
                concentration(value)

    def test_a_value_that_omits_its_weights_is_distinguished_from_an_empty_book(self):
        """The sentinel's whole purpose: two different reports."""

        @dataclasses.dataclass(frozen=True)
        class NoWeights:
            positions: dict[str, float]

        with pytest.raises(LimitRequestError) as absent:
            concentration(NoWeights({BTC: 0.1}))
        with pytest.raises(LimitRequestError) as empty:
            concentration(_StandInWeights({}))
        assert "carries no ``weights``" in str(absent.value)
        assert "cover at least one symbol" in str(empty.value)

    @pytest.mark.parametrize(
        "weights",
        [
            {},
            {BTC: float("nan")},
            {BTC: float("inf")},
            {BTC: True},
            {BTC: "0.1"},
            {BTC: None},
            {None: 0.1},
            {"": 0.1},
            {"  ": 0.1},
            {0.1: 0.1},
        ],
    )
    def test_a_weight_set_that_cannot_be_a_book_is_refused(self, weights):
        """Both the predicate and the figure read the same ask."""
        with pytest.raises(LimitRequestError):
            concentration(_StandInWeights(weights))
        with pytest.raises(LimitRequestError):
            is_breaching_limits(
                _StandInWeights(weights),
                per_position_limit=1.0,
                concentration_limit=1.0,
            )

    def test_the_ask_carries_no_code_word(self):
        """A malformed ask names its subject in its first words."""
        with pytest.raises(LimitRequestError) as caught:
            _limits({BTC: 0.1}, per_position=-1.0)
        message = str(caught.value)
        assert not message.startswith(PER_POSITION_LIMIT_CODE)
        assert not message.startswith(CONCENTRATION_LIMIT_CODE)
        assert message.startswith("the per_position_limit is zero or more")

    def test_the_book_is_read_before_either_limit(self):
        """*This is not a book* is never dressed as *your limit was malformed*.

        Both are true of this call, and the book's fact is the one reported —
        the ordering every verdict and act in this workspace states, so a
        caller is told the thing it got wrong first rather than the thing it
        happened to get wrong second.
        """
        with pytest.raises(LimitRequestError) as caught:
            rejects_breaching_target_weights(
                None, per_position_limit=-1.0, concentration_limit=-1.0
            )
        assert str(caught.value).startswith("the limits judge the target weights")

    def test_the_per_position_limit_is_read_before_the_concentration_limit(self):
        """And when both limits are malformed, the sentence's first is named.

        *"per-position and concentration"* — a caller fixing one at a time is
        told the bound the sentence names first, which is also the one the
        judgment would have fired on.
        """
        with pytest.raises(LimitRequestError) as caught:
            _limits({BTC: 0.1}, per_position=-1.0, concentration_limit=-1.0)
        assert str(caught.value).startswith("the per_position_limit")
        with pytest.raises(LimitRequestError) as caught:
            _limits({BTC: 0.1}, per_position=1.0, concentration_limit=-1.0)
        assert str(caught.value).startswith("the concentration_limit")


class TestTheVerdictRefusesRatherThanReshaping:
    """A breach is rejected, and nothing about the caller's book is changed."""

    def test_the_book_is_unchanged_by_the_refusal(self):
        """Nothing is scaled down, re-weighted or clamped.

        The caller's value is untouched — refusing rather than reshaping is
        what keeps this a bound rather than a second sizing act, and it is why
        a caller can trust that a returned book is the book it handed over.
        """
        target = _weights()
        before = dict(target.weights)
        with pytest.raises(LimitBreachError):
            rejects_breaching_target_weights(
                target, per_position_limit=0.13, concentration_limit=1.0
            )
        assert dict(target.weights) == before
        assert target.weights[BTC] == BTC_WEIGHT

    def test_the_verdict_forms_no_value(self):
        """A refusal leaves nothing behind: the verb answers ``None`` or raises."""
        answered = rejects_breaching_target_weights(
            _weights(), per_position_limit=1.0, concentration_limit=1.0
        )
        assert answered is None

    def test_the_predicate_and_the_verdict_cannot_disagree(self):
        """One reading, two spellings — an exhaustive sweep over the edge.

        Every position and the concentration are swept across their bounds, and
        the predicate's answer must be exactly *the verdict raised*.
        """
        target = _weights()
        for per_position in (0.0, 0.12, 0.13, 0.14, 0.2, 1.0):
            for concentration_limit in (0.0, 0.3, 0.34, 0.35, 0.5, 1.0):
                raised = False
                try:
                    rejects_breaching_target_weights(
                        target,
                        per_position_limit=per_position,
                        concentration_limit=concentration_limit,
                    )
                except LimitBreachError:
                    raised = True
                assert (
                    is_breaching_limits(
                        target,
                        per_position_limit=per_position,
                        concentration_limit=concentration_limit,
                    )
                    is raised
                ), (per_position, concentration_limit)

    def test_the_verdict_is_deterministic(self):
        """Two identical calls answer identically — import-cheap and stateless."""
        first = rejects_breaching_target_weights(
            _weights(), per_position_limit=1.0, concentration_limit=1.0
        )
        second = rejects_breaching_target_weights(
            _weights(), per_position_limit=1.0, concentration_limit=1.0
        )
        assert first == second


class TestTheVocabularyIsTheActsOwnTwoClasses:
    """Two faces of one sentence, siblings under the member's one base."""

    def test_both_classes_descend_from_the_members_base(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(LimitRequestError, BookConstructionError)
        assert issubclass(LimitBreachError, BookConstructionError)

    def test_neither_class_is_the_other(self):
        """The facts are genuinely different, so the classes are siblings.

        A breaching book is refusable though both limits were perfectly well
        stated, and a mis-stated limit is refusable though the book sits inside
        a perfectly good bound — folding them together would make a caller that
        must react differently catch one class and re-inspect something it
        cannot tell apart.
        """
        assert not issubclass(LimitRequestError, LimitBreachError)
        assert not issubclass(LimitBreachError, LimitRequestError)

    def test_the_judgment_is_catchable_without_the_ask_and_the_other_way_round(self):
        """The distinction a caller has to be able to make, exercised."""
        with pytest.raises(LimitBreachError):
            _limits({BTC: 0.9}, per_position=0.5)
        with pytest.raises(LimitRequestError):
            _limits({BTC: 0.9}, per_position=-0.5)

    def test_the_judgment_opens_with_the_code_of_the_bound_that_was_breached(self):
        """Two bounds, two greppable words — the word for the repair."""
        with pytest.raises(LimitBreachError) as position:
            _limits({BTC: 0.9}, per_position=0.5)
        assert str(position.value).startswith(PER_POSITION_LIMIT_CODE)
        with pytest.raises(LimitBreachError) as shape:
            _limits({BTC: 0.5, ETH: 0.5}, concentration_limit=0.4)
        assert str(shape.value).startswith(CONCENTRATION_LIMIT_CODE)

    def test_the_codes_are_the_modules_own_constants(self):
        """The codes cannot drift from the messages that must open with them."""
        assert PER_POSITION_LIMIT_CODE == "position_above_limit"
        assert CONCENTRATION_LIMIT_CODE == "concentration_above_limit"
        with pytest.raises(LimitBreachError) as caught:
            _limits({BTC: 0.9}, per_position=0.5)
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)

    def test_the_members_other_features_still_raise_the_bare_base(self):
        """The act's two classes leave the old surface reachable.

        ``combine([])`` still raises the base itself, and feature 303's record
        still answers ``uncovered_symbol`` under it, so a caller written
        against feature 301 goes on catching what it caught.
        """
        with pytest.raises(BookConstructionError) as caught:
            combine([])
        assert type(caught.value) is BookConstructionError
        with pytest.raises(BookConstructionError) as coverage:
            _weights().weight("DOGE")
        assert type(coverage.value) is BookConstructionError

    def test_a_book_that_breaches_a_bound_is_not_a_flat_book(self):
        """Feature 303's judgment and this one's are different facts."""
        from book import VolatilityTargetError

        with pytest.raises(LimitBreachError):
            _limits({BTC: 0.9}, per_position=0.5)
        assert not issubclass(LimitBreachError, VolatilityTargetError)


class TestTheActIsAVerdictOverAValueTheCallerHolds:
    """No store, no environment, no clock, no other member."""

    def test_the_act_accepts_duck_typed_target_weights(self):
        """The seam reads the ``weights`` surface, not the type."""
        stand_in = _StandInWeights({BTC: 0.2, ETH: 0.3, SOL: 0.5})
        assert concentration(stand_in) == 0.5
        assert (
            rejects_breaching_target_weights(
                stand_in, per_position_limit=0.5, concentration_limit=0.5
            )
            is None
        )

    def test_the_concentration_needs_nothing_but_the_weights(self):
        """No membership map, no theme, no store — the whole-book reading.

        The everyday meaning of a concentration limit is a bound on a *group*
        of correlated names, and this system has that axis (``theme_root``,
        §11.1) — but no feature of this category hands a target weight set a
        symbol's theme: feature 301's composite is keyed by symbol and carries
        nothing else.  So the bound is stated over the book as a whole, where
        the figure is computable from the weights themselves; this test pins
        that a value carrying *only* ``weights`` is judged in full, which is
        the seam a per-theme bound could not be read from.
        """
        assert set(_StandInWeights.__dataclass_fields__) == {"weights"}
        assert concentration(_StandInWeights({BTC: 0.25, ETH: 0.25})) == 0.5

    def test_the_act_runs_with_no_database_and_no_environment(self, monkeypatch):
        """Exercised with the deployment's variables deleted."""
        for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
            monkeypatch.delenv(gone, raising=False)
        assert (
            rejects_breaching_target_weights(
                _weights(), per_position_limit=1.0, concentration_limit=1.0
            )
            is None
        )

    def test_the_module_opens_no_store_and_reads_no_environment(self):
        """The source facts behind the behavioural claim above."""
        source = MODULE_PATH.read_text()
        for forbidden in (
            "sqlite3",
            "os.environ",
            "getenv",
            "datetime",
            "time.",
            "polars",
            "pyarrow",
        ):
            assert forbidden not in source, forbidden

    def test_the_module_imports_no_other_workspace_member(self):
        """A member never imports a member — the workspace's own contract.

        Only relative imports (``from .errors import …``) are admissible, so a
        future edit cannot reach out to ``book._volatility`` for a figure it
        restates here, nor to another member for a theme membership this seam
        is not handed.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {
            "collections",
            "dataclasses",
            "math",
            "typing",
            "__future__",
        }, imported
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module == "errors", node.module


class TestFeature304ComposesWithTheMembersOwnChain:
    """§C8's chain, read end to end through the member's own values."""

    def test_signals_in_and_bounded_weights_out(self):
        """Three signals → combine → target weights → both bounds, no gap.

        The chain docs/alpha-engine-prd.md §C8 and
        docs/nullius-tech-architecture.md §13.1 both state, exercised as one
        composition: the composite feature 301 ranks, the exposure feature 303
        sets, and the two bounds this feature applies, with no member imported
        and no step of the chain standing in for another.
        """
        composite = combine(
            [
                StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
                StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
                StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
            ]
        )
        target = apply_volatility_target(
            composite, volatility=BOOK_VOLATILITY, target_volatility=TARGET_VOLATILITY
        )
        assert target.weights[BTC] == BTC_WEIGHT
        assert target.gross_exposure == pytest.approx(GROSS_EXPOSURE)
        # Inside the deployment's bounds, so it proceeds to the order layer.
        assert (
            rejects_breaching_target_weights(
                target,
                per_position_limit=MAJOR_WEIGHT,
                concentration_limit=BOOK_CONCENTRATION,
            )
            is None
        )

    def test_the_bounds_are_the_two_the_sentence_names_and_neither_is_anothers(self):
        """This bound is not feature 308's cap and not feature 303's target.

        The cap judges the *book's exposure* — the leverage it is held at — and
        this act judges a position's size and the book's shape.  A book at a
        leverage the cap would refuse can sit inside both bounds here, and the
        figures this act takes are limits rather than a target: nothing about
        the book is returned.
        """
        levered = apply_volatility_target(
            _book(), volatility=0.1, target_volatility=0.2
        )
        assert levered.gross_exposure == pytest.approx(2.0)
        # 2.0 of gross exposure — the same leverage, and it is the per-position
        # bound that has to answer for it, at the book's own largest weight.
        assert (
            rejects_breaching_target_weights(
                levered, per_position_limit=0.7, concentration_limit=1.0
            )
            is None
        )
        with pytest.raises(LimitBreachError) as caught:
            rejects_breaching_target_weights(
                levered, per_position_limit=MAJOR_WEIGHT, concentration_limit=1.0
            )
        assert str(caught.value).startswith(PER_POSITION_LIMIT_CODE)
        assert concentration(levered) == BOOK_CONCENTRATION

    def test_the_act_is_a_pure_function_of_the_value_and_the_figures(self):
        """Two calls over the same book and figures share nothing mutable."""
        target = _weights()
        assert not is_breaching_limits(
            target, per_position_limit=1.0, concentration_limit=1.0
        )
        assert not is_breaching_limits(
            target, per_position_limit=1.0, concentration_limit=1.0
        )
        assert concentration(target) == concentration(_weights())


class TestTheActIsAPureFunctionOfWhatItIsHanded:
    """The records this feature reads are exactly feature 303's, unedited."""

    def test_the_real_target_weights_is_the_intended_input(self):
        """The suite's stand-ins prove the seam; this proves the seam is used."""
        target = _weights()
        assert isinstance(target, object)
        assert target.weights[BTC] == BTC_WEIGHT
        assert target.gross_weights == {BTC: 0.3, ETH: 0.35, SOL: 0.35}
        # And they are frozen, so no bound could have been applied by editing.
        with pytest.raises(dataclasses.FrozenInstanceError):
            target.scale = 1.0  # type: ignore[misc]

    def test_both_verbs_read_the_same_surface(self):
        """The figure and the verdict cannot see different books."""
        target = _weights()
        assert concentration(target) == BOOK_CONCENTRATION
        assert not is_breaching_limits(
            target,
            per_position_limit=BOOK_CONCENTRATION,
            concentration_limit=BOOK_CONCENTRATION,
        )

    def test_a_negative_weight_is_a_short_position_not_a_smaller_one(self):
        """Magnitudes throughout — the same reading the gross exposure takes."""
        net_flat = _StandInWeights({BTC: 0.5, ETH: -0.5})
        # Net exposure is zero, and the book is not thereby cheap to bound:
        # its gross is 1.0 and its largest position is half the book.
        assert concentration(net_flat) == 0.5
        with pytest.raises(LimitBreachError):
            _limits({BTC: 0.5, ETH: -0.5}, per_position=0.4)
