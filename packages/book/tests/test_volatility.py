"""Feature 303's claim, stated as tests: the volatility target.

app_spec.xml, "Portfolio Book Construction", feature 303: *System applies
volatility targeting to the combined book, which returns weights scaled to a
configured annualized volatility.*  docs/alpha-engine-prd.md §C8 puts the step
in the construction's own chain — *"Signal book → IR-weighted combination with
shrinkage → volatility targeting → position and concentration limits →
orders.  Version-controlled, human-authored, explicitly outside the search
space."* — and the document states no figure for it: it states a *discount* on
a Kelly fraction (Appendix B's *"use ≤ ¼ Kelly"*, feature 308's constant) and
the *form* of a bar, but nowhere a risk level.  So the figure is a
deployment's, and this suite pins the act that applies it.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the act is two steps, in this order** — normalize the composite into a
  book at one unit of gross exposure, then scale it by
  ``target_volatility / volatility``.  The normalization is the load-bearing
  half: a target *score* carries free sign and scale (PRD §3), a weight does
  not, and a gross book is what makes the caller's volatility figure
  interpretable at all;
* **the configured annualized volatility is the deployment's parameter** — a
  required keyword with no default, the category's one knob, and the module
  carries no fallback risk level and no annualization factor of its own;
* **the record is a check, not a claim** — :class:`book.TargetWeights`
  enforces that every weight is its own gross weight times its own scale, that
  the scale is the two figures' quotient, and that the gross book is at one
  unit of gross; a hand-built record that disagrees with itself is refused;
* **absence is not zero** — a composite scored at zero *everywhere* is refused
  as a flat book (the normalization would divide by exactly nothing), while a
  *zero configured target* is answered (a deployment asking for no risk gets a
  flat book, which is its own consequence rather than a view this act
  invented);
* **the ask settles before the judgment** — a malformed figure is refused
  before the book is judged, however flat the book meant to be, and a value
  that is not a book is refused as the ask's own fact;
* **the act scales exposure and does not bound it** — a target above the
  book's volatility is answered (a book levered up to its risk level is what
  targeting is for), and the gross exposure the cap of feature 308 judges is
  exposed rather than clamped to;
* **the vocabulary is the act's own two classes** — the ask
  (:class:`book.VolatilityTargetRequestError`) and the one judgment the
  sentence mints (:class:`book.VolatilityTargetError`), both under the
  member's :class:`book.BookConstructionError`, and a caller must be able to
  catch one without catching the other.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
from pathlib import Path

import pytest
from book import (
    FLAT_BOOK_CODE,
    BookConstructionError,
    CompositeBook,
    PromotedSignal,
    TargetWeights,
    VolatilityTargetError,
    VolatilityTargetRequestError,
    apply_volatility_target,
    combine,
    rejects_overleveraged_target,
)
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal

#: The module the layering pin at the foot of this file parses — anchored to
#: the file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_volatility.py"

#: The book's own annualized volatility, and the configured target — dyadic,
#: so the scale is 0.4 exactly and every weight is checkable with ``==``.  The
#: figure is a plausible live-book volatility (PRD §11.1 puts a live strategy
#: at *"30–80% annualized at low leverage"*), and the target sits below it, so
#: the book is *de-risked* rather than levered — the ordinary case.
BOOK_VOLATILITY = 0.5
TARGET_VOLATILITY = 0.2
SCALE = TARGET_VOLATILITY / BOOK_VOLATILITY


def _book() -> CompositeBook:
    """The combined book the conftest's three signals answer.

    Rebuilt here rather than requested as a fixture: this suite's subject is
    the *act*, and the book it takes is feature 301's own value — the VIP the
    sentence names — so the tests below exercise the real seam a composed
    application hands over.
    """
    return combine(
        [
            PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
            PromotedSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
            PromotedSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
        ]
    )


def _scaled() -> TargetWeights:
    """The act applied to that book at the suite's two figures."""
    return apply_volatility_target(
        _book(), volatility=BOOK_VOLATILITY, target_volatility=TARGET_VOLATILITY
    )


@dataclasses.dataclass(frozen=True)
class _StandInBook:
    """A stand-in for the combined book.

    The act reads the ``scores`` mapping duck-typed — the loader imports
    members under synthetic names and re-executes them, so a book this process
    composed may be a second class object — and this is the shape that proves
    it: exactly one attribute, ``scores``, nothing else.  A test scaling one of
    these exercises the seam the act actually depends on, not the member's own
    class.
    """

    scores: object


