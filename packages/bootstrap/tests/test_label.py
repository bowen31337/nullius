"""Feature 181's headline: *a ground-truth score per node*.

app_spec.xml feature 181 asks for the world, and docs/nullius-tech-
architecture.md §10.6 says what the world is *for*: *"Build the
non-financial ground-truth worlds so pool size becomes a compute problem
rather than a calendar problem."*  The word doing the work is **ground
truth**, and it is a much stronger claim than "a score".  These tests are
how the member holds itself to it, and they pin four things:

* **a label is a pure function of ``(world, node)``.**  The same node
  labelled twice, or labelled after any number of other nodes, or labelled
  after a whole sweep, answers the *identical* number — not a close one.
  This is the property that lets a replay reveal cells in whatever order
  the policy chooses (§10.1) and still have every revealed value mean
  something; a label that moved with the path would not be a ground truth
  but a measurement of the path.  The test is written as an interleaving:
  a full sweep between two asks of one node.
* **the label is honest.**  It is the *held-out* ``R²``, so memorising the
  training split does not raise it — the curve over the lattice is real
  (`test_the_landscape_peaks_where_the_model_really_is`), and a wider
  model that overfits is *punished* rather than rewarded.  A bootstrap
  world is where §14's ``meta_overfit`` signal is calibrated, and this is
  the honest pair that calibrates it.
* **the world is discriminating.**  Six features, noise, and a true model
  that is *not* the widest thing the lattice can express: the optimum sits
  at degree 2 with interactions, and the root, the widest design and the
  degree-3 designs all score well below it.  A world where the first cell
  was already best, or where every cell scored the same, would be
  technically a ground truth and useless as a search problem — §10.6.1's
  whole argument is that these worlds make the *policy* the thing under
  test.
* **the world is cheap and renewable.**  Two worlds of one seed are one
  world; two worlds of different seeds are two worlds with the same
  lattice and different labels.  §10.6 wants 40-50 of them, so a world
  must cost nothing to *hold* (the dataset is generated on first label and
  not before) and must be addressed by its seed alone.

The values pinned here are of two kinds, deliberately.  The *structural*
ones — which cell is best, which family of designs beats which, that the
degree-3 designs overfit — are properties of the world's construction and
are asserted with a margin, so they survive an arithmetic refactor that
does not change what the world *is*.  The exact numbers are not pinned as
literals: a regression that moved a label's last bits would be caught by
§12's canary, in its own suite, against its own tolerance, and pinning
them here would only mean this file failed every time the arithmetic was
legitimately improved.
"""

from __future__ import annotations

import pytest
from bootstrap import (
    DEFAULT_RIDGE,
    HYPERPARAMETER_WORLD_ID,
    PRICED_ROWS,
    PRICED_SEED,
    BootstrapScoringError,
    BootstrapWorldError,
    FitResult,
    HyperparameterAxis,
    HyperparameterWorld,
)

#: The degree and interaction coordinates the world pinned by
#: ``PRICED_SEED`` peaks at: degree 2 *with* interactions — the shallowest
#: design that can express the truth's cross term and its square term, and
#: no wider.  Pinned as coordinates rather than as a whole node id because
#: the winning ``alpha`` is a *seed-dependent* detail on a near-flat axis;
#: what has to be stable is where the optimum sits on the two axes that
#: carry the signal.
PEAK_DEGREE = 2
PEAK_INTERACTIONS = True


def _best(scores: dict[str, FitResult]) -> tuple[str, FitResult]:
    """The highest-scoring cell of a labelled landscape."""
    best = max(scores, key=lambda node_id: scores[node_id].r2_holdout)
    return best, scores[best]


def _best_in(
    world: HyperparameterWorld, scores: dict[str, FitResult], **match: object
) -> float:
    """The highest score among the cells matching ``match`` on their setting."""
    values = [
        result.r2_holdout
        for node_id, result in scores.items()
        if all(getattr(world.setting(node_id), key) == value for key, value in match.items())
    ]
    assert values, match  # an empty family would make the assertion vacuous
    return max(values)


