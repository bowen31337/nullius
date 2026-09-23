"""Feature 281's claim, stated as tests: the paired continuous statistic.

app_spec.xml, "Dreaming Loop & Meta-Selection", feature 281: *System rejects a
difference-in-proportions comparison, using a paired continuous statistic over
the same worlds instead.*  docs/alpha-engine-prd.md §11.0 states both halves —
*"Raw FDR is a proportion, and proportions are power-poor … Fix the statistic,
not the ambition"* — and docs/nullius-tech-architecture.md §10.3.1 states the
replacement as the reason the M3 gate is written the way it is: *"Policy
comparison uses a **paired** continuous statistic — OOS IR of the committed
pick, same policy pair on the same worlds — not a difference in proportions."*

So the claims worth pinning are these, and they are what the classes below are
arranged around:

* the **arithmetic reproduces the documents**.  This is the strongest claim in
  the file and the reason it is first: §11.0's own figures are *derived* here,
  not quoted.  ``power_capacity(0.3, spread=0.8)`` must answer **56** — the
  PRD's *"~56 worlds"*, which Appendix B writes as ``n ≈ 8(σ_diff/Δ)²`` — and
  the proportion side must answer **365** at ``0.30 → 0.21``, the PRD's *"~364
  independent commits per arm"*.  A test that only checked *a comparison is
  refused* would pass against an arithmetic that refused everything;
* the **pairing is the statistic**, so a world only one arm carries is
  **refused** rather than dropped, and a bare sequence of figures — no world
  ids to pair on — is refused too.  Dropping is the silent failure: the
  comparison becomes the unpaired one §11.0 rejects while the ``t`` figure
  still looks paired;
* the **two effect sizes stay separate**, because §11.0 names two on two
  different scales — a 0.09 *rate* shift and a 0.3 ``ΔIR``.  One keyword
  serving both formulas is the substitution that returns a plausible integer
  and announces nothing;
* the **two refusals are different repairs** — *the statistic is wrong*
  (:class:`ProportionComparisonError`) against *the worlds will not pair*
  (:class:`PairedComparisonError`) — and the ``arm_size`` band between the two
  capacity figures is where the feature's own sentence lives;
* the **store seam** reads the pool's own rows and **writes nothing**, refuses
  a database without them, and refuses a policy compared against itself.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from contextlib import closing
from pathlib import Path

import pytest
from dreaming import (
    PAIRED_CODE,
    PAIRED_LEVEL,
    POOL_TOO_THIN_CODE,
    POWER,
    PROPORTION_CODE,
    PROPORTION_DESIGN_EFFECT,
    CycleFreeze,
    DreamingError,
    FreezeRequestError,
    PairedComparisonError,
    PairedDifference,
    PoolFrozenError,
    PoolTooThinError,
    ProportionComparisonError,
    paired_ir_difference,
    paired_pool_difference,
    pool_bootstrap_schema,
    power_capacity,
    rejects_proportion_comparison,
    sqlite_path,
)
from dreaming.paired import _proportion_arm_size

#: §11.0's two worked figures, spelled once so every test below is written
#: against the documents rather than against a number this file invented.
#: The section: *"a paired t-test detecting ``ΔIR = 0.3`` with ``σ_diff ≈ 0.8``
#: needs ~56 worlds"*, and Appendix B's ``n ≈ 8(σ_diff/Δ)²``.
PRD_DELTA = 0.3
PRD_SPREAD = 0.8
PRD_PAIRED_WORLDS = 56

#: §11.0's *proportion* pair — the other scale entirely, and the reason the
#: call takes two effect sizes: *"Detecting ``0.30 → 0.21`` at 80% power needs
#: ~364 independent commits per arm"*.
PRD_RATE = 0.30
PRD_LOWER_RATE = 0.21
PRD_RATE_DELTA = PRD_RATE - PRD_LOWER_RATE
PRD_PROPORTION_COMMITS = 364

#: The clustered requirement §11.0 states as *"well over a thousand"*.
PRD_CLUSTERED_FLOOR = 1000

#: What §11.0's clustered requirement actually comes to at its own figures,
#: derived rather than written: ``ceil(365 · 4)``, which is the figure the
#: refusal's message carries.
PRD_CLUSTERED = 1460


def _arm(worlds: int, *, mean: float, step: float = 0.05) -> dict[str, float]:
    """One arm's readings: ``worlds`` worlds, rising by ``step`` from ``mean``.

    Two arms built with the *same* ``step`` differ by a **constant**, which is
    the one state this module refuses outright — a standard error of exactly
    zero.  So a test pairing two arms gives them different steps: the variation
    has to come from somewhere, and taking it from the world-to-world trend is
    what makes the differences vary without the readings becoming arbitrary.
    """
    return {f"world-{index:03d}": mean + step * index for index in range(worlds)}


def _unclustered_commits() -> int:
    """§11.0's unclustered proportion requirement, from the formula itself."""
    return _proportion_arm_size(PRD_RATE, delta=PRD_RATE_DELTA, power=POWER)


def _band_arm_size() -> int:
    """An ``arm_size`` inside §11.0's own band: funds the paired test, not the proportion one.

    Derived from the two formulas rather than written as a literal, so the
    refusal tests below cannot drift out of the band if either formula is
    corrected: the band is closed on the left by the paired requirement and
    open on the right by the clustered proportion one, and this answers the
    midpoint of it.
    """
    clustered = math.ceil(_unclustered_commits() * PROPORTION_DESIGN_EFFECT)
    return (power_capacity(PRD_DELTA, spread=PRD_SPREAD) + clustered) // 2


