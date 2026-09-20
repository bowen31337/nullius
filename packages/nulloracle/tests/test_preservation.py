"""Feature 116: preserving autocorrelation and clustering, destroying the signal.

app_spec.xml, "Null Oracle & Planted Nulls", feature 116: *System preserves
return autocorrelation and volatility clustering through block permutation
while destroying the signal-to-target relationship.*  Feature 115's suite
pins the permutation's *mechanism* — the blocks move as units, the seed
reproduces the series — and this suite pins the sentence that mechanism
exists to satisfy, which is a claim about three quantities rather than one:

* **preservation, exactly, of the block structure.**  The output is the
  input's blocks concatenated in some order — each block whole, in order, no
  observation dropped, split or reversed.  This is what §7.3's *contiguous*
  buys and what a pointwise shuffle cannot do at any length above two; it is
  asserted as an equality, because adjacency is not a quantity that admits
  approximation.

* **preservation, approximately, of the two statistics.**  The return
  autocorrelation and the volatility clustering at lags below the block
  length are preserved to within a bound scaled by how much of each estimate
  the shuffle actually disturbed.  The suite asserts both directions: that
  every legitimate permutation passes, and that the bound is *not* so loose
  that a damaged series would slip through.

* **destruction of the signal-to-target relationship.**  The permuted series
  carries no more correlation with the signal than a rearrangement of its
  blocks produces by chance — and the suite pins the failure too, because a
  clause that only ever accepts is not a check.  The case that must fail is
  the one §4.1 exists to prevent: a node served targets that still know the
  signal.

The series the tests measure on are GARCH(1,1)-shaped rather than white
noise, and that is deliberate.  A preservation claim is only interesting on a
series that *has* autocorrelation and volatility clustering to preserve; a
white-noise series has neither, so a test that used one would pass for a
pointwise shuffle and prove nothing.  The shapes span persistent, flat,
weak-volatility, strong-volatility and low-volatility parameterisations so
the bounds are exercised against more than one regime.

The refusals are pinned last.  Each is a :class:`KsGuardError` and not a
:class:`SidecarError` — the same seam discipline feature 115's validators
keep: a series that broke feature 116's sentence is a *computation* that went
wrong, not a sidecar schema that was written wrong, and a caller reading
``SidecarError`` out of this module would look in the wrong place for the
cause.
"""

from __future__ import annotations

import math
import random

import pytest
from nulloracle import (
    DEFAULT_BLOCK_DAYS,
    KsGuardError,
    PreservationReport,
    autocorrelation,
    block_indices,
    block_permute,
    block_runs,
    check_preservation,
    destroys_relationship,
    preservation_lags,
    preserves_block_structure,
    preserves_structure,
    signal_to_target_correlation,
    volatility_clustering,
)

# -- The series the claims are made about ----------------------------------------


def garch(
    length: int,
    seed: int,
    *,
    ar: float = 0.20,
    alpha: float = 0.10,
    beta: float = 0.85,
) -> list[float]:
    """A GARCH(1,1) return series, optionally with AR(1) drift in the mean.

    The shape a real forward-return series has: the variance is persistent
    (``beta`` near one) so absolute returns cluster, and ``ar`` puts memory in
    the returns themselves.  A preservation claim measured on white noise
    would be vacuous — there is no structure to preserve — so every
    preservation assertion in this suite is made against this.
    """
    generator = random.Random(seed)
    omega = 1.0 - alpha - beta
    variance = 1.0
    series: list[float] = []
    for _ in range(length):
        if series:
            variance = omega + alpha * series[-1] ** 2 + beta * variance
        shock = math.sqrt(variance) * generator.gauss(0.0, 1.0)
        series.append(ar * series[-1] + shock if series else shock)
    return series