class TestTheAct:
    """``apply_volatility_target`` — normalizing, then scaling."""

    def test_the_weights_are_the_gross_book_scaled(self):
        """The sentence's *weights scaled to a configured annualized
        volatility*, exactly.

        Read against the record's own two mappings rather than against numbers
        written here, so the claim is the act's identity and not a
        transcription: each scaled weight is its gross weight times the scale.
        """
        target = _scaled()
        assert target.scale == SCALE
        for symbol in (BTC, ETH, SOL):
            assert target.weights[symbol] == target.gross_weights[symbol] * target.scale

    def test_the_gross_book_is_normalized_to_one_unit_of_gross_exposure(self):
        """The act's first step — and the reason the volatility figure means
        anything.

        A composite is a *score* whose absolute magnitude is an artifact of the
        signals' units (PRD §3: *"Sign and scale are free"*), so the caller's
        volatility figure can only describe the book the scores normalize to.
        Gross rather than net, because a cross-sectional composite is long
        *and* short and a net divisor would be whatever the signals netted
        out to.
        """
        target = _scaled()
        assert math.fsum(abs(w) for w in target.gross_weights.values()) == 1.0
        # The book's own composites, normalized: they sum in absolute value
        # to one, and their signs are preserved untouched — the act re-ranks
        # nothing feature 301 ranked.
        assert target.gross_weights[BTC] == pytest.approx(0.1875 / 0.625)
        assert target.gross_weights[ETH] == pytest.approx(0.21875 / 0.625)
        assert target.gross_weights[SOL] == pytest.approx(0.21875 / 0.625)

    def test_the_scale_is_the_configured_target_over_the_books_volatility(self):
        """The one factor, with no annualization applied on top of it.

        Both figures arrive annualized and on the same basis (crypto's year is
        365 calendar days — the basis feature 55's realized volatility
        annualizes on), so the act divides one by the other and applies no
        factor of its own.  A book whose volatility *is* the target is
        therefore held unchanged, exactly — the claim an annualization could
        not survive.
        """
        target = apply_volatility_target(
            _book(), volatility=0.4, target_volatility=0.4
        )
        assert target.scale == 1.0
        assert target.weights == target.gross_weights
        assert target.weight(BTC) == target.gross_weights[BTC]

    def test_a_quieter_book_is_levered_up_to_the_target(self):
        """The point of targeting: a scale above one is answered, not clamped.

        This act sets exposure; feature 308's cap is the bound on it and
        feature 304's limits are the bound on a position's size.  A module that
        refused leverage here would be a bound wearing a scaling's name, and a
        book refused for reaching its configured risk would report the
        configuration as the fault.
        """
        target = apply_volatility_target(
            _book(), volatility=0.1, target_volatility=0.2
        )
        assert target.scale == 2.0
        assert target.gross_exposure == pytest.approx(2.0)
        assert target.gross_exposure > 1.0

    def test_the_scaled_books_volatility_reproduces_the_target(self):
        """The sentence's own claim, read as arithmetic.

        Gross exposure enters a book's volatility linearly, so the scaled
        book's volatility is ``scale · volatility`` — which is
        ``target_volatility`` by construction.  This is the act's *returns
        weights scaled to a configured annualized volatility* stated as the
        identity it is, at several figure pairs.
        """
        book = _book()
        for volatility, target_volatility in ((0.5, 0.2), (0.1, 0.2), (0.4, 0.4), (2.0, 0.75)):
            scaled = apply_volatility_target(
                book, volatility=volatility, target_volatility=target_volatility
            )
            assert scaled.scale * scaled.volatility == pytest.approx(
                scaled.target_volatility
            )

    def test_the_scaled_books_gross_exposure_is_its_scale(self):
        """The exposure the cap of feature 308 judges, derived not stored.

        ``Σ_s |gross_s · scale| = scale · Σ_s |gross_s| = scale``, and the
        record derives it from its own weights so it can never disagree with
        them — the discipline :class:`replay.ReplayDuration` states for its
        derived flags.  Exposed because it is the figure a caller hands
        feature 308's verdict, which is how the two features meet without
        either importing the other.
        """
        target = _scaled()
        assert target.gross_exposure == pytest.approx(target.scale)
        levered = apply_volatility_target(
            _book(), volatility=0.1, target_volatility=0.5
        )
        assert levered.gross_exposure == pytest.approx(levered.scale)
        assert levered.gross_exposure == pytest.approx(5.0)

    def test_symbols_are_emitted_sorted_and_the_act_is_order_independent(self):
        """Two calls over the same book and figures answer one record.

        The record is a normalization (a sum over the book) and a scaling (one
        factor over it), so nothing about it depends on the iteration order the
        composite arrived in; symbols are emitted sorted so the two mappings
        compare equal however the book was built.
        """
        target = _scaled()
        assert list(target.weights) == sorted(target.weights) == [BTC, ETH, SOL]
        assert list(target.gross_weights) == sorted(target.gross_weights)
        assert _scaled() == target

    def test_the_act_is_deterministic(self):
        """Same book, same figures, same record — every time."""
        first, second = _scaled(), _scaled()
        assert first.weights == second.weights
        assert first.gross_weights == second.gross_weights
        assert first.scale == second.scale
        assert math.isfinite(first.scale)

    def test_a_partially_zero_composite_is_a_book_and_is_scaled(self):
        """Only *every* score at zero is a flat book.

        A symbol scored at zero while others carry a view is a symbol the book
        holds *none* of — a weight of exactly zero, which is a decision the
        composite made and this act preserves.  The refusal is over the
        divisor, not over any zero in the book.
        """
        stand_in = _StandInBook({BTC: 0.4, ETH: 0.0, SOL: -0.6})
        target = apply_volatility_target(
            stand_in, volatility=BOOK_VOLATILITY, target_volatility=TARGET_VOLATILITY
        )
        assert target.gross_weights[ETH] == 0.0
        assert target.weights[ETH] == 0.0
        assert target.gross_weights[BTC] == 0.4
        # The sign is the view and the act does not re-open it: a negative
        # composite stays a negative weight — a short in a long/short book.
        assert target.gross_weights[SOL] == -0.6

    def test_a_zero_configured_target_is_answered_with_a_flat_book(self):
        """*Take no risk* is a level, not a malformed ask.

        The reading feature 308 gives a zero Sharpe — *"a zero Sharpe answers a
        zero cap and admits only the flat book"* — applied to the deployment's
        own figure instead of the book's.  The flat book here is the
        configuration's consequence, which is exactly what separates it from
        the flat *composite*, whose refusal this suite pins below: there the
        divisor is nothing, here the caller chose nothing.
        """
        target = apply_volatility_target(
            _book(), volatility=BOOK_VOLATILITY, target_volatility=0.0
        )
        assert target.scale == 0.0
        assert target.target_volatility == 0.0
        assert dict(target.weights) == {BTC: 0.0, ETH: 0.0, SOL: 0.0}
        assert target.gross_exposure == 0.0
        # The gross book is still the book — the normalization happened; only
        # the scaling is the caller's zero.
        assert target.gross_weights[BTC] == pytest.approx(0.1875 / 0.625)

    def test_the_weights_are_the_order_layers_figure_for_a_symbol(self):
        """``weight(symbol)`` is the ranking's entry, and it is the record's."""
        target = _scaled()
        for symbol in (BTC, ETH, SOL):
            assert target.weight(symbol) == target.weights[symbol]

    def test_weight_refuses_a_symbol_the_book_does_not_cover(self):
        """A symbol the weights hold no entry for is refused, not zeroed.

        A fabricated zero would read to the order layer as *hold none of it* —
        a position decision this act never made — so the refusal names the
        symbol and the book's own coverage, under the same ``uncovered_symbol``
        word feature 301's ``CompositeBook.target_score`` answers with.
        """
        with pytest.raises(BookConstructionError) as caught:
            _scaled().weight("DOGE")
        assert str(caught.value).startswith("uncovered_symbol")
        assert "DOGE" in str(caught.value)