class TestTheArithmeticReproducesTheDocuments:
    """Feature 281's strongest claim: the PRD's figures are derived, not quoted.

    Every test here compares the module against a number that appears in
    ``docs/alpha-engine-prd.md`` itself.  That is deliberate and it is the
    point: a refusal that fired on *everything* would satisfy every other class
    in this file, and only these pin that the module is doing §11.0's actual
    arithmetic rather than a shape that resembles it.
    """

    def test_the_paired_requirement_is_the_prds_fifty_six_worlds(self):
        """``8(σ_diff/Δ)²`` at the PRD's own figures answers 56.

        §11.0: *"A paired t-test detecting ``ΔIR = 0.3`` with ``σ_diff ≈ 0.8``
        needs ~56 worlds, which is reachable."*  The module answers exactly
        that — not "about 56", and not a figure that merely rises as the effect
        shrinks.  Pinned against the document because the figure is the reason
        §12's M3 precondition is a pool of that order at all.
        """
        assert power_capacity(PRD_DELTA, spread=PRD_SPREAD) == PRD_PAIRED_WORLDS

    def test_the_paired_requirement_states_appendix_bs_formula(self):
        """``n ≈ 8(σ_diff/Δ)²`` — reproduced independently, then compared.

        The ``8`` in Appendix B is not a constant this module is allowed to
        hard-code: it is ``(z_{α/2} + z_β)²`` at 95% confidence and 80% power,
        which is what :func:`power_capacity` computes.  Recomputing it here
        from the quantiles makes the agreement a claim about the *formula*
        rather than about a literal two spellings of one number happen to share.
        """
        quantile = statistics.NormalDist().inv_cdf(1.0 - (1.0 - PAIRED_LEVEL) / 2.0)
        beta_quantile = statistics.NormalDist().inv_cdf(POWER)
        eight = (quantile + beta_quantile) ** 2
        assert eight == pytest.approx(7.8489, abs=1e-4)

        for delta, spread in ((0.3, 0.8), (0.5, 0.8), (0.2, 0.4), (1.0, 0.25)):
            assert power_capacity(delta, spread=spread) == max(
                2, math.ceil(eight * (spread / delta) ** 2)
            )

    def test_the_proportion_requirement_is_the_prds_three_sixty_four(self):
        """The standard two-proportion sizing at ``0.30 → 0.21`` answers ~364.

        §11.0: *"Detecting ``0.30 → 0.21`` at 80% power needs ~364 independent
        commits per arm; replays clustered by world inflate that by the design
        effect to well over a thousand."*  Both halves are pinned — this figure
        and the inflated one in
        :meth:`test_the_clustered_requirement_is_well_over_a_thousand` —
        because the sentence is the *whole* argument for the refusal, and a
        module reproducing only one end of it would be reproducing half the
        claim.

        Asserted as the neighbourhood the PRD states rather than as the
        literal: the closed form answers 364.25 and this module rounds a
        *requirement* up, so the figure is 365.  The claim is that the module
        reproduces the section's arithmetic, not that it reproduces its
        rounding.
        """
        assert abs(_unclustered_commits() - PRD_PROPORTION_COMMITS) <= 1

    def test_the_clustered_requirement_is_well_over_a_thousand(self):
        """The design effect takes ~365 past a thousand — §11.0's second figure.

        *"replays clustered by world inflate that by the design effect to well
        over a thousand"*.  The module applies the inflation as a named
        multiple (:data:`PROPORTION_DESIGN_EFFECT`) rather than modelling it,
        which is the honest reading of an order-of-magnitude claim; what this
        test pins is that the resulting figure lands where the PRD says it
        does, so the two ends of §11.0's sentence agree.
        """
        clustered = math.ceil(_unclustered_commits() * PROPORTION_DESIGN_EFFECT)
        assert clustered > PRD_CLUSTERED_FLOOR
        assert clustered == PRD_CLUSTERED
        assert PROPORTION_DESIGN_EFFECT == 4.0

    def test_the_paired_statistic_needs_far_fewer_worlds_than_the_proportion_test(self):
        """The whole point of §11.0, as one comparison.

        *"Fix the statistic, not the ambition."*  If the paired requirement were
        not dramatically smaller than the proportion requirement, the feature's
        sentence would be an aesthetic preference rather than the only
        comparison this pool can fund.  Pinned as a ratio so a later edit to
        either formula that quietly erased the gap fails here.
        """
        assert power_capacity(PRD_DELTA, spread=PRD_SPREAD) * 6 < _unclustered_commits()