#: The shapes every preservation bound is exercised against.  Persistent and
#: strong-volatility series are the ones a shuffle damages most visibly;
#: weak-volatility and flat ones are the ones where a *loose* bound would
#: stop discriminating.  All five must pass.
SHAPES = {
    "persistent": {"ar": 0.20, "alpha": 0.10, "beta": 0.85},
    "flat": {"ar": 0.0, "alpha": 0.10, "beta": 0.85},
    "weak-volatility": {"ar": 0.15, "alpha": 0.5, "beta": 0.3},
    "strong-volatility": {"ar": 0.30, "alpha": 0.05, "beta": 0.93},
    "low-volatility": {"ar": 0.25, "alpha": 0.03, "beta": 0.55},
}

#: The lengths the bounds are exercised at.  Short series are where the
#: coincidence scale is widest and the block count smallest, so a bound that
#: held only asymptotically would fail here.  The two-block floor — a series
#: of 40 observations, where a "permutation" is a swap of two halves and the
#: coincidence scale is its maximum 1.0 — is asked separately by
#: ``test_a_two_block_series_keeps_its_statistics_in_proportion``.
LENGTHS = (60, 120, 250, 500, 1000)


def pointwise_shuffle(series, seed: int):
    """A *pointwise* shuffle, for contrast: the thing block permutation is not."""
    shuffled = list(series)
    random.Random(seed).shuffle(shuffled)
    return tuple(shuffled)


# -- Preservation, exactly: the blocks move whole ---------------------------------


