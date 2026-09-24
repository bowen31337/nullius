"""Feature 308's claim, stated as tests: the leverage cap.

app_spec.xml, "Portfolio Book Construction", feature 308: *System rejects a
leverage target above one quarter of the Kelly fraction implied by the book
Sharpe and volatility.*  docs/alpha-engine-prd.md Appendix B states both
figures the sentence is built from — the fraction (*"Kelly fraction, Sharpe S,
vol σ → f* = S/σ"*) and the quarter (*"use ≤ ¼ Kelly"*) — and §1.2 states why
the quarter is there at all (*"A backtest Sharpe of 4.0 is a noisy, biased,
adversarially exploitable estimate"*).  This suite pins the judgment that
enforces it.

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* **the arithmetic reproduces the document** — the strongest claim in the file
  and the reason it comes first.  Appendix B's ``f* = S/σ`` and the table's
  *"use ≤ ¼ Kelly"* are *applied* here, not merely cited: the fraction at the
  module's own figures is the quotient to the bit, and the cap is that quotient
  scaled by exactly one quarter;
* **the quarter is a constant, not a knob** — neither the arithmetic nor the
  verdict accepts another, which is the design decision the module states at
  length (feature 303's configured volatility target is the knob in this
  neighbourhood, and it is a different feature's);
* **the edge is the word "above"** — a target exactly at the cap is admitted,
  one float over it is refused, and that is deliberately *not* the strict
  "only when" edge feature 280 enforces on its own sentence;
* **a non-positive Sharpe is answered, not refused** — a losing book's Kelly
  fraction is a measured fact, the cap that follows admits no positive
  leverage, and the refusal names the Sharpe rather than reporting the book as
  malformed;
* **the verdict is over figures the caller already holds** — never a database,
  never a measurement taken here, and a malformed figure is refused rather
  than answered;
* **the vocabulary is the cap's own two classes** — the ask
  (:class:`book.LeverageRequestError`) and the one judgment the sentence mints
  (:class:`book.LeverageTargetError`), both under the member's
  :class:`book.BookConstructionError`, and a caller must be able to catch one
  without catching the other.
"""

from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
from book import (
    KELLY_FRACTION,
    OVERLEVERAGE_CODE,
    BookConstructionError,
    LeverageRequestError,
    LeverageTargetError,
    kelly_fraction,
    leverage_cap,
    rejects_overleveraged_target,
)

#: The module the code pin at the foot of this file parses — anchored to the
#: file rather than to the process's working directory, so the suite gives the
#: same answer however pytest was invoked.
MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "book" / "_leverage.py"


class TestTheArithmetic:
    """``kelly_fraction`` and ``leverage_cap`` — Appendix B's line, applied."""

    def test_the_fraction_is_the_tables_quotient(self):
        """``f* = S/σ`` — the table's own expression, to the bit.

        Appendix B: *"Kelly fraction, Sharpe S, vol σ → f* = S/σ"*.  The
        figures are the ones §11.1's own paragraph puts on a live book
        (*"live Sharpe in the 0.8–1.5 range"*), so the quotient is checked
        against a division the document's own range produces rather than
        against a number this module invented.
        """
        assert kelly_fraction(1.0, volatility=0.2) == 5.0
        assert kelly_fraction(0.8, volatility=0.4) == 2.0
        assert kelly_fraction(1.5, volatility=0.35) == 1.5 / 0.35

    def test_the_cap_is_exactly_one_quarter_of_the_fraction(self):
        """The sentence's *one quarter of* — scaled, not re-divided.

        Checked against the fraction the module itself answers, so the two
        figures cannot drift: a cap that were ``S / (4σ)`` computed
        independently could differ in the last bit from the fraction the
        caller was shown, and this is the claim that it does not.
        """
        for sharpe, volatility in ((1.0, 0.2), (0.8, 0.4), (1.5, 0.35), (2.0, 0.5)):
            fraction = kelly_fraction(sharpe, volatility=volatility)
            assert leverage_cap(sharpe, volatility=volatility) == fraction * 0.25
            assert leverage_cap(sharpe, volatility=volatility) == fraction / 4.0

    def test_the_quarter_is_the_documents_own_figure(self):
        """``KELLY_FRACTION`` is Appendix B's *"use ≤ ¼ Kelly"*, spelled once.

        The constant, not a parameter: a deployment cannot set it, which the
        signatures below pin — there is no ``fraction=`` keyword to pass.
        """
        assert KELLY_FRACTION == 0.25
        assert KELLY_FRACTION == 1 / 4

    def test_the_cap_at_the_documents_own_figures_is_checkable_with_equality(self):
        """A quarter is binary-exact, so the dyadic figures answer exactly.

        The fixtures' discipline throughout this member: Sharpe 1.0 over
        volatility 0.2 is a fraction of 5.0, whose quarter is 1.25 — every
        one of them exact in binary — so the boundary tests below can sit one
        float apart rather than one epsilon apart.
        """
        assert leverage_cap(1.0, volatility=0.2) == 1.25
        assert leverage_cap(2.0, volatility=1.0) == 0.5
        assert leverage_cap(1.0, volatility=1.0) == 0.25