class TestTheRefusalIsTheFeaturesOwnSentence:
    """The **rejects** half: a comparison the pool cannot fund is refused."""

    def test_the_band_between_the_two_requirements_is_refused(self):
        """The feature's own refusal: the paired statistic is funded and this is not.

        An ``arm_size`` between §11.0's two capacity figures is the case the
        sentence is *about* — the size buys the paired comparison and does not
        buy the proportion one.  A module that only refused sizes funding
        neither would have refused this for the M3 precondition instead, and
        the caller would be told to grow a pool already large enough.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=_band_arm_size(),
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        message = str(refusal.value)
        # The refusal names *both* requirements, because that is the judgement.
        assert f"~{PRD_PAIRED_WORLDS}" in message
        assert f"~{PRD_CLUSTERED}" in message
        # ...and it names the replacement, which is the "instead" clause.
        assert "paired_ir_difference" in message

    def test_a_size_that_funds_neither_is_refused_as_the_precondition(self):
        """Below the *paired* requirement the repair is the pool's, not the statistic's.

        A caller holding 40 worlds is refused for a different reason than a
        caller holding 100: §12's M3 precondition is a pool of the paired
        figure's order, and no statistic whatever funds the comparison at 40.
        The distinction is load-bearing because the repairs differ — accumulate
        worlds, against ask for the paired statistic — and a caller told to
        *fix the statistic* while holding 40 worlds would switch statistics and
        still be under-powered.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=40,
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        message = str(refusal.value)
        assert "accumulate worlds" in message
        assert "M3 precondition" in message
        # The *other* repair must not appear, or the caller would take it.
        assert "Fix the statistic" not in message

    def test_a_size_that_funds_the_proportion_test_is_admitted(self):
        """The module forbids a comparison the evidence *does not* support.

        It is not a blanket ban on proportion tests — a pool large enough to
        fund one is a pool where the comparison is legitimate, and refusing
        there would be editorialising rather than judging.  Load-bearing
        because the tempting implementation is a refusal that always fires,
        which would pass every refusal test in this class.
        """
        needed = math.ceil(_unclustered_commits() * PROPORTION_DESIGN_EFFECT)
        assert (
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=needed,
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )
            is None
        )

    def test_the_refusal_opens_with_its_code(self):
        """``proportion_comparison`` — the word an operator greps for."""
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=_band_arm_size(),
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        assert str(refusal.value).startswith(PROPORTION_CODE)
        assert PROPORTION_CODE == "proportion_comparison"

    def test_the_message_quotes_the_sections_reason(self):
        """The rule's provenance is in the refusal, not only in the docstring.

        A caller who has never read §11.0 is exactly the caller who meets this
        message, so the message is where the section's own sentence has to be
        legible — the stance ``test_errors.py`` states for feature 270's guard
        refusal.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=_band_arm_size(),
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        assert "power-poor" in str(refusal.value)


class TestTheTwoEffectSizesStaySeparate:
    """§11.0 names two effect sizes on two scales, and they are two keywords.

    The single-``delta`` signature is the tempting edit — the two formulas both
    take "a difference" — and it is silently wrong: §11.0's proportion pair
    differs by ``0.09`` while its paired example is ``ΔIR = 0.3``, so one
    figure serving both would inflate one requirement by
    ``(0.3/0.09)² ≈ 11×`` or shrink the other past the precondition's meaning.
    The result is still a plausible integer either way.
    """

    def _message(self, **overrides) -> str:
        """The band refusal's message, with any keyword replaced."""
        call = {
            "arm_size": _band_arm_size(),
            "rate_delta": PRD_RATE_DELTA,
            "delta": PRD_DELTA,
            "spread": PRD_SPREAD,
        }
        call.update(overrides)
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(PRD_RATE, **call)
        return str(refusal.value)

    def test_each_requirement_in_the_message_answers_to_its_own_keyword(self):
        """Each figure in the message comes from its own keyword.

        Pinned by moving one keyword and watching exactly one figure move: the
        proportion requirement answers to ``rate_delta`` and the paired one to
        ``delta``, so a refactor that crossed the two shows up here as two
        messages differing in the wrong figure.
        """
        baseline = self._message()
        assert f"~{PRD_CLUSTERED}" in baseline and f"~{PRD_PAIRED_WORLDS}" in baseline

        # A wider rate shift is an easier proportion test: fewer commits needed.
        assert f"~{PRD_CLUSTERED}" not in self._message(rate_delta=0.12)
        # A smaller ΔIR is a harder paired test: more worlds needed.
        assert f"~{PRD_PAIRED_WORLDS} " not in self._message(delta=0.15)

    def test_the_precondition_is_tested_against_the_paired_figure(self):
        """``delta``/``spread`` decide the M3 precondition; ``rate_delta`` does not.

        The order of the two judgements is the whole shape of the function: the
        precondition is asked first and asked of the *paired* requirement,
        because that is the one §12's M3 gate is written against.  A caller
        whose ``rate_delta`` is enormous would otherwise shrink the proportion
        requirement below its arm size and be admitted past an unfunded pool —
        so the precondition must not be reachable-around by the other keyword.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=40,
                rate_delta=0.30,  # a rate pair that would need almost nothing
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        assert "M3 precondition" in str(refusal.value)

    def test_the_precondition_is_asked_before_the_admission(self):
        """The requirements are **not** ordered, so the precondition cannot be asked second.

        A large enough ``spread`` — a pool whose worlds disagree wildly — makes
        the *paired* test harder than the proportion one, so
        ``paired_needs > needed`` and the band between them is **empty**.  An
        implementation that checked ``count >= needed`` first would then admit
        an arm that funds the proportion test and not the statistic §12's M3
        gate is written against — the exact inversion of the feature's
        sentence, arrived at from the other side.

        This is the case the three-outcome band cannot express, and it is why
        the precondition is asked first rather than merely asked.  Found by
        probing the edge rather than by the tests above, which all sat in the
        ordinary ``spread = 0.8`` regime where the band is wide.
        """
        # A spread wide enough to push the paired requirement past the
        # proportion one, so funding the latter no longer implies the former.
        spread = 5.0
        paired_needs = power_capacity(PRD_DELTA, spread=spread)
        needed = math.ceil(_unclustered_commits() * PROPORTION_DESIGN_EFFECT)
        assert paired_needs > needed, (
            "the premise of this test: the paired requirement now exceeds the "
            "proportion one, so the band is empty"
        )

        # An arm that funds the proportion test but not the paired statistic.
        middle = (needed + paired_needs) // 2
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=middle,
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=spread,
            )

        # Refused as the precondition, not admitted for funding the other test.
        assert "M3 precondition" in str(refusal.value)
        # ...and the message states the arm's own size against the requirement
        # it actually missed, rather than claiming it funds "neither".
        assert f"holds {middle}" in str(refusal.value)
        assert "neither" not in str(refusal.value)

        # Above the paired requirement it is admitted, since both are cleared.
        assert (
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=paired_needs,
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=spread,
            )
            is None
        )

    def test_a_rate_shift_off_the_unit_interval_is_refused(self):
        """§11.0 compares two *rates*; a shift landing outside [0, 1] names none."""
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                0.05,
                arm_size=_band_arm_size(),
                rate_delta=0.3,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        assert "unit interval" in str(refusal.value)

    @pytest.mark.parametrize("shift", [0.0, -0.09])
    def test_a_rate_shift_of_nothing_or_backwards_is_refused(self, shift):
        """A shift of zero divides by ``delta ** 2``; a negative one reverses the pair.

        Both refused by name rather than left to the arithmetic: zero would
        raise the interpreter's own ``ZeroDivisionError`` about floats for a
        fact about the pair of rates, and a negative shift would size the same
        pair read the other way round while the variance term — symmetric in
        the two rates — silently cancelled the sign.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            _proportion_arm_size(PRD_RATE, delta=shift, power=POWER)

        assert str(refusal.value).startswith(PROPORTION_CODE)


