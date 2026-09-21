"""The feature selection world — feature 182's space, support, and objectives.

app_spec.xml feature 182: *System exposes a feature selection world
over labeled machine-learning benchmarks, which returns a ground-truth
objective per node.*  docs/nullius-tech-architecture.md §10.6 names the
domain in its own tree (``featsel/  # feature selection on labeled ML
benchmarks``), and the sentence has three parts this suite holds apart,
because each is a different claim:

* **"a feature selection world"** — a node is a *subset* of the
  benchmark's columns, addressed as a point of a rooted lattice exactly
  the way a hyperparameter setting is in ``test_world.py`` and a
  candidate structure is in ``test_symreg.py``.  The lattice claims are
  the same lattice claims: bounded, connected, one-axis-one-step,
  addressed by a strict codec that round-trips every cell and refuses
  every string its encoder cannot have produced — including the
  hyperparameter and symbolic worlds' own node ids, which are other
  domains' addresses.

* **"over labeled machine-learning benchmarks"** — the benchmark is the
  world's fixed half, generated from its seed, and the sparse linear
  truth its labels were drawn from is *published*
  (:class:`~bootstrap.FeatureSupport`), drawn deterministically from
  the seed or planted by the caller, and a support the lattice cannot
  express is refused rather than scored around: a truth no cell can
  recover would leave the world holding no oracle, and a ground-truth
  world must refuse that one configuration.  The benchmark is auditable
  against the support down to the row, which is what "labeled" buys:
  the noise-free value the noise was hiding is a method call.

* **"returns a ground-truth objective"** — the feature's own word, and
  the label answers it: the fixed model's out-of-sample performance
  over the chosen subset, the held-out ``R²`` of the least-squares fit
  on the subset's columns through the same fit the sibling worlds use,
  a pure function of ``(world, node)``.  And the objective
  *discriminates*: the cell carrying the drawn support clears the
  published evidential bar on every seed of the pool band, the
  subset-less cells are nulls on every seed, and a cell that stops at
  the wrong candidate, misses the decisive column, or stands on the
  proxies alone — the copies, the marginal correlation without the
  conditional relevance — is beaten by the oracle by a margin: pinned
  over the band, the way ``FEATSEL_NOISE_SCALE`` is, not asserted for
  one seed.

The claims asserted are structural, read off the labels themselves
rather than pinned as literal scores: exact numbers are §12's canary's
to hold, and a test that survives an arithmetic refactor which does not
change what the world *is* is the only kind worth keeping here.
"""

from __future__ import annotations

import pytest
from bootstrap import (
    DISCOVERY_BAR,
    FEATSEL_FEATURE_COUNT,
    FEATSEL_ROWS,
    FEATSEL_SEED,
    FEATSEL_WORLD_ID,
    FEATURE_AXES,
    FEATURE_AXIS_ORDER,
    NOISE_TERMS,
    POOL_SEED,
    PROXY_TERMS,
    STRONG_TERMS,
    WEAK_TERMS,
    BootstrapWorldError,
    FeatureAxis,
    FeatureSelectionWorld,
    FeatureSetting,
    FeatureSupport,
    LabeledBenchmark,
    canonical_featsel_node_id,
    decode_featsel_node_id,
    draw_world_seed,
    encode_featsel_node_id,
    featsel_setting_dimensions,
    generate_benchmark,
    support_for_seed,
)

#: The pool band: the pool's own seed plus a band of offsets, then seeds
#: the pool's own draw would author — the sweep ``test_truth.py`` uses,
#: so the two suites sweep the same worlds the pool will hold.
BAND = [POOL_SEED + offset for offset in range(8)]
BAND += [draw_world_seed(POOL_SEED, index) for index in (0, 7, 23, 44)]

_TABLE_OF = {
    FeatureAxis.STRONG: STRONG_TERMS,
    FeatureAxis.WEAK: WEAK_TERMS,
    FeatureAxis.PROXY: PROXY_TERMS,
    FeatureAxis.NOISE: NOISE_TERMS,
}


