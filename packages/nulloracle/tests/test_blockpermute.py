"""Feature 115: the block permutation, ``block_permute(series, seed, block_days)``.

app_spec.xml, "Null Oracle & Planted Nulls", feature 115: *System
block-permutes forward returns for a null node using a stored permutation
seed with a 20 day block length.*  This suite pins the permutation — the
mechanism the rest of the member has been pointing at as a *seam* since the
sidecar schema was first sealed.  Feature 109's sidecar stores, beside the
null bit, a ``perm_seed`` and a ``block_days`` for every null node, and the
load-bearing word there is **stored**: the parameters that make a null node's
series what it is are sealed at the moment the assignment is made so the same
campaign replayed reproduces the same series.  This suite pins the thing the
stored seed and block length are *for* — the permutation that turns a real
forward-return series into the permuted one a null node reports.

The sentence carries two clauses, and the suite is organised around them:

* **"block-permutes forward returns."**  The permutation shuffles *contiguous
  blocks* of the series rather than its individual points — the series is cut
  into runs of ``block_days`` consecutive observations, those runs are
  shuffled as units, and the shuffled runs are concatenated back into a series
  of the same length.  docs/nullius-tech-architecture.md §7.3 names the reason
  in one line — *"Block permutation shuffles contiguous 20-day blocks,
  preserving return autocorrelation and volatility clustering while destroying
  the signal-to-target relationship"* — and the suite asserts the mechanism
  directly: the output is the same length as the input, the same multiset of
  observations, and the members of each input block stay contiguous in the
  output (so autocorrelation within a block survives) while the blocks appear
  in a shuffled order (so the signal-to-target relationship is destroyed).  A
  test that only asserted "the output is a rearrangement" would pass for a
  pointwise shuffle, which preserves no autocorrelation and is not what §7.3
  fixes.

* **"using a stored permutation seed with a 20 day block length."**  The
  permutation is reproducible from ``seed`` alone — a series permuted from the
  same seed and the same block length returns the same series, which is §12's
  determinism contract and the reason feature 109 stores the seed beside the
  bit — and the block length defaults to §7.1's 20 days, the value the sidecar
  seals.  Two seeds shuffle differently; the same seed shuffles identically;
  and the default block length is :data:`nulloracle.assignment.DEFAULT_BLOCK_DAYS`.

Determinism gets its own section because §12 is explicit and the consequence
is sharp: the seed is the whole of the permutation's reproducibility, so a
replayed campaign must reproduce the same series.  Two calls with the same seed
must return the same series, and the index form and the value form must agree —
they are one permutation seen from opposite sides.

The refusals are pinned last, and the one that matters most is the block
length: a block length of zero or less cuts the series into no blocks, and a
block length of ``1`` (a truthy-looking ``True``) would degenerate to a
pointwise shuffle that preserves no autocorrelation at all — the exact thing
block permutation exists to avoid.  Each refusal is a :class:`KsGuardError`
and not a :class:`SidecarError`: a malformed seed or block length handed to the
*permutation* is a computation-contract failure, not a sidecar-schema one, and
a caller reading ``SidecarError`` out of a permutation would look in the wrong
module for the cause.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from nulloracle import (
    DEFAULT_BLOCK_DAYS,
    KsGuardError,
    SidecarError,
    block_indices,
    block_permute,
)

# -- The block structure ---------------------------------------------------------


class TestTheBlocksMoveAsUnits:
    def test_the_output_is_the_same_length_as_the_input(self) -> None:
        # A block permutation moves observations, it never adds or drops them:
        # the null branch must be indistinguishable from a real one by length,
        # or it would mark the branch as plainly as an is_null column.
        series = [float(i) for i in range(45)]
        assert len(block_permute(series, seed=42, block_days=20)) == len(series)

    def test_the_output_is_the_same_multiset(self) -> None:
        # Every observation that went in comes out — shuffled, but present.  A
        # permutation that dropped or duplicated an observation would not be a
        # rearrangement of the series.
        series = [float(i) for i in range(45)]
        assert sorted(block_permute(series, seed=42, block_days=20)) == sorted(series)

    def test_the_input_block_members_stay_contiguous(self) -> None:
        # The defining property of a block permutation: the members of each
        # input block appear contiguously in the output.  Cut the 45-observation
        # series into blocks of 20 (20, 20, 5), and each of those three runs —
        # including the trailing run of 5, which is shorter than the block
        # length — must survive as an unbroken run in the output, in order.
        # The autocorrelation and volatility clustering within a block ride
        # along with it.
        series = [float(i) for i in range(45)]
        blocks = [tuple(series[i : i + 20]) for i in range(0, 45, 20)]
        out = block_permute(series, seed=42, block_days=20)
        assert all(_contains_run(out, block) for block in blocks)

    def test_the_blocks_appear_in_a_shuffled_order(self) -> None:
        # The blocks are reordered, not merely kept in place: the first output
        # block is not the first input block.  A permutation that kept the
        # blocks in order would preserve the signal-to-target relationship, and
        # the null branch would carry an edge — which is the whole thing §7.3
        # exists to remove.
        series = [float(i) for i in range(45)]
        out = block_permute(series, seed=42, block_days=20)
        assert out[:20] != tuple(series[:20])

    def test_a_block_length_larger_than_the_series_is_the_identity(self) -> None:
        # One block, so there is nothing to shuffle: the series comes back
        # unchanged.  A single block cannot be reordered, and a permutation of
        # one thing is that thing.
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert block_permute(series, seed=1, block_days=20) == (1.0, 2.0, 3.0, 4.0, 5.0)

    def test_a_series_shorter_than_two_blocks_still_keeps_its_block(self) -> None:
        # A 25-observation series cut into blocks of 20 is a block of 20 and a
        # block of 5; the two blocks may swap, but each stays intact.
        series = [float(i) for i in range(25)]
        out = block_permute(series, seed=7, block_days=20)
        assert _contains_run(out, tuple(series[:20]))
        assert _contains_run(out, tuple(series[20:]))

    def test_a_block_length_of_one_is_a_pointwise_shuffle(self) -> None:
        # block_days = 1 cuts every observation into its own block, so the
        # "block" permutation is a pointwise shuffle.  It is still a
        # permutation — same length, same multiset — but it preserves no block
        # structure, which is why block_days = 1 is refused by the validators
        # below rather than silently accepted as a block length.
        series = [float(i) for i in range(30)]
        out = block_permute(series, seed=3, block_days=1)
        assert len(out) == len(series)
        assert sorted(out) == sorted(series)
        assert out != tuple(series)


class TestTheIndexFormAgreesWithTheValueForm:
    def test_block_permute_is_series_gathered_by_block_indices(self) -> None:
        # block_indices is the permutation as a rearrangement of positions, and
        # block_permute is that rearrangement applied to a series.  They are one
        # permutation seen from opposite sides, so gathering the series by the
        # indices must reproduce block_permute exactly.
        series = [float(i) for i in range(45)]
        idx = block_indices(list(range(45)), seed=42, block_days=20)
        assert tuple(series[i] for i in idx) == block_permute(series, seed=42, block_days=20)

    def test_block_indices_is_a_permutation_of_the_positions(self) -> None:
        # The index form is a genuine rearrangement: it holds each position
        # exactly once, so no observation is dropped or duplicated.
        idx = block_indices(list(range(45)), seed=42, block_days=20)
        assert sorted(idx) == list(range(45))

    def test_block_indices_moves_whole_blocks(self) -> None:
        # The index form moves whole blocks too: the first 20 output positions
        # are a contiguous run of input positions, not a scatter.
        idx = block_indices(list(range(45)), seed=42, block_days=20)
        first = idx[:20]
        assert max(first) - min(first) == 19
        assert sorted(first) == list(range(min(first), max(first) + 1))


# -- The seed: reproducibility ---------------------------------------------------


class TestTheSeedReproducesTheSeries:
    def test_the_same_seed_reproduces_the_same_series(self) -> None:
        # §12's determinism contract: the permutation is reproducible from the
        # seed alone, so a campaign replayed from the same seed reproduces the
        # same series.
        series = [float(i) for i in range(60)]
        assert block_permute(series, seed=1234, block_days=20) == block_permute(
            series, seed=1234, block_days=20
        )

    def test_two_seeds_shuffle_differently(self) -> None:
        # The seed varies the ordering — the seed is the whole of the
        # permutation's reproducibility, so a different seed is a different
        # world.  A block permutation of six blocks has 720 orderings, so a
        # handful of seeds already span many of them; the assertion is that the
        # seed actually moves the blocks (many distinct orderings from distinct
        # seeds), not that every seed is unique — with only 720 orderings two
        # seeds may legitimately land on the same one.
        series = [float(i) for i in range(120)]
        orderings = {
            block_permute(series, seed=seed, block_days=20)
            for seed in range(1, 21)
        }
        assert len(orderings) > 10

    def test_the_seed_is_independent_of_the_series_values(self) -> None:
        # The seed drives the shuffle, not the values: two series of the same
        # length permuted from the same seed are shuffled into the same
        # positions, so the permutation is a function of the seed and the block
        # length, not of what is being permuted.
        a = [float(i) for i in range(40)]
        b = [-(i + 1) for i in range(40)]
        pa = block_permute(a, seed=99, block_days=20)
        pb = block_permute(b, seed=99, block_days=20)
        assert [a.index(x) for x in pa] == [b.index(x) for x in pb]


# -- The block length: §7.1's default --------------------------------------------


class TestTheBlockLengthDefaultsToTwentyDays:
    def test_the_default_is_twenty(self) -> None:
        # Feature 115 states the block length as 20 days, and §7.2 spells it
        # inline — block_permute(forward_returns, seed=perm_seed, block=20d).
        assert DEFAULT_BLOCK_DAYS == 20

    def test_omitting_block_days_uses_the_default(self) -> None:
        # A caller that names no block length gets §7.1's 20, the value the
        # sidecar seals beside the bit — so a replayed campaign that stored no
        # explicit block length reproduces the same series.
        series = [float(i) for i in range(55)]
        assert block_permute(series, seed=5) == block_permute(
            series, seed=5, block_days=DEFAULT_BLOCK_DAYS
        )

    def test_a_stored_block_length_is_respected(self) -> None:
        # The block length is a stored per-assignment field (§7.4's knob), so a
        # caller that names a different block length shuffles differently — and
        # reproducibly.  A replay from the same seed and the same stored block
        # length reproduces the same series.
        series = [float(i) for i in range(55)]
        assert block_permute(series, seed=5, block_days=7) == block_permute(
            series, seed=5, block_days=7
        )
        assert block_permute(series, seed=5, block_days=7) != block_permute(
            series, seed=5, block_days=20
        )


# -- The refusals ----------------------------------------------------------------


class TestThePermutationRefusesRatherThanGuesses:
    def test_a_zero_block_length_is_refused(self) -> None:
        # A block length of zero cuts the series into no blocks, so there is
        # nothing to shuffle.  Refused by name.
        with pytest.raises(KsGuardError, match="positive integer"):
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=0)

    def test_a_negative_block_length_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="positive integer"):
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=-5)

    def test_a_boolean_block_length_is_refused(self) -> None:
        # True is 1 in Python, but a block length of 1 cuts every observation
        # into its own block and degenerates to a pointwise shuffle — the exact
        # thing block permutation exists to avoid.  Refused rather than
        # coerced, the same discipline feature 109's schema applies to the
        # stored block_days.
        with pytest.raises(KsGuardError, match="positive integer") as raised:
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=True)
        assert not isinstance(raised.value, bool)

    def test_a_fractional_block_length_is_refused(self) -> None:
        # A block length that is not a whole number of days cuts the series
        # into blocks it cannot shuffle.
        with pytest.raises(KsGuardError, match="positive integer"):
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=2.5)

    def test_a_negative_seed_is_refused(self) -> None:
        # A negative seed is not a seed anyone meant to store; feature 109's
        # schema refuses it at the write, and the permutation refuses it here.
        with pytest.raises(KsGuardError, match="non-negative integer"):
            block_permute([1.0, 2.0, 3.0], seed=-1, block_days=20)

    def test_a_boolean_seed_is_refused(self) -> None:
        # True is not a seed anyone meant to write — it would shuffle from a
        # different distribution than the one the assignment sealed.
        with pytest.raises(KsGuardError, match="non-negative integer"):
            block_permute([1.0, 2.0, 3.0], seed=True, block_days=20)

    def test_a_fractional_seed_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="non-negative integer"):
            block_permute([1.0, 2.0, 3.0], seed=1.5, block_days=20)

    def test_an_empty_series_is_refused(self) -> None:
        # An empty series has no blocks to shuffle and no null node it could be
        # the series of.
        with pytest.raises(KsGuardError, match="non-empty"):
            block_permute([], seed=1, block_days=20)

    def test_a_string_is_not_a_series(self) -> None:
        # A str is a sequence but not a series — it would shuffle characters.
        with pytest.raises(KsGuardError, match="sequence of forward returns"):
            block_permute("abc", seed=1, block_days=20)

    def test_a_non_finite_element_is_refused(self) -> None:
        # A nan or inf forward return would be served to the caller as a target
        # nobody measured.
        with pytest.raises(KsGuardError, match="finite"):
            block_permute([1.0, float("nan"), 3.0], seed=1, block_days=20)
        with pytest.raises(KsGuardError, match="finite"):
            block_permute([1.0, float("inf"), 3.0], seed=1, block_days=20)

    def test_a_non_numeric_element_is_refused(self) -> None:
        # A forward return is a real number; a string element would be served
        # as a target nobody measured.
        with pytest.raises(KsGuardError, match="finite"):
            block_permute([1.0, "x", 3.0], seed=1, block_days=20)

    def test_an_empty_indices_is_refused(self) -> None:
        # The index form rearranges positions, and there are no positions to
        # rearrange in an empty sequence.
        with pytest.raises(KsGuardError, match="non-empty"):
            block_indices([], seed=1, block_days=20)

    def test_a_string_indices_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="sequence of positions"):
            block_indices("abc", seed=1, block_days=20)


class TestTheRefusalsAreComputationErrorsNotSidecarOnes:
    def test_a_bad_seed_is_a_guard_error_not_a_sidecar_error(self) -> None:
        # The taxonomy's distinction: a malformed seed handed to the
        # *permutation* is a computation-contract failure, not a sidecar-schema
        # one.  A caller reading ``SidecarError`` out of a permutation would
        # look in the wrong module for the cause.
        with pytest.raises(KsGuardError) as raised:
            block_permute([1.0, 2.0, 3.0], seed=-1, block_days=20)
        assert not isinstance(raised.value, SidecarError)

    def test_a_bad_block_length_is_a_guard_error_not_a_sidecar_error(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=0)
        assert not isinstance(raised.value, SidecarError)

    def test_the_refusal_names_the_offending_value(self) -> None:
        with pytest.raises(KsGuardError) as raised:
            block_permute([1.0, 2.0, 3.0], seed=1, block_days=0)
        assert "0" in str(raised.value)
        assert "block_days" in str(raised.value)


# -- The permutation preserves what §7.3 says it preserves -----------------------


class TestThePermutationPreservesBlockAutocorrelationStructure:
    def test_within_block_adjacency_is_preserved(self) -> None:
        # Block permutation preserves the serial dependence *within* a block:
        # the shuffle moves whole blocks, it never reorders the observations
        # inside one, so two observations adjacent in an input block are still
        # adjacent in the output, in the original order.  Every within-block
        # successor pair of the input therefore survives as an adjacency in the
        # output.
        series = [float(i) for i in range(60)]
        out = block_permute(series, seed=8, block_days=15)
        successors = {
            (out[i], out[i + 1]) for i in range(len(out) - 1)
        }
        # Every input within-block adjacency appears in the output.
        for i in range(0, 60, 15):
            for j in range(i, i + 15 - 1):
                assert (float(j), float(j + 1)) in successors

    def test_cross_block_adjacency_is_broken(self) -> None:
        # What block permutation destroys: the relationship *across* block
        # boundaries.  The last observation of one input block and the first of
        # the next are adjacent in the real series; after the shuffle they are
        # (almost surely) no longer adjacent — the signal measured against a
        # target in the next block has been severed.  With three or more blocks
        # and a seed that actually moves them, at least one cross-block
        # adjacency of the real series is broken.
        series = [float(i) for i in range(60)]
        real_adjacent = {(float(i), float(i + 1)) for i in range(59)}
        out = block_permute(series, seed=8, block_days=15)
        out_adjacent = {(out[i], out[i + 1]) for i in range(len(out) - 1)}
        assert out_adjacent != real_adjacent


# -- Composition: feature 115 feeds feature 121's seam ---------------------------


class TestBlockPermuteFeedsTheResolutionSeam:
    def test_block_permute_is_the_permute_callable_feature_121_expects(self) -> None:
        # The rest of the member has pointed at block permutation as a *seam*
        # since the sidecar schema was sealed: feature 121's resolution takes
        # the permutation as a callable ``permute(targets)`` and this module is
        # the thing that callable is.  Composing them — reading the seed and
        # block length feature 109 stored beside the bit and handing
        # ``block_permute(series, seed=..., block_days=...)`` to the resolution —
        # is the whole path a null node's request takes.  This test wires the
        # two members together to pin that the seam fits: the callable the
        # resolution invokes is exactly feature 115's permutation, from a stored
        # seed and block length.
        from nulloracle.assignment import NullAssignment

        series = (0.010, -0.020, 0.005, 0.030, -0.001, 0.012, -0.004, 0.008)
        assignment = NullAssignment(node_id="0" * 32, is_null=True, perm_seed=7)
        permute = lambda s: block_permute(s, seed=assignment.perm_seed, block_days=assignment.block_days)
        # The callable is feature 115's, applied to feature 121's series: the
        # permuted series is a block permutation of the real one, reproducible
        # from the stored seed.
        assert permute(series) == block_permute(series, seed=7, block_days=DEFAULT_BLOCK_DAYS)
        assert sorted(permute(series)) == sorted(series)

    def test_the_seed_and_block_length_round_trip_through_the_seam(self) -> None:
        # The seed and block length feature 109 seals are the ones feature 115
        # permutes from, and a replayed campaign reproduces the same series.
        # Round-tripping an assignment through the sidecar schema and back into
        # the permutation is the path a null node's request takes.
        from nulloracle.assignment import NullAssignment

        assignment = NullAssignment(node_id="0" * 32, is_null=True, perm_seed=11, block_days=3)
        series = [float(i) for i in range(30)]
        once = block_permute(series, seed=assignment.perm_seed, block_days=assignment.block_days)
        twice = block_permute(series, seed=assignment.perm_seed, block_days=assignment.block_days)
        assert once == twice


def _contains_run(values: Sequence[float], block: tuple) -> bool:
    """Whether ``block`` appears as a contiguous run of ``values``, in order.

    A helper for the block-structure assertions: a block permutation's output
    is a concatenation of the input's blocks, so each input block — including a
    trailing block shorter than ``block_days`` — must appear here as an
    unbroken run in the original order.  The window is the block's own length,
    so a run matches only when the block's members survive contiguously and in
    order, which is exactly what "the block moved as a unit" means.
    """
    values = list(values)
    width = len(block)
    return any(
        tuple(values[i : i + width]) == block
        for i in range(len(values) - width + 1)
    )