class TestTheAsksOwnFacts:
    """A malformed ask is refused as the ask's own fault, before any judgement."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"proportion": 1.5},
            {"proportion": -0.1},
            {"proportion": "0.3"},
            {"proportion": True},
            {"arm_size": 40.5},
            {"arm_size": -1},
            {"arm_size": True},
            {"rate_delta": "0.09"},
            {"rate_delta": True},
            {"delta": "0.3"},
            {"delta": True},
            {"spread": float("nan")},
            {"spread": float("inf")},
        ],
    )
    def test_a_malformed_figure_is_refused(self, kwargs):
        """Each figure is a finite real of its own kind, and each is refused by name."""
        call = {
            "proportion": PRD_RATE,
            "arm_size": _band_arm_size(),
            "rate_delta": PRD_RATE_DELTA,
            "delta": PRD_DELTA,
            "spread": PRD_SPREAD,
        }
        call.update(kwargs)
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(call.pop("proportion"), **call)

        assert str(refusal.value).startswith(PROPORTION_CODE)

    def test_a_zero_delta_is_refused_rather_than_answered_with_infinity(self):
        """An effect of zero is detected by no number of worlds.

        The arithmetic's own answer is an infinity, and an infinity returned as
        a float is a number a caller can compare against its pool size and act
        on — which is the failure this module's refusals exist to prevent.  So
        it is refused by name instead.
        """
        with pytest.raises(ProportionComparisonError) as refusal:
            power_capacity(0.0, spread=PRD_SPREAD)

        assert "detected by no number of worlds" in str(refusal.value)

    def test_a_zero_spread_answers_zero_worlds(self):
        """Two arms read identically everywhere need no worlds to be told apart.

        Deliberately *answered* rather than refused: the arithmetic's own value
        is right, and a refusal here would be refusing a question whose answer
        is known.
        """
        assert power_capacity(PRD_DELTA, spread=0.0) == 0

    @pytest.mark.parametrize("power", [1.0, 0.0, -0.5, 1.5])
    def test_a_power_outside_the_open_interval_is_refused(self, power):
        """A power of one needs an infinite ``z``; a power of zero is not a power."""
        with pytest.raises(ProportionComparisonError):
            power_capacity(PRD_DELTA, spread=PRD_SPREAD, power=power)


class TestThePairedStatistic:
    """The replacement half: two arms in, a :class:`PairedDifference` out."""

    def test_the_difference_is_the_mean_of_the_per_world_differences(self):
        """Paired means *differenced world by world*, then averaged.

        Not the difference of the two means — those agree only when both arms
        cover the same worlds, which is exactly the case the module refuses
        rather than assumes.  Pinned by computing the per-world differences
        independently and comparing against the record's own ``differences``.
        """
        candidate = {"w-a": 0.4, "w-b": 0.6, "w-c": 0.5}
        baseline = {"w-a": 0.1, "w-b": 0.3, "w-c": 0.32}

        record = paired_ir_difference(candidate, baseline)

        assert record.paired_worlds == 3
        assert record.differences == (
            ("w-a", pytest.approx(0.3)),
            ("w-b", pytest.approx(0.3)),
            ("w-c", pytest.approx(0.18)),
        )
        assert record.mean_difference == pytest.approx(statistics.fmean([0.3, 0.3, 0.18]))

    def test_the_spread_is_the_sample_deviation_of_the_differences(self):
        """Bessel-corrected — ``(n − 1)``, not ``n``.

        The deviation is *estimated* from the same worlds the test runs on, and
        the correction is what makes it unbiased.  Recomputed independently
        through :func:`statistics.stdev`, the standard library's own
        Bessel-corrected sample deviation, so the agreement is a claim about
        the estimator rather than about arithmetic shared with the module.
        """
        candidate = _arm(8, mean=0.5, step=0.07)
        baseline = _arm(8, mean=0.1, step=0.05)

        record = paired_ir_difference(candidate, baseline)

        differences = [candidate[world] - baseline[world] for world in sorted(candidate)]
        assert record.spread == pytest.approx(statistics.stdev(differences))
        # ...and the differences are genuinely not all the same, or the
        # assertion above would hold trivially against a constant.
        assert len(set(differences)) > 1

    def test_the_t_statistic_and_standard_error_are_the_documents_figures(self):
        """``SE = s/√n`` and ``t = d̄/SE`` — recomputed independently."""
        candidate = _arm(10, mean=0.5, step=0.07)
        baseline = _arm(10, mean=0.1, step=0.05)

        record = paired_ir_difference(candidate, baseline)

        differences = [candidate[world] - baseline[world] for world in sorted(candidate)]
        mean = statistics.fmean(differences)
        standard_error = statistics.stdev(differences) / math.sqrt(10)
        assert record.mean_difference == pytest.approx(mean)
        assert record.standard_error == pytest.approx(standard_error)
        assert record.t_statistic == pytest.approx(mean / standard_error)

    def test_the_p_value_is_two_sided(self):
        """A difference and its negation are equally significant.

        A one-sided ``p`` would report half the figure for the same evidence,
        which is a comparison that finds an effect wherever it looks — the
        direction §11.0's *"zero in expectation under the null"* specifically
        does not assume.  Pinned by comparing a comparison against its own
        negation.
        """
        candidate = _arm(10, mean=0.5)
        baseline = _arm(10, mean=0.1)

        forward = paired_ir_difference(candidate, baseline)
        backward = paired_ir_difference(baseline, candidate)

        assert forward.p_value == pytest.approx(backward.p_value)
        assert forward.t_statistic == pytest.approx(-backward.t_statistic)

    def test_the_p_value_is_the_normal_tail_the_record_names(self):
        """``p = 2·Φ(−|t|)`` — the tail limit the ``method`` field admits to.

        Recomputed from :class:`statistics.NormalDist` rather than compared to
        the module's own output, so the agreement is about the *distribution*
        and not about both spellings calling the same helper.
        """
        record = paired_ir_difference(_arm(12, mean=0.5), _arm(12, mean=0.2))

        expected = 2.0 * statistics.NormalDist().cdf(-abs(record.t_statistic))
        assert record.p_value == pytest.approx(min(1.0, expected))
        assert "normal" in record.method
        assert "two-sided" in record.method

    def test_a_null_pair_reads_as_no_evidence(self):
        """Two arms differing only by which world is which do not read as significant.

        The pool's own null: §11.0's figure is *"zero in expectation under the
        null"*, so a comparison whose differences average zero must produce a
        large ``p``.  This is the "does it ever say no" test that the refusal
        classes cannot state — a statistic that always found an effect would
        pass every refusal test in this file.
        """
        candidate = {f"w{i}": float(i % 2) for i in range(20)}
        baseline = {f"w{i}": 1.0 - float(i % 2) for i in range(20)}

        record = paired_ir_difference(candidate, baseline)

        assert record.mean_difference == pytest.approx(0.0)
        assert record.p_value > 0.05
        assert not record.clears(delta=0.0, level=0.05)

    def test_the_two_means_are_carried_and_are_not_the_differences(self):
        """Each arm's mean is its own figure, in its own units.

        §12's M3 criterion is written on the *difference*, but a reader
        auditing a comparison needs the levels it came from: a difference of
        ``+0.3`` between arms reading ``0.6`` and ``0.3`` is a different fact
        from the same difference between ``0.1`` and ``-0.2``.
        """
        candidate = {"w-a": 0.6, "w-b": 0.63}
        baseline = {"w-a": 0.3, "w-b": 0.32}

        record = paired_ir_difference(candidate, baseline)

        assert record.candidate_mean == pytest.approx(0.615)
        assert record.baseline_mean == pytest.approx(0.31)
        assert record.mean_difference == pytest.approx(0.305)
        # The difference of the means and the mean of the differences agree
        # here only because both arms cover the same worlds — which is the
        # property the pairing refusal exists to keep true.
        assert record.mean_difference == pytest.approx(
            record.candidate_mean - record.baseline_mean
        )

    def test_the_record_states_the_direction_and_the_criterion(self):
        """``is_positive`` and ``clears`` read the record; they compute nothing.

        §12's M3 exit criterion is *"Paired ΔIR > 0.3 with ``p < 0.05``"* and
        both edges are strict, as the criterion writes them — a ``ΔIR`` exactly
        at the bar is not *greater* than it.  Pinned because the tempting edit
        is to make one edge inclusive, which would clear a candidate the gate
        refuses.
        """
        record = paired_ir_difference(
            {f"w{i}": 0.5 + 0.05 * i for i in range(30)},
            {f"w{i}": 0.1 + 0.05 * i for i in range(30)},
        )

        assert record.is_positive
        assert record.mean_difference == pytest.approx(0.4)
        assert record.p_value < 0.05
        assert record.clears(delta=0.3, level=0.05)
        # Strict edges: at the bar itself the criterion is not met.
        assert not record.clears(delta=record.mean_difference, level=0.05)
        assert not record.clears(delta=0.3, level=record.p_value)

    def test_a_worse_arm_reports_a_negative_difference(self):
        """The sign is §C5's ``V^{m★} ≥ V^0``, and it is carried — not squared away."""
        record = paired_ir_difference(_arm(8, mean=0.1), _arm(8, mean=0.5))

        assert record.mean_difference < 0.0
        assert not record.is_positive

    def test_the_record_is_a_value_not_a_live_view(self):
        """A caller holding a comparison must not hold a handle the pool can move.

        The stance :class:`~dreaming.split.PoolSplit` and
        :class:`~dreaming.cycle.FreezeRecord` state for their own records:
        §C5's hold exists to stop the pool moving under a cycle, and a record
        that recomputed on read would defeat that from inside the member.
        """
        candidate = {"w-a": 0.5, "w-b": 0.7}
        baseline = {"w-a": 0.1, "w-b": 0.2}

        record = paired_ir_difference(candidate, baseline)
        candidate["w-a"] = 99.0  # mutate the caller's own inputs
        baseline["w-b"] = -99.0

        assert record.differences == (
            ("w-a", pytest.approx(0.4)),
            ("w-b", pytest.approx(0.5)),
        )
        assert record.paired_worlds == 2
        assert record.candidate_mean == pytest.approx(0.6)

    def test_the_row_is_a_fresh_dict_per_call(self):
        """A store-shaped mapping, and a new object each time."""
        record = paired_ir_difference(_arm(4, mean=0.5), _arm(4, mean=0.1))

        first = record.row()
        first["p_value"] = "tampered"

        assert record.row()["p_value"] != "tampered"
        assert set(record.row()) == {
            "paired_worlds",
            "candidate_mean",
            "baseline_mean",
            "mean_difference",
            "spread",
            "standard_error",
            "t_statistic",
            "p_value",
            "method",
            "differences",
        }

    def test_the_record_compares_and_hashes_by_value(self):
        """Two comparisons of the same worlds are one comparison."""
        candidate = {"w-a": 0.5, "w-b": 0.7, "w-c": 0.6}
        baseline = {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3}

        first = paired_ir_difference(candidate, baseline)
        second = paired_ir_difference(dict(candidate), dict(baseline))

        assert first == second
        assert hash(first) == hash(second)
        assert first != object()
        assert isinstance(first, PairedDifference)


