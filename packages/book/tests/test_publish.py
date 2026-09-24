"""Feature 305's claim, stated as tests: the one output the orders consume.

app_spec.xml, "Portfolio Book Construction", feature 305: *System returns
final target weights as the only output consumed by the order layer.*  Both
documents state the fact at the foot of the construction's own chain and as its
last arrow rather than as another step: docs/alpha-engine-prd.md §C8 writes it
*"Signal book → IR-weighted combination with shrinkage → volatility targeting →
position and concentration limits → orders"*, and
docs/nullius-tech-architecture.md §13.1 writes the same chain through to
*"target weights"*, with §13.2's execution engine on the other side of the
seam.  Neither document adds an arithmetic to the sentence, so the claims worth
pinning are about the **shape** of the construction's answer:

* **the act publishes and never recomputes** — the final weights are the very
  floats feature 303 scaled and feature 304 bounded, so there is no second
  answer to a question an earlier step answered (which is the drift the
  sentence's *only* forecloses);
* **the output is one value and it is self-describing** — a frozen
  :class:`book.FinalTargetWeights` carrying the weights, the symbols and the
  gross exposure the chain's next step reads, and nothing else: the composite,
  the gross book, the scale and the two volatility figures stay on the record
  the construction computed them on;
* **the *only* is readable over the whole surface** — a caller may hold the
  construction's working beside the published set (that is where those figures
  belong), but a second *published* set in the instruction is refused, because
  two instructions leave the order layer choosing between them;
* **absence is not zero, on the last step of the chain** — a value carrying no
  ``weights``, a set covering no symbols, a blank symbol and a non-finite
  weight are the *absence* of a book and are refused, while a book held flat
  (every weight ``0.0``, feature 303's zero-target answer) is a decision and is
  published;
* **the vocabulary is the act's own two classes** — the ask
  (:class:`book.FinalWeightsRequestError`) and the one judgment the sentence
  mints (:class:`book.OrderLayerOutputError`), both under the member's
  :class:`book.BookConstructionError`, and a caller must be able to catch one
  without catching the other;
* **the act is a free function over a value the caller holds** — no store, no
  environment, no clock, no other member, no new component, and no arithmetic
  beyond reading a mapping.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math
from pathlib import Path

import pytest
from book import (
    ANNEXED_RECORD_CODE,
    NO_BOOK_CODE,
    PUBLISHED_KIND,
    BookConstructionError,
    CompositeBook,
    FinalTargetWeights,
    FinalWeightsRequestError,
    LimitBreachError,
    OrderLayerOutputError,
    PromotedSignal,
    VolatilityTargetError,
    apply_volatility_target,
    assert_only_output,
    combine,
    final_target_weights,
    is_only_output,
    rejects_breaching_target_weights,
)
from conftest import BTC, ETH, SIGNAL_ONE, SIGNAL_THREE, SIGNAL_TWO, SOL, StandInSignal

#: The module the layering pin at the foot of this file parses — anchored to
#: the file rather than to the process's working directory, so the suite gives
#: the same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_publish.py"

#: The figures the conftest's three signals answer along §C8's chain, all dyadic
#: so every one is checkable with ``==``: the composites are 0.1875 / 0.21875 /
#: 0.21875, so at a book volatility of 0.5 and a configured target of 0.2 the
#: scaled weights are 0.12 / 0.14 / 0.14 and the gross exposure is 0.4.
BOOK_VOLATILITY = 0.5
TARGET_VOLATILITY = 0.2
BTC_WEIGHT = 0.12
MAJOR_WEIGHT = 0.14
GROSS_EXPOSURE = 0.4


def _book() -> CompositeBook:
    """The combined book the conftest's three signals answer (feature 301)."""
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


def _final() -> FinalTargetWeights:
    """The publication of feature 303's answer — feature 305's act."""
    return final_target_weights(_weights())


@dataclasses.dataclass(frozen=True)
class _StandInWeights:
    """A stand-in for the target weights feature 303 answers.

    Feature 305's act reads the ``weights`` surface duck-typed — the loader
    imports members under synthetic names and re-executes them, so a value this
    process composed may be a second class object — and this is the shape that
    proves it: exactly the one attribute the chain's last step reads.
    """

    weights: dict[str, float]


