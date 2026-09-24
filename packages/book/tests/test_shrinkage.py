"""Feature 302's claim, stated as tests: the covariance shrinkage.

app_spec.xml, "Portfolio Book Construction", feature 302: *System applies
Ledoit-Wolf shrinkage to the signal covariance before combination, which
returns a stabilized weight vector.*  docs/alpha-engine-prd.md §C8 puts the
step inside the chain's own first arrow — *"Signal book → IR-weighted
combination **with shrinkage** → volatility targeting → position and
concentration limits → orders"* — so the shrinkage is the qualifier *on* the
combination, and this suite pins the act that takes it.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the covariance is the signals' own, and the symbols are its observations**
  — the ``p × p`` matrix of the signals' demeaned per-symbol target scores,
  each symbol one joint observation (the only joint sample a promoted signal
  carries), estimated with the ``1/n`` divisor Ledoit & Wolf (2004) state;
* **the intensity is estimated, never configured** — the sentence names
  *Ledoit-Wolf*, and what that names over a bare shrinkage is precisely that
  the shrinkage intensity is a measurement the estimator takes from the
  sample (``min(b̄², d²)/d²``, total when the sample is already its own
  target): no ``shrinkage=`` keyword exists, and no figure a deployment could
  dial survives in the module's literals;
* **the weight vector is the solve ``Σ⁻¹·IR``, gross-normalized** — the
  weighting that maximizes the combined information ratio under the shrunk
  covariance, normalized to one unit of gross (feature 303's own convention,
  read one arrow earlier) so a correlated signal can stabilize to a
  *negative* weight: the hedge the arithmetic produces, its sign the view;
* **the isotropic limit agrees with feature 301 exactly** — orthogonal
  signals of equal variance shrink fully to the scaled identity, and the
  stabilized vector *is* the information-ratio weighting, so the two acts
  agree precisely on the book where the covariance adds nothing and disagree
  precisely where it does;
* **absence is not zero, twice** — a book with no dispersion at all is
  refused as ``dispersionless_book`` (a one-symbol book is always this
  refusal), and a book whose shrunk covariance has no inverse is refused as
  ``singular_covariance`` (a two-symbol book of two or more signals is always
  this one), while a *thin but lift-able* book — three signals over three
  symbols — is answered, because carrying the sample off its deficiency is
  what the shrinkage is for;
* **the record is a check, not a claim** — :class:`book.StabilizedWeights`
  enforces its own mixture, normalization and solve, and a hand-built record
  that disagrees with itself is refused;
* **the ask settles before the judgment** — a signal that cannot be read as
  the surface feature 301 defined is refused in this act's own class with
  **301's own code words**, before any covariance is estimated;
* **the vocabulary is the act's own two classes** — the ask
  (:class:`book.ShrinkageRequestError`) and the one judgment the sentence
  mints (:class:`book.ShrinkageError`, carrying both codes), siblings under
  the member's :class:`book.BookConstructionError`.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools
import math
from pathlib import Path

import pytest
from book import (
    DISPERSIONLESS_BOOK_CODE,
    SINGULAR_COVARIANCE_CODE,
    BookConstructionError,
    PromotedSignal,
    ShrinkageError,
    ShrinkageRequestError,
    StabilizedWeights,
    combine,
    stabilize_weights,
)
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_TWO, SOL, StandInSignal

#: The module the layering pins at the foot of this file parse — anchored to
#: the file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_shrinkage.py"

#: The book's fourth symbol.  The conftest's three carry every other suite in
#: the member; the covariance's exact hand-computable cases want a fourth
#: observation, because two demeaned observations are always collinear (the
#: ``singular_covariance`` boundary) and three leave no room for a fourth
#: signal to be anything but a copy of the first three's span.
ADA = "ADA"

#: The Ledoit-Wolf intensity of the correlated case below, derived by hand:
#: ``d² = 153/256`` and ``b̄² = 17/512``, both dyadic, so the clipped ratio is
#: ``(17/512)/(153/256) = 1/18`` — correctly rounded to the same float the
#: ``1/18`` literal spells, and therefore checkable with ``==``.
CORRELATED_INTENSITY = 1 / 18


def _orthogonal() -> list[PromotedSignal]:
    """Two orthogonal signals of equal variance over four symbols.

    Both demean to themselves (each row sums to zero), so the sample
    covariance is exactly the identity, ``m = 1.0``, the dispersion from the
    target is exactly zero, and the estimator's own limit applies: total
    shrinkage to the scaled identity.  The IRs (1.0, 3.0) are the conftest's
    own dyadic choice, so the solve ``I·v = IR`` is the identity and every
    figure below is checkable with ``==``.
    """
    return [
        PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0, ADA: -1.0}),
        PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 1.0, ETH: -1.0, SOL: 1.0, ADA: -1.0}),
    ]


def _correlated() -> list[PromotedSignal]:
    """Two correlated signals: beta is alpha scaled and damped per symbol.

    The sample covariance is ``[[1.0, 0.75], [0.75, 0.625]]`` exactly (every
    entry a sum of dyadic products over four symbols), ``m = 0.8125``, and
    the intensity is :data:`CORRELATED_INTENSITY` — the partial-shrinkage
    case, where the estimator trusts some of the sample and not all of it.
    """
    return [
        PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0, ADA: -1.0}),
        PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 1.0, ETH: 0.5, SOL: -1.0, ADA: -0.5}),
    ]


def _thin() -> list[PromotedSignal]:
    """Three signals over three symbols whose sample is rank-deficient.

    gamma is exactly alpha + beta, so the demeaned observations span only two
    of the three dimensions the matrix is keyed by: the raw sample has no
    inverse, and only the shrinkage lifts it off that — the rescue that makes
    the sentence's *stabilized* structural rather than decorative.
    """
    return [
        PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 0.0, SOL: -1.0}),
        PromotedSignal(SIGNAL_TWO, 1.0, {BTC: 0.0, ETH: 1.0, SOL: -1.0}),
        PromotedSignal("copy", 1.0, {BTC: 1.0, ETH: 1.0, SOL: -2.0}),
    ]


class TestTheAct:
    """``stabilize_weights`` — estimate, shrink, solve, normalize."""

    def test_the_isotropic_book_shrinks_fully_and_answers_the_ir_weights(self):
        """The estimator's limit, and the category's own agreement.

        A sample covariance that already equals ``m·I`` has zero dispersion
        from its target, and the estimator's intensity goes to one — the
        shrunk estimate is the scaled identity outright, the solve is the
        identity, and the stabilized vector is exactly the information-ratio
        weighting feature 301 answers.  This is the claim that the two acts
        are the same act on the book where the covariance adds nothing: same
        signals in, identical weights out, under the gross normalization both
        features share.
        """
        stabilized = stabilize_weights(_orthogonal())
        combined = combine(_orthogonal())
        assert stabilized.shrinkage == 1.0
        assert dict(stabilized.direction) == {SIGNAL_ONE: 1.0, SIGNAL_TWO: 3.0}
        assert dict(stabilized.weights) == {SIGNAL_ONE: 0.25, SIGNAL_TWO: 0.75}
        assert dict(stabilized.weights) == dict(combined.weights)

    def test_the_correlated_book_shrinks_partially_by_the_papers_own_figures(self):
        """``min(b̄², d²)/d²``, hand-computed on a book where both are exact.

        The sample covariance entries are dyadic (``1.0``, ``0.75``,
        ``0.625``), the dispersion is ``153/256`` and the estimation error
        ``17/512``, so the intensity is exactly ``1/18`` — the one figure of
        the estimator's spelled on a book a reader can check to the bit.
        """
        stabilized = stabilize_weights(_correlated())
        assert stabilized.shrinkage == CORRELATED_INTENSITY
        assert 0.0 < stabilized.shrinkage < 1.0
        assert dict(stabilized.sample_covariance[SIGNAL_ONE]) == {
            SIGNAL_ONE: 1.0,
            SIGNAL_TWO: 0.75,
        }
        assert dict(stabilized.sample_covariance[SIGNAL_TWO]) == {
            SIGNAL_ONE: 0.75,
            SIGNAL_TWO: 0.625,
        }

    def test_the_covariance_is_of_signals_with_symbols_as_observations(self):
        """The matrix is keyed by signal_id in both directions.

        The sentence says *signal* covariance, and the shape below is what
        that means: a ``p × p`` matrix over the signals, estimated from the
        symbols' joint observations of them — not a symbol-by-symbol matrix,
        which would be the *book's* covariance and would answer a question
        about positions rather than about the signals' standing.
        """
        stabilized = stabilize_weights(_correlated())
        assert set(stabilized.sample_covariance) == {SIGNAL_ONE, SIGNAL_TWO}
        for row in stabilized.sample_covariance.values():
            assert set(row) == {SIGNAL_ONE, SIGNAL_TWO}

    def test_the_answer_is_normalized_to_one_unit_of_gross(self):
        """Gross, not net — the convention feature 303 states, read earlier.

        A correlated signal stabilizes to a negative weight, and a net divisor
        would divide by whatever the hedges happened to cancel to.  The
        weights sum in absolute value to one on every answered book, and each
        weight is its direction over the direction's gross — the record's own
        law, read here as arithmetic.
        """
        for signals in (_orthogonal(), _correlated(), _thin()):
            stabilized = stabilize_weights(signals)
            gross = math.fsum(abs(entry) for entry in stabilized.direction.values())
            for signal_id, weight in stabilized.weights.items():
                assert weight == stabilized.direction[signal_id] / gross
            assert math.isclose(
                math.fsum(abs(w) for w in stabilized.weights.values()), 1.0
            )

    def test_a_correlated_signal_stabilizes_to_a_hedge(self):
        """The sign the sentence's *before combination* buys.

        Conditioning the standing on the covariance is what lets the solve
        hedge: alpha and beta above co-move (sample correlation ``0.75`` over
        variances ``1.0`` and ``0.625``), so the stronger beta's weight eats
        the view alpha would have carried alone, and alpha earns its keep by
        fading it.  The information-ratio weighting feature 301 answers
        cannot hedge (every ratio is positive); this vector can, and does.
        """
        stabilized = stabilize_weights(_correlated())
        assert stabilized.weights[SIGNAL_TWO] > 0.0
        assert stabilized.weights[SIGNAL_ONE] < 0.0
        # The same scores with the correlated signal the weaker one: the
        # hedge flips to the other name, because the fade follows the
        # standing, not the spelling.
        flipped = stabilize_weights(
            [
                PromotedSignal(
                    SIGNAL_ONE, 3.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0, ADA: -1.0}
                ),
                PromotedSignal(
                    SIGNAL_TWO, 0.1, {BTC: 1.0, ETH: 0.5, SOL: -1.0, ADA: -0.5}
                ),
            ]
        )
        assert flipped.weights[SIGNAL_ONE] > 0.0
        assert flipped.weights[SIGNAL_TWO] < 0.0

    def test_the_stabilized_vector_disagrees_with_the_ir_weighting_where_it_must(self):
        """Two acts over one book, read against each other.

        On the correlated book the two weightings disagree — alpha at ``0.25``
        under the IR weighting, negative under the stabilized one — and the
        disagreement is the whole content of *before combination*: a weighting
        that knows how the signals move together is a different answer, not a
        re-derivation of feature 301's.
        """
        stabilized = stabilize_weights(_correlated())
        combined = combine(_correlated())
        assert dict(combined.weights) == {SIGNAL_ONE: 0.25, SIGNAL_TWO: 0.75}
        assert dict(stabilized.weights) != dict(combined.weights)

    def test_a_rank_deficient_sample_is_answered_off_its_deficiency(self):
        """The rescue: three signals over three symbols, sample of rank two.

        The raw sample has no inverse (the demeaned observations span only two
        dimensions), and the solve that refused is exactly what the shrinkage
        exists to make safe: the estimator lifts the matrix off its
        deficiency and the answer is carried — with the intensity the sample
        itself asked for, strictly between the raw sample and the target.
        """
        stabilized = stabilize_weights(_thin())
        assert 0.0 < stabilized.shrinkage < 1.0
        assert math.isclose(math.fsum(abs(w) for w in stabilized.weights.values()), 1.0)
        # The symmetry of the book is the symmetry of the answer: alpha and
        # beta enter identically, and the redundant copy is faded.
        assert stabilized.weights[SIGNAL_ONE] == pytest.approx(
            stabilized.weights[SIGNAL_TWO]
        )
        assert stabilized.weights["copy"] < 0.0

    def test_a_single_signal_is_answered_as_the_whole_book(self):
        """The one-signal book lands in the intensity's limit branch.

        Its ``1 × 1`` covariance is its own average variance, the dispersion
        from the target is zero, and the solve of a positive scalar against a
        positive ratio is one weight: the whole book, ``1.0`` — answered
        rather than refused, because nothing divides by nothing on that path
        and a refusal would invent a degeneracy the arithmetic does not have.
        """
        stabilized = stabilize_weights(
            [PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 2.0, SOL: 3.0})]
        )
        assert stabilized.shrinkage == 1.0
        assert dict(stabilized.weights) == {SIGNAL_ONE: 1.0}

    def test_the_act_is_order_independent_and_deterministic(self):
        """Signals, symbol keys and call order leave the record unmoved.

        Signals and symbols are read in sorted order and every sum is an
        :func:`math.fsum`, so a re-run over the same signals in a different
        order — or with the same scores spelled in a different key order —
        answers an identical record, and two deployments handed the same book
        read the same stabilization.
        """
        first = stabilize_weights(_correlated())
        for permutation in itertools.permutations(_correlated()):
            assert stabilize_weights(list(permutation)) == first
        reversed_scores = [
            PromotedSignal(
                signal.signal_id,
                signal.information_ratio,
                dict(reversed(list(signal.target_scores.items()))),
            )
            for signal in _correlated()
        ]
        assert stabilize_weights(reversed_scores) == first
        assert stabilize_weights(_correlated()) == first

    def test_the_weights_are_keyed_by_signal_id_sorted(self):
        """The vector is over signals, emitted sorted so records compare."""
        stabilized = stabilize_weights(_correlated())
        assert list(stabilized.weights) == sorted(stabilized.weights)
        assert list(stabilized.direction) == sorted(stabilized.direction)
        assert list(stabilized.information_ratios) == sorted(
            stabilized.information_ratios
        )

    def test_weight_is_the_vectors_entry_for_one_signal(self):
        """``weight(signal_id)`` is the answer's entry, and it is the record's."""
        stabilized = stabilize_weights(_orthogonal())
        assert stabilized.weight(SIGNAL_ONE) == stabilized.weights[SIGNAL_ONE]
        assert stabilized.weight(SIGNAL_ONE) == 0.25

    def test_weight_refuses_a_signal_the_book_does_not_cover(self):
        """A signal the vector holds no weight for is refused, not zeroed.

        A fabricated zero would read as *this signal stabilizes to nothing* —
        a weighting decision this act never made.  The refusal carries no
        code word: it names the signal and the ones carried, and that is the
        whole fact.
        """
        with pytest.raises(BookConstructionError) as caught:
            stabilize_weights(_orthogonal()).weight("DOGE")
        message = str(caught.value)
        assert "DOGE" in message
        assert not message.startswith(DISPERSIONLESS_BOOK_CODE)
        assert not message.startswith(SINGULAR_COVARIANCE_CODE)


class TestTheIntensityIsEstimatedNeverConfigured:
    """The one figure the estimator produces belongs to nobody to set."""

    def test_the_verb_takes_the_signals_and_nothing_else(self):
        """No ``shrinkage=`` keyword — the sentence names Ledoit-Wolf.

        What that names over a bare shrinkage is precisely that the intensity
        is a measurement taken from the sample; a keyword would be a knob §C8
        states no figure for, and a deployment that dialled it to zero would
        hold the raw sample covariance wearing a stabilized name.  Pinned
        through the function object, so a renamed keyword still fails, and
        behaviourally, so a default that later appeared would be caught too.
        """
        parameters = inspect.signature(stabilize_weights).parameters
        assert set(parameters) == {"signals"}
        with pytest.raises(TypeError):
            stabilize_weights(_orthogonal(), shrinkage=0.5)  # type: ignore[call-arg]

    def test_the_module_carries_no_intensity_of_its_own(self):
        """The only numeric literals are the estimator's and the checks' own.

        Checked by parsing the module: ``0.0`` and ``1.0`` (the interval, the
        mixture and the unit of gross), ``2`` (the estimation error's squared
        divisor), and the three comparisons' tolerances (the pivot threshold
        at a trillionth, the gross-one law and the solve residual).  Anything
        else would be a figure nobody handed the act — a default intensity
        wearing a constant's name.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        }
        assert literals == {0.0, 1.0, 2, 1e-12, 1e-9, 1e-6}, literals

    def test_the_intensity_sits_in_the_unit_interval_on_every_answered_book(self):
        """The clipped ratio never leaves ``[0, 1]``, whatever the sample.

        The ``min(b̄², d²)`` numerator does the clipping — no branch, no
        clamp, no configuration — and the two boundary books below land on
        the two ends: the isotropic sample at total shrinkage, the noisy thin
        one partway between the sample and the target.
        """
        assert stabilize_weights(_orthogonal()).shrinkage == 1.0
        thin = stabilize_weights(_thin()).shrinkage
        assert 0.0 <= thin <= 1.0