class TestTheConfiguredTargetIsTheDeploymentsKnob:
    """The one figure in this category that a deployment supplies."""

    def test_the_target_is_required(self):
        """No default: a module-chosen risk level would be no document's.

        §C8 names the step and the document states no figure for it, so a
        fallback here would be a risk level this module invented, silently
        applied to every deployment that never configured one — the failure
        mode feature 308's constant exists to avoid on the other side.  The
        signature is checked through the function object, so a renamed keyword
        still fails, and the call is made without the keyword so a default
        that later appeared would be caught behaviourally too.
        """
        parameters = inspect.signature(apply_volatility_target).parameters
        assert set(parameters) == {"book", "volatility", "target_volatility"}
        for name in ("volatility", "target_volatility"):
            assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
            assert parameters[name].default is inspect.Parameter.empty
        with pytest.raises(TypeError):
            apply_volatility_target(_book(), volatility=BOOK_VOLATILITY)  # type: ignore[call-arg]

    def test_the_module_carries_no_default_risk_level(self):
        """``0.15``/``0.2``/``10%`` — none of them is written down here.

        Checked by parsing the module: the only numeric literals it carries are
        the two the record's own identities need (``0.0`` for the zero-target
        case, ``1.0`` for the unit of gross) and the ``isclose`` tolerances of
        the gross-one check.  Anything else would be a figure the document does
        not state — a risk level or a clamp — spelled into an act that is
        supposed to apply the caller's.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        }
        assert literals == {0.0, 1.0, 1e-9, 1e-12}, literals

    def test_the_module_applies_no_annualization(self):
        """No root and no exponent is taken anywhere in the act.

        The sentence's target is *annualized* and the book's volatility arrives
        already annualized on its own basis, so a factor applied here would be
        this module re-deriving the units of a measurement it was handed (and
        would double-count whenever both figures arrived annualized, which they
        do).  Pinned on the *executable* code rather than the source text,
        because the module's prose legitimately names the 365-day basis it
        declines to apply: what is checked is that no code line takes a square
        root (the shape an annualization factor is spelled in — feature 55's
        ``sqrt(365)``) or raises anything to a power.  A textual check would
        also be fooled by an edit that moved the constant into a docstring.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "sqrt", "the act takes no square root"
            if isinstance(node, ast.BinOp):
                assert not isinstance(node.op, ast.Pow), "the act raises nothing"
        # And behaviourally: 0.5 over 0.5 is one, not one times a year's worth
        # of anything.
        target = apply_volatility_target(
            _book(), volatility=0.5, target_volatility=0.5
        )
        assert target.scale == 1.0

    def test_the_act_is_reachable_without_the_factory(self):
        """A free function, not a component: the target reaches the *call*.

        The factory's registration protocol takes no arguments, so a configured
        volatility could not cross it; the figure is the caller's, handed to
        the call, which is what makes it a deployment's knob rather than a
        composed constant.  (The composition half of that claim — that no
        second component is registered — is pinned in ``test_component.py``.)
        """
        assert callable(apply_volatility_target)
        assert callable(TargetWeights)
        assert FLAT_BOOK_CODE == "flat_book"