def _scores(world: HyperparameterWorld) -> dict[str, FitResult]:
    """Every cell's label, as a plain dict, refusing nothing.

    The sweep is *total* by contract, so a refusal here is a failure of
    that contract rather than a corner of the landscape — asserted as such
    rather than silently filtered, so a world that started refusing cells
    would fail this helper's every caller instead of quietly reporting a
    smaller space.
    """
    labelled = dict(world.label_all())
    for node_id, result in labelled.items():
        assert isinstance(result, FitResult), (node_id, result)
    return labelled  # type: ignore[return-value]


# -- A label is a function ---------------------------------------------------------


def test_a_label_is_the_holdout_score_the_feature_asks_for(
    world: HyperparameterWorld, wide_node: str
) -> None:
    # ``FitResult.r2_holdout`` — not the training score, and not some
    # combined figure.  Pinned explicitly because the two are far apart
    # (the gap is the point) and picking the wrong one would still produce
    # a plausible number for every node.
    result = world.label(wide_node)
    assert result.r2_holdout != result.r2_train
    assert result.row()["world_score"] == result.r2_holdout


def test_the_same_node_labelled_twice_answers_the_identical_number(
    world: HyperparameterWorld, wide_node: str
) -> None:
    # Bit-identical, not merely close.  Nothing in the path holds state,
    # memoises or accumulates, so there is no mechanism by which two asks
    # could differ — and the assertion is written as equality so that a
    # future cache, which *would* be a mechanism, fails here.
    first = world.label(wide_node)
    second = world.label(wide_node)
    assert first.r2_holdout == second.r2_holdout
    assert first.coefficients == second.coefficients


def test_a_label_does_not_depend_on_what_was_labelled_before_it(
    world: HyperparameterWorld, wide_node: str
) -> None:
    # The property the whole design exists for, and the reason the draw is
    # a content-addressed hash rather than :class:`random.Random`.  A
    # policy reveals cells in an order *it* chooses (§10.1); if a label
    # depended on the path taken to it, the policy's own history would be
    # in the score and the score would not be a ground truth.
    #
    # Written as an interleave: take the label, then label every cell of
    # the lattice, then take it again.  A generator-based world answers a
    # different number the second time.  This one answers the same bits.
    before = world.label(wide_node)
    _scores(world)  # the whole space, in between
    after = world.label(wide_node)
    assert after.r2_holdout == before.r2_holdout
    assert after.coefficients == before.coefficients


def test_the_sweep_and_a_single_ask_agree_cell_for_cell(
    world: HyperparameterWorld,
) -> None:
    # ``label_all`` routes through the same implementation a single
    # ``label`` does (``label_setting``), so a sweep cannot drift from an
    # ask.  Asserted rather than assumed: two code paths that agreed
    # *today* is not the same as one code path, and the sweep is what a
    # pool report reads.
    swept = _scores(world)
    for node_id in world.cells():
        assert world.label(node_id).r2_holdout == swept[node_id].r2_holdout


def test_the_sweep_is_ascending_and_covers_every_cell(
    world: HyperparameterWorld,
) -> None:
    # Ascending node ids and one entry per cell — §12's ordering rule, so
    # two sweeps of one world are comparable element by element and a
    # pool's report of the space does not depend on iteration order.
    labelled = list(world.label_all())
    node_ids = [node_id for node_id, _ in labelled]
    assert node_ids == list(world.cells())
    assert node_ids == sorted(node_ids)
    assert len(node_ids) == len(set(node_ids))


def test_a_missing_node_id_is_refused_rather_than_defaulted_to_the_root(
    world: HyperparameterWorld,
) -> None:
    # The root is a node like any other and is asked for *by name*.  A
    # defaulted argument would make a caller's missing node id look like a
    # deliberate root ask — every score in a replay's report would come
    # from one cell, silently, and the report would look fine.  This is
    # the same discipline §10.6.1 applies to ``commit``.
    with pytest.raises(BootstrapWorldError, match="needs the node id to label"):
        world.label("")
    with pytest.raises(BootstrapWorldError, match="needs the node id to label"):
        world.label(None)  # type: ignore[arg-type]