class TestTheDispersionlessBookIsRefused:
    """No second moment to stabilize — the first of the two judgments."""

    def test_a_book_whose_signals_never_vary_is_refused(self):
        """Every signal scoring every symbol identically demeans to nothing.

        The sample covariance is the zero matrix, there is no second moment
        for any shrinkage to stabilize, and answering a weight vector anyway
        would counterfeit a stabilization no sample supports — the same
        perpetration feature 303 refuses when it declines to normalize a flat
        composite, read here on the covariance's own divisor.
        """
        flat = [
            PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 2.0, ETH: 2.0, SOL: 2.0}),
            PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 4.0, ETH: 4.0, SOL: 4.0}),
        ]
        with pytest.raises(ShrinkageError) as caught:
            stabilize_weights(flat)
        message = str(caught.value)
        assert message.startswith(DISPERSIONLESS_BOOK_CODE)
        assert "BTC" in message and "ETH" in message and "SOL" in message
        assert "no second moment" in message

    def test_a_one_symbol_book_is_always_this_refusal(self):
        """A cross-section of one demeans to nothing, whatever it scored.

        Two signals, two different scores, one symbol: the refusal is not
        about the signals' agreement but about the book's width — there is no
        variation across a cross-section of one, and the message says so in
        the clause an operator greps for.
        """
        with pytest.raises(ShrinkageError) as caught:
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0}),
                    PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 2.0}),
                ]
            )
        message = str(caught.value)
        assert message.startswith(DISPERSIONLESS_BOOK_CODE)
        assert "one symbol" in message

    def test_a_refused_book_forms_no_value(self):
        """A refused act leaves nothing behind — no record, no weights."""
        with pytest.raises(ShrinkageError):
            stabilize_weights([PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 5.0, ETH: 5.0})])

    def test_one_varying_signal_is_enough_to_be_a_book(self):
        """Only the *wholly* dispersionless book is refused.

        A signal that holds a constant view across the symbols while another
        varies is a book with dispersion: the constant one simply contributes
        a zero row to the demeaned observations, which the covariance states
        and the shrinkage handles — the refusal is over the book's second
        moment, not over any one signal's.
        """
        stabilized = stabilize_weights(
            [
                PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 2.0, ETH: 2.0, SOL: 2.0}),
                PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 1.0, ETH: 2.0, SOL: 3.0}),
            ]
        )
        assert stabilized.sample_covariance[SIGNAL_ONE][SIGNAL_ONE] == 0.0
        assert math.isclose(math.fsum(abs(w) for w in stabilized.weights.values()), 1.0)