class TestTheFlatBookIsRefused:
    """A composite with no view anywhere — the one judgment this act mints."""

    def test_a_composite_of_zeros_is_refused_as_a_flat_book(self):
        """``Σ_t |score_t| = 0`` makes the normalization a division by nothing.

        The weights are undefined, not flat: answering an all-zero weight set
        would counterfeit a book from no view — the perpetration feature 301
        refuses when it declines to zero-fill a signal that misses a symbol —
        and it would hand the order layer a *decision to hold nothing* that no
        signal made.
        """
        stand_in = _StandInBook({BTC: 0.0, ETH: 0.0, SOL: 0.0})
        with pytest.raises(VolatilityTargetError) as caught:
            apply_volatility_target(
                stand_in,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )
        message = str(caught.value)
        assert message.startswith(FLAT_BOOK_CODE)
        # The refusal names the book it refuses and the divisor that makes the
        # act impossible, so the operator sees *why* rather than taking it on
        # faith.
        assert "BTC" in message and "ETH" in message and "SOL" in message
        assert "0.0" in message

    def test_the_flat_book_is_refused_at_every_pair_of_figures(self):
        """No figure pair rescues it — the divisor does not involve them.

        Including the zero target: a request for no risk is answered on a book
        that *has* a view (delivering a flat book by scale), but it cannot
        rescue a book with none, because the refusal fires at the normalization
        which happens before the scale exists.
        """
        stand_in = _StandInBook({BTC: 0.0, ETH: 0.0})
        for volatility, target_volatility in ((0.5, 0.2), (0.1, 0.5), (0.5, 0.0), (1.0, 0.0)):
            with pytest.raises(VolatilityTargetError) as caught:
                apply_volatility_target(
                    stand_in,
                    volatility=volatility,
                    target_volatility=target_volatility,
                )
            assert str(caught.value).startswith(FLAT_BOOK_CODE)

    def test_a_flat_book_forms_no_value(self):
        """A refused act leaves nothing behind — no record, no weights."""
        stand_in = _StandInBook({BTC: 0.0})
        with pytest.raises(VolatilityTargetError):
            apply_volatility_target(
                stand_in, volatility=0.5, target_volatility=0.2
            )

    def test_the_flat_book_refusal_names_its_repair(self):
        """The one repair that exists, because this act fabricates no view."""
        stand_in = _StandInBook({BTC: 0.0, ETH: 0.0})
        with pytest.raises(VolatilityTargetError) as caught:
            apply_volatility_target(
                stand_in, volatility=0.5, target_volatility=0.2
            )
        message = str(caught.value)
        assert "expresses a view" in message
        assert "configured target of zero" in message