class TestThePairingIsTheStatistic:
    """The *"same worlds"* clause — and the refusal that keeps it true."""

    def test_a_world_only_one_arm_carries_is_refused(self):
        """Not dropped.  Dropping is the silent failure this class exists for.

        A world the candidate was replayed against and the baseline was not
        contributes no difference, so the tempting edit is to skip it.  That
        edit converts the comparison into the *unpaired* one §11.0 rejects —
        the two arms end up averaged over different world sets — while the
        ``t`` figure that comes out still looks paired, and nothing in the
        result announces the change.
        """
        candidate = {"w-a": 0.5, "w-b": 0.7, "w-c": 0.4}
        baseline = {"w-a": 0.1, "w-b": 0.2}

        with pytest.raises(PairedComparisonError) as refusal:
            paired_ir_difference(candidate, baseline)

        message = str(refusal.value)
        assert message.startswith(PAIRED_CODE)
        assert "w-c" in message
        # ...and it states the repair, which is not "widen the pool".
        assert "carry both" in message
        assert "unpaired" in message

    def test_arms_over_disjoint_world_sets_are_refused(self):
        """Nothing is paired by construction — this is two populations.

        The extreme of the previous case, and the one a caller reaches by
        comparing two *campaigns* rather than two policies over one pool.  The
        refusal names both sizes so the operator can see how far apart they
        are.
        """
        with pytest.raises(PairedComparisonError) as refusal:
            paired_ir_difference({"w-a": 0.5, "w-b": 0.7}, {"w-x": 0.1, "w-y": 0.2})

        message = str(refusal.value)
        assert message.startswith(PAIRED_CODE)
        assert "2 candidate world(s)" in message

    def test_one_paired_world_is_refused_for_having_no_spread(self):
        """One difference has no deviation: ``n − 1`` is a division by zero.

        A ``t`` figure reported off it would be a spread this pool does not
        have.  Refused with the same code as the pairing failures because the
        repair is the same word — compare the arms over more worlds.
        """
        with pytest.raises(PairedComparisonError) as refusal:
            paired_ir_difference({"w-a": 0.5}, {"w-a": 0.1})

        message = str(refusal.value)
        assert message.startswith(PAIRED_CODE)
        assert "at least two worlds" in message

    def test_a_constant_difference_is_refused_for_having_no_spread(self):
        """The ``n = 1`` fact arriving at a larger ``n``.

        Every world moved by the same amount, so the standard error is exactly
        zero and the statistic divides by nothing.  The refusal is spelled here
        rather than left to Python's own ``ZeroDivisionError``, because the
        interpreter's message names floats while the caller's fact is about the
        pool — and an infinity returned as a ``t`` would read like
        overwhelming evidence.
        """
        candidate = {f"w{i}": 0.5 for i in range(6)}
        baseline = {f"w{i}": 0.2 for i in range(6)}

        with pytest.raises(PairedComparisonError) as refusal:
            paired_ir_difference(candidate, baseline)

        assert "standard error of exactly zero" in str(refusal.value)

    @pytest.mark.parametrize(
        "arm",
        [
            ["0.1", "0.2", "0.3"],
            (0.1, 0.2, 0.3),
            "world-a",
            b"world-a",
            42,
            None,
            {"w-a": "0.5"},
            {"w-a": None},
            {"": 0.5},
            {"w-a": float("nan")},
        ],
    )
    def test_an_arm_that_is_not_world_keyed_readings_is_refused(self, arm):
        """A sequence of figures carries no ids, so there is nothing to pair on.

        This is the module's central claim as an input check: without world ids
        a caller has two samples, not one set of differences, and accepting the
        sequence would mean pairing **by position** — the unpaired comparison
        §11.0 rejects, arriving through the signature of the paired one.  A
        bare string or bytes is refused separately because Python would iterate
        its characters into worlds nobody holds.
        """
        with pytest.raises(PairedComparisonError) as refusal:
            paired_ir_difference(arm, {"w-a": 0.1, "w-b": 0.2})

        assert str(refusal.value).startswith(PAIRED_CODE)

    def test_the_pairing_is_by_world_id_not_by_position(self):
        """The same figures in a different dict order answer the same comparison.

        What a mapping buys, and the reason the arms are not sequences: a
        caller reading two arms from two queries must not have its result
        depend on the rows' arrival order — §12's determinism contract,
        restated for a comparison.
        """
        candidate = {"w-a": 0.5, "w-b": 0.7, "w-c": 0.6}
        baseline = {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3}

        forward = paired_ir_difference(candidate, baseline)
        reordered = paired_ir_difference(
            dict(reversed(list(candidate.items()))),
            dict(reversed(list(baseline.items()))),
        )

        assert forward == reordered

    def test_a_spread_the_caller_supplies_is_judged_but_not_reported(self):
        """``spread`` sizes the power check; the record carries what the worlds measured.

        §11.0's ``σ_diff ≈ 0.8`` is a pool-scale figure a caller may already
        hold.  Given it, the capacity check runs against *it* — the figure the
        comparison's power is a function of — while the record reports the
        deviation these particular worlds produced.  Conflating the two would
        put a borrowed figure in a field that reads as a measurement.
        """
        candidate = _arm(6, mean=0.5, step=0.02)
        baseline = _arm(6, mean=0.1, step=0.02)

        record = paired_ir_difference(
            candidate, baseline, spread=PRD_SPREAD, delta=PRD_DELTA
        )

        differences = [candidate[world] - baseline[world] for world in sorted(candidate)]
        assert record.spread == pytest.approx(statistics.stdev(differences))
        assert record.spread != PRD_SPREAD

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan")])
    def test_a_spread_that_cannot_size_a_comparison_is_refused_as_the_evidence(
        self, bad
    ):
        """A supplied deviation that is not positive is a fact about the pool.

        Refused in :class:`PairedComparisonError`'s vocabulary rather than the
        proportion class's, because the repair is the evidence's: these worlds
        cannot support a test.  Pinned because the tempting edit is to route
        every sizing figure through one validator with one error class — which
        would tell the caller to change its statistic when the problem is its
        pool.
        """
        with pytest.raises(PairedComparisonError):
            paired_ir_difference(_arm(6, mean=0.5), _arm(6, mean=0.1), spread=bad)