class TestTheSingularCovarianceIsRefused:
    """No inverse to solve against — the second of the two judgments."""

    def test_a_two_symbol_book_of_two_signals_is_refused(self):
        """``n`` demeaned observations span at most ``n − 1`` dimensions.

        Two symbols give two demeaned observations that are always collinear
        (each symbol's is the other's negation), so the sample is rank one
        and the shrinkage that would lift it is zero here — every
        observation's own outer product already equals the sample, so the
        estimator measured no estimation error to shrink by.  No weight
        vector solves ``Σ·w = IR``, and the refusal names both counts the
        boundary turns on.
        """
        with pytest.raises(ShrinkageError) as caught:
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: -1.0}),
                    PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 2.0, ETH: -2.0}),
                ]
            )
        message = str(caught.value)
        assert message.startswith(SINGULAR_COVARIANCE_CODE)
        assert "2 signals" in message
        assert "2 symbols" in message
        assert "more symbols" in message and "fewer signals" in message

    def test_a_one_signal_book_over_two_symbols_is_answered(self):
        """The boundary is signals against symbols, not a symbol count.

        One signal over two symbols has a ``1 × 1`` covariance — the
        variance of its demeaned scores, strictly positive on a book with
        dispersion — and the solve is a division, not an inversion.  The
        answer is the whole book, as every one-signal book's is.
        """
        stabilized = stabilize_weights(
            [PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: -1.0})]
        )
        assert dict(stabilized.weights) == {SIGNAL_ONE: 1.0}

    def test_the_refused_book_forms_no_value(self):
        """No pseudo-inverse, no fabricated direction — nothing is answered."""
        with pytest.raises(ShrinkageError):
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: -1.0}),
                    PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 3.0, ETH: -3.0}),
                ]
            )

    def test_the_rescue_is_the_sharp_edge_of_this_refusal(self):
        """Rank deficiency is survivable exactly when the estimator shrank.

        The thin book below has the same rank problem one symbol wider, and
        it is answered (pinned exactly in ``TestTheAct`` above); the
        difference is the intensity, which the sample itself set above zero
        there.  This test pins the pairing — the refusal and the rescue are
        one boundary, drawn by the estimator's own measurement.
        """
        assert 0.0 < stabilize_weights(_thin()).shrinkage < 1.0
        with pytest.raises(ShrinkageError):
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: -1.0}),
                    PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 2.0, ETH: -2.0}),
                ]
            )