def _oracle_setting(world: FeatureSelectionWorld) -> FeatureSetting:
    """The cell carrying the drawn support — derived, not named.

    Derived from the published support's own features: the strong level
    that carries the drawn candidate, and the weak level that carries
    the drawn weak block.  The world does not ship an ``oracle_node()``
    for the same reason the sibling worlds do not — the answer key is
    the published truth, and the cell is a fact about it a caller reads
    off, not a second authority beside it.
    """
    features = set(world.support.features)
    return FeatureSetting(
        strong=1 if 0 in features else 2,
        weak=2 if {2, 3} <= features else 1,
        proxy=0,
        noise=0,
    )


def _r2(world: FeatureSelectionWorld, setting: FeatureSetting) -> float:
    return world.label_setting(setting).r2_holdout


# -- The lattice's shape -----------------------------------------------------------


def test_the_axes_are_the_four_structural_choices_in_a_declared_order() -> None:
    # The order is load-bearing for the same reason the hyperparameter
    # lattice's is: it is the order a step vector is spelled in, and
    # therefore the order the node id encodes.  Pinned literally so a
    # reordering cannot pass as a refactor.
    assert featsel_setting_dimensions() == ("strong", "weak", "proxy", "noise")
    assert tuple(axis.value for axis in FEATURE_AXIS_ORDER) == (
        featsel_setting_dimensions()
    )
    # Every axis declares the same shape: nothing, then two selections —
    # which is what makes the strong axis's middle value a wrong answer
    # sitting between two honest ones, and every growth axis's level 2 a
    # widening of its level 1.
    for axis in FEATURE_AXIS_ORDER:
        assert FEATURE_AXES[axis] == (0, 1, 2), axis


def test_the_axis_tables_speak_one_column_vocabulary() -> None:
    # A term is a tuple of feature indices to include, and the four
    # tables are the whole vocabulary: every feature of the benchmark is
    # load-bearing to some axis, and no column is spelled by two axes —
    # within an axis a level may repeat the level below it (the weak
    # block grows by containment), but across axes the vocabularies are
    # disjoint, so a support's term names exactly one axis and the world
    # can derive the oracle cell from the support alone.
    per_axis = {
        axis: {feature for level in table for feature in level}
        for axis, table in _TABLE_OF.items()
    }
    axes = FEATURE_AXIS_ORDER
    for i, axis in enumerate(axes):
        for other in axes[i + 1 :]:
            assert not per_axis[axis] & per_axis[other], (axis, other)
    features = {
        feature for columns in per_axis.values() for feature in columns
    }
    assert features == set(range(FEATSEL_FEATURE_COUNT))
    # The strong axis is a *choice*, not a growth: its two levels are
    # different single columns, neither containing the other, so a walk
    # up the axis that stops at level 1 on a world whose support chose
    # level 2 has added a column and recovered nothing.
    assert not set(STRONG_TERMS[1]) <= set(STRONG_TERMS[2])
    assert not set(STRONG_TERMS[2]) <= set(STRONG_TERMS[1])
    # The growing blocks: level 2 strictly contains level 1.
    assert set(WEAK_TERMS[1]) < set(WEAK_TERMS[2])
    assert set(PROXY_TERMS[1]) < set(PROXY_TERMS[2])
    assert set(NOISE_TERMS[1]) < set(NOISE_TERMS[2])
    # The noise axis owns the columns no drawn truth ever carries.
    assert per_axis[FeatureAxis.NOISE] == {6, 7}


def test_the_canonical_setting_is_the_root_and_addresses_itself(
    featsel_world: FeatureSelectionWorld, featsel_root_node: str
) -> None:
    assert featsel_world.canonical_node() == featsel_root_node == "s+0.w+0.p+0.n+0"
    assert featsel_world.setting(featsel_root_node) == featsel_world.canonical_setting
    assert featsel_world.steps(featsel_root_node) == (0, 0, 0, 0)
    assert featsel_world.depth(featsel_root_node) == 0
    assert featsel_world.canonical_setting.text == "intercept-only"