class TestTheStoreSeam:
    """``paired_pool_difference`` — the comparison read from the pool's own rows."""

    def test_the_arms_are_read_from_replay_score_and_compared(self, pool, monkeypatch):
        """§10.3.1's *"same policy pair on the same worlds"*, over the store.

        The worlds pair **by construction** here rather than by the caller's
        bookkeeping: both arms are read from one table keyed by ``world_id``,
        so a world only one arm was replayed against is refused rather than
        silently dropped.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3, "w-d": 0.4})
        _write_arm(pool, "pi-1", {"w-a": 0.5, "w-b": 0.65, "w-c": 0.7, "w-d": 0.9})
        monkeypatch.setenv("DATABASE_URL", pool)

        record = paired_pool_difference("pi-1", "pi-0")

        assert record.paired_worlds == 4
        assert record.mean_difference == pytest.approx(
            statistics.fmean([0.4, 0.45, 0.4, 0.5])
        )
        assert record.candidate_mean == pytest.approx(0.6875)
        assert record.baseline_mean == pytest.approx(0.25)

    def test_the_comparison_writes_nothing(self, pool, monkeypatch):
        """Feature 270 holds the pool fixed; a comparison that wrote would be the mutation.

        The same read-time restraint :mod:`dreaming.split` states for the
        pool's membership.  Asserted by counting the pool's rows before and
        after rather than by trusting the module's own docstring, and over a
        pool that already has rows, so an insert of any kind would show.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3})
        _write_arm(pool, "pi-1", {"w-a": 0.5, "w-b": 0.6, "w-c": 0.7})
        monkeypatch.setenv("DATABASE_URL", pool)
        before = _pool_rows(pool)

        paired_pool_difference("pi-1", "pi-0")

        assert _pool_rows(pool) == before
        assert before == 6

    def test_a_comparison_runs_over_a_held_pool(self, pool, monkeypatch):
        """A comparison is a *read*, so feature 270's hold does not refuse it.

        Load-bearing for the loop: §C5 holds the pool fixed for the whole outer
        iteration, and the comparison is what the iteration is *for*.  If the
        hold refused reads the loop could not run.  Asserted against the real
        guards rather than a mock, and the hold is **verified** after the read
        so the test also pins that the comparison did not quietly release it.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3})
        _write_arm(pool, "pi-1", {"w-a": 0.5, "w-b": 0.6, "w-c": 0.7})
        monkeypatch.setenv("DATABASE_URL", pool)

        freeze = CycleFreeze(pool)
        hold = freeze.open("cycle-1")

        record = paired_pool_difference("pi-1", "pi-0")

        assert record.paired_worlds == 3
        assert freeze.held()
        assert freeze.verify(hold)

        # ...and a write is still refused, so the read above was not merely
        # permitted because the guards had been taken down.
        with pytest.raises(PoolFrozenError):
            freeze.guard(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, is_holdout) VALUES ('x', 'pi-2', 'w-a', 0.0, 0.0, 0)"
            )

    def test_a_database_with_no_pool_is_refused(self, database_url, monkeypatch):
        """No ``replay_score`` table means no pool to compare over.

        A difference reported there would be a difference between two arms that
        were never read, and the figures would look exactly like ones that had
        been — the refusal :func:`dreaming.split.pool_worlds` states for its own
        read, made here for the comparison's own reason.
        """
        monkeypatch.setenv("DATABASE_URL", database_url)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-1", "pi-0")

        message = str(refusal.value)
        assert "replay_score" in message
        assert "no pool here to compare" in message

    def test_no_database_named_is_refused(self, monkeypatch):
        """An act that means to read the pool and resolves nothing is refused by name.

        Not answered with ``None``: a comparison taken over no database would
        report a difference between two arms that were never read.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-1", "pi-0", env={})

        assert "DATABASE_URL" in str(refusal.value)

    def test_a_url_the_member_cannot_speak_is_refused_in_this_modules_vocabulary(
        self, pool, monkeypatch
    ):
        """Translated at the seam — never feature 270's ``FreezeRequestError``.

        The seam discipline the whole workspace states for error vocabularies:
        a caller comparing two arms must not meet *your hold was malformed*
        about an act that held nothing.  Pinned by asserting the *class*, since
        the message quotes the freeze's refusal on purpose — a caller needs the
        reason, not only the class.
        """
        monkeypatch.setenv("DATABASE_URL", pool)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-1", "pi-0", database_url="postgresql://h/db")

        assert not isinstance(refusal.value, FreezeRequestError)
        assert str(refusal.value).startswith(PAIRED_CODE)

    def test_a_policy_compared_against_itself_is_refused(self, pool, monkeypatch):
        """Every difference would be exactly zero — a fact about the *comparison*.

        The arithmetic's own message describes a pool on which every world
        moved identically, which is true of a self-comparison and reads like a
        fact about the pool.  So it is refused by name here instead, before any
        database is opened.
        """
        monkeypatch.setenv("DATABASE_URL", pool)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-0", "pi-0")

        assert "compared against itself" in str(refusal.value)

    @pytest.mark.parametrize("version", ["", "   ", None, 42, b"pi-0"])
    def test_a_malformed_policy_version_is_refused(self, pool, monkeypatch, version):
        """An arm named by nothing names no arm to pair the other against."""
        monkeypatch.setenv("DATABASE_URL", pool)

        with pytest.raises(PairedComparisonError):
            paired_pool_difference(version, "pi-0")

    def test_a_policy_with_no_rows_pairs_with_nothing_and_is_refused(
        self, pool, monkeypatch
    ):
        """An arm with no rows reads as empty, and the pairing refusal names it.

        Deliberately not a second refusal spelled in the store function: the
        world sets fail to pair, and that is the fact — stated by the function
        that knows what pairing means, in one place.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.2})
        monkeypatch.setenv("DATABASE_URL", pool)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-9", "pi-0")

        assert str(refusal.value).startswith(PAIRED_CODE)

    def test_an_arm_only_one_policy_was_replayed_against_is_refused(
        self, pool, monkeypatch
    ):
        """The unpaired case reached through the store rather than through a caller.

        The claim that reading both arms from one table makes the pairing a
        fact rather than bookkeeping, tested by writing the two arms over
        different world sets — the state a partially-replayed pool is in.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.2, "w-c": 0.3})
        _write_arm(pool, "pi-1", {"w-a": 0.5, "w-b": 0.6})
        monkeypatch.setenv("DATABASE_URL", pool)

        with pytest.raises(PairedComparisonError) as refusal:
            paired_pool_difference("pi-1", "pi-0")

        assert "carry both" in str(refusal.value)

    def test_one_policys_last_row_for_a_world_decides_that_worlds_reading(
        self, pool, monkeypatch
    ):
        """Several readings of one world resolve to one, by an id rule rather than by luck.

        A policy with several ``beta`` rows for a world has several readings
        for it, and a comparison needs exactly one.  The member takes the row
        that sorts last by ``id``, which is a *rule* — the §12 determinism
        contract at the row level — but **not** the same thing as "the last one
        written": ``0109``'s ``id`` is a UUID, so insertion order and id order
        are unrelated.  This test writes the two batches so that the ids agree
        with one reading and disagree with the other, and pins the ids: if the
        read were ever changed to insertion order or to ``rowid``, the
        assertion below would flip.

        It is also the reason the read cannot be ``SELECT DISTINCT`` over the
        two columns, which would return two readings for the world and drop one
        silently at the dict boundary.
        """
        _write_arm(pool, "pi-0", {"w-a": 0.1, "w-b": 0.1}, order=2)
        _write_arm(pool, "pi-1", {"w-a": 0.5, "w-b": 0.6}, order=2)
        # A *later* reading for w-a with an *earlier* id, and for w-b with a
        # later id — so the two worlds disagree about which rule is in play.
        _write_arm(pool, "pi-0", {"w-a": 0.9}, order=1)
        _write_arm(pool, "pi-1", {"w-a": 0.95}, order=1)
        _write_arm(pool, "pi-0", {"w-b": 0.3}, order=3)
        _write_arm(pool, "pi-1", {"w-b": 0.8}, order=3)
        monkeypatch.setenv("DATABASE_URL", pool)

        record = paired_pool_difference("pi-1", "pi-0")

        differences = dict(record.differences)
        # w-a: the id-3x row wins, so 0.5 − 0.1 — not the later-written 0.95 − 0.9.
        assert differences["w-a"] == pytest.approx(0.4)
        # w-b: the id-3 row is also last, so 0.8 − 0.3.
        assert differences["w-b"] == pytest.approx(0.5)