class TestTheAskIsRefusedBeforeAnythingIsJudged:
    """The ask's own facts — :class:`book.ShrinkageRequestError`."""

    @pytest.mark.parametrize("signals", [None, [], (), 42, True, "alpha", b"alpha"])
    def test_no_book_at_all_is_refused_as_empty(self, signals):
        """Nothing handed, or something that is not an iterable of signals.

        A bare string is the sharp one: it *is* iterable, and a caller that
        meant to hand one signal by name would otherwise have its characters
        read as signals — refused here as the ask's own fact.
        """
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(signals)
        assert str(caught.value).startswith("empty_book")

    def test_a_signal_without_a_name_is_refused(self):
        """A weight cannot be attributed to a signal that carries no id.

        The three spellings of the same fact: no attribute at all, a blank
        string, a non-string — refused under feature 301's own word, because
        it is the same fact about the same surface read one step earlier on
        the chain.
        """
        for bad_id in (None, "   ", 42):
            with pytest.raises(ShrinkageRequestError) as caught:
                stabilize_weights([StandInSignal(bad_id, 1.0, {BTC: 1.0, ETH: -1.0})])
            assert str(caught.value).startswith("unnamed_signal")

    def test_two_signals_sharing_a_name_are_refused(self):
        """One signal, one id — the covariance is attributed per id."""
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: -1.0, SOL: 1.0}),
                    PromotedSignal(SIGNAL_ONE, 3.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0}),
                ]
            )
        assert str(caught.value).startswith("duplicate_signal")

    @pytest.mark.parametrize(
        "ratio",
        [None, True, "1.0", float("nan"), float("inf"), float("-inf")],
    )
    def test_a_ratio_that_is_not_a_finite_real_is_refused(self, ratio):
        """A standing the solve cannot condition on, under 301's own word.

        A missing attribute is the sentinel's fact (*the signal named
        nothing*) rather than a value read and refused; a ``bool`` is a flag
        where a magnitude belongs; a ``NaN`` or ±inf would reach the weights
        dressed as a standing.
        """
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(
                [StandInSignal(SIGNAL_ONE, ratio, {BTC: 1.0, ETH: -1.0, SOL: 1.0})]
            )
        assert str(caught.value).startswith("non_finite_ir")

    @pytest.mark.parametrize("ratio", [0.0, -2.0])
    def test_a_non_positive_ratio_is_refused_not_zero_weighted(self, ratio):
        """Silently dropping a losing signal would hide a portfolio decision.

        Feature 301's own line, read before the combination: the standing to
        weight the book is undefined, and zero-weighting it would be a
        decision the caller never sees made.
        """
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(
                [StandInSignal(SIGNAL_ONE, ratio, {BTC: 1.0, ETH: -1.0, SOL: 1.0})]
            )
        assert str(caught.value).startswith("non_positive_ir")

    def test_a_signal_without_scores_is_refused(self):
        """A signal that expresses no view contributes no observation.

        No mapping, a non-mapping, an empty mapping and a blank symbol key
        are the four spellings: the covariance is a joint sample, and a
        signal with no scores observed a different book.
        """
        for bad_scores in (None, [0.1, 0.2], {}, {"  ": 1.0}):
            with pytest.raises(ShrinkageRequestError) as caught:
                stabilize_weights([StandInSignal(SIGNAL_ONE, 1.0, bad_scores)])
            assert str(caught.value).startswith("signal_without_scores")

    @pytest.mark.parametrize(
        "score", ["1.0", None, True, float("nan"), float("inf"), float("-inf")]
    )
    def test_a_score_that_is_not_a_finite_real_is_refused(self, score):
        """A ``NaN`` observation would reach the covariance dressed as a view.

        Every entry of the estimate is a product of demeaned scores, so one
        non-finite score makes the whole matrix unboundable — refused at the
        read, under 301's own word, before any product is taken.
        """
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(
                [StandInSignal(SIGNAL_ONE, 1.0, {BTC: score, ETH: 1.0, SOL: -1.0})]
            )
        assert str(caught.value).startswith("non_finite_score")

    def test_a_signal_that_misses_a_symbol_the_book_covers_is_refused(self):
        """The union is the book, and every signal must observe all of it.

        The covariance is estimated over the symbols the book covers, so a
        grid with holes in it is not a joint sample.  Refused under 301's own
        word — zero-filling would counterfeit a view, exactly as it would
        there.
        """
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(
                [
                    PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 1.0}),
                    PromotedSignal(SIGNAL_TWO, 3.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0}),
                ]
            )
        message = str(caught.value)
        assert message.startswith("uncovered_symbol")
        assert SIGNAL_ONE in message and "SOL" in message

    def test_the_ask_settles_before_the_book_is_judged(self):
        """A broken read is *fix the ask*, never *your book has no dispersion*.

        The ordering every verdict in this workspace states.  Both faces
        apply below — the book is dispersionless *and* the ask is malformed —
        and the ask's class is the one that fires, because a caller told its
        book has no second moment when the real fault is a ratio it mistyped
        would be told to re-examine its signals.
        """
        flat_and_broken = [StandInSignal(SIGNAL_ONE, 0.0, {BTC: 2.0, ETH: 2.0})]
        with pytest.raises(ShrinkageRequestError) as caught:
            stabilize_weights(flat_and_broken)
        assert not isinstance(caught.value, ShrinkageError)
        flat_and_uncovered = [
            StandInSignal(SIGNAL_ONE, 1.0, {BTC: 2.0, ETH: 2.0}),
            StandInSignal(SIGNAL_TWO, 3.0, {BTC: 2.0}),
        ]
        with pytest.raises(ShrinkageRequestError) as second:
            stabilize_weights(flat_and_uncovered)
        assert str(second.value).startswith("uncovered_symbol")

    def test_the_ask_borrows_the_combiners_words_and_mints_none_of_its_own(self):
        """The code words on the ask are feature 301's, one for one.

        The act reads the same promoted-signal surface the combiner reads,
        one step earlier on the chain, so the facts are the same facts — and
        a caller reading a deployment log should not have to learn a second
        token for *a signal missed a symbol the book covers*.  The one place
        this feature mints words is the judgment's two, pinned above.
        """
        for bad, word in (
            ([], "empty_book"),
            ([StandInSignal(None, 1.0, {BTC: 1.0})], "unnamed_signal"),
            ([StandInSignal(SIGNAL_ONE, 0.0, {BTC: 1.0})], "non_positive_ir"),
            ([StandInSignal(SIGNAL_ONE, float("nan"), {BTC: 1.0})], "non_finite_ir"),
            ([StandInSignal(SIGNAL_ONE, 1.0, {})], "signal_without_scores"),
            ([StandInSignal(SIGNAL_ONE, 1.0, {BTC: float("inf")})], "non_finite_score"),
        ):
            with pytest.raises(ShrinkageRequestError) as caught:
                stabilize_weights(bad)
            assert str(caught.value).startswith(word), word