def test_the_refusal_names_the_root_so_the_repair_is_visible(
    world: HyperparameterWorld,
) -> None:
    # A refusal is only useful if it says what to do instead, and here the
    # repair is a specific string the caller should have passed.
    with pytest.raises(BootstrapWorldError) as refusal:
        world.label("")
    assert world.canonical_node() in str(refusal.value)


def test_an_out_of_lattice_node_is_refused_before_any_fit_happens(
    world: HyperparameterWorld,
) -> None:
    # A world error, not a scoring error: the ask named a cell this world
    # does not hold, which is a different failure from "the honest label
    # could not be computed".  The distinction is what lets a pool builder
    # tell "draw another world" (a scoring refusal) from "re-aim the ask"
    # (a world refusal) — the split ``bootstrap.errors`` exists for.
    with pytest.raises(BootstrapWorldError, match="past the end of the 'degree' axis"):
        world.label("d+9.i+0.s+0.a+0")


# -- The label is honest -----------------------------------------------------------


def test_a_wider_design_does_not_simply_score_higher(
    world: HyperparameterWorld,
) -> None:
    # The check that the held-out score is doing its job.  If a wider
    # design always won, the label would be measuring capacity rather than
    # generalisation, and the "search" would be a one-line rule.
    #
    # Two facts make that concrete here.  The honest label can be
    # *negative* — the linear designs on this world score well below
    # predicting the mean, because the truth's signal is concentrated in
    # curvature a line cannot reach — and the widest design does not beat
    # the optimum despite having strictly more columns to work with.
    scores = _scores(world)
    assert min(result.r2_holdout for result in scores.values()) < 0.0

    optimum = _best(scores)[1].r2_holdout
    assert _best_in(world, scores, degree=3, interactions=True) < optimum


def test_the_overfit_gap_is_a_calibration_reference(world: HyperparameterWorld) -> None:
    # §14's ``meta_overfit`` signal, honestly measured.  A bootstrap world
    # is where that signal is *calibrated* — a financial world's gap is
    # only alarming relative to what the gap looks like when nothing is
    # being gamed, and this world is that reference.
    #
    # The gap does *not* track capacity, and pinning the truth of that
    # rather than the tidier claim is the point.  A degree-1 design has the
    # *largest* gap on this world — larger than either of the wider
    # designs — because a misspecified model still fits its training split
    # as well as it can while generalising badly, so the gap measures
    # misspecification as well as overfitting.  That ambiguity is exactly
    # what a calibrating reference has to make visible, and a test that
    # asserted "the gap widens with degree" would have hidden it.
    scores = _scores(world)
    gaps: dict[int, list[float]] = {}
    for node_id, result in scores.items():
        gaps.setdefault(world.setting(node_id).degree, []).append(result.overfit_gap)
    mean_gap = {degree: sum(values) / len(values) for degree, values in gaps.items()}
    assert mean_gap[1] > mean_gap[2]  # misspecification dominates here
    assert mean_gap[1] > mean_gap[3]
    assert mean_gap[2] < mean_gap[3]  # and overfitting shows beyond it
    # The training side rises monotonically while this happens, which is
    # what makes the gap a *gap* rather than an undifferentiated number.
    train: dict[int, list[float]] = {}
    for node_id, result in scores.items():
        train.setdefault(world.setting(node_id).degree, []).append(result.r2_train)
    mean_train = {degree: sum(values) / len(values) for degree, values in train.items()}
    assert mean_train[1] < mean_train[2] <= mean_train[3]


def test_the_widest_cell_has_the_largest_training_holdout_gap(
    world: HyperparameterWorld,
) -> None:
    # The same signal per-cell rather than averaged: the cell with the most
    # columns memorises most and generalises least, relative to the
    # optimum.  This is the single pair an operator would read off a
    # report to see what "overfitting" looks like on a world whose answer
    # is known.
    scores = _scores(world)
    optimum = _best(scores)[1]
    widest = max(
        (result for node_id, result in scores.items() if world.setting(node_id).degree == 3),
        key=lambda result: result.overfit_gap,
    )
    assert widest.overfit_gap > optimum.overfit_gap