class TestTheAskIsRefusedBeforeAnythingIsJudged:
    """The ask's own facts — :class:`book.VolatilityTargetRequestError`."""

    @pytest.mark.parametrize(
        "volatility",
        ["0.5", None, True, float("nan"), float("inf"), float("-inf"), 0.0, -0.5],
    )
    def test_a_malformed_book_volatility_is_refused(self, volatility):
        """A scale that is not a finite strictly positive real names no book.

        Zero is the sharp one: ``target / volatility`` is a division by
        exactly nothing, so a book with no volatility has no target weights at
        all rather than infinitely many — the reading feature 308 gives the
        same figure for its own fraction.
        """
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _book(), volatility=volatility, target_volatility=TARGET_VOLATILITY
            )

    @pytest.mark.parametrize(
        "target_volatility",
        ["0.2", None, True, float("nan"), float("inf"), float("-inf"), -0.2],
    )
    def test_a_malformed_target_is_refused(self, target_volatility):
        """A target is a finite scale of zero or more — never a direction.

        ``-0.20`` would flip every weight's sign through an arithmetic that
        read a risk level as a view, and a ``bool`` where a level belongs reads
        as *one hundred percent annualized*.  Zero is deliberately **not** in
        this list: *take no risk* is a level, and it is answered.
        """
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _book(), volatility=BOOK_VOLATILITY, target_volatility=target_volatility
            )

    def test_a_negative_target_is_refused_as_the_ask_rather_than_judged(self):
        """The refusal names the repair: ask the composite for the other book.

        A direction is not this act's to take — the sign of a book is the
        composite's view, decided by the signals feature 301 weighted, and a
        negative target would overrule them silently.
        """
        with pytest.raises(VolatilityTargetRequestError) as caught:
            apply_volatility_target(
                _book(), volatility=BOOK_VOLATILITY, target_volatility=-0.2
            )
        message = str(caught.value)
        assert "scale" in message
        assert "direction" in message
        assert not message.startswith(FLAT_BOOK_CODE)

    @pytest.mark.parametrize("book", [None, 42, "the book", object()])
    def test_a_value_that_is_not_a_book_is_refused(self, book):
        """The act takes the combined book, and says so when it is not one.

        Read duck-typed from the ``scores`` surface, so *this is not a book* is
        a different report from *this book covers no symbols* — the sentinel
        keeps them apart, and both are refused before any figure is read.
        """
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                book, volatility=BOOK_VOLATILITY, target_volatility=TARGET_VOLATILITY
            )

    def test_a_book_covering_no_symbols_is_refused(self):
        """A book that covers nothing has no weights to scale."""
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _StandInBook({}),
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_book_whose_scores_are_not_a_mapping_is_refused(self):
        """A book's scores are read one symbol at a time."""
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _StandInBook([0.1, 0.2]),
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_blank_symbol_is_refused(self):
        """A weight cannot be attributed to a symbol the book does not name."""
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _StandInBook({"  ": 0.5, BTC: 0.5}),
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    @pytest.mark.parametrize(
        "score", ["0.5", None, True, float("nan"), float("inf"), float("-inf")]
    )
    def test_a_score_that_is_not_a_finite_real_is_refused(self, score):
        """A book whose score is not a number has no weight to scale.

        A ``nan`` or infinite score is the sharp one: it would reach the
        weights dressed as a measurement, and every weight scaled from it
        would be a weight no limit could bound.
        """
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _StandInBook({BTC: score}),
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_the_ask_settles_before_the_flat_book_is_judged(self):
        """A broken figure is *fix the ask*, never *your book expresses no view*.

        The ordering every verdict in this workspace states.  Both the ask and
        the judgment apply here — the book is flat and the target is negative —
        and the ask's class is the one that fires, because a caller told its
        book has no view when the real fault is a figure it mistyped would be
        told to re-examine its signals.
        """
        stand_in = _StandInBook({BTC: 0.0, ETH: 0.0})
        with pytest.raises(VolatilityTargetRequestError) as caught:
            apply_volatility_target(
                stand_in, volatility=BOOK_VOLATILITY, target_volatility=-0.2
            )
        assert not isinstance(caught.value, VolatilityTargetError)
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                stand_in, volatility=0.0, target_volatility=TARGET_VOLATILITY
            )

    def test_the_ask_carries_no_code_word(self):
        """A malformed ask names its subject in its first words, not a token.

        The one code on this feature's path is the *judgment*'s — an operator
        greps a deployment log for *why was this book not sized?* — and a
        developer's token on a fact the caller can simply fix would be the
        wrong report.
        """
        with pytest.raises(VolatilityTargetRequestError) as caught:
            apply_volatility_target(
                _book(), volatility=0.5, target_volatility=-0.2
            )
        assert not str(caught.value).startswith(FLAT_BOOK_CODE)
        assert "configured volatility target" in str(caught.value)