def test_the_lattice_is_the_product_of_the_declared_levels(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # Eighty-one cells: three levels on each of four axes.  Pinned as a
    # product rather than a literal so the assertion states *why* the
    # count is what it is.
    expected = 1
    for axis in FEATURE_AXIS_ORDER:
        expected *= len(FEATURE_AXES[axis])
    assert len(featsel_world.cells()) == expected == 81
    assert len(set(featsel_world.cells())) == expected  # one address per cell


def test_every_cell_is_reachable_from_the_root_by_legal_moves(
    featsel_world: FeatureSelectionWorld, featsel_root_node: str
) -> None:
    # The property a policy's edge-only walk depends on: nothing in the
    # lattice is an island, and a feature selection search that only
    # ever moves along edges can reach every subset.
    seen = {featsel_root_node}
    frontier = [featsel_root_node]
    while frontier:
        node = frontier.pop()
        for neighbour in featsel_world.legal_moves(node):
            if neighbour not in seen:
                seen.add(neighbour)
                frontier.append(neighbour)
    assert seen == set(featsel_world.cells())


def test_a_move_moves_exactly_one_axis_by_one_position(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # The structural rule §10.6.1's CellMeta describes: a move proposes
    # one block change, not a rewrite — which is what makes depth
    # meaningful and a walk legible as a sequence of tries.
    origin = featsel_world.steps("s+1.w+2.p+1.n+1")
    for move in featsel_world.legal_moves("s+1.w+2.p+1.n+1"):
        step = featsel_world.steps(move)
        difference = [after - before for before, after in zip(origin, step)]
        assert max(abs(delta) for delta in difference) == 1
        assert sum(1 for delta in difference if delta != 0) == 1, move


def test_legal_moves_answers_the_roots_neighbours_without_being_told(
    featsel_world: FeatureSelectionWorld, featsel_root_node: str
) -> None:
    assert featsel_world.legal_moves() == featsel_world.legal_moves(featsel_root_node)
    assert featsel_world.legal_moves(featsel_root_node) == (
        "s+0.w+0.p+0.n+1",
        "s+0.w+0.p+1.n+0",
        "s+0.w+1.p+0.n+0",
        "s+1.w+0.p+0.n+0",
    )


def test_no_cell_is_a_dead_end(featsel_world: FeatureSelectionWorld) -> None:
    # Every axis declares three levels, so even the fully saturated
    # corner still has a step *down* available — a search can walk until
    # its own stopping rule fires, never until the world runs out.
    corner = "s+2.w+2.p+2.n+2"
    assert featsel_world.setting(corner).depth == 8
    assert len(featsel_world.legal_moves(corner)) == 4
    for node_id in featsel_world.cells():
        assert featsel_world.legal_moves(node_id), node_id


def test_legal_roots_is_the_single_declared_root(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # Three domains of one category, one rule: two policies compared on
    # a world begin from the same place (§10.3.1's paired comparison),
    # and a featsel walk starts where every bootstrap walk starts — the
    # root.
    assert featsel_world.legal_roots() == (featsel_world.canonical_node(),)


def test_a_step_past_the_end_of_an_axis_is_refused_by_name(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # ``proxy`` declares three levels, so a +9 step names a subset
    # nobody agreed to score.  The refusal names the axis, so an
    # operator reads *what* overshot.
    with pytest.raises(BootstrapWorldError, match="past the end of the 'proxy' axis"):
        featsel_world.setting("s+0.w+0.p+9.n+0")
    with pytest.raises(BootstrapWorldError, match="past the end of the 'noise' axis"):
        featsel_world.setting("s+0.w+0.p+0.n-1")


def test_a_level_outside_the_lattice_is_refused_at_construction() -> None:
    # The value type refuses too, and *before* a fit: a setting that
    # holds is a subset the world has agreed to score.
    with pytest.raises(BootstrapWorldError, match="not a level of the 'strong' axis"):
        FeatureSetting(strong=7)
    with pytest.raises(BootstrapWorldError, match="is a flag"):
        FeatureSetting(proxy=True)


# -- The address codec -------------------------------------------------------------


def test_the_codec_round_trips_every_cell_of_the_committed_world(
    featsel_world: FeatureSelectionWorld,
) -> None:
    for node_id in featsel_world.cells():
        assert encode_featsel_node_id(decode_featsel_node_id(node_id)) == node_id
        assert featsel_world.node_id(featsel_world.setting(node_id)) == node_id


def test_the_root_encodes_as_the_all_zero_step_vector() -> None:
    assert encode_featsel_node_id((0, 0, 0, 0)) == canonical_featsel_node_id()


def test_a_negative_step_round_trips() -> None:
    # The sign is always written, so the encoding is injective and a
    # step below the root is representable — the codec is a codec, and
    # the lattice bound is the world's.
    assert encode_featsel_node_id((1, -1, 2, 0)) == "s+1.w-1.p+2.n+0"
    assert decode_featsel_node_id("s+1.w-1.p+2.n+0") == (1, -1, 2, 0)


def test_a_malformed_node_id_is_refused_with_what_is_wrong() -> None:
    with pytest.raises(BootstrapWorldError, match="carries 3 field"):
        decode_featsel_node_id("s+0.w+0.p+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_featsel_node_id("x+0.w+0.p+0.n+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_featsel_node_id("s0.w0.p0.n0")
    with pytest.raises(BootstrapWorldError, match="non-numeric magnitude"):
        decode_featsel_node_id("s+0.w+0.p+0.n+x")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_featsel_node_id("")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_featsel_node_id(7)  # type: ignore[arg-type]


def test_another_domains_node_id_is_not_quietly_read_as_a_featsel_one() -> None:
    # The domains share a codec *shape* and nothing else: an hpo id and
    # a symreg id spell four axes the featsel lattice does not declare,
    # and a lenient decode that matched on field count alone would
    # address a cell the policy was never shown.  The first field's
    # initial refuses both.
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_featsel_node_id("d+0.i+0.s+0.a+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_featsel_node_id("l+0.c+0.p+0.s+0")


# -- The setting value type --------------------------------------------------------


def test_settings_that_name_one_point_are_equal_and_hash_alike() -> None:
    left = FeatureSetting(strong=2, weak=1, proxy=1)
    right = FeatureSetting(proxy=1, weak=1, strong=2)
    assert left == right
    assert hash(left) == hash(right)
    assert len({left, right}) == 1


def test_a_setting_is_not_equal_to_a_bare_mapping() -> None:
    assert FeatureSetting() != {"strong": 0}
    assert FeatureSetting() != ()


def test_with_value_moves_one_axis_and_leaves_the_original_alone() -> None:
    original = FeatureSetting(strong=1)
    moved = original.with_value(FeatureAxis.STRONG, 2)
    assert moved.value(FeatureAxis.STRONG) == 2
    assert original.value(FeatureAxis.STRONG) == 1
    assert moved != original


def test_the_columns_are_read_off_the_axis_tables() -> None:
    # The features a level *means* come from the tables, never stored
    # beside the levels, so the setting and the vocabulary cannot drift.
    assert FeatureSetting().features == ()
    assert FeatureSetting(strong=2).features == (1,)
    assert FeatureSetting(weak=2).features == (2, 3)
    assert FeatureSetting(proxy=1).features == (4,)
    assert FeatureSetting(noise=2).features == (6, 7)
    wide = FeatureSetting(strong=2, weak=2, proxy=2, noise=2)
    assert wide.features == (1, 2, 3, 4, 5, 6, 7)
    assert wide.text == "x1 + x2 + x3 + x4 + x5 + x6 + x7"


def test_depth_is_the_sum_of_the_absolute_steps() -> None:
    setting = FeatureSetting(strong=2, weak=1, proxy=2)
    assert setting.steps() == (2, 1, 2, 0)
    assert setting.depth == 5


def test_row_hands_out_the_shape_the_store_wants() -> None:
    row = FeatureSetting(strong=1, proxy=2).row()
    assert row == {"strong": 1, "weak": 0, "proxy": 2, "noise": 0}
    # Round-trips into a setting: the row is the constructor's keywords.
    assert FeatureSetting(**row) == FeatureSetting(strong=1, proxy=2)
    assert row is not FeatureSetting().row()  # a fresh dict per call


# -- The published support ---------------------------------------------------------


def test_the_world_publishes_the_support_its_seed_draws(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # The "known" of the category: the truth is a property on the world,
    # not a fact about its construction a caller has to reconstruct.
    # The draw is a pure function of the seed.
    assert featsel_world.support == support_for_seed(FEATSEL_SEED)
    assert featsel_world.support.terms  # at least one term, always


def test_the_drawn_supports_form_a_family_not_one_truth() -> None:
    # "Benchmarks", plural: across the pool band the seeds draw
    # different candidates, weak widths and sign patterns — a pool of
    # worlds is a family of supports, every one built from the lattice's
    # own tables and none of them the proxy or noise axes' columns.
    texts = {support_for_seed(seed).text for seed in BAND}
    assert len(texts) > 1
    for seed in BAND:
        support = support_for_seed(seed)
        features = set(support.features)
        # The decisive column, always: the drawn strong level never
        # chooses the empty 0, so the oracle is a real cell of every
        # world — and it is exactly one of the two candidates, the
        # choice that makes the axis's middle value a wrong one.
        assert len(features & {0, 1}) == 1, (seed, features)
        # The weak block, always entered: at least x2, never level 0.
        assert 2 in features, (seed, features)
        # And never a proxy or a distractor: those axes are pure width,
        # the directions a subset grows away from or beside the truth.
        assert not features & {4, 5, 6, 7}, (seed, features)
        # The decisive weight dominates the weak ones: finding it is the
        # discovery, the rest is refinement.
        weights = sorted(abs(weight) for _, weight in support.terms)
        assert weights[-1] > 2 * weights[0]


def test_a_support_is_equal_by_its_terms_as_a_set() -> None:
    # Sorted into a canonical order at construction: two spellings of
    # one truth are one support, whatever order built them.
    left = FeatureSupport(intercept=1.0, terms=((0, 2.8), (2, 0.5)))
    right = FeatureSupport(intercept=1.0, terms=((2, 0.5), (0, 2.8)))
    assert left == right
    assert left.text == right.text == "1 + 2.8*x0 + 0.5*x2"


def test_a_planted_support_is_scored_against_and_kept_whole() -> None:
    # The other half of "known": a caller that wants a *specific*
    # support plants it, and the world's labels answer to it — the
    # truth a policy's commits are audited against is the one the
    # caller named.
    planted = FeatureSupport(intercept=1.0, terms=((2, 0.4), (1, -2.0)))
    world = FeatureSelectionWorld("bootstrap-featsel-planted", support=planted)
    assert world.support is planted
    # The text renders in the canonical term order the support sorts its
    # terms into, not the order they were planted in.
    assert world.support.text == "1 - 2*x1 + 0.4*x2"
    # The planted world's benchmark is generated from its own seed
    # against the planted truth: the audit below reads the planted
    # expression.
    benchmark = world.benchmark
    assert benchmark.truth_for(0) == planted.evaluate(benchmark.features[0])


def test_a_support_the_lattice_cannot_express_is_refused() -> None:
    # A truth no cell can recover would leave the world holding no
    # oracle, and the answer key pointing outside its own space — the
    # one configuration a ground-truth world must refuse rather than
    # score around.  The vocabulary spans all eight columns, so what is
    # inexpressible is a *combination*: the strong axis is a choice, and
    # a support asking for both candidates names two levels of one axis
    # no single cell can hold.  Each refusal names what is inexpressible.
    with pytest.raises(
        BootstrapWorldError, match="cannot carry 'x0, x1' together on its 'strong' axis"
    ):
        FeatureSupport(intercept=0.0, terms=((0, 1.0), (1, 2.0)))


def test_a_support_naming_no_column_of_the_benchmark_is_refused() -> None:
    # The vocabulary is the benchmark's own eight columns; an index
    # outside them names no column of any benchmark this world holds.
    with pytest.raises(
        BootstrapWorldError, match="names a feature of this world's benchmark"
    ):
        FeatureSupport(intercept=0.0, terms=((8, 1.0),))


def test_an_incoherent_support_is_refused() -> None:
    # The value type's own edges: no structure to find, weights that
    # name nothing, one term spelled twice, an index that is not one,
    # and constants that are not numbers — each refused, naming what
    # was wrong, rather than defaulted into a truth nobody named.
    good = ((0, 0.5),)
    with pytest.raises(BootstrapWorldError, match="at least one term"):
        FeatureSupport(intercept=0.0, terms=())
    with pytest.raises(BootstrapWorldError, match="weight 0"):
        FeatureSupport(intercept=0.0, terms=((0, 0.0),))
    with pytest.raises(BootstrapWorldError, match="twice"):
        FeatureSupport(intercept=0.0, terms=((0, 0.5), (0, 0.6)))
    with pytest.raises(BootstrapWorldError, match="names its features by index"):
        FeatureSupport(intercept=0.0, terms=((True, 0.5),))
    with pytest.raises(BootstrapWorldError, match="intercept is a real constant"):
        FeatureSupport(intercept=True, terms=good)
    with pytest.raises(BootstrapWorldError, match="intercept is a finite constant"):
        FeatureSupport(intercept=float("nan"), terms=good)
    with pytest.raises(BootstrapWorldError, match="finite coefficient"):
        FeatureSupport(intercept=0.0, terms=((0, float("inf")),))
    with pytest.raises(BootstrapWorldError, match="real coefficient"):
        FeatureSupport(intercept=0.0, terms=((0, "big"),))  # type: ignore[arg-type]


def test_a_world_refuses_a_support_that_is_not_one() -> None:
    with pytest.raises(BootstrapWorldError, match="scored against a FeatureSupport"):
        FeatureSelectionWorld("w", support=((0,), 1.0))  # type: ignore[arg-type]


# -- The fixed benchmark -----------------------------------------------------------


def test_the_benchmark_is_fixed_and_auditable_against_the_support(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # The benchmark is the world's *fixed* half: its shape is a property
    # of the domain, and its labels are the known truth plus noise — the
    # audit being the noise-free value at the row's own features.
    benchmark = featsel_world.benchmark
    assert isinstance(benchmark, LabeledBenchmark)
    assert benchmark.rows == FEATSEL_ROWS
    assert all(len(row) == FEATSEL_FEATURE_COUNT for row in benchmark.features)
    assert benchmark.support is featsel_world.support
    assert benchmark.seed == FEATSEL_SEED
    for row in (0, 1, FEATSEL_ROWS // 2, FEATSEL_ROWS - 1):
        assert benchmark.truth_for(row) == featsel_world.support.evaluate(
            benchmark.features[row]
        )


def test_generation_is_a_pure_function_of_seed_and_support() -> None:
    # Same seed and support, same benchmark to the last bit — in any
    # process and any order of calls.  Two world objects of one identity
    # answer one benchmark; a changed seed answers a different one,
    # because the seed names the rows the support labels.
    support = support_for_seed(FEATSEL_SEED)
    left = generate_benchmark(FEATSEL_SEED, support=support)
    right = generate_benchmark(FEATSEL_SEED, support=support)
    assert left.features == right.features
    assert left.labels == right.labels
    other = generate_benchmark(FEATSEL_SEED + 1, support=support)
    assert other.features != left.features
    assert other.labels != left.labels


def test_the_proxies_correlate_with_the_candidates_they_copy(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # The axis the domain exists to teach, verified on the drawn rows:
    # x4 is a correlation-PROXY_CORRELATION copy of x0 and x5 of x1 —
    # unit variance marginally, correlated with the label only through
    # the candidate each copies, and uncorrelated with the *other*
    # candidate.  A subset that ranks columns by marginal association
    # is told by that ranking to spend its width on the copies.
    from bootstrap import PROXY_CORRELATION

    benchmark = featsel_world.benchmark
    n = benchmark.rows

    def covariance(left: int, right: int) -> float:
        xs = [benchmark.feature(row, left) for row in range(n)]
        ys = [benchmark.feature(row, right) for row in range(n)]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n

    for proxy, candidate, other in ((4, 0, 1), (5, 1, 0)):
        variance = covariance(proxy, proxy)
        assert abs(variance - 1.0) < 0.2, (proxy, variance)  # marginal standard
        correlation = covariance(proxy, candidate) / variance
        assert abs(correlation - PROXY_CORRELATION) < 0.15, (proxy, correlation)
        assert abs(covariance(proxy, other)) < 0.15, (proxy, other)


def test_the_benchmark_is_generated_once_and_held(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # Lazy on first use, held after: a pool holds many worlds and pays
    # for a benchmark only when a label is asked of it — and the label
    # then answers from the same numbers every time.
    assert featsel_world.benchmark is featsel_world.benchmark


# -- The objective -----------------------------------------------------------------


def test_the_label_is_a_pure_function_of_world_and_node(
    featsel_world: FeatureSelectionWorld,
) -> None:
    oracle = featsel_world.node_id(_oracle_setting(featsel_world))
    first = featsel_world.label(oracle)
    second = featsel_world.label(oracle)
    assert (first.coefficients, first.r2_train, first.r2_holdout) == (
        second.coefficients,
        second.r2_train,
        second.r2_holdout,
    )
    # Interleaving another cell's label changes nothing, and neither does
    # a fresh world of the same identity: the objective is a fact about
    # the subset, not about the path that reached it or the object asked.
    featsel_world.label(featsel_world.canonical_node())
    third = featsel_world.label(oracle)
    assert third.r2_holdout == first.r2_holdout
    twin = FeatureSelectionWorld(FEATSEL_WORLD_ID, seed=FEATSEL_SEED)
    assert twin.label(oracle).coefficients == first.coefficients


def test_label_all_covers_the_lattice_in_the_worlds_own_order(
    featsel_world: FeatureSelectionWorld,
) -> None:
    swept = dict(featsel_world.label_all())
    assert list(swept) == list(featsel_world.cells())
    for node_id, fit in swept.items():
        assert not isinstance(fit, Exception), node_id
        assert fit is featsel_world.label(node_id) or (
            fit.coefficients == featsel_world.label(node_id).coefficients
        )


def test_label_refuses_a_missing_address_and_an_out_of_lattice_one(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # The root is a node like any other, asked for by name: a defaulted
    # argument would let a missing one answer the same objective as a
    # deliberate root ask.
    with pytest.raises(BootstrapWorldError, match="needs the node id to label"):
        featsel_world.label("")
    with pytest.raises(BootstrapWorldError, match="past the end of the 'weak' axis"):
        featsel_world.label("s+0.w+3.p+0.n+0")


def test_node_id_refuses_something_that_is_not_a_setting(
    featsel_world: FeatureSelectionWorld,
) -> None:
    with pytest.raises(BootstrapWorldError, match="addresses a FeatureSetting"):
        featsel_world.node_id("s+0.w+0.p+0.n+0")  # type: ignore[arg-type]


def test_a_world_id_is_required_and_a_seed_is_an_integer() -> None:
    # The id is how an objective is attributed to a pool entry; the seed
    # names the benchmark the support labels — neither can be defaulted
    # into something unnameable.
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        FeatureSelectionWorld("")
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        FeatureSelectionWorld("   ")
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        FeatureSelectionWorld("w", seed=1.5)  # type: ignore[arg-type]
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        FeatureSelectionWorld("w", seed=True)


def test_the_world_declares_the_featsel_family_and_domain_values(
    featsel_world: FeatureSelectionWorld,
) -> None:
    # §11.1's family conditioning reads theme_root off the meta; the
    # domain value is what a later pool authoring seats under the
    # ``domain`` column the bootstrap world table already carries.
    from bootstrap import FEATSEL_DOMAIN, FEATSEL_THEME_ROOT

    assert featsel_world.theme_root == FEATSEL_THEME_ROOT == "featsel"
    assert FEATSEL_DOMAIN == "featsel"


# -- The objective discriminates ---------------------------------------------------


def test_the_oracle_cell_clears_the_bar_on_every_seed_of_the_band() -> None:
    # The feature's headline read structurally: the subset carrying the
    # drawn support *recovers* it — held-out R² clears the published
    # evidential bar with margin, on every world the pool band would
    # author, not just the committed one.  The oracle cell is derived
    # from each world's own published support, so this is a claim about
    # the world's honesty, not about one lucky seed.
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        oracle = world.node_id(_oracle_setting(world))
        score = world.label(oracle).r2_holdout
        assert score >= DISCOVERY_BAR, (seed, score)
        assert score >= DISCOVERY_BAR + 0.2, (seed, score)


def test_the_decisive_column_alone_is_already_a_discovery_on_the_band() -> None:
    # The strong weight dominates by design, and the design's payoff is
    # this: finding the decisive column alone — nothing else in the
    # subset — clears the bar on every seed of the band.  Feature
    # selection's honest shape is a problem where finding the decisive
    # column is the discovery and everything else is refinement, and a
    # world where the discovery needed the whole oracle cell would not
    # have that shape.
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        features = set(world.support.features)
        strong_only = FeatureSetting(strong=1 if 0 in features else 2)
        score = world.label_setting(strong_only).r2_holdout
        assert score >= DISCOVERY_BAR, (seed, score)


def test_the_subset_less_cells_are_nulls_on_every_seed_of_the_band() -> None:
    # The other side of discrimination: a subset carrying no column of
    # the truth — the root, and the weak block alone, which explains a
    # fraction of the label's variance far below the bar — is a null on
    # every seed.  A world whose empty cells scored as discoveries would
    # be calibrating against noise.
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        root = world.label(world.canonical_node()).r2_holdout
        assert root < DISCOVERY_BAR, (seed, root)
        features = set(world.support.features)
        weak_only = FeatureSetting(weak=2 if {2, 3} <= features else 1)
        partial = world.label_setting(weak_only).r2_holdout
        assert partial < DISCOVERY_BAR, (seed, partial)


def test_the_wrong_candidate_recovers_less_than_the_truth_does() -> None:
    # The honest shape of feature selection as a search problem: the
    # strong axis carries a *wrong* middle value — a real column of the
    # benchmark, spelled in the vocabulary, that this world's support
    # did not choose — and a policy that stops at the first thing that
    # sounds like progress lands on it.  The oracle beats that cell by a
    # wide margin on every seed of the band: swapping the unchosen
    # candidate in beside the drawn weak block added a column and
    # recovered a fraction of what the decisive column recovers.  Where
    # the wrong-candidate cell sits relative to the bar is deliberately
    # not pinned — the unchosen candidate is pure noise beside the
    # label, so the cell is a null with the weak block's shape.
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        wrong = [level for level in (1, 2) if level != oracle_setting.value(FeatureAxis.STRONG)]
        for level in wrong:
            score = world.label_setting(
                oracle_setting.with_value(FeatureAxis.STRONG, level)
            )
            assert oracle - score.r2_holdout >= 0.1, (seed, level)


def test_a_cell_missing_the_decisive_column_is_beaten_by_the_oracle() -> None:
    # Missing the strong column costs nearly the whole recovered
    # variance: the oracle beats the weak-block-alone cell by a margin
    # on every seed.  (The weak axis is deliberately *not* asserted this
    # way — it is refinement, a fraction of a fraction, and pinning a
    # margin on it would be pinning the world's noise.)
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        missing = world.label_setting(oracle_setting.with_value(FeatureAxis.STRONG, 0))
        assert oracle - missing.r2_holdout >= 0.1, seed


def test_the_proxies_cannot_stand_in_for_the_feature_they_copy() -> None:
    # The axis the domain exists to teach, scored: a subset standing on
    # both copies — carrying the weak block and the proxy pair, but not
    # the decisive column — is beaten by the oracle by a margin on every
    # seed of the band.  The copies carry a quarter of the candidate's
    # variance each, which is enough to look like a lead on the training
    # split and not enough to stand in for the feature being copied.
    # Where the proxy cell sits *relative to the bar* is deliberately
    # not pinned: it straddles it from seed to seed, which is the
    # contentful case for calibration (the boundary follows the world's
    # drawn coefficients, not a constant of the domain).
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        proxies = world.label_setting(
            oracle_setting.with_value(FeatureAxis.STRONG, 0).with_value(
                FeatureAxis.PROXY, 2
            )
        )
        assert oracle - proxies.r2_holdout >= 0.1, seed


def test_the_noise_axis_is_the_quiet_one() -> None:
    # Columns no truth carries, priced: the widest distractor level
    # moves a cell's held-out score by less than a tenth either way —
    # quiet, the way the hyperparameter world's ``standardize`` axis and
    # the symbolic world's ``spurious`` axis are, because a lattice
    # where every axis paid equally would be a lattice where search
    # policy does not matter.  The margin this *doesn't* hide: noise
    # width cannot carry a subset-less cell over the bar.
    for seed in BAND:
        world = FeatureSelectionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        widened = world.label_setting(
            oracle_setting.with_value(FeatureAxis.NOISE, 2)
        ).r2_holdout
        assert abs(oracle - widened) < 0.1, (seed, oracle, widened)
        root_widened = world.label_setting(
            world.canonical_setting.with_value(FeatureAxis.NOISE, 2)
        ).r2_holdout
        assert root_widened < DISCOVERY_BAR, seed


def test_two_worlds_of_one_lattice_are_still_two_worlds() -> None:
    # §10.6.1's provenance rule from the authored side: the lattice is a
    # property of the domain, so two worlds agree on their cells, and
    # the *support* and benchmark are properties of the seed, so they
    # disagree on their labels — two pool entries, not two names for one
    # world.
    left = FeatureSelectionWorld(FEATSEL_WORLD_ID, seed=FEATSEL_SEED)
    right = FeatureSelectionWorld("bootstrap-featsel-other", seed=FEATSEL_SEED + 1)
    assert left.cells() == right.cells()
    assert left.world_id != right.world_id
    assert left.benchmark.features != right.benchmark.features