def test_the_training_score_rises_with_capacity_even_as_the_holdout_falls(
    world: HyperparameterWorld,
) -> None:
    # The two halves of the pair, pulling in opposite directions — which is
    # what makes the *gap* informative rather than merely large.  If both
    # moved together there would be nothing to calibrate against.
    scores = _scores(world)
    linear = [
        result.r2_train
        for node_id, result in scores.items()
        if world.setting(node_id).degree == 1 and not world.setting(node_id).interactions
    ]
    wide = [
        result.r2_train
        for node_id, result in scores.items()
        if world.setting(node_id).degree == 3 and world.setting(node_id).interactions
    ]
    assert sum(linear) / len(linear) < sum(wide) / len(wide)  # training: wider wins


# -- The world is discriminating ---------------------------------------------------


def test_the_landscape_peaks_where_the_model_really_is(
    world: HyperparameterWorld,
) -> None:
    # *The* pin on the world's usableness as a search problem.  The true
    # model is an expression with one pairwise cross term and one square
    # term, so the shallowest design that can express it is degree 2 *with*
    # interactions — and that is where the held-out score peaks.  A world
    # whose optimum sat at the root would be solved by doing nothing; a
    # world whose optimum sat at degree 1 with interactions would make two
    # thirds of the space uninformative.
    scores = _scores(world)
    best, result = _best(scores)
    setting = world.setting(best)
    assert setting.degree == PEAK_DEGREE
    assert setting.interactions is PEAK_INTERACTIONS
    assert result.r2_holdout == _best_in(world, scores, degree=2, interactions=True)


def test_the_optimum_beats_the_root_by_a_wide_margin(
    world: HyperparameterWorld, root_node: str
) -> None:
    # Not a tie broken by floating point: the search has somewhere to go.
    # The margin is what makes a policy's *path* through the lattice
    # measurable at all.
    scores = _scores(world)
    assert _best(scores)[1].r2_holdout - scores[root_node].r2_holdout > 0.5


def test_the_optimum_is_stable_across_the_pool(world: HyperparameterWorld) -> None:
    # §10.6 wants 40-50 worlds, and they share one lattice — so the
    # *identity* of the optimum has to be a fact about the truth model
    # rather than about one seed's luck.  If it wandered with the seed, a
    # policy tuned on one world would be tuned on noise, and the
    # category's claim that these worlds transfer what they teach would be
    # false.
    #
    # Asserted over a *sample* of seeds rather than the whole pool
    # (feature 188 draws those), and asserted as a large majority rather
    # than unanimity: the noise is real, so a seed where the cubic's extra
    # columns happen to pay is a legitimate world rather than a bug.  What
    # must hold is that this is rare enough to be an exception rather than
    # the rule.
    winners: dict[tuple[int, bool], int] = {}
    for seed in range(1, 13):
        sample = HyperparameterWorld(f"bootstrap-hpo-sample-{seed}", seed=seed)
        scores = _scores(sample)
        best = max(scores, key=lambda node_id: scores[node_id].r2_holdout)
        setting = sample.setting(best)
        key = (setting.degree, setting.interactions)
        winners[key] = winners.get(key, 0) + 1
    assert winners.get((2, True), 0) >= 9  # the strong majority
    assert set(winners) <= {(2, True), (3, True)}  # never a linear design


def test_interactions_are_load_bearing_on_this_world(
    world: HyperparameterWorld,
) -> None:
    # The axis exists because the true model has a cross term, and the
    # *only* way the lattice can express it is by turning interactions on.
    # So at every degree, the interaction cells must dominate — an axis
    # that changed nothing would make half the space uninformative and any
    # policy's exploration of it pure noise.
    #
    # Asserted *at each degree* rather than only at the optimum's: the
    # claim is about the axis, and an axis that paid at degree 2 while
    # being dead at degrees 1 and 3 would still be a search problem with a
    # large uninformative region in it.
    scores = _scores(world)
    for degree in (1, 2, 3):
        assert _best_in(world, scores, degree=degree, interactions=True) > _best_in(
            world, scores, degree=degree, interactions=False
        ), degree