class TestTheRecordIsACheckNotAClaim:
    """:class:`book.StabilizedWeights` — the record enforces the act's terms."""

    def test_an_honest_record_is_admitted(self):
        """The check admits what the act answers — it is not a wall."""
        answered = stabilize_weights(_correlated())
        rebuilt = StabilizedWeights(
            weights=dict(answered.weights),
            direction=dict(answered.direction),
            shrinkage=answered.shrinkage,
            information_ratios=dict(answered.information_ratios),
            sample_covariance={
                key: dict(row) for key, row in answered.sample_covariance.items()
            },
            covariance={key: dict(row) for key, row in answered.covariance.items()},
        )
        assert rebuilt == answered

    def test_a_shrunk_covariance_that_is_not_the_intensitys_mixture_is_refused(self):
        """The record's own identity, exact: ``ρ·m·I + (1 − ρ)·S``.

        The verb and the check share one spelling of the expression, so a
        record whose shrunk covariance disagrees with its own intensity
        applied to its own sample — by a part in a billion, below any
        rounding the honest arithmetic could produce — is refused.
        """
        answered = stabilize_weights(_correlated())
        tampered = {key: dict(row) for key, row in answered.covariance.items()}
        tampered[SIGNAL_ONE][SIGNAL_ONE] += 1e-9
        with pytest.raises(ShrinkageRequestError):
            StabilizedWeights(
                weights=dict(answered.weights),
                direction=dict(answered.direction),
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance=tampered,
            )

    def test_weights_that_are_not_the_direction_normalized_are_refused(self):
        """A weight is its direction over the direction's gross, exactly."""
        answered = stabilize_weights(_correlated())
        tampered = dict(answered.weights)
        tampered[SIGNAL_ONE] += 1e-9
        with pytest.raises(ShrinkageRequestError):
            StabilizedWeights(
                weights=tampered,
                direction=dict(answered.direction),
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )

    def test_a_zero_direction_is_refused(self):
        """The solve of a covariance against positive ratios is never zero."""
        answered = stabilize_weights(_orthogonal())
        with pytest.raises(ShrinkageRequestError):
            StabilizedWeights(
                weights={SIGNAL_ONE: 1.0, SIGNAL_TWO: 0.0},
                direction={SIGNAL_ONE: 0.0, SIGNAL_TWO: 0.0},
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )

    def test_a_direction_that_does_not_solve_is_refused(self):
        """``Σ·v = IR`` — the residual check, with its stated tolerance.

        A direction scaled by two normalizes to the same weights and passes
        the mixture and the gross-one law; what it cannot pass is the solve
        it claims to be, because ``Σ·(2v)`` is ``2·IR`` and the residual is
        checked at a part in a million — far above elimination noise, far
        below a factor of two.  The smaller perturbation below (a thousandth
        on one entry, weights rebuilt consistently) is caught by the same
        check, proving the tolerance admits only the rounding it says it
        does.
        """
        answered = stabilize_weights(_orthogonal())
        doubled = {key: 2.0 * value for key, value in answered.direction.items()}
        with pytest.raises(ShrinkageRequestError) as caught:
            StabilizedWeights(
                weights={
                    key: doubled[key] / math.fsum(abs(v) for v in doubled.values())
                    for key in doubled
                },
                direction=doubled,
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )
        assert "solve" in str(caught.value)
        nudged = dict(answered.direction)
        nudged[SIGNAL_ONE] += 1e-3
        gross = math.fsum(abs(v) for v in nudged.values())
        with pytest.raises(ShrinkageRequestError):
            StabilizedWeights(
                weights={key: nudged[key] / gross for key in nudged},
                direction=nudged,
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )

    @pytest.mark.parametrize("intensity", [1.5, -0.1, True, "0.5", float("nan")])
    def test_an_intensity_outside_the_unit_interval_is_refused(self, intensity):
        """The mixture's weight is a probability, not a free real.

        A figure outside ``[0, 1]`` extrapolates past both matrices into a
        covariance nobody estimated, and a ``bool`` is a flag where a
        measurement belongs — refused as the ask's own fact, before any
        identity between fields is read.
        """
        answered = stabilize_weights(_orthogonal())
        with pytest.raises(ShrinkageRequestError):
            StabilizedWeights(
                weights=dict(answered.weights),
                direction=dict(answered.direction),
                shrinkage=intensity,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )

    def test_an_asymmetric_covariance_is_refused(self):
        """A covariance that disagrees across its diagonal is two matrices.

        The sample is computed once per pair and mirrored, and the mixture
        of a symmetric matrix with the identity stays symmetric, so a record
        carrying ``(i, j) ≠ (j, i)`` is not one covariance stated twice —
        and which one the solve used would be the record's untold half.
        """
        answered = stabilize_weights(_correlated())
        tampered = {key: dict(row) for key, row in answered.sample_covariance.items()}
        tampered[SIGNAL_ONE][SIGNAL_TWO] += 1e-9
        with pytest.raises(ShrinkageRequestError) as caught:
            StabilizedWeights(
                weights=dict(answered.weights),
                direction=dict(answered.direction),
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance=tampered,
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )
        assert "symmetric" in str(caught.value)

    def test_surfaces_that_name_different_signal_sets_are_refused(self):
        """One book read five ways — a weight checked against a row its own
        mapping does not carry would make every check vacuous."""
        answered = stabilize_weights(_correlated())
        short_direction = dict(answered.direction)
        del short_direction[SIGNAL_ONE]
        with pytest.raises(ShrinkageRequestError) as caught:
            StabilizedWeights(
                weights=dict(answered.weights),
                direction=short_direction,
                shrinkage=answered.shrinkage,
                information_ratios=dict(answered.information_ratios),
                sample_covariance={
                    key: dict(row) for key, row in answered.sample_covariance.items()
                },
                covariance={key: dict(row) for key, row in answered.covariance.items()},
            )
        assert SIGNAL_ONE in str(caught.value)

    def test_the_record_carries_the_estimate_behind_it(self):
        """The sample, the intensity and the shrunk matrix are on the record.

        The refusals above are legible only because the record states the
        arithmetic it was built from — the same discipline
        :class:`book.CompositeBook` states by carrying its contributions, and
        the reason a caller can audit a stabilization without re-estimating
        it.
        """
        answered = stabilize_weights(_correlated())
        assert answered.information_ratios[SIGNAL_ONE] == 1.0
        assert answered.information_ratios[SIGNAL_TWO] == 3.0
        assert answered.sample_covariance[SIGNAL_ONE][SIGNAL_TWO] == 0.75
        assert answered.covariance is not answered.sample_covariance

    def test_the_record_is_frozen(self):
        """A weight vector that could move after it was read would be a
        stabilization that changed beneath the book it stabilized."""
        with pytest.raises(dataclasses.FrozenInstanceError):
            stabilize_weights(_orthogonal()).shrinkage = 0.5  # type: ignore[misc]

    def test_the_records_mappings_are_read_only(self):
        """The mappings are the value's own; none can be edited in place."""
        answered = stabilize_weights(_correlated())
        with pytest.raises(TypeError):
            answered.weights[SIGNAL_ONE] = 1.0  # type: ignore[index]
        with pytest.raises(TypeError):
            answered.direction[SIGNAL_ONE] = 1.0  # type: ignore[index]
        with pytest.raises(TypeError):
            answered.information_ratios[SIGNAL_ONE] = 1.0  # type: ignore[index]
        with pytest.raises(TypeError):
            answered.sample_covariance[SIGNAL_ONE][SIGNAL_TWO] = 1.0  # type: ignore[index]
        with pytest.raises(TypeError):
            answered.covariance[SIGNAL_ONE][SIGNAL_TWO] = 1.0  # type: ignore[index]