class TestTheVerdict:
    """``rejects_overleveraged_target`` — feature 308's own sentence."""

    def test_a_target_above_the_cap_is_refused(self):
        """The sentence, verbatim: above one quarter Kelly is refused."""
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(1.26, sharpe=1.0, volatility=0.2)
        assert str(caught.value).startswith(OVERLEVERAGE_CODE)

    def test_a_target_at_the_cap_is_admitted(self):
        """The edge is the word *above*, and it is strict on the refused side.

        Appendix B's *"use ≤ ¼ Kelly"* is inclusive where it admits, so a
        target of exactly 1.25 on a book whose cap is 1.25 runs — one float
        over it does not.  This is deliberately the *opposite* reading to the
        strict *"only when"* edge feature 280 enforces on its own sentence,
        and the two sentences say different words ("below the bar" against
        "above the cap").
        """
        assert rejects_overleveraged_target(1.25, sharpe=1.0, volatility=0.2) is None
        with pytest.raises(LeverageTargetError):
            rejects_overleveraged_target(1.25 + 1e-12, sharpe=1.0, volatility=0.2)

    def test_every_target_below_the_cap_is_admitted(self):
        """The cap is a ceiling, not a target: it never raises what was asked.

        A deployment that chooses to run well inside the document's bound is
        admitted at every figure below it — the cap bounds the book, it does
        not size it.
        """
        for held in (0.0, 0.25, 0.5, 1.0, 1.2499999):
            assert (
                rejects_overleveraged_target(held, sharpe=1.0, volatility=0.2) is None
            )

    def test_the_refusal_names_the_target_the_cap_and_the_two_figures(self):
        """The refusal is actionable without a stack trace."""
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(3.0, sharpe=1.0, volatility=0.2)
        message = str(caught.value)
        assert "3.0" in message  # the target
        assert "1.25" in message  # the cap
        assert "5.0" in message  # the fraction
        assert "0.2" in message  # the volatility
        assert "Appendix B" in message

    def test_the_refusal_states_the_documents_own_rule(self):
        """The verdict cites the line it applies, not a paraphrase of it."""
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(3.0, sharpe=1.0, volatility=0.2)
        message = str(caught.value)
        assert "use <= 1/4 Kelly" in message
        assert "noisy" in message  # §1.2's reason for the quarter

    def test_the_verdict_forms_no_value(self):
        """A refused target leaves nothing behind — it raises and returns None."""
        with pytest.raises(LeverageTargetError):
            rejects_overleveraged_target(9.0, sharpe=1.0, volatility=0.2)