@dataclasses.dataclass(frozen=True)
class _StandInPublished:
    """A stand-in for a published final target weights — a caller's own spelling.

    The ``only`` predicate gates on each value's own declaration rather than on
    this member's class, precisely because a member never isinstance-gates the
    value a composition seam hands out.  This is the shape that proves it.
    """

    weights: dict[str, float]
    kind: str = PUBLISHED_KIND


# -- The act publishes and never recomputes ---------------------------------------


class TestTheActPublishesRatherThanRecomputing:
    """§C8's last arrow: the construction's book, handed on unchanged."""

    def test_the_final_weights_are_the_constructed_floats(self):
        """Every published weight is the very figure feature 303 answered.

        The load-bearing half of "returns final target weights": publication is
        the chain's last arrow, so re-normalizing, re-scaling or re-rounding
        here would be a second answer to a question feature 301, 303 or 304
        already answered — and the order layer would hold a book nobody
        bounded.
        """
        target = _weights()
        final = final_target_weights(target)
        assert final.weights[BTC] == BTC_WEIGHT
        # ETH and SOL are the major weights — 0.35 of gross scaled by 0.4, which
        # lands one float below 0.14 in binary (the same value feature 303
        # answers and feature 304 bounds), so the claim is identity against the
        # constructed figure rather than a re-derived decimal.
        for symbol in (BTC, ETH, SOL):
            assert final.weight(symbol) == target.weight(symbol)
        assert final.weights == dict(target.weights)
        assert final.weights[ETH] == target.gross_weights[ETH] * target.scale

    def test_no_figure_is_rounded_or_normalized_on_the_way_out(self):
        """A non-dyadic book crosses the seam bit for bit.

        Dyadic weights could survive a stray rounding step unnoticed, so this
        one is deliberately not: the published figure is compared with ``==``
        against the figure feature 303 answered, and it is not the rounded
        decimal a "clean-up" on the way out would produce.
        """
        third = 1.0 / 3.0
        target = _StandInWeights({BTC: third, ETH: -2.0 * third})
        final = final_target_weights(target)
        assert final.weights[BTC] == third
        assert final.weights[ETH] == -2.0 * third
        assert final.gross_exposure == 1.0

    def test_the_published_record_carries_only_the_books_own_facts(self):
        """The working stays where the construction computed it.

        The composite and the two volatility figures are not lost — they are on
        the records that computed them — and they are deliberately *not*
        re-published here, because the sentence names one output.
        """
        final = _final()
        assert {field.name for field in dataclasses.fields(final)} == {"weights"}
        assert final.symbols == (BTC, ETH, SOL)
        assert final.gross_exposure == pytest.approx(GROSS_EXPOSURE)
        assert final.consumed_by_order_layer() is True

    def test_the_published_record_is_frozen(self):
        """What the order layer holds cannot move beneath the instruction.

        On this record that guarantee carries the sentence's own subject: a
        published set a later edit could re-scale would be a rebalance nobody
        decided, and the order layer has no bound to re-run and no act to
        re-apply, so nothing downstream could catch it.
        """
        final = _final()
        with pytest.raises(dataclasses.FrozenInstanceError):
            final.weights = {}  # type: ignore[misc]
        assert isinstance(final.weights, type(final.weights))

    def test_an_uncovered_symbol_is_refused_not_answered_zero(self):
        """A zero would read to the order layer as *hold none of it*."""
        with pytest.raises(FinalWeightsRequestError) as caught:
            _final().weight("DOGE")
        assert str(caught.value).startswith("uncovered_symbol")

    def test_two_publications_of_one_book_are_equal(self):
        """Deterministic and order-independent — no state between calls.

        The same book handed in a different insertion order publishes the same
        mapping: the act emits sorted, and it derives no figure, so the two
        answers agree symbol for symbol and float for float.
        """
        assert _final() == _final()
        target = _weights()
        assert _final().weights == final_target_weights(
            _StandInWeights({SOL: target.weight(SOL), BTC: target.weight(BTC), ETH: target.weight(ETH)})
        ).weights


# -- The only output ------------------------------------------------------------