class TestTheVocabularyIsTheActsOwnTwoClasses:
    """Two faces of one sentence, siblings under the member's one base."""

    def test_both_classes_descend_from_the_members_base(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(ShrinkageRequestError, BookConstructionError)
        assert issubclass(ShrinkageError, BookConstructionError)

    def test_neither_class_is_the_other(self):
        """The facts are genuinely different, so the classes are siblings.

        A dispersionless book is refusable though every signal was perfectly
        well stated, and a mis-stated signal is refusable though the book
        expresses a perfectly good view — folding them together would make a
        caller that must react differently catch one class and re-inspect
        something it cannot tell apart.
        """
        assert not issubclass(ShrinkageRequestError, ShrinkageError)
        assert not issubclass(ShrinkageError, ShrinkageRequestError)

    def test_the_members_other_features_still_raise_the_bare_base(self):
        """The act's two classes leave the old surface reachable.

        ``combine([])`` still raises the base itself, and the accessor's own
        refusal still answers under it, so a caller written against feature
        301 goes on catching what it caught.
        """
        with pytest.raises(BookConstructionError) as caught:
            combine([])
        assert type(caught.value) is BookConstructionError
        with pytest.raises(BookConstructionError) as accessor:
            stabilize_weights(_orthogonal()).weight("DOGE")
        assert type(accessor.value) is BookConstructionError

    def test_the_judgment_is_catchable_without_the_ask_and_the_other_way_round(
        self,
    ):
        """The distinction a caller has to be able to make, exercised."""
        with pytest.raises(ShrinkageError):
            stabilize_weights(
                [PromotedSignal(SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 1.0, SOL: 1.0})]
            )
        with pytest.raises(ShrinkageRequestError):
            stabilize_weights(
                [StandInSignal(SIGNAL_ONE, 0.0, {BTC: 1.0, ETH: 1.0, SOL: 1.0})]
            )

    def test_the_two_codes_are_greppable_and_distinct(self):
        """One word per repair, so an operator's log line lands on the fact.

        *Hand signals that vary* against *hand more symbols or fewer
        signals* — two repairs, two tokens, one class, because the caller's
        position is the same either way.
        """
        assert DISPERSIONLESS_BOOK_CODE == "dispersionless_book"
        assert SINGULAR_COVARIANCE_CODE == "singular_covariance"