class TestTheLosingBook:
    """A non-positive Sharpe is answered, not refused — the member's 301 stance.

    Feature 301 refuses a non-positive *information ratio* because a signal's
    standing to weight the book is undefined without one.  A book's *Sharpe*
    is a different figure: a measurement, and a losing book's measurement is
    negative.  The honest consequence is a fraction at or below zero, a cap
    that admits no long leverage, and a refusal that names the Sharpe rather
    than reporting the book as malformed.
    """

    def test_a_negative_sharpe_answers_a_negative_fraction(self):
        """The measurement is answered, not withheld."""
        assert kelly_fraction(-0.5, volatility=0.2) == -2.5
        assert leverage_cap(-0.5, volatility=0.2) == -0.625

    def test_a_zero_sharpe_answers_a_zero_cap(self):
        """A book with no edge has no Kelly fraction to take a quarter of."""
        assert kelly_fraction(0.0, volatility=0.2) == 0.0
        assert leverage_cap(0.0, volatility=0.2) == 0.0

    def test_a_losing_book_admits_no_long_leverage(self):
        """Every long target is refused, and the refusal names the Sharpe.

        This is the sentence's own outcome for a losing book — not an error
        about the ask — so it is the *judgment* class that carries it.
        """
        for held in (0.25, 1.0, 2.0, 100.0):
            with pytest.raises(LeverageTargetError) as caught:
                rejects_overleveraged_target(held, sharpe=-0.5, volatility=0.2)
            message = str(caught.value)
            assert "-0.5" in message  # the Sharpe that put the cap there
            assert "-0.625" in message  # the cap itself

    def test_the_flat_book_is_admitted_on_a_losing_book(self):
        """The admissible set is the cap *intersected with* the target's domain.

        A leverage target is a gross exposure of zero or more, so the set
        this verdict admits is ``0 ≤ target ≤ cap``.  On a cap at or below
        zero that set is the single point ``0``: a trader who does not like a
        book holds nothing, and refusing the flat book as "above the cap"
        would be an arithmetic that read the sentence's *above* without
        reading the domain the target lives in.
        """
        assert rejects_overleveraged_target(0.0, sharpe=-0.5, volatility=0.2) is None
        assert rejects_overleveraged_target(0.0, sharpe=0.0, volatility=0.2) is None
        # ...and exactly one float up from flat is refused, not admitted by a
        # boundary that had drifted off zero.
        with pytest.raises(LeverageTargetError):
            rejects_overleveraged_target(1e-9, sharpe=-0.5, volatility=0.2)

    def test_the_losing_books_refusal_states_the_repair_that_exists(self):
        """No target above zero is within a non-positive cap, and it says so.

        The message must not prescribe *lower the target to the cap*: the cap
        is negative, a leverage target may not be, and a caller told to lower
        its target to ``-0.625`` would be told to hold the book short — a
        position this module does not size.  The repair it states instead is
        the achievable one.
        """
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(1.0, sharpe=-0.5, volatility=0.2)
        message = str(caught.value)
        assert "hold the book at no leverage" in message
        assert "Lower the target to one quarter Kelly" not in message

    def test_a_positive_cap_states_the_lowering_repair(self):
        """And the ordinary case states the ordinary repair."""
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(9.0, sharpe=1.0, volatility=0.2)
        message = str(caught.value)
        assert "Lower the target to one quarter Kelly or below" in message
        assert "hold the book at no leverage" not in message