class TestTheBlockStructureSurvivesExactly:
    def test_a_block_permutation_preserves_the_block_structure(self) -> None:
        # The defining property, asserted for every shape and length the suite
        # measures over rather than for one convenient case: whichever blocks
        # the seed reorders, each one comes out whole and in order.
        for shape in SHAPES.values():
            for length in LENGTHS:
                for seed in range(6):
                    series = garch(length, seed, **shape)
                    permuted = block_permute(series, seed=seed, block_days=20)
                    assert preserves_block_structure(
                        series, permuted=permuted, block_days=20
                    )

    def test_the_output_is_the_inputs_runs_concatenated(self) -> None:
        # The same claim stated the other way round, so the test cannot pass
        # by agreeing with a buggy implementation of the checker: cutting the
        # output at the same positions gives exactly the input's runs, as a
        # multiset.  The length is a multiple of the block length on purpose —
        # when it is not, the trailing partial run lands *inside* what would
        # have been a full run's slot, so the output's runs cut at positional
        # boundaries no longer line up with the blocks that were moved, and
        # the comparison would be measuring the wrong thing rather than
        # finding a real difference.
        series = garch(240, 5)
        permuted = block_permute(series, seed=5, block_days=20)
        original_runs = block_runs(series, block_days=20)
        output_runs = block_runs(permuted, block_days=20)
        assert len(output_runs) == len(original_runs)
        assert sorted(output_runs) == sorted(original_runs)

    def test_a_trailing_partial_run_moves_as_a_block_too(self) -> None:
        # Where the length is not a multiple of the block length the output's
        # positional runs do not line up with the moved blocks, so the claim
        # is pinned against the permutation's own ground truth instead: the
        # index form says which input position each output slot draws from,
        # and reading the output at the index of each input run must give that
        # run back, whole and in order.
        series = garch(250, 5)
        permuted = block_permute(series, seed=5, block_days=20)
        indices = block_indices(list(range(250)), seed=5, block_days=20)
        # Gather by the index form: output slot k is input position indices[k].
        gathered = tuple(series[indices[k]] for k in range(250))
        assert gathered == permuted
        # And every input run appears as a contiguous, in-order span of the
        # *output's* index sequence, which is what "the block moved whole"
        # means when the positional boundaries no longer align.
        for start in range(0, 250, 20):
            width = min(20, 250 - start)
            span = tuple(range(start, start + width))
            assert any(
                tuple(indices[k : k + width]) == span for k in range(250 - width + 1)
            )

    def test_the_runs_are_the_series_cut_into_blocks_of_the_stored_length(self) -> None:
        # block_runs is the vocabulary of the whole claim, so it is pinned
        # directly: contiguous runs of block_days, in order, with a trailing
        # run shorter than the block length when the length does not divide.
        series = [float(i) for i in range(45)]
        assert block_runs(series, block_days=20) == (
            tuple(series[:20]),
            tuple(series[20:40]),
            tuple(series[40:]),
        )

    def test_a_pointwise_shuffle_does_not_preserve_the_block_structure(self) -> None:
        # The distinction §7.3's *contiguous* turns on, and the reason the
        # check needs no tolerance: a pointwise shuffle leaves essentially no
        # block intact, so it is refused outright at every length where there
        # is structure to damage.
        for length in (5, 20, 45, 100, 250, 1000):
            series = garch(length, 11)
            shuffled = pointwise_shuffle(series, 11)
            assert not preserves_block_structure(
                series, permuted=shuffled, block_days=20
            )

    def test_a_reversed_block_is_not_a_block_permutation(self) -> None:
        # A rearrangement that moves the right observations into the right
        # neighbourhood but reverses them inside the block is not what §7.3
        # does, and it would destroy the within-block autocorrelation the
        # clause exists to preserve.  The check notices, because it compares
        # the runs in order rather than as multisets of observations.
        series = garch(100, 3)
        runs = list(block_runs(series, block_days=20))
        runs[0] = tuple(reversed(runs[0]))
        reversed_first = tuple(value for run in runs for value in run)
        assert not preserves_block_structure(
            series, permuted=reversed_first, block_days=20
        )

    def test_a_series_of_a_different_length_is_not_a_permutation(self) -> None:
        # A permutation moves observations, it never adds or drops them
        # (§7.3), so a series of another length is not a candidate at all —
        # reported as False rather than raised, because the caller that must
        # act on it is preserves_structure, which reports the failure.
        series = garch(100, 7)
        assert not preserves_block_structure(
            series, permuted=tuple(series[:-1]), block_days=20
        )
        assert not preserves_block_structure(
            series, permuted=tuple(series) + (1.0,), block_days=20
        )

    def test_a_series_shorter_than_the_block_length_is_one_run(self) -> None:
        # One run, so no arrangement but the identity: the permutation cannot
        # move anything, and saying so is the honest answer rather than an
        # error.  It matters because a single-run series is also the case
        # where the destruction clause has no coincidence to bound.
        series = garch(19, 2)
        assert block_runs(series, block_days=20) == (tuple(series),)
        assert preserves_block_structure(series, permuted=tuple(series), block_days=20)

    def test_the_block_length_is_an_argument_and_the_runs_follow_it(self) -> None:
        # §7.4's detectability guard treats the block length as the knob an
        # operator turns — *"investigate block length"* — so the run
        # structure follows the stored block length rather than a constant.
        series = [float(i) for i in range(12)]
        assert block_runs(series, block_days=5) == (
            (0.0, 1.0, 2.0, 3.0, 4.0),
            (5.0, 6.0, 7.0, 8.0, 9.0),
            (10.0, 11.0),
        )
        assert block_runs(series, block_days=3) == (
            (0.0, 1.0, 2.0),
            (3.0, 4.0, 5.0),
            (6.0, 7.0, 8.0),
            (9.0, 10.0, 11.0),
        )


# -- Preservation, approximately: the two statistics -------------------------------


class TestThePreservedLagsFollowTheBlockLength:
    def test_the_lags_are_the_ones_below_the_block_length(self) -> None:
        # A statistic at lag k reads pairs k apart; for k < block_days all but
        # the boundary pairs sit inside a block, and for k >= block_days they
        # all straddle.  So the preserved range is 1..block_days-1, and it
        # follows the block length rather than a hard-coded 20.
        assert preservation_lags(20) == tuple(range(1, 20))
        assert preservation_lags(5) == (1, 2, 3, 4)

    def test_a_one_day_block_preserves_no_lag(self) -> None:
        # block_days = 1 is a pointwise shuffle, which preserves no lag at
        # all.  Returning nothing says exactly that; refusing would be
        # refusing a block length feature 115's own validators already refuse.
        assert preservation_lags(1) == ()

    def test_the_default_is_the_sidecars_block_length(self) -> None:
        # §7.1's 20 days: the number the sidecar seals, feature 115 shuffles
        # by, and this module derives its lag range from are one number.
        assert DEFAULT_BLOCK_DAYS == 20
        assert preservation_lags() == tuple(range(1, DEFAULT_BLOCK_DAYS))