class TestTheRecordIsACheckNotAClaim:
    """:class:`book.TargetWeights` — the record enforces the act's own terms."""

    def test_an_honest_record_is_admitted(self):
        """The check admits what the act answers — it is not a wall."""
        target = _scaled()
        rebuilt = TargetWeights(
            weights=dict(target.weights),
            gross_weights=dict(target.gross_weights),
            scale=target.scale,
            volatility=target.volatility,
            target_volatility=target.target_volatility,
        )
        assert rebuilt == target

    def test_a_weight_that_is_not_its_gross_weight_scaled_is_refused(self):
        """The act's identity, enforced on the record that claims it.

        The discipline :class:`book.CompositeBook` states for its composite and
        :class:`evaluator.MarginalIR` for its ratios: a hand-built record whose
        weights are not its own gross book scaled is refused, so the record is
        a check rather than a claim.
        """
        with pytest.raises(VolatilityTargetRequestError):
            TargetWeights(
                weights={BTC: 0.21, ETH: 0.14, SOL: 0.05},
                gross_weights={BTC: 0.3, ETH: 0.35, SOL: 0.35},
                scale=SCALE,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_scale_that_is_not_the_figures_quotient_is_refused(self):
        """A record cannot carry one pair of figures and another factor."""
        with pytest.raises(VolatilityTargetRequestError):
            TargetWeights(
                weights={BTC: 0.15, ETH: 0.175, SOL: 0.175},
                gross_weights={BTC: 0.3, ETH: 0.35, SOL: 0.35},
                scale=0.5,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_gross_book_that_is_not_at_unit_gross_is_refused(self):
        """The normalization is what makes the volatility figure mean anything."""
        with pytest.raises(VolatilityTargetRequestError):
            TargetWeights(
                weights={BTC: 0.2},
                gross_weights={BTC: 0.5},
                scale=SCALE,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_book_whose_two_readings_cover_different_symbols_is_refused(self):
        """One book read twice — a symbol weighed without its gross weight
        would make the scaling check vacuous."""
        with pytest.raises(VolatilityTargetRequestError) as caught:
            TargetWeights(
                weights={BTC: 0.2, ETH: 0.2},
                gross_weights={BTC: 0.5},
                scale=SCALE,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )
        assert "ETH" in str(caught.value)

    @pytest.mark.parametrize("field", ["weights", "gross_weights"])
    def test_a_mapping_that_cannot_be_a_book_is_refused(self, field):
        """Both mappings are the same shape, read by one helper."""
        good: dict[str, object] = {"weights": {BTC: 0.5}, "gross_weights": {BTC: 1.0}}
        bad: dict[str, object] = dict(good)
        bad[field] = {}
        with pytest.raises(VolatilityTargetRequestError):
            TargetWeights(
                weights=bad["weights"],  # type: ignore[arg-type]
                gross_weights=bad["gross_weights"],  # type: ignore[arg-type]
                scale=SCALE,
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )

    def test_a_non_finite_weight_is_refused(self):
        """A ``nan`` weight is not a position, and no limit could bound it."""
        with pytest.raises(VolatilityTargetRequestError):
            TargetWeights(
                weights={BTC: float("nan")},
                gross_weights={BTC: 1.0},
                scale=1.0,
                volatility=BOOK_VOLATILITY,
                target_volatility=BOOK_VOLATILITY,
            )

    def test_the_record_carries_the_figures_behind_it(self):
        """The two volatilities and the scale are on the record, not implied.

        The refusal above is legible only because the record states the figures
        it was built from — the same discipline :class:`book.CompositeBook`
        states by carrying its contributions.
        """
        target = _scaled()
        assert target.volatility == BOOK_VOLATILITY
        assert target.target_volatility == TARGET_VOLATILITY
        assert target.scale == SCALE

    def test_the_record_is_frozen(self):
        """A target-weight set that could move after it was read would be a
        rebalance nobody decided."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            _scaled().scale = 99.0  # type: ignore[misc]

    def test_the_records_mappings_are_read_only(self):
        """The mappings are the value's own; neither can be edited in place."""
        target = _scaled()
        with pytest.raises(TypeError):
            target.weights[BTC] = 1.0  # type: ignore[index]
        with pytest.raises(TypeError):
            target.gross_weights[BTC] = 1.0  # type: ignore[index]


class TestTheVocabularyIsTheActsOwnTwoClasses:
    """Two faces of one sentence, siblings under the member's one base."""

    def test_both_classes_descend_from_the_members_base(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(VolatilityTargetRequestError, BookConstructionError)
        assert issubclass(VolatilityTargetError, BookConstructionError)

    def test_neither_class_is_the_other(self):
        """The facts are genuinely different, so the classes are siblings.

        A flat composite is refusable though both figures were perfectly well
        stated, and a mis-stated figure is refusable though the book expresses
        a perfectly good view — folding them together would make a caller that
        must react differently catch one class and re-inspect something it
        cannot tell apart.
        """
        assert not issubclass(VolatilityTargetRequestError, VolatilityTargetError)
        assert not issubclass(VolatilityTargetError, VolatilityTargetRequestError)

    def test_the_members_other_features_still_raise_the_bare_base(self):
        """The act's two classes leave the old surface reachable.

        ``combine([])`` still raises the base itself, and the act's own
        ``weight`` accessor still answers ``uncovered_symbol`` under it, so a
        caller written against feature 301 goes on catching what it caught.
        """
        with pytest.raises(BookConstructionError) as caught:
            combine([])
        assert type(caught.value) is BookConstructionError
        with pytest.raises(BookConstructionError) as coverage:
            _scaled().weight("DOGE")
        assert type(coverage.value) is BookConstructionError

    def test_the_judgment_is_catchable_without_the_ask_and_the_other_way_round(
        self,
    ):
        """The distinction a caller has to be able to make, exercised."""
        with pytest.raises(VolatilityTargetError):
            apply_volatility_target(
                _StandInBook({BTC: 0.0}),
                volatility=BOOK_VOLATILITY,
                target_volatility=TARGET_VOLATILITY,
            )
        with pytest.raises(VolatilityTargetRequestError):
            apply_volatility_target(
                _StandInBook({BTC: 0.0}),
                volatility=-1.0,
                target_volatility=TARGET_VOLATILITY,
            )


class TestTheActIsAVerdictOverAValueTheCallerHolds:
    """No store, no environment, no clock, no other member."""

    def test_the_act_accepts_a_duck_typed_book(self):
        """The seam reads the ``scores`` surface, not the type.

        The loader imports members under synthetic names and re-executes them,
        so a book composed in this process may be a second class object; a
        stand-in proving the seam is what the composed application actually
        depends on.
        """
        stand_in = _StandInBook({BTC: 0.2, ETH: 0.3, SOL: 0.5})
        target = apply_volatility_target(
            stand_in, volatility=0.5, target_volatility=0.25
        )
        assert target.scale == 0.5
        assert target.gross_weights == {BTC: 0.2, ETH: 0.3, SOL: 0.5}
        assert target.weights[BTC] == 0.1

    def test_the_act_composes_with_the_combiner(self):
        """Feature 303 consumes feature 301's answer, whole.

        The category's own chain (§C8) read as a composition: the signals
        arrive as the member's own values, :func:`book.combine` answers the
        composite, and the act scales it — three signals in, target weights
        out, with no step of the chain missing and no member imported.
        """
        signals = [
            StandInSignal(SIGNAL_ONE, 1.0, {BTC: 0.25, ETH: 0.125, SOL: 0.25}),
            StandInSignal(SIGNAL_TWO, 2.0, {BTC: 0.125, ETH: 0.25, SOL: 0.25}),
            StandInSignal(SIGNAL_THREE, 1.0, {BTC: 0.25, ETH: 0.25, SOL: 0.125}),
        ]
        target = apply_volatility_target(
            combine(signals), volatility=0.5, target_volatility=0.2
        )
        assert target.scale == SCALE
        # The ranking feature 301 fixed is the ranking the weights carry: the
        # two equally-scored symbols stay equal, and the quieter one stays
        # quieter.
        assert target.weights[ETH] == target.weights[SOL]
        assert abs(target.weights[BTC]) < abs(target.weights[ETH])
        assert math.fsum(target.weights.values()) == pytest.approx(
            SCALE * math.fsum(target.gross_weights.values())
        )

    def test_the_act_runs_with_no_database_and_no_environment(self, monkeypatch):
        """Exercised with the deployment's variables deleted.

        A version that had grown a store dependency, an environment knob or a
        clock would fail here rather than in production.
        """
        for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
            monkeypatch.delenv(gone, raising=False)
        target = _scaled()
        assert target.scale == SCALE

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
        future edit cannot reach out to ``scoring`` or ``evaluator`` for a
        normalization it restates here, nor to ``book._leverage`` for a
        validator that would raise the wrong feature's error class.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"collections", "dataclasses", "math", "types", "typing", "__future__"}, imported
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module == "errors", node.module

    def test_the_gross_exposure_is_the_figure_feature_308s_cap_judges(self):
        """The two features meet without either importing the other.

        Feature 308 rejects a leverage target above one quarter of the book's
        Kelly fraction, and the leverage a caller would hand it *is* the
        exposure this act produces.  ``gross_exposure`` exists on the record
        for exactly this seam, so the size the act sets is the size the cap
        bounds — the category's §C8 chain read across two features, with no
        import between them (the cap takes figures, and this is the figure).

        Exercised end to end: a book levered to 2.0 by the target is refused by
        the cap at a Sharpe of 0.5 and a volatility of 0.2 (a cap of 0.625),
        while the same book at a target *below* the cap runs.  That is what
        makes the two features a bound and a scaling rather than a bound and a
        rival one.
        """
        levered = apply_volatility_target(
            _book(), volatility=0.1, target_volatility=0.2
        )
        assert levered.gross_exposure == pytest.approx(2.0)
        with pytest.raises(BookConstructionError) as caught:
            rejects_overleveraged_target(
                levered.gross_exposure, sharpe=0.5, volatility=0.2
            )
        assert str(caught.value).startswith("leverage_above_quarter_kelly")
        # And the act does not bound that exposure itself — the refusal above
        # came from feature 308's verdict, never from this one.
        assert levered.scale == 2.0
        gentle = apply_volatility_target(
            _book(), volatility=0.5, target_volatility=0.2
        )
        assert (
            rejects_overleveraged_target(
                gentle.gross_exposure, sharpe=0.5, volatility=0.2
            )
            is None
        )

    def test_the_act_holds_no_state(self):
        """Two records from the same book share nothing mutable.

        The act is a pure function of the value and the figures it is handed,
        so one record's mappings cannot be another's — the property a composed
        application depends on when it scales a book twice at different
        targets.
        """
        first = apply_volatility_target(
            _book(), volatility=0.5, target_volatility=0.2
        )
        second = apply_volatility_target(
            _book(), volatility=0.5, target_volatility=0.4
        )
        assert first.weights is not second.weights
        assert first.gross_weights == second.gross_weights
        assert second.scale == 0.8
        assert first.scale == 0.4