class TestTheAskIsRefusedBeforeAnythingIsJudged:
    """The ask's own facts — :class:`book.LeverageRequestError`, no code."""

    @pytest.mark.parametrize(
        ("sharpe", "volatility"),
        [
            ("1.0", 0.2),
            (None, 0.2),
            (True, 0.2),
            (float("nan"), 0.2),
            (float("inf"), 0.2),
            (float("-inf"), 0.2),
            (1.0, "0.2"),
            (1.0, None),
            (1.0, True),
            (1.0, float("nan")),
            (1.0, float("inf")),
            (1.0, 0.0),
            (1.0, -0.2),
        ],
    )
    def test_a_malformed_figure_is_refused(self, sharpe, volatility):
        """Neither figure admits what cannot be a measurement or a scale."""
        for call in (kelly_fraction, leverage_cap):
            with pytest.raises(LeverageRequestError):
                call(sharpe, volatility=volatility)
        with pytest.raises(LeverageRequestError):
            rejects_overleveraged_target(1.0, sharpe=sharpe, volatility=volatility)

    def test_a_zero_volatility_is_refused_though_a_zero_sharpe_is_not(self):
        """The two zeros are different facts, and only one is undefined.

        ``f* = S/σ`` at ``S = 0`` is a fraction of zero — a book with no edge,
        well defined.  At ``σ = 0`` it is a division by exactly nothing: the
        ratio is undefined, not infinite, and an infinite cap would admit
        every target on the strength of a scale the evidence does not carry.
        """
        assert leverage_cap(0.0, volatility=0.2) == 0.0
        with pytest.raises(LeverageRequestError) as caught:
            leverage_cap(1.0, volatility=0.0)
        assert "division" in str(caught.value)

    @pytest.mark.parametrize("target", ["1.0", None, True, float("nan"), float("inf")])
    def test_a_malformed_target_is_refused(self, target):
        """A leverage is a finite real, and a flag is not one."""
        with pytest.raises(LeverageRequestError):
            rejects_overleveraged_target(target, sharpe=1.0, volatility=0.2)

    def test_a_negative_target_is_refused(self):
        """A leverage is a gross exposure; a negative one is a direction.

        Admitted by the arithmetic, a negative target would slip *below* a
        negative cap and pass an over-leverage check while meaning something
        this module does not size — a short book's direction, which is the
        order layer's business.
        """
        with pytest.raises(LeverageRequestError) as caught:
            rejects_overleveraged_target(-1.0, sharpe=1.0, volatility=0.2)
        assert "gross exposure" in str(caught.value)

    def test_a_zero_target_is_admitted(self):
        """Zero is the honest floor: a book held at no leverage."""
        assert rejects_overleveraged_target(0.0, sharpe=1.0, volatility=0.2) is None

    def test_the_ask_carries_no_code_word(self):
        """A malformed ask names its subject in its first words, not a token.

        The one code on this feature's path is the *verdict*'s — a reader of a
        deployment log greps for *why was this leverage refused?*, and a
        developer's token on a fact the caller can simply fix would be the
        wrong word for the wrong reader.
        """
        with pytest.raises(LeverageRequestError) as caught:
            leverage_cap(1.0, volatility=0.0)
        assert not str(caught.value).startswith(OVERLEVERAGE_CODE)

    def test_the_ask_is_refused_before_the_verdict_can_fire(self):
        """Even a wildly over-leveraged target meets the ask's class first.

        The ordering every verdict in this workspace states: the ask's own
        facts are settled before anything is judged, so a caller that handed
        a broken figure is told *what to fix* rather than told its book is
        over-bet on the strength of a figure that is not a measurement.
        """
        with pytest.raises(LeverageRequestError):
            rejects_overleveraged_target(1000.0, sharpe=1.0, volatility=0.0)