class TestTheOnlyOutputIsReadableOverTheWholeSurface:
    """The sentence's *only*, read as a fact a caller can ask for."""

    def test_the_final_weights_are_the_only_output_among_the_working(self):
        """The construction's working may be held beside the published set.

        The composite, the target weights and their figures are not contraband:
        those records are where the construction's arithmetic *belongs*, and the
        sentence forecloses a second published *instruction*, not the working
        that produced the first.
        """
        composite = _book()
        target = _weights()
        final = final_target_weights(target)
        assert is_only_output(final, composite, target) is True
        assert assert_only_output(final, composite, target) is None
        assert is_only_output(final) is True

    def test_a_second_published_set_is_refused(self):
        """Two instructions leave the order layer choosing between them.

        The judgment is the verdict's, and the predicate answers the *fact*
        — ``False`` — rather than raising it, which is the split feature 304
        draws between :func:`book.is_breaching_limits` and
        :func:`book.rejects_breaching_target_weights`: a caller that only wants
        to know reads the bool; a caller that must be stopped before the venue
        runs the verdict.
        """
        final = _final()
        second = final_target_weights(_StandInWeights({BTC: 0.5, ETH: 0.5}))
        with pytest.raises(OrderLayerOutputError) as caught:
            assert_only_output(final, second)
        assert str(caught.value).startswith(ANNEXED_RECORD_CODE)
        assert is_only_output(final, second) is False
        # And the verdict never contradicts the predicate on the admitted path.
        assert is_only_output(final, _book(), _weights()) is True
        assert assert_only_output(final, _book(), _weights()) is None

    def test_the_predicate_and_the_verdict_settle_the_ask_identically(self):
        """One read, two spellings: they cannot disagree about a malformed ask."""
        for not_a_book in (_book(), _weights(), None):
            with pytest.raises(FinalWeightsRequestError):
                is_only_output(not_a_book)
            with pytest.raises(FinalWeightsRequestError):
                assert_only_output(not_a_book, _final())

    def test_the_same_record_twice_is_one_output_not_two(self):
        """The sentence counts outputs, not repetitions of one value.

        A caller passing its whole surface through — or listing a value it
        already passed beside itself — has still published one instruction;
        refusing that would report the caller's own bookkeeping as a second
        published set.  A *differently-built* record holding equal weights is a
        second output and is caught, which is what makes the reading one of
        identity rather than equality.
        """
        final = _final()
        assert is_only_output(final, final) is True
        assert assert_only_output(final, final, final) is None
        # Equal but distinct: two publications of the same book are two
        # instructions, and the order layer would have to choose between them.
        twin = final_target_weights(_weights())
        assert twin == final and twin is not final
        assert is_only_output(final, twin) is False
        with pytest.raises(OrderLayerOutputError):
            assert_only_output(final, twin, twin)

    def test_a_caller_s_own_spelling_of_a_published_set_is_judged_by_its_word(self):
        """No class is isinstance-gated at this seam, and it is load-bearing.

        The loader imports every member under a synthetic name, so a value this
        process composed may be a second class object; the declaration is what
        the seam reads, exactly as the chain's earlier steps read ``scores`` and
        ``weights``.
        """
        mine = _StandInPublished({BTC: 0.5, ETH: -0.5})
        assert is_only_output(mine) is True
        assert assert_only_output(mine, _book(), _weights()) is None
        assert is_only_output(mine, _final()) is False
        with pytest.raises(OrderLayerOutputError):
            assert_only_output(mine, _final())

    def test_a_value_declaring_itself_nothing_is_refused_as_the_ask(self):
        """The ask settles before the judgment: no book named, no count taken."""
        for not_a_book in (_book(), _weights(), {"BTC": 0.5}, None, "final_target_weights"):
            with pytest.raises(FinalWeightsRequestError) as caught:
                is_only_output(not_a_book)
            assert str(caught.value).startswith(NO_BOOK_CODE)

    def test_the_ask_settles_before_the_annexed_record_is_judged(self):
        """A malformed ask is refused even when a second set is annexed.

        The ordering every verdict in this workspace states: a caller that
        handed no book is told *what to fix*, never told its instruction carried
        two published sets.
        """
        with pytest.raises(FinalWeightsRequestError) as caught:
            assert_only_output(_book(), _final())
        assert str(caught.value).startswith(NO_BOOK_CODE)
        with pytest.raises(FinalWeightsRequestError):
            assert_only_output(None, _final(), _final())

    def test_a_record_declaring_another_kind_is_not_a_published_set(self):
        """The word is the gate, and a near-miss is not the word."""
        for kind in ("target_weights", "FinalTargetWeights", "final targets", None):
            near_miss = _StandInPublished({BTC: 0.5}, kind=kind)
            with pytest.raises(FinalWeightsRequestError):
                assert_only_output(near_miss)
        # And a near-miss is not counted as an annexed record either, so the
        # judgment is over the sentence's own word rather than over duck-typing.
        assert assert_only_output(_final(), _StandInPublished({BTC: 0.5}, kind=None)) is None
        assert isinstance(_StandInPublished({BTC: 0.5}, kind=None), object)