class TestTheVocabulary:
    """Feature 281's two classes, and the line between them and their neighbours."""

    def test_both_classes_share_the_member_base(self):
        """One member, one base — the workspace's per-member rule."""
        for refusal in (ProportionComparisonError, PairedComparisonError):
            assert issubclass(refusal, DreamingError)
        assert issubclass(DreamingError, Exception)

    def test_the_two_classes_are_siblings(self):
        """*Your statistic is wrong* is not *your worlds are wrong*.

        The repairs differ — ask for the paired statistic, against compare the
        arms over the worlds that carry both — so a caller that must react
        differently must be able to catch them apart.  Pinned because the
        tempting edit is to fold the pairing refusal into the proportion one,
        since both are feature 281's own sentence.
        """
        assert not issubclass(ProportionComparisonError, PairedComparisonError)
        assert not issubclass(PairedComparisonError, ProportionComparisonError)

    def test_neither_class_is_a_pool_frozen_refusal(self):
        """A comparison reads; it never held anything."""
        for refusal in (ProportionComparisonError, PairedComparisonError):
            assert not issubclass(refusal, PoolFrozenError)
            assert not issubclass(PoolFrozenError, refusal)

    def test_neither_class_is_the_thin_pool_refusal(self):
        """Feature 275's floor is a different fact with a different repair.

        The floor judges the *pool* against §12.1's ladder rung and its repair
        is *grow the pool*; the proportion refusal judges the *statistic* and
        its repair is *ask for the paired one*.  A caller that caught them
        together would go looking for more worlds when its statistic was the
        problem.
        """
        for refusal in (ProportionComparisonError, PairedComparisonError):
            assert not issubclass(refusal, PoolTooThinError)
            assert not issubclass(PoolTooThinError, refusal)

    def test_the_two_codes_are_distinct(self):
        """One code, one repair.  A shared token lands an operator on the wrong one."""
        assert PROPORTION_CODE == "proportion_comparison"
        assert PAIRED_CODE == "unpaired_worlds"
        assert PROPORTION_CODE != PAIRED_CODE

    def test_each_refusal_opens_with_its_own_code(self):
        """The prefix is what makes a rejection greppable by its own word."""
        with pytest.raises(ProportionComparisonError) as proportion:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=_band_arm_size(),
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )
        with pytest.raises(PairedComparisonError) as paired:
            paired_ir_difference({"w-a": 0.5, "w-b": 0.6}, {"w-a": 0.1})

        assert str(proportion.value).startswith(PROPORTION_CODE)
        assert str(paired.value).startswith(PAIRED_CODE)

    def test_neither_refusal_borrows_the_thin_pools_word(self):
        """``pool_too_thin`` is feature 275's, and this module never speaks for it."""
        with pytest.raises(ProportionComparisonError) as refusal:
            rejects_proportion_comparison(
                PRD_RATE,
                arm_size=_band_arm_size(),
                rate_delta=PRD_RATE_DELTA,
                delta=PRD_DELTA,
                spread=PRD_SPREAD,
            )

        assert POOL_TOO_THIN_CODE not in str(refusal.value)
        assert POOL_TOO_THIN_CODE != PROPORTION_CODE

    def test_the_module_is_reachable_from_the_member(self):
        """The feature's surface is the member's, as the ladder's other rungs are."""
        import dreaming

        for name in (
            "PairedDifference",
            "PairedComparisonError",
            "ProportionComparisonError",
            "PROPORTION_CODE",
            "PROPORTION_DESIGN_EFFECT",
            "PAIRED_CODE",
            "PAIRED_LEVEL",
            "POWER",
            "paired_ir_difference",
            "paired_pool_difference",
            "power_capacity",
            "rejects_proportion_comparison",
        ):
            assert name in dreaming.__all__, name
            assert hasattr(dreaming, name), name

    def test_the_module_is_stdlib_only_and_imports_no_member(self):
        """The comparison is stdlib-only, and the member imports no sibling.

        The factory's scan imports this package to fire its ``@register``, so a
        module-scope third-party import would make composition pay for a feature
        it is not using — the restraint every rung of this member's ladder
        states for its own module.
        """
        import sys

        import dreaming.paired as module

        source = Path(module.__file__).read_text()
        for forbidden in (
            "import numpy",
            "import scipy",
            "import pandas",
            "from dreaming",
            "from app",
        ):
            assert forbidden not in source, forbidden
        assert sys.modules["dreaming.paired"] is module