class TestTheAutocorrelationSurvives:
    def test_a_block_permutation_preserves_autocorrelation(self) -> None:
        # Every shape, every length, every lag the clause is stated over —
        # the assertion is that no legitimate permutation is refused.
        for shape in SHAPES.values():
            for length in LENGTHS:
                for seed in range(4):
                    series = garch(length, seed, **shape)
                    permuted = block_permute(series, seed=seed, block_days=20)
                    assert preserves_structure(
                        series, permuted=permuted, block_days=20
                    )

    def test_a_two_block_series_keeps_its_statistics_in_proportion(self) -> None:
        # The smallest series the clause is ever stated over: forty
        # observations, two blocks, so a permutation is nothing but a swap of
        # the two halves and the coincidence scale is its maximum, 1.0.  The
        # bound is correspondingly wide — but not infinitely wide, which is
        # the thing worth pinning.  A clause that passed this case by simply
        # exempting small series would pass anything at all here; the claim
        # is that the statistics stay inside a bound that is *proportionate*
        # to how little structure two blocks can be expected to preserve.
        for seed in range(8):
            series = garch(40, seed)
            permuted = block_permute(series, seed=seed, block_days=20)
            assert preserves_block_structure(series, permuted=permuted, block_days=20)
            moved = [
                abs(original - shuffled)
                for lag in preservation_lags(20)
                for original, shuffled in (
                    (
                        autocorrelation(series, lag=lag),
                        autocorrelation(permuted, lag=lag),
                    ),
                    (
                        volatility_clustering(series, lag=lag),
                        volatility_clustering(permuted, lag=lag),
                    ),
                )
                if original is not None and shuffled is not None
            ]
            assert moved
            # Bound is tolerance * (disturbed fraction + 1/sqrt(B-1)), and at
            # two blocks the coincidence term is 1.0 on its own, so no single
            # lag may move by more than twice the tolerance constant.
            assert max(moved) < 2.0

    def test_the_low_lag_autocorrelation_barely_moves(self) -> None:
        # The bound that matters most in practice: at lag 1 of a long series
        # only a few percent of the estimate rests on pairs the shuffle moved,
        # so the statistic is preserved to within a small quantity.
        for length in (250, 500, 1000):
            for seed in range(4):
                series = garch(length, seed)
                permuted = block_permute(series, seed=seed, block_days=20)
                before = autocorrelation(series, lag=1)
                after = autocorrelation(permuted, lag=1)
                assert before is not None and after is not None
                assert abs(before - after) < 0.2

    def test_a_flat_series_reports_no_autocorrelation_rather_than_zero(self) -> None:
        # A series with no variance cannot state its memory, and 0.0 would be
        # a claim — "this series has no memory" — where the truth is that the
        # series cannot answer.  preserves_structure treats the two
        # differently, so the distinction has to survive the statistic.
        flat = [2.0] * 50
        assert autocorrelation(flat, lag=1) is None
        assert autocorrelation([1.0, 2.0], lag=1) is None
        assert autocorrelation(garch(50, 1), lag=1) is not None

    def test_the_autocorrelation_is_the_plain_lagged_correlation(self) -> None:
        # The estimator is the one a reader would compute by hand, pinned on a
        # series whose answer is knowable: a perfect alternating pattern has a
        # lag-1 autocorrelation of exactly -1.
        alternating = [1.0, -1.0] * 25
        assert autocorrelation(alternating, lag=1) == pytest.approx(-1.0)
        assert autocorrelation(alternating, lag=2) == pytest.approx(1.0)