# -- Absence is not zero ---------------------------------------------------------


class TestAbsenceIsNotZeroOnTheLastStepOfTheChain:
    """What reaches the order layer must be a book; a flat book is one."""

    def test_a_value_carrying_no_weights_is_refused(self):
        """*Not a book* and *a book covering nothing* are different reports."""
        with pytest.raises(FinalWeightsRequestError) as caught:
            final_target_weights(object())
        assert NO_BOOK_CODE in str(caught.value)

    def test_an_empty_book_is_refused(self):
        """An empty instruction is not a decision to hold nothing."""
        with pytest.raises(FinalWeightsRequestError) as caught:
            final_target_weights(_StandInWeights({}))
        assert NO_BOOK_CODE in str(caught.value)

    def test_a_non_mapping_is_refused(self):
        with pytest.raises(FinalWeightsRequestError) as caught:
            final_target_weights(_StandInWeights([("BTC", 0.5)]))  # type: ignore[arg-type]
        assert NO_BOOK_CODE in str(caught.value)

    def test_a_blank_symbol_and_a_non_finite_weight_are_refused(self):
        for bad in (_StandInWeights({"  ": 0.5}), _StandInWeights({BTC: math.nan})):
            with pytest.raises(FinalWeightsRequestError):
                final_target_weights(bad)
        for bad in (
            _StandInWeights({BTC: True}),
            _StandInWeights({BTC: "0.5"}),  # type: ignore[dict-item]
            _StandInWeights({BTC: math.inf}),
        ):
            with pytest.raises(FinalWeightsRequestError):
                final_target_weights(bad)

    def test_a_book_held_flat_is_published(self):
        """Feature 303's zero-target answer is a decision, not an absence.

        *Hold nothing* is an instruction the construction is entitled to
        publish — every symbol is named and weighted ``0.0`` — where a value
        carrying no weights and a set covering no symbols are the absence of a
        book and are refused.  The two zeros this member distinguishes one step
        upstream are distinguished here too, read on the published set.
        """
        flat = apply_volatility_target(
            _book(), volatility=BOOK_VOLATILITY, target_volatility=0.0
        )
        published = final_target_weights(flat)
        assert published.weights == {BTC: 0.0, ETH: 0.0, SOL: 0.0}
        assert published.symbols == (BTC, ETH, SOL)
        assert published.gross_exposure == 0.0
        assert published.consumed_by_order_layer() is True

    def test_the_flat_book_is_admitted_by_the_members_own_bounds(self):
        """Feature 304's verdict lets it through, so the chain reaches 305."""
        flat = apply_volatility_target(
            _book(), volatility=BOOK_VOLATILITY, target_volatility=0.0
        )
        assert (
            rejects_breaching_target_weights(
                flat, per_position_limit=0.0, concentration_limit=0.0
            )
            is None
        )
        assert final_target_weights(flat).gross_exposure == 0.0


# -- The vocabulary --------------------------------------------------------------