def test_the_degree_axis_is_load_bearing_on_this_world(
    world: HyperparameterWorld,
) -> None:
    # The other axis, and the reason the truth's curvature terms outweigh
    # its linear ones.  A linear design cannot reach a square term at all,
    # so degree 1 must lose badly to degree 2 — and the *shallowest* design
    # that reaches the truth must beat the cubic, which pays variance for
    # columns the truth never uses.
    #
    # This is the crossing that makes the world a search problem rather
    # than a hill-climb: the optimum is not at either end of either axis,
    # so neither "more is better" nor "less is better" is a rule that
    # finds it.
    scores = _scores(world)
    best_at = lambda degree, interactions: _best_in(
        world, scores, degree=degree, interactions=interactions
    )
    assert best_at(2, True) > best_at(1, True) + 0.5  # curvature is reachable
    assert best_at(2, True) > best_at(3, True)  # and the cubic overfits


def test_the_two_main_axes_dominate_and_the_flat_ones_are_not_dead(
    world: HyperparameterWorld,
) -> None:
    # The shape of the search problem in one assertion: the degree and
    # interaction axes move the score by a lot, and the standardize and
    # alpha axes move it by less.  A policy therefore has to *learn* which
    # axes are worth exploring — which is precisely the "problem
    # structure" §10.6 says a bootstrap world is for teaching.
    #
    # Neither flat axis is *dead*, though: each moves the score somewhere,
    # so exploring them is not exploring a constant.  Asserting both
    # halves is what keeps this test from being satisfied by a world that
    # simply has fewer real dimensions than its lattice claims.
    scores = _scores(world)

    def spread(**match: object) -> float:
        values = [
            result.r2_holdout
            for node_id, result in scores.items()
            if all(
                getattr(world.setting(node_id), key) == value
                for key, value in match.items()
            )
        ]
        return max(values) - min(values)

    # The alpha axis, isolated at the optimum's degree and interaction: it
    # moves the score substantially, so probing it is not wasted effort.
    assert spread(degree=2, interactions=True) > 0.05
    # And it is small beside what turning interactions on is worth, which
    # is what makes *choosing* between the axes a decision a policy has to
    # learn rather than a tie it can break arbitrarily.
    assert _best_in(world, scores, interactions=True) - _best_in(
        world, scores, interactions=False
    ) > 0.15


def test_the_standardize_axis_is_flat_until_the_penalty_is_heavy(
    world: HyperparameterWorld,
) -> None:
    # The member's docstring calls ``standardize`` the flat axis, and the
    # honest version of that claim is *conditional* — which is why the
    # test is written as a curve rather than as one assertion.
    #
    # A linear rescaling of a polynomial design's inputs does not change
    # its span, so both standardisations can express the same predictions
    # and the *unpenalised* least-squares optimum is the same point.  But
    # the penalty is not scale-invariant: a ridge applied to unstandardised
    # columns penalises them in their own units, so a feature drawn at a
    # different scale is shrunk by a different amount.  The axis therefore
    # starts flat and bites as ``alpha`` grows, which is exactly the
    # interaction a policy has to learn — the two axes are not independent,
    # and neither "more standardisation is better" nor "less is better" is
    # a rule that finds the optimum.
    scores = _scores(world)

    def gap_at(alpha: float) -> float:
        """The largest standardize flip's effect at one ridge strength."""
        return max(
            abs(
                scores[
                    world.node_id(
                        world.setting(node_id).with_value(
                            HyperparameterAxis.STANDARDIZE,
                            not world.setting(node_id).standardize,
                        )
                    )
                ].r2_holdout
                - result.r2_holdout
            )
            for node_id, result in scores.items()
            if world.setting(node_id).alpha == alpha
        )

    # Flat where the fit is nearly unpenalised...
    assert gap_at(0.01) < 1e-3
    assert gap_at(0.1) < 1e-3
    # ...and load-bearing where the penalty is heavy, strictly increasing
    # in between.  Monotone rather than merely "bigger at the top": the
    # claim is that the effect is driven by the penalty, and a
    # non-monotone curve would mean something else is moving it.
    gaps = [gap_at(alpha) for alpha in (0.01, 0.1, 1.0, 10.0, 100.0)]
    assert gaps == sorted(gaps)
    assert gaps[-1] > 0.05

    # And even at its largest it is a fraction of what the interaction axis
    # is worth, so the *ordering* of which axes repay probing is not in
    # doubt — only the absolute claim that this one is dead is wrong.
    assert gaps[-1] < _best_in(world, scores, interactions=True) - _best_in(
        world, scores, interactions=False
    )