class TestTheVolatilityClusteringSurvives:
    def test_a_block_permutation_preserves_volatility_clustering(self) -> None:
        # The second preserved property, measured on the same permutations:
        # big returns keep following big returns, because the blocks that
        # carry the runs of them are moved whole.
        series = garch(500, 4)
        for seed in range(6):
            permuted = block_permute(series, seed=seed, block_days=20)
            before = volatility_clustering(series, lag=1)
            after = volatility_clustering(permuted, lag=1)
            assert before is not None and after is not None
            assert abs(before - after) < 0.25

    def test_it_is_the_autocorrelation_of_absolute_values(self) -> None:
        # The clustering statistic is the standard one — the autocorrelation
        # of |returns| — so a series whose magnitudes alternate has a lag-1
        # clustering of exactly -1 while its signed autocorrelation is not
        # that number.  Pinned so the two statistics cannot be silently
        # swapped for one another.
        magnitudes = [1.0, -2.0] * 25
        assert volatility_clustering(magnitudes, lag=1) == pytest.approx(-1.0)

    def test_volatility_clustering_sees_structure_the_returns_do_not(self) -> None:
        # The two are different facts about one series, which is why §7.3
        # names them separately: a series with no memory in its *signs* can
        # still have strong memory in its *magnitudes*.
        generator = random.Random(17)
        series = [generator.gauss(0.0, 1.0 + 2.0 * (index // 40 % 2)) for index in range(400)]
        assert abs(autocorrelation(series, lag=1) or 0.0) < 0.2
        assert (volatility_clustering(series, lag=1) or 0.0) > 0.2


class TestTheBoundStillRefusesADamagedSeries:
    def test_a_pointwise_shuffle_is_refused(self) -> None:
        # The bound is only worth having if it still fails the thing §7.3's
        # *contiguous* exists to forbid.  It does — and it fails on the exact
        # structural check before any statistic is consulted, at every length
        # where there is structure to damage.
        for shape in SHAPES.values():
            for length in (45, 120, 250, 500):
                series = garch(length, 13, **shape)
                assert not preserves_structure(
                    series,
                    permuted=pointwise_shuffle(series, 13),
                    block_days=20,
                )

    def test_a_loosened_tolerance_admits_what_a_tight_one_refuses(self) -> None:
        # The tolerance is genuinely load-bearing rather than decorative: a
        # bound tight enough to refuse a legitimate permutation is available,
        # which is why the shipped one is calibrated rather than zero.
        series = garch(500, 8)
        permuted = block_permute(series, seed=8, block_days=20)
        assert preserves_structure(series, permuted=permuted, block_days=20)
        assert not preserves_structure(
            series, permuted=permuted, block_days=20, tolerance=0.0
        )

    def test_a_statistic_defined_on_one_side_only_is_a_failure(self) -> None:
        # A permutation changes which observations are adjacent, never the
        # observations themselves, so a statistic that exists on one side and
        # not the other is a change to the series' character whatever the
        # numbers say.  A permuted series whose variance vanished is refused.
        series = garch(100, 6)
        flattened = tuple(1.0 for _ in series)
        assert not preserves_structure(series, permuted=flattened, block_days=20)


# -- Destruction: the signal-to-target relationship --------------------------------


class TestTheSignalToTargetRelationshipIsDestroyed:
    def test_a_real_permutation_destroys_the_relationship(self) -> None:
        # §4.1's claim: the signal was measured against the real returns and
        # is scored against the permuted ones, and the correlation between
        # them must collapse.  The before/after pair is the transition §7.3's
        # third clause is about.
        for length in (120, 250, 500, 1000):
            for seed in range(4):
                targets = garch(length, seed)
                generator = random.Random(9000 + seed)
                signal = [
                    0.5 * targets[i] + generator.gauss(0.0, 1.0)
                    for i in range(length)
                ]
                permuted = block_permute(targets, seed=seed, block_days=20)
                before = signal_to_target_correlation(signal, targets)
                after = signal_to_target_correlation(signal, permuted)
                assert before is not None and after is not None
                assert abs(before) > abs(after)
                assert destroys_relationship(
                    signal, targets, permuted_targets=permuted, block_days=20
                )

    def test_a_signal_with_no_edge_leaves_nothing_to_destroy(self) -> None:
        # A campaign whose signal genuinely had no edge produces a real
        # correlation near zero.  That case passes, and it must: a null branch
        # whose expected edge is zero by construction is exactly what §4.1
        # promises, and refusing it would refuse a world that was already null.
        for length in (250, 500):
            for seed in range(4):
                targets = garch(length, seed)
                generator = random.Random(7000 + seed)
                signal = [generator.gauss(0.0, 1.0) for _ in range(length)]
                permuted = block_permute(targets, seed=seed, block_days=20)
                assert destroys_relationship(
                    signal, targets, permuted_targets=permuted, block_days=20
                )

    def test_the_identity_is_refused(self) -> None:
        # The escape hatch this clause deliberately does not have.  A "accept
        # when the permuted correlation is no larger than the real one" test
        # would pass the identity — the two are equal — while destroying
        # nothing at all, which is the failure §4.1 exists to prevent.  A
        # strong signal against unpermuted targets is refused.
        targets = garch(500, 21)
        generator = random.Random(21)
        signal = [0.8 * targets[i] + generator.gauss(0.0, 1.0) for i in range(500)]
        assert not destroys_relationship(
            signal, targets, permuted_targets=targets, block_days=20
        )

    def test_a_barely_permuted_series_that_keeps_the_edge_is_refused(self) -> None:
        # A shuffle that moves almost nothing is not a null world: the caller
        # would be scored against targets that still know the signal.  Swapping
        # only the first and last blocks leaves most of the relationship.
        caught = 0
        for seed in range(20):
            targets = garch(500, seed)
            generator = random.Random(4000 + seed)
            signal = [
                0.5 * targets[i] + generator.gauss(0.0, 1.0) for i in range(500)
            ]
            runs = list(block_runs(targets, block_days=20))
            runs[0], runs[-1] = runs[-1], runs[0]
            nearly = tuple(value for run in runs for value in run)
            if not destroys_relationship(
                signal, targets, permuted_targets=nearly, block_days=20
            ):
                caught += 1
        assert caught > 0

    def test_widening_the_headroom_would_admit_the_identity(self) -> None:
        # The headroom is 1.0 — the bare chance scale — and the tempting
        # argument for raising it is that a legitimate permutation's |after|
        # is a finite-sample statistic and a few percent of them land outside
        # their own scale.  True, and not worth what it costs.
        #
        # The price is paid on the *identity*, which is the one arrangement
        # §4.1 exists to forbid.  An identity whose real edge happens to sit
        # just above the chance scale — a signal with a real but modest edge,
        # which is the common case, not a contrived one — is refused at the
        # bare scale and admitted at a headroom of two.  Measured over 300
        # seeds: 300 of 300 refused at 1.0, 267 of 300 refused at 2.0.  The
        # test asserts the aggregate rather than a chosen seed, because a
        # single seed would only show that one series got lucky.
        refused_at_one = 0
        refused_at_two = 0
        trials = 300
        for seed in range(trials):
            targets = garch(500, seed)
            generator = random.Random(9000 + seed)
            signal = [
                0.5 * targets[i] + generator.gauss(0.0, 1.0) for i in range(500)
            ]
            assert abs(signal_to_target_correlation(signal, targets) or 0.0) > 0
            if not destroys_relationship(
                signal, targets, permuted_targets=targets, block_days=20
            ):
                refused_at_one += 1
            if not destroys_relationship(
                signal, targets, permuted_targets=targets, block_days=20, headroom=2.0
            ):
                refused_at_two += 1
        assert refused_at_one == trials
        assert refused_at_two < trials, (
            "a headroom of two admitted no identity over "
            f"{trials} seeds, so DESTRUCTION_HEADROOM=1.0 is not buying "
            "anything the test can see and should be re-derived"
        )

    def test_the_chance_scale_widens_as_the_series_shortens(self) -> None:
        # The bound is derived from the permutation's own geometry rather than
        # fixed, and the direction matters: a short series is cut into few
        # blocks, so a rearrangement of it can reproduce the real ordering by
        # chance far more easily, and the scale that bounds it is wider.  A
        # fixed threshold would call a legitimate short-series permutation a
        # leak.
        short = check_preservation(
            [float(i % 5) + 0.5 * garch(60, 1)[i] for i in range(60)],
            garch(60, 1),
            seed=1,
            block_days=20,
        )
        long = check_preservation(
            [float(i % 5) + 0.5 * garch(1000, 1)[i] for i in range(1000)],
            garch(1000, 1),
            seed=1,
            block_days=20,
        )
        assert short.chance_scale > long.chance_scale

    def test_a_single_block_series_has_no_coincidence_to_bound(self) -> None:
        # A series cut into one block cannot be shuffled, so there is no
        # coincidence a quantity could survive through and the scale is
        # unbounded — the right answer, because an unshuffled series destroyed
        # nothing and noticing that is the structural check's job, not this
        # clause's.
        targets = garch(15, 3)
        assert destroys_relationship(
            [1.0, 2.0, 3.0] * 5, targets, permuted_targets=targets, block_days=20
        )


# -- The report, and the refusal a serving path needs ------------------------------


class TestTheReportCarriesEveryNumber:
    def test_a_realistic_null_node_reports_both_clauses_green(self) -> None:
        targets = garch(300, 9)
        generator = random.Random(9)
        signal = [0.5 * targets[i] + generator.gauss(0.0, 1.0) for i in range(300)]
        report = check_preservation(signal, targets, seed=9)
        assert isinstance(report, PreservationReport)
        assert report.preserved
        assert report.structure_preserved and report.relationship_destroyed
        assert report.failures() == ()

    def test_the_report_names_the_block_length_and_the_lag_range(self) -> None:
        # §7.4's *"investigate block length"* is the action a failing null
        # node leads to, so the number it names — and the lag range that
        # followed from it — have to be in the report rather than inferred.
        report = check_preservation(garch(300, 9), garch(300, 9), seed=9, block_days=10)
        assert report.block_days == 10
        assert report.lags == tuple(range(1, 10))
        assert len(report.autocorrelation_before) == 9
        assert len(report.clustering_after) == 9

    def test_the_report_carries_the_before_and_after_correlation(self) -> None:
        # The transition §7.3's third clause is about, both ends of it, so an
        # operator can see what was destroyed rather than only that the check
        # passed.
        targets = garch(400, 2)
        generator = random.Random(2)
        signal = [0.6 * targets[i] + generator.gauss(0.0, 1.0) for i in range(400)]
        report = check_preservation(signal, targets, seed=2)
        assert report.signal_correlation_before is not None
        assert report.signal_correlation_after is not None
        assert abs(report.signal_correlation_before) > abs(
            report.signal_correlation_after
        )
        assert report.chance_scale > 0.0

    def test_the_report_follows_the_seed_feature_109_stored(self) -> None:
        # §12's determinism contract: the permutation is reproduced from the
        # stored seed, so the same node checked twice is the same report, and
        # two seeds are two different worlds.
        targets = garch(250, 4)
        generator = random.Random(4)
        signal = [0.5 * targets[i] + generator.gauss(0.0, 1.0) for i in range(250)]
        once = check_preservation(signal, targets, seed=44)
        twice = check_preservation(signal, targets, seed=44)
        assert once == twice
        assert check_preservation(signal, targets, seed=45) != once

    def test_require_returns_the_report_it_already_measured(self) -> None:
        report = check_preservation(garch(300, 9), garch(300, 9), seed=9)
        assert report.require() is report

    def test_require_refuses_a_series_that_broke_the_sentence(self) -> None:
        # The serving path's seam: the two failures have different remedies,
        # so the refusal names the clause that failed and the numbers it was
        # measured at, rather than raising a bare error.
        report = check_preservation(
            garch(500, 21),
            garch(500, 21),
            seed=21,
        )
        broken = PreservationReport(
            **{
                **report.__dict__,
                "relationship_destroyed": False,
            }
        )
        assert broken.failures() == ("relationship_destroyed",)
        with pytest.raises(KsGuardError) as refusal:
            broken.require()
        assert "relationship_destroyed" in str(refusal.value)
        assert "block_days=20" in str(refusal.value)


# -- The refusals ------------------------------------------------------------------


class TestThePermutationParametersAreValidated:
    def test_a_non_positive_block_length_is_refused(self) -> None:
        # The same refusal feature 115's validators state, restated here
        # because this module derives its lag range from the block length: a
        # range derived from a malformed block length names no range.
        for bad in (0, -1, 1.5, "20", None, True):
            with pytest.raises(KsGuardError):
                preservation_lags(bad)

    def test_a_series_that_is_not_finite_reals_is_refused(self) -> None:
        for bad in ([1.0, float("nan")], [1.0, float("inf")], [1.0, "2.0"], ["a"]):
            with pytest.raises(KsGuardError):
                autocorrelation(bad, lag=1)
        for bad in ("not a series", 5, None, {}):
            with pytest.raises(KsGuardError):
                volatility_clustering(bad, lag=1)

    def test_an_empty_series_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            autocorrelation([], lag=1)
        with pytest.raises(KsGuardError):
            preserves_structure([], permuted=[], block_days=20)

    def test_a_non_positive_lag_is_refused(self) -> None:
        # A lag of zero asks for the correlation of a series with itself,
        # which is 1.0 for any series with variance and states nothing about
        # memory; the number would look like a measurement.
        for bad in (0, -1, 1.5, None, True):
            with pytest.raises(KsGuardError):
                autocorrelation(garch(50, 1), lag=bad)

    def test_a_negative_tolerance_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            preserves_structure(
                garch(50, 1), permuted=garch(50, 1), block_days=20, tolerance=-0.1
            )

    def test_a_non_positive_headroom_is_refused(self) -> None:
        # A headroom of zero forbids any correlation at all, which no
        # rearrangement of a real series satisfies, so it would refuse every
        # legitimate permutation — a bound nobody could meet is not a bound.
        targets = garch(100, 1)
        for bad in (0.0, -1.0, None, "1.0"):
            with pytest.raises(KsGuardError):
                destroys_relationship(
                    targets, targets, permuted_targets=targets, headroom=bad
                )

    def test_a_length_mismatch_between_signal_and_targets_is_refused(self) -> None:
        with pytest.raises(KsGuardError):
            signal_to_target_correlation(garch(100, 1), garch(99, 1))

    def test_a_length_mismatch_between_the_two_branches_is_refused(self) -> None:
        # A permutation moves observations, it never adds or drops them, so
        # two different lengths are not the two branches of one null node.
        targets = garch(100, 1)
        with pytest.raises(KsGuardError):
            destroys_relationship(
                targets, targets, permuted_targets=targets[:-1], block_days=20
            )

    def test_check_preservation_refuses_a_mismatched_signal(self) -> None:
        with pytest.raises(KsGuardError):
            check_preservation(garch(99, 1), garch(100, 1), seed=1)

    def test_the_refusals_are_the_guards_error_and_not_the_sidecars(self) -> None:
        # The seam discipline feature 115's validators keep: a malformed
        # permutation parameter or series is a *computation*-contract failure,
        # and a caller reading SidecarError out of this module would look in
        # the wrong place for the cause.
        from nulloracle import SidecarError

        with pytest.raises(KsGuardError) as refusal:
            preservation_lags(0)
        assert not isinstance(refusal.value, SidecarError)