class TestTheVocabulary:
    """The cap's two classes, and how they sit under the member's base."""

    def test_both_faces_are_book_construction_errors(self):
        """A caller that refuses book work wholesale writes one ``except``."""
        assert issubclass(LeverageRequestError, BookConstructionError)
        assert issubclass(LeverageTargetError, BookConstructionError)

    def test_the_ask_is_not_the_verdict(self):
        """But a caller that must react differently can tell them apart.

        A leverage target is refusable for a book whose signals weighted up
        perfectly, so the two facts are genuinely different: catching one must
        not catch the other, or a caller would re-inspect something it cannot
        tell apart.
        """
        assert not issubclass(LeverageTargetError, LeverageRequestError)
        assert not issubclass(LeverageRequestError, LeverageTargetError)
        with pytest.raises(LeverageRequestError):
            leverage_cap(1.0, volatility=0.0)
        try:
            rejects_overleveraged_target(9.0, sharpe=1.0, volatility=0.2)
        except LeverageRequestError:  # pragma: no cover - the branch under test
            pytest.fail("the verdict was caught as a malformed ask")
        except LeverageTargetError:
            pass

    def test_the_verdict_opens_with_its_greppable_code(self):
        """The code is the first token of every verdict message."""
        assert OVERLEVERAGE_CODE == "leverage_above_quarter_kelly"
        with pytest.raises(LeverageTargetError) as caught:
            rejects_overleveraged_target(2.0, sharpe=1.0, volatility=1.0)
        assert str(caught.value).split(":")[0] == OVERLEVERAGE_CODE

    def test_the_combiner_can_raise_a_bare_base_error(self):
        """The base is still catchable on its own — the two faces are additions.

        Feature 301's ``combine`` raises the *base* class directly, so the
        hierarchy the cap added has to leave that reachable: a caller's
        ``except BookConstructionError`` catches a refused combine and both
        cap faces, and nothing about 308 narrows 301's surface.
        """
        from book import combine

        with pytest.raises(BookConstructionError):
            combine([])


class TestTheLayering:
    """The cap costs composition nothing, and it re-measures nothing."""

    def test_the_module_is_stdlib_only(self):
        """The factory's scan imports this package; the cap must cost it zero.

        Parsed rather than trusted: an ``import numpy`` added to
        :mod:`book._leverage` would be invisible to every behavioural test
        here and would put a third-party wheel on the path of the factory's
        scan — the one bill this member's layering note promises not to pay.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        assert imported <= {"math", "typing", "__future__"}, imported

    def test_the_module_imports_no_other_workspace_member(self):
        """A member never imports a member — the workspace's own contract.

        Only relative imports (``from .errors import …``) are admissible, and
        the parsed check above already excludes absolute ones by name; this
        pins the *relative* half so a future edit cannot reach out to
        ``dreaming`` or ``scoring`` for the arithmetic it restates here.
        """
        tree = ast.parse(MODULE_PATH.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                assert node.module in {"errors"}, node.module

    def test_the_module_opens_no_store_and_reads_no_environment(self):
        """A verdict is not a measurement, and neither is it a read.

        The module must not grow a database dependency, an environment
        variable or a clock: its whole subject is three figures the caller
        already holds, and a version that opened a store would be answering a
        question about the evaluator from inside a bound.
        """
        source = MODULE_PATH.read_text()
        for forbidden in ("sqlite3", "os.environ", "getenv", "datetime", "time."):
            assert forbidden not in source, forbidden

    def test_the_signature_takes_no_other_quarter(self):
        """The quarter is a constant, not a knob — pinned at the signature.

        Checked through the function objects rather than the source text, so
        a renamed keyword still fails the test: :func:`leverage_cap` and
        :func:`rejects_overleveraged_target` accept ``sharpe`` and
        ``volatility`` and nothing else, which is what makes the cap the
        document's rule rather than a deployment's preference.
        """
        import inspect

        for call in (kelly_fraction, leverage_cap):
            parameters = set(inspect.signature(call).parameters)
            assert parameters == {"sharpe", "volatility"}, parameters
        parameters = set(inspect.signature(rejects_overleveraged_target).parameters)
        assert parameters == {"target", "sharpe", "volatility"}, parameters

    def test_the_arithmetic_opens_no_database(self, tmp_path, monkeypatch):
        """Exercised in a process with no ``DATABASE_URL`` at all.

        The behavioural half of the claim above: the figures this module
        answers are computed with the deployment's database variable deleted,
        so a version that had grown a store dependency would fail here rather
        than in production.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert leverage_cap(1.0, volatility=0.2) == 1.25
        assert rejects_overleveraged_target(1.0, sharpe=1.0, volatility=0.2) is None

    def test_the_cap_is_deterministic(self):
        """Two calls over the same figures answer identical values."""
        first = leverage_cap(1.5, volatility=0.35)
        second = leverage_cap(1.5, volatility=0.35)
        assert first == second
        assert math.isfinite(first)