def test_the_alpha_axis_is_ordered_by_its_own_meaning(
    world: HyperparameterWorld,
) -> None:
    # The ridge is a bias-variance knob like any other, and on this world
    # the ordering is the textbook one at the optimum's degree: a *very*
    # strong ridge is worse than a light one, because it shrinks genuine
    # signal.
    #
    # This pins the axis's *direction*, which is the part a refactor can
    # silently invert — passing ``1/alpha``, or adding the penalty to the
    # wrong side of the system — while every other test in this file would
    # still pass, since an inverted axis still moves the score.
    scores = _scores(world)
    assert _best_in(world, scores, degree=2, interactions=True, alpha=0.01) > _best_in(
        world, scores, degree=2, interactions=True, alpha=100.0
    )


# -- Two worlds, one lattice -------------------------------------------------------


def test_two_worlds_of_one_seed_are_one_world() -> None:
    # §10.6.1's provenance rule from the generated side.  A world has no
    # upstream to check — its seed *is* its identity — so reproducibility
    # is a property of construction: the same id and seed is the same
    # world, byte for byte, and a pool entry can be re-derived rather than
    # archived.
    left = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    right = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    for node_id in left.cells():
        assert left.label(node_id).r2_holdout == right.label(node_id).r2_holdout


def test_a_different_seed_is_a_different_world_over_the_same_lattice(
    world: HyperparameterWorld, other_world: HyperparameterWorld
) -> None:
    # §10.6 wants 40-50 of these, and this is what lets it: a new world
    # costs a seed, not a new lattice.  The *space* the policy walks is the
    # same shape, so a policy is portable across them; the *labels* differ,
    # so they are genuinely different search problems rather than 40 copies
    # of one.
    assert world.cells() == other_world.cells()
    differing = sum(
        1
        for node_id in world.cells()
        if world.label(node_id).r2_holdout != other_world.label(node_id).r2_holdout
    )
    assert differing > len(world.cells()) * 0.9


def test_a_world_costlessly_holds_a_dataset_it_may_never_use() -> None:
    # Construction performs no arithmetic.  §10.6 has a pool builder
    # holding 40-50 of these, most of which a given replay will not reach,
    # so "build a world" must not mean "generate a dataset" — the same
    # stance feature 169's store and the null sidecar take for their own
    # construction.  The check is *timing-free* and structural: the world
    # has a dataset slot that is empty until something needs it, and it is
    # filled the moment a label does, so the laziness is a deferral rather
    # than an absence.
    fresh = HyperparameterWorld("bootstrap-hpo-unused", seed=1)
    assert "_dataset" in fresh.__slots__
    assert fresh._dataset is None  # nothing generated yet
    fresh.label(fresh.canonical_node())
    assert fresh._dataset is not None  # and now it is
    assert fresh.dataset.rows == PRICED_ROWS