def _write_arm(
    url: str,
    policy_version: str,
    readings: dict[str, float],
    *,
    order: int = 0,
) -> None:
    """Write one arm's score rows into a pool, through ``0109``'s columns.

    The rows are written the way the owner declares them — the eight columns
    :data:`dreaming.REPLAY_SCORE_COLUMNS` restates — which is the same
    discipline the member's own ``scores`` fixture states: a fixture that wrote
    a narrower row would make every read pass for the wrong reason.

    ``order`` is a **zero-padded prefix** on the score id rather than a suffix,
    and that is load-bearing rather than cosmetic.  ``0109``'s ``id`` is a
    ``UUID`` in production, so a real pool's insertion order and its id order
    are unrelated; the member's read resolves several rows for one world by
    ``ORDER BY id``, which is deterministic but *not* insertion-ordered.  A
    fixture that appended a suffix would be testing an id scheme whose sort
    order matched its write order, which is the one arrangement that hides the
    difference — so the prefix makes the fixture state the ordering it means.
    """
    with closing(sqlite3.connect(sqlite_path(url))) as connection, connection:
        for world_id, score in readings.items():
            connection.execute(
                "INSERT INTO replay_score (id, policy_version, world_id, beta, "
                "score, committed_pick, is_holdout, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{order:04d}-score-{policy_version}-{world_id}",
                    policy_version,
                    world_id,
                    0.0,
                    score,
                    None,
                    0,
                    "2026-01-01T00:00:00Z",
                ),
            )


def _pool_rows(url: str) -> int:
    """How many rows the pool's score table holds — the write-detection probe."""
    with closing(sqlite3.connect(sqlite_path(url))) as connection:
        return connection.execute("SELECT COUNT(*) FROM replay_score").fetchone()[0]


def test_the_pool_fixture_exists(pool):
    """The pool this suite compares over is a real one.

    A guard against the whole store class silently skipping: ``pool`` stands
    the two tables up through the member's own restatement, and the schema text
    is counted here so the class depending on it cannot pass on a fixture that
    silently created nothing.
    """
    assert sqlite_path(pool).exists()
    assert pool_bootstrap_schema().count("CREATE TABLE") == 2
    with closing(sqlite3.connect(sqlite_path(pool))) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"replay_score", "bootstrap_world"} <= tables
    assert _pool_rows(pool) == 0