class TestTheActIsAVerdictOverAValueTheCallerHolds:
    """No store, no environment, no clock, no other member."""

    def test_the_act_accepts_duck_typed_signals(self):
        """The seam reads the promoted-signal surface, not the type.

        The loader imports members under synthetic names and re-executes
        them, so a signal this process composed may be a second class
        object; a stand-in proving the seam is what the composed application
        actually depends on.
        """
        stabilized = stabilize_weights(
            [
                StandInSignal(
                    SIGNAL_ONE, 1.0, {BTC: 1.0, ETH: 1.0, SOL: -1.0, ADA: -1.0}
                ),
                StandInSignal(
                    SIGNAL_TWO, 3.0, {BTC: 1.0, ETH: -1.0, SOL: 1.0, ADA: -1.0}
                ),
            ]
        )
        assert dict(stabilized.weights) == {SIGNAL_ONE: 0.25, SIGNAL_TWO: 0.75}

    def test_the_act_reads_the_signals_the_combiner_reads(self):
        """§C8's first arrow as a composition: one input, two readings.

        The same promoted signals feed both acts — this one *before* the
        combination, as its sentence places it — and the composite feature
        301 answers is untouched by the stabilization: the shrinkage answers
        a vector *beside* the combiner's, and neither re-opens the other.
        """
        signals = _orthogonal()
        stabilized = stabilize_weights(signals)
        combined = combine(signals)
        assert dict(stabilized.weights) == dict(combined.weights)
        # And the combiner's own answer is unchanged by the stabilization
        # having run: two pure functions over one value.
        assert combine(_orthogonal()).scores == combined.scores

    def test_the_act_runs_with_no_database_and_no_environment(self, monkeypatch):
        """Exercised with the deployment's variables deleted.

        A version that had grown a store dependency, an environment knob or
        a clock would fail here rather than in production.
        """
        for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
            monkeypatch.delenv(gone, raising=False)
        stabilized = stabilize_weights(_correlated())
        assert stabilized.shrinkage == CORRELATED_INTENSITY

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

        Only relative imports (``from .errors import …``) are admissible, and
        only the stdlib beside them — the Ledoit & Wolf estimator is spelled
        on the page rather than imported, because no third party may sit on
        the replay path's import bill.  A future edit cannot reach out to
        ``scoring`` or ``evaluator`` for a normalization it restates here,
        nor to ``book._combine`` for a validator that would raise feature
        301's error class from this feature's path.
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
            "types",
            "typing",
            "__future__",
        }, imported
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module == "errors", node.module

    def test_the_act_holds_no_state(self):
        """Two records from the same signals share nothing mutable.

        The act is a pure function of the signals it is handed, so one
        record's mappings cannot be another's — the property a composed
        application depends on when it stabilizes the same book at two
        points of a run.
        """
        first = stabilize_weights(_correlated())
        second = stabilize_weights(_correlated())
        assert first == second
        assert first.weights is not second.weights
        assert first.covariance is not second.covariance