def test_the_dataset_is_fixed_and_a_property_of_the_seed(
    world: HyperparameterWorld, other_world: HyperparameterWorld
) -> None:
    # "a *fixed* model and dataset" — feature 181's words.  Fixed means the
    # same seed yields the same rows and targets, so a label is traceable
    # to a dataset that can be regenerated rather than merely trusted.
    #
    # ``other_world`` carries a different seed, so this asserts the *shape*
    # the two share (a fixed row count and feature width) rather than
    # their values — the values are the next test's business, from the
    # other side.
    assert world.dataset.rows == other_world.dataset.rows == PRICED_ROWS
    assert len(world.dataset.features[0]) == len(other_world.dataset.features[0])
    assert len(world.dataset.targets) == PRICED_ROWS


def test_two_worlds_of_one_seed_share_one_dataset() -> None:
    # The identity half of §10.6.1's provenance rule, at the dataset
    # level: a world *is* its seed, so re-deriving the world re-derives
    # the data rather than approximating it.  A pool entry can therefore
    # be named by (id, seed) and recovered, instead of archived.
    left = HyperparameterWorld("same", seed=7)
    right = HyperparameterWorld("same", seed=7)
    assert left.dataset.features == right.dataset.features
    assert left.dataset.targets == right.dataset.targets


def test_the_two_worlds_datasets_differ_because_their_seeds_do() -> None:
    # The other direction: the seeds are not decorative.  Two worlds with
    # different seeds must have different *data*, or "40-50 worlds" would
    # be one world shipped 40-50 times and §10.6's pool would be 40-50
    # copies of one search problem — the independence claim it rests on
    # would be false while every individual label stayed perfectly honest.
    left = HyperparameterWorld("w-left", seed=1)
    right = HyperparameterWorld("w-right", seed=2)
    assert left.dataset.features != right.dataset.features
    assert left.dataset.targets != right.dataset.targets
    # And the difference is *dense*, not one row: a coincidence of a single
    # feature draw would satisfy the inequality above while leaving the two
    # worlds nearly identical.
    shared = sum(
        1
        for a, b in zip(left.dataset.targets, right.dataset.targets)
        if a == b
    )
    assert shared == 0


# -- The label is a complete answer -------------------------------------------------


def test_a_label_carries_what_a_policy_needs_to_interpret_it(
    world: HyperparameterWorld, wide_node: str
) -> None:
    # The score alone is not an answer a policy can *reason* about: "a
    # wider model did worse" and "a wider model was not what I asked for"
    # are different facts, and telling them apart needs the width the fit
    # actually used beside the score.  The training score is there for
    # §14's gap, and the coefficients are what make the world's truth
    # *inspectable* rather than merely reported — the property §10.6
    # states when it calls these worlds ground truth.
    result = world.label(wide_node)
    setting = world.setting(wide_node)
    assert len(result.coefficients) == result.n_columns
    assert result.n_columns == len(
        [
            column
            for column in range(result.n_columns)
        ]
    )  # a width the pipeline can index
    assert setting.interactions is True  # and the wider cells really are wider
    assert result.n_columns > 7  # more than the linear design's intercept + 6


def test_every_cell_of_the_lattice_is_answerable(world: HyperparameterWorld) -> None:
    # Totality on the committed world: nothing in the space refuses at the
    # default ridge.  This is the property feature 188's pool builder
    # relies on when it draws worlds, and the reason the ridge floor
    # exists — with a zero ridge the widest designs would be at the edge
    # of the refusal and a pool's coverage would depend on the seed's luck.
    refusals = [
        (node_id, result)
        for node_id, result in world.label_all()
        if isinstance(result, BootstrapScoringError)
    ]
    assert refusals == []
    assert len(world.cells()) == 60


def test_the_world_reports_the_ridge_its_labels_were_computed_at() -> None:
    # A label is meaningless without the ridge it was fitted at, and the
    # figure is a *constant* rather than a per-call argument: if a caller
    # could pass one, two replays of one world could disagree about a
    # label while both claiming to report the same world's ground truth.
    # The world exposes the value and takes no ridge parameter.
    import inspect

    signature = inspect.signature(HyperparameterWorld.label)
    assert "ridge" not in signature.parameters
    assert DEFAULT_RIDGE > 0.0