class TestTheVocabularyIsTheActsOwnTwoClasses:
    """The ask's own facts and the one judgment the sentence mints."""

    def test_both_classes_are_siblings_under_the_members_base(self):
        for error in (FinalWeightsRequestError, OrderLayerOutputError):
            assert issubclass(error, BookConstructionError)
        assert not issubclass(FinalWeightsRequestError, OrderLayerOutputError)
        assert not issubclass(OrderLayerOutputError, FinalWeightsRequestError)

    def test_the_new_classes_are_not_their_neighbours(self):
        """The facts are different, so a caller's ``except`` can tell them apart.

        One step upstream a breaching book is feature 304's judgment and a flat
        composite is feature 303's; neither is *no book reached the orders*, and
        a caller that conflated them would re-inspect something it cannot tell
        apart.
        """
        assert not issubclass(FinalWeightsRequestError, LimitBreachError)
        assert not issubclass(FinalWeightsRequestError, VolatilityTargetError)
        assert not issubclass(LimitBreachError, OrderLayerOutputError)

    def test_the_judgment_carries_its_greppable_code(self):
        with pytest.raises(OrderLayerOutputError) as caught:
            assert_only_output(_final(), _final(), _final())
        assert str(caught.value).startswith(ANNEXED_RECORD_CODE)
        # Every annexed record is named, because the repair is one instruction.
        assert "2 further record(s)" in str(caught.value)
        assert ANNEXED_RECORD_CODE == "annexed_record"
        assert NO_BOOK_CODE == "no_book"
        assert PUBLISHED_KIND == "final_target_weights"

    def test_the_old_surface_is_still_reachable(self):
        """This feature's hierarchy leaves the earlier failures where they were."""
        with pytest.raises(BookConstructionError):
            combine([])
        with pytest.raises(BookConstructionError):
            _weights().weight("DOGE")


# -- The chain, end to end -------------------------------------------------------


class TestFeature305ClosesTheMembersOwnChain:
    """§C8's chain read end to end: signals in, one instruction out."""

    def test_signals_in_and_one_published_book_out(self):
        """301 → 303 → 304 → 305 with no member imported and no step skipped."""
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
        rejects_breaching_target_weights(
            target, per_position_limit=MAJOR_WEIGHT, concentration_limit=0.35
        )
        final = final_target_weights(target)
        assert final.weights[BTC] == BTC_WEIGHT
        assert final.gross_exposure == pytest.approx(GROSS_EXPOSURE)
        # The construction's working travels beside the one output, and the
        # consumption claim holds over the whole surface §C8's chain produced.
        assert is_only_output(final, composite, target) is True

    def test_the_published_set_is_the_figure_the_orders_hold(self):
        """The last arrow adds nothing to the figure the limits let through."""
        target = _weights()
        rejects_breaching_target_weights(
            target, per_position_limit=MAJOR_WEIGHT, concentration_limit=0.35
        )
        final = final_target_weights(target)
        for symbol in (BTC, ETH, SOL):
            assert final.weight(symbol) == target.weight(symbol)


# -- No store, no environment, no clock, no other member -------------------------


class TestTheActIsAPureFunctionOfWhatItIsHanded:
    """No store, no environment, no clock, no other member, no state."""

    def test_the_act_accepts_duck_typed_target_weights(self):
        """The seam reads the ``weights`` surface, not the type."""
        stand_in = _StandInWeights({BTC: 0.2, ETH: 0.3, SOL: 0.5})
        final = final_target_weights(stand_in)
        assert final.weights == {BTC: 0.2, ETH: 0.3, SOL: 0.5}
        assert final.gross_exposure == 1.0

    def test_the_act_runs_with_no_database_and_no_environment(self, monkeypatch):
        for gone in ("DATABASE_URL", "ARTIFACT_ROOT", "NULL_SIDECAR_PATH"):
            monkeypatch.delenv(gone, raising=False)
        assert final_target_weights(_weights()).weights[BTC] == BTC_WEIGHT

    def test_the_module_opens_no_store_and_reads_no_environment(self):
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
        future edit cannot reach out to ``book._volatility`` for the figure it
        publishes nor to another member for a record it does not need.
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

    def test_the_act_takes_no_figure_to_configure(self):
        """Nothing about this step is a deployment's number.

        The chain's earlier steps carry the figures — feature 303's configured
        volatility, feature 304's two limits — and each reaches *its own* call.
        A keyword here would be a risk level or a bound wearing the publication
        step's name.
        """
        assert set(inspect.signature(final_target_weights).parameters) == {
            "target_weights"
        }
        assert set(inspect.signature(is_only_output).parameters) == {
            "published",
            "also_handed",
        }
        assert set(inspect.signature(assert_only_output).parameters) == {
            "published",
            "also_handed",
        }
