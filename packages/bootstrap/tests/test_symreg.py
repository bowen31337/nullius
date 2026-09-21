"""The symbolic regression world — feature 183's space, target, and labels.

app_spec.xml feature 183: *System exposes a symbolic regression world,
which returns a ground-truth score against known target expressions.*
docs/nullius-tech-architecture.md §10.6 names the domain in its own tree
(``symreg/  # symbolic regression against known target expressions``),
and the sentence has three parts this suite holds apart, because each is
a different claim:

* **"a symbolic regression world"** — a node is a candidate *expression
  structure*, a small sum of monomials, addressed as a point of a rooted
  lattice exactly the way a hyperparameter setting is in
  ``test_world.py``.  The lattice claims are the same lattice claims:
  bounded, connected, one-axis-one-step, addressed by a strict codec
  that round-trips every cell and refuses every string its encoder
  cannot have produced — including the hyperparameter world's own node
  ids, which are a different domain's addresses.

* **"known target expressions"** — the truth is *published*
  (:class:`~bootstrap.TargetExpression`), drawn deterministically from
  the world's seed or planted by the caller, and a target the lattice
  cannot express is refused rather than scored around: a truth no cell
  can recover would leave the world holding no oracle, and a
  ground-truth world must refuse that one configuration.  The dataset is
  auditable against the target down to the row, which is what "known"
  buys: the noise-free value the noise was hiding is a method call.

* **"returns a ground-truth score"** — the label is the structure
  completed by least squares and scored by held-out ``R²`` through the
  same fit the hyperparameter world uses, a pure function of
  ``(world, node)``.  And the score *discriminates*: the cell carrying
  the target's whole structure clears the published evidential bar on
  every seed of the pool band, the structure-less cells are nulls on
  every seed, and a cell that stops at a wrong middle value or misses a
  load-bearing term is beaten by the oracle by a margin — pinned over
  the band, the way ``NOISE_SCALE`` is, not asserted for one seed.

The claims asserted are structural, read off the labels themselves
rather than pinned as literal scores: exact numbers are §12's canary's
to hold, and a test that survives an arithmetic refactor which does not
change what the world *is* is the only kind worth keeping here.
"""

from __future__ import annotations

import pytest
from bootstrap import (
    CURVATURE_TERMS,
    DISCOVERY_BAR,
    LINEAR_TERMS,
    POOL_SEED,
    PRODUCT_TERMS,
    SPURIOUS_TERMS,
    SYMBOLIC_AXES,
    SYMBOLIC_AXIS_ORDER,
    SYMREG_FEATURE_COUNT,
    SYMREG_ROWS,
    SYMREG_SEED,
    SYMREG_WORLD_ID,
    BootstrapWorldError,
    ExpressionSetting,
    SymbolicAxis,
    SymbolicDataset,
    SymbolicRegressionWorld,
    TargetExpression,
    canonical_symbolic_node_id,
    decode_symbolic_node_id,
    draw_world_seed,
    encode_symbolic_node_id,
    generate_symbolic_dataset,
    symbolic_setting_dimensions,
    target_for_seed,
)

#: The pool band: the pool's own seed plus a band of offsets, then seeds
#: the pool's own draw would author — the sweep ``test_truth.py`` uses,
#: so the two suites sweep the same worlds the pool will hold.
BAND = [POOL_SEED + offset for offset in range(8)]
BAND += [draw_world_seed(POOL_SEED, index) for index in (0, 7, 23, 44)]


def _oracle_setting(world: SymbolicRegressionWorld) -> ExpressionSetting:
    """The cell carrying the target's whole structure — derived, not named.

    Derived from the published target's own terms: for each axis, the
    level that carries the target's monomial.  The world does not ship
    an ``oracle_node()`` for the same reason the hyperparameter world
    does not — the answer key is the published model, and the cell is a
    fact about it a caller reads off, not a second authority beside it.
    """
    levels: dict[str, int] = {}
    for monomial, _ in world.target.terms:
        for axis in SYMBOLIC_AXIS_ORDER:
            for level, terms in enumerate(_TABLE_OF[axis]):
                if monomial in terms:
                    levels[axis.value] = max(levels.get(axis.value, 0), level)
    return ExpressionSetting(**levels)


_TABLE_OF = {
    SymbolicAxis.LINEAR: LINEAR_TERMS,
    SymbolicAxis.CURVATURE: CURVATURE_TERMS,
    SymbolicAxis.PRODUCT: PRODUCT_TERMS,
    SymbolicAxis.SPURIOUS: SPURIOUS_TERMS,
}


def _r2(world: SymbolicRegressionWorld, setting: ExpressionSetting) -> float:
    return world.label_setting(setting).r2_holdout


# -- The lattice's shape -----------------------------------------------------------


def test_the_axes_are_the_four_structural_choices_in_a_declared_order() -> None:
    # The order is load-bearing for the same reason the hyperparameter
    # lattice's is: it is the order a step vector is spelled in, and
    # therefore the order the node id encodes.  Pinned literally so a
    # reordering cannot pass as a refactor.
    assert symbolic_setting_dimensions() == ("linear", "curvature", "product", "spurious")
    assert tuple(axis.value for axis in SYMBOLIC_AXIS_ORDER) == (
        symbolic_setting_dimensions()
    )
    # Every axis declares the same shape: nothing, then two structural
    # choices — which is what makes each axis's middle value a wrong
    # answer sitting between two honest ones.
    for axis in SYMBOLIC_AXIS_ORDER:
        assert SYMBOLIC_AXES[axis] == (0, 1, 2), axis


def test_the_axis_tables_speak_one_monomial_vocabulary() -> None:
    # A term is a tuple of feature indices to multiply, and the four
    # tables are the whole vocabulary: every feature of the dataset is
    # load-bearing to some axis, and no monomial is spelled by two axes
    # — within an axis a level may repeat the level below it (the linear
    # block grows by containment), but across axes the vocabularies are
    # disjoint, so a target's term names exactly one axis and the world
    # can derive the oracle cell from the target alone.
    per_axis = {
        axis: {monomial for level in table for monomial in level}
        for axis, table in _TABLE_OF.items()
    }
    axes = SYMBOLIC_AXIS_ORDER
    for i, axis in enumerate(axes):
        for other in axes[i + 1 :]:
            assert not per_axis[axis] & per_axis[other], (axis, other)
    features = {
        feature for monomials in per_axis.values() for monomial in monomials
        for feature in monomial
    }
    assert features == set(range(SYMREG_FEATURE_COUNT))
    # The spurious axis owns the one feature no truth ever carries.
    assert per_axis[SymbolicAxis.SPURIOUS] == {(5,), (5, 5)}
    # The growing linear block: level 2 strictly contains level 1.
    assert set(LINEAR_TERMS[1]) < set(LINEAR_TERMS[2])


def test_the_canonical_setting_is_the_root_and_addresses_itself(
    symreg_world: SymbolicRegressionWorld, symreg_root_node: str
) -> None:
    assert symreg_world.canonical_node() == symreg_root_node == "l+0.c+0.p+0.s+0"
    assert symreg_world.setting(symreg_root_node) == symreg_world.canonical_setting
    assert symreg_world.steps(symreg_root_node) == (0, 0, 0, 0)
    assert symreg_world.depth(symreg_root_node) == 0
    assert symreg_world.canonical_setting.text == "intercept-only"


def test_the_lattice_is_the_product_of_the_declared_levels(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # Eighty-one cells: three levels on each of four axes.  Pinned as a
    # product rather than a literal so the assertion states *why* the
    # count is what it is.
    expected = 1
    for axis in SYMBOLIC_AXIS_ORDER:
        expected *= len(SYMBOLIC_AXES[axis])
    assert len(symreg_world.cells()) == expected == 81
    assert len(set(symreg_world.cells())) == expected  # one address per cell


def test_every_cell_is_reachable_from_the_root_by_legal_moves(
    symreg_world: SymbolicRegressionWorld, symreg_root_node: str
) -> None:
    # The property a policy's edge-only walk depends on: nothing in the
    # lattice is an island, and a symbolic search that only ever moves
    # along edges can reach every structure.
    seen = {symreg_root_node}
    frontier = [symreg_root_node]
    while frontier:
        node = frontier.pop()
        for neighbour in symreg_world.legal_moves(node):
            if neighbour not in seen:
                seen.add(neighbour)
                frontier.append(neighbour)
    assert seen == set(symreg_world.cells())


def test_a_move_moves_exactly_one_axis_by_one_position(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # The structural rule §10.6.1's CellMeta describes: a move proposes
    # one structural change, not a rewrite — which is what makes depth
    # meaningful and a walk legible as a sequence of tries.
    origin = symreg_world.steps("l+1.c+2.p+1.s+1")
    for move in symreg_world.legal_moves("l+1.c+2.p+1.s+1"):
        step = symreg_world.steps(move)
        difference = [after - before for before, after in zip(origin, step)]
        assert max(abs(delta) for delta in difference) == 1
        assert sum(1 for delta in difference if delta != 0) == 1, move


def test_legal_moves_answers_the_roots_neighbours_without_being_told(
    symreg_world: SymbolicRegressionWorld, symreg_root_node: str
) -> None:
    assert symreg_world.legal_moves() == symreg_world.legal_moves(symreg_root_node)
    assert symreg_world.legal_moves(symreg_root_node) == (
        "l+0.c+0.p+0.s+1",
        "l+0.c+0.p+1.s+0",
        "l+0.c+1.p+0.s+0",
        "l+1.c+0.p+0.s+0",
    )


def test_no_cell_is_a_dead_end(symreg_world: SymbolicRegressionWorld) -> None:
    # Every axis declares three levels, so even the fully saturated
    # corner still has a step *down* available — a search can walk until
    # its own stopping rule fires, never until the world runs out.
    corner = "l+2.c+2.p+2.s+2"
    assert symreg_world.setting(corner).depth == 8
    assert len(symreg_world.legal_moves(corner)) == 4
    for node_id in symreg_world.cells():
        assert symreg_world.legal_moves(node_id), node_id


def test_legal_roots_is_the_single_declared_root(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # Two domains of one category, one rule: two policies compared on a
    # world begin from the same place (§10.3.1's paired comparison), and
    # a symreg walk starts where every bootstrap walk starts — the root.
    assert symreg_world.legal_roots() == (symreg_world.canonical_node(),)


def test_a_step_past_the_end_of_an_axis_is_refused_by_name(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # ``curvature`` declares three levels, so a +9 step names a term
    # nobody agreed to score.  The refusal names the axis, so an
    # operator reads *what* overshot.
    with pytest.raises(BootstrapWorldError, match="past the end of the 'curvature' axis"):
        symreg_world.setting("l+0.c+9.p+0.s+0")
    with pytest.raises(BootstrapWorldError, match="past the end of the 'spurious' axis"):
        symreg_world.setting("l+0.c+0.p+0.s-1")


def test_a_level_outside_the_lattice_is_refused_at_construction() -> None:
    # The value type refuses too, and *before* a fit: a setting that
    # holds is a structure the world has agreed to score.
    with pytest.raises(BootstrapWorldError, match="not a level of the 'linear' axis"):
        ExpressionSetting(linear=7)
    with pytest.raises(BootstrapWorldError, match="is a flag"):
        ExpressionSetting(linear=True)


# -- The address codec -------------------------------------------------------------


def test_the_codec_round_trips_every_cell_of_the_committed_world(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    for node_id in symreg_world.cells():
        assert encode_symbolic_node_id(decode_symbolic_node_id(node_id)) == node_id
        assert symreg_world.node_id(symreg_world.setting(node_id)) == node_id


def test_the_root_encodes_as_the_all_zero_step_vector() -> None:
    assert encode_symbolic_node_id((0, 0, 0, 0)) == canonical_symbolic_node_id()


def test_a_negative_step_round_trips() -> None:
    # The sign is always written, so the encoding is injective and a
    # step below the root is representable — the codec is a codec, and
    # the lattice bound is the world's.
    assert encode_symbolic_node_id((1, -1, 2, 0)) == "l+1.c-1.p+2.s+0"
    assert decode_symbolic_node_id("l+1.c-1.p+2.s+0") == (1, -1, 2, 0)


def test_a_malformed_node_id_is_refused_with_what_is_wrong() -> None:
    with pytest.raises(BootstrapWorldError, match="carries 3 field"):
        decode_symbolic_node_id("l+0.c+0.p+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_symbolic_node_id("x+0.c+0.p+0.s+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_symbolic_node_id("l0.c0.p0.s0")
    with pytest.raises(BootstrapWorldError, match="non-numeric magnitude"):
        decode_symbolic_node_id("l+0.c+0.p+0.s+x")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_symbolic_node_id("")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_symbolic_node_id(7)  # type: ignore[arg-type]


def test_a_hyperparameter_node_id_is_not_quietly_read_as_a_symreg_one() -> None:
    # The two domains share a codec *shape* and nothing else: an hpo id
    # spells four axes the symreg lattice does not declare, and a lenient
    # decode that matched on field count alone would address a cell the
    # policy was never shown.  The first field's initial refuses it.
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_symbolic_node_id("d+0.i+0.s+0.a+0")


# -- The setting value type --------------------------------------------------------


def test_settings_that_name_one_point_are_equal_and_hash_alike() -> None:
    left = ExpressionSetting(linear=2, curvature=1, product=1)
    right = ExpressionSetting(product=1, curvature=1, linear=2)
    assert left == right
    assert hash(left) == hash(right)
    assert len({left, right}) == 1


def test_a_setting_is_not_equal_to_a_bare_mapping() -> None:
    assert ExpressionSetting() != {"linear": 0}
    assert ExpressionSetting() != ()


def test_with_value_moves_one_axis_and_leaves_the_original_alone() -> None:
    original = ExpressionSetting(linear=1)
    moved = original.with_value(SymbolicAxis.LINEAR, 2)
    assert moved.value(SymbolicAxis.LINEAR) == 2
    assert original.value(SymbolicAxis.LINEAR) == 1
    assert moved != original


def test_the_monomials_are_read_off_the_axis_tables() -> None:
    # The terms a level *means* come from the tables, never stored beside
    # the levels, so the setting and the vocabulary cannot drift.
    assert ExpressionSetting().monomials == ()
    assert ExpressionSetting(linear=2).monomials == ((0,), (1,))
    assert ExpressionSetting(curvature=1).monomials == ((2, 2),)
    assert ExpressionSetting(product=2).monomials == ((2, 3),)
    assert ExpressionSetting(spurious=2).monomials == ((5,), (5, 5))
    wide = ExpressionSetting(linear=2, curvature=2, product=2, spurious=2)
    assert wide.monomials == ((0,), (1,), (4, 4), (2, 3), (5,), (5, 5))
    assert wide.text == "x0 + x1 + x4^2 + x2*x3 + x5 + x5^2"


def test_depth_is_the_sum_of_the_absolute_steps() -> None:
    setting = ExpressionSetting(linear=2, curvature=1, product=2)
    assert setting.steps() == (2, 1, 2, 0)
    assert setting.depth == 5


def test_row_hands_out_the_shape_the_store_wants() -> None:
    row = ExpressionSetting(linear=1, product=2).row()
    assert row == {"linear": 1, "curvature": 0, "product": 2, "spurious": 0}
    # Round-trips into a setting: the row is the constructor's keywords.
    assert ExpressionSetting(**row) == ExpressionSetting(linear=1, product=2)
    assert row is not ExpressionSetting().row()  # a fresh dict per call


# -- The known target --------------------------------------------------------------


def test_the_world_publishes_the_target_its_seed_draws(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # The "known" of the feature's own sentence: the truth is a property
    # on the world, not a fact about its construction a caller has to
    # reconstruct.  The draw is a pure function of the seed.
    assert symreg_world.target == target_for_seed(SYMREG_SEED)
    assert symreg_world.target.terms  # at least one term, always


def test_the_drawn_targets_form_a_family_not_one_expression() -> None:
    # "Expressions", plural: across the pool band the seeds draw
    # different squares, pairs and sign patterns — a pool of worlds is a
    # family of targets, every one built from the lattice's tables and
    # none of them the spurious axis's terms.
    texts = {target_for_seed(seed).text for seed in BAND}
    assert len(texts) > 1
    for seed in BAND:
        target = target_for_seed(seed)
        # Both load-bearing terms, always: the drawn levels never choose
        # the empty 0, so the oracle is a real cell of every world.
        monomials = {monomial for monomial, _ in target.terms}
        assert any(len(monomial) == 2 for monomial in monomials)
        # And never a spurious term: the axis is pure width, the
        # direction a candidate grows away from the truth.
        assert all(5 not in monomial for monomial in monomials)
        # Every drawn target carries a linear term or not per its own
        # level, but the structural axes always carry theirs.
        assert len(target.terms) >= 3


def test_a_target_is_equal_by_its_terms_as_a_set() -> None:
    # Sorted into a canonical order at construction: two spellings of
    # one expression are one target, whatever order built them.
    left = TargetExpression(
        intercept=1.0, terms=(((0,), 0.5), ((2, 2), 1.8), ((2, 3), 2.6))
    )
    right = TargetExpression(
        intercept=1.0, terms=(((2, 3), 2.6), ((2, 2), 1.8), ((0,), 0.5))
    )
    assert left == right
    assert left.text == right.text == "1 + 0.5*x0 + 1.8*x2^2 + 2.6*x2*x3"


def test_a_planted_target_is_scored_against_and_kept_whole() -> None:
    # The other half of "known": a caller that wants a *specific*
    # expression plants it, and the world's labels answer to it — the
    # target a policy is scored against is the one the caller named.
    planted = TargetExpression(
        intercept=1.0, terms=(((0,), 0.5), ((4, 4), 1.8), ((0, 1), 2.6))
    )
    world = SymbolicRegressionWorld("bootstrap-symreg-planted", target=planted)
    assert world.target is planted
    # The text renders in the canonical term order the target sorts its
    # terms into, not the order they were planted in.
    assert world.target.text == "1 + 0.5*x0 + 2.6*x0*x1 + 1.8*x4^2"
    # The planted world's dataset is priced from its own seed against
    # the planted truth: the audit below reads the planted expression.
    dataset = world.dataset
    assert dataset.truth_for(0) == planted.evaluate(dataset.features[0])


def test_a_target_the_lattice_cannot_express_is_refused() -> None:
    # A truth no cell can recover would leave the world holding no
    # oracle, and the answer key pointing outside its own space — the
    # one configuration a ground-truth world must refuse rather than
    # score around.  Each refusal names what is inexpressible.
    with pytest.raises(BootstrapWorldError, match="cannot express the term 'x3'"):
        TargetExpression(intercept=0.0, terms=(((3,), 1.0),))
    # ``match`` is a regex and ``^`` anchors, so the carets are escaped.
    with pytest.raises(BootstrapWorldError, match=r"cannot carry 'x2\^2, x4\^2'"):
        TargetExpression(
            intercept=0.0, terms=(((2, 2), 1.0), ((4, 4), 1.0))
        )


def test_an_incoherent_target_is_refused() -> None:
    # The value type's own edges: no structure to find, weights that
    # name nothing, one term spelled twice, a monomial that is not one,
    # and constants that are not numbers — each refused, naming what
    # was wrong, rather than defaulted into a target nobody named.
    good = (((0,), 0.5),)
    with pytest.raises(BootstrapWorldError, match="at least one term"):
        TargetExpression(intercept=0.0, terms=())
    with pytest.raises(BootstrapWorldError, match="weight 0"):
        TargetExpression(intercept=0.0, terms=(((0,), 0.0),))
    with pytest.raises(BootstrapWorldError, match="twice"):
        TargetExpression(intercept=0.0, terms=(((0,), 0.5), ((0,), 0.6)))
    with pytest.raises(BootstrapWorldError, match="term of one or two features"):
        TargetExpression(intercept=0.0, terms=(((), 0.5),))
    with pytest.raises(BootstrapWorldError, match="ascending order"):
        TargetExpression(intercept=0.0, terms=(((3, 1), 0.5),))
    with pytest.raises(BootstrapWorldError, match="names its features by index"):
        TargetExpression(intercept=0.0, terms=(((True,), 0.5),))
    with pytest.raises(BootstrapWorldError, match="intercept is a real constant"):
        TargetExpression(intercept=True, terms=good)
    with pytest.raises(BootstrapWorldError, match="intercept is a finite constant"):
        TargetExpression(intercept=float("nan"), terms=good)
    with pytest.raises(BootstrapWorldError, match="finite coefficient"):
        TargetExpression(intercept=0.0, terms=(((0,), float("inf")),))
    with pytest.raises(BootstrapWorldError, match="real coefficient"):
        TargetExpression(intercept=0.0, terms=(((0,), "big"),))  # type: ignore[arg-type]


def test_a_world_refuses_a_target_that_is_not_one() -> None:
    with pytest.raises(BootstrapWorldError, match="scored against a TargetExpression"):
        SymbolicRegressionWorld("w", target=((0,), 1.0))  # type: ignore[arg-type]


# -- The fixed dataset -------------------------------------------------------------


def test_the_dataset_is_fixed_and_auditable_against_the_target(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # The dataset is the world's *fixed* half: its shape is a property of
    # the domain, and its targets are the known expression plus noise —
    # the audit being the noise-free value at the row's own features.
    dataset = symreg_world.dataset
    assert isinstance(dataset, SymbolicDataset)
    assert dataset.rows == SYMREG_ROWS
    assert all(len(row) == SYMREG_FEATURE_COUNT for row in dataset.features)
    assert dataset.target is symreg_world.target
    assert dataset.seed == SYMREG_SEED
    for row in (0, 1, SYMREG_ROWS // 2, SYMREG_ROWS - 1):
        assert dataset.truth_for(row) == symreg_world.target.evaluate(
            dataset.features[row]
        )


def test_generation_is_a_pure_function_of_seed_and_target() -> None:
    # Same seed and target, same dataset to the last bit — in any process
    # and any order of calls.  Two world objects of one identity answer
    # one dataset; a changed seed answers a different one, because the
    # seed names the rows the target is priced against.
    target = target_for_seed(SYMREG_SEED)
    left = generate_symbolic_dataset(SYMREG_SEED, target=target)
    right = generate_symbolic_dataset(SYMREG_SEED, target=target)
    assert left.features == right.features
    assert left.targets == right.targets
    other = generate_symbolic_dataset(SYMREG_SEED + 1, target=target)
    assert other.features != left.features
    assert other.targets != left.targets


def test_the_dataset_is_generated_once_and_held(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # Lazy on first use, held after: a pool holds many worlds and pays
    # for a dataset only when a label is asked of it — and the label
    # then answers from the same numbers every time.
    assert symreg_world.dataset is symreg_world.dataset


# -- The label ---------------------------------------------------------------------


def test_the_label_is_a_pure_function_of_world_and_node(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    oracle = symreg_world.node_id(_oracle_setting(symreg_world))
    first = symreg_world.label(oracle)
    second = symreg_world.label(oracle)
    assert (first.coefficients, first.r2_train, first.r2_holdout) == (
        second.coefficients,
        second.r2_train,
        second.r2_holdout,
    )
    # Interleaving another cell's label changes nothing, and neither does
    # a fresh world of the same identity: the score is a fact about the
    # structure, not about the path that reached it or the object asked.
    symreg_world.label(symreg_world.canonical_node())
    third = symreg_world.label(oracle)
    assert third.r2_holdout == first.r2_holdout
    twin = SymbolicRegressionWorld(SYMREG_WORLD_ID, seed=SYMREG_SEED)
    assert twin.label(oracle).coefficients == first.coefficients


def test_label_all_covers_the_lattice_in_the_worlds_own_order(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    swept = dict(symreg_world.label_all())
    assert list(swept) == list(symreg_world.cells())
    for node_id, fit in swept.items():
        assert not isinstance(fit, Exception), node_id
        assert fit is symreg_world.label(node_id) or (
            fit.coefficients == symreg_world.label(node_id).coefficients
        )


def test_label_refuses_a_missing_address_and_an_out_of_lattice_one(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # The root is a node like any other, asked for by name: a defaulted
    # argument would let a missing one answer the same label as a
    # deliberate root ask.
    with pytest.raises(BootstrapWorldError, match="needs the node id to label"):
        symreg_world.label("")
    with pytest.raises(BootstrapWorldError, match="past the end of the 'product' axis"):
        symreg_world.label("l+0.c+0.p+3.s+0")


def test_node_id_refuses_something_that_is_not_a_setting(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    with pytest.raises(BootstrapWorldError, match="addresses an ExpressionSetting"):
        symreg_world.node_id("l+0.c+0.p+0.s+0")  # type: ignore[arg-type]


def test_a_world_id_is_required_and_a_seed_is_an_integer() -> None:
    # The id is how a label is attributed to a pool entry; the seed names
    # the dataset the target is priced against — neither can be defaulted
    # into something unnameable.
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        SymbolicRegressionWorld("")
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        SymbolicRegressionWorld("   ")
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        SymbolicRegressionWorld("w", seed=1.5)  # type: ignore[arg-type]
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        SymbolicRegressionWorld("w", seed=True)


def test_the_world_declares_the_symreg_family_and_domain_values(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # §11.1's family conditioning reads theme_root off the meta; the
    # domain value is what a later pool authoring seats under the
    # ``domain`` column the bootstrap world table already carries.
    from bootstrap import SYMREG_DOMAIN, SYMREG_THEME_ROOT

    assert symreg_world.theme_root == SYMREG_THEME_ROOT == "symreg"
    assert SYMREG_DOMAIN == "symreg"


# -- The score discriminates -------------------------------------------------------


def test_the_oracle_cell_clears_the_bar_on_every_seed_of_the_band() -> None:
    # The feature's headline read structurally: the cell carrying the
    # target's whole structure *recovers* it — held-out R² clears the
    # published evidential bar with margin, on every world the pool band
    # would author, not just the committed one.  The oracle cell is
    # derived from each world's own published target, so this is a claim
    # about the world's honesty, not about one lucky seed.
    for seed in BAND:
        world = SymbolicRegressionWorld(f"band-{seed}", seed=seed)
        oracle = world.node_id(_oracle_setting(world))
        score = world.label(oracle).r2_holdout
        assert score >= DISCOVERY_BAR, (seed, score)
        assert score >= DISCOVERY_BAR + 0.2, (seed, score)


def test_the_structureless_cells_are_nulls_on_every_seed_of_the_band() -> None:
    # The other side of discrimination: a candidate carrying no term of
    # the truth — the root, and the linear block alone, which explains a
    # fraction of the target's variance far below the bar — is a null on
    # every seed.  A world whose empty cells scored as discoveries would
    # be calibrating against noise.
    for seed in BAND:
        world = SymbolicRegressionWorld(f"band-{seed}", seed=seed)
        root = world.label(world.canonical_node()).r2_holdout
        assert root < DISCOVERY_BAR, (seed, root)
        linear_only = _oracle_setting(world).with_value(SymbolicAxis.CURVATURE, 0)
        linear_only = linear_only.with_value(SymbolicAxis.PRODUCT, 0)
        partial = world.label_setting(linear_only).r2_holdout
        assert partial < DISCOVERY_BAR, (seed, partial)


def test_the_wrong_middle_values_recover_less_than_the_truth_does() -> None:
    # The honest shape of symbolic regression as a search problem: each
    # structural axis carries a *wrong* middle value — a real term,
    # spelled in the vocabulary, that this world's target did not choose
    # — and a policy that stops at the first thing that sounds like
    # progress lands on it.  The oracle beats every such cell by a wide
    # margin on every seed of the band: swapping the wrong square in
    # beside the right pair (or the reverse) added a column and recovered
    # a fraction of what the right term recovers.  Where the wrong-middle
    # cells sit relative to the bar is deliberately not pinned — on the
    # committed world the wrong square lands just over it, which is the
    # contentful case: a term that *reads* like progress is not one, and
    # only the score against the known target says which is which.
    for seed in BAND:
        world = SymbolicRegressionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        for axis in (SymbolicAxis.CURVATURE, SymbolicAxis.PRODUCT):
            wrong = [level for level in (1, 2) if level != oracle_setting.value(axis)]
            for level in wrong:
                score = world.label_setting(oracle_setting.with_value(axis, level))
                assert oracle - score.r2_holdout >= 0.1, (seed, axis, level)


def test_a_cell_missing_a_load_bearing_term_is_beaten_by_the_oracle() -> None:
    # Missing either structural term costs roughly half the recovered
    # variance: the oracle beats every such cell by a margin on every
    # seed — neither axis can be skipped on the way to the optimum.
    # Where the partial cells sit *relative to the bar* is deliberately
    # not pinned: they straddle it from seed to seed, which is the
    # contentful case for calibration (the boundary follows the world's
    # drawn coefficients, not a constant of the domain).
    for seed in BAND:
        world = SymbolicRegressionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        for axis in (SymbolicAxis.CURVATURE, SymbolicAxis.PRODUCT):
            missing = world.label_setting(oracle_setting.with_value(axis, 0))
            assert oracle - missing.r2_holdout >= 0.1, (seed, axis)


def test_the_spurious_axis_is_the_quiet_one() -> None:
    # Terms no target carries, priced: the widest spurious level moves a
    # cell's held-out score by less than a tenth either way — quiet, the
    # way the hyperparameter world's ``standardize`` axis is, because a
    # lattice where every axis paid equally would be a lattice where
    # search policy does not matter.  The margin this *doesn't* hide:
    # spurious width cannot carry a structureless cell over the bar.
    for seed in BAND:
        world = SymbolicRegressionWorld(f"band-{seed}", seed=seed)
        oracle_setting = _oracle_setting(world)
        oracle = world.label_setting(oracle_setting).r2_holdout
        widened = world.label_setting(
            oracle_setting.with_value(SymbolicAxis.SPURIOUS, 2)
        ).r2_holdout
        assert abs(oracle - widened) < 0.1, (seed, oracle, widened)
        root_widened = world.label_setting(
            world.canonical_setting.with_value(SymbolicAxis.SPURIOUS, 2)
        ).r2_holdout
        assert root_widened < DISCOVERY_BAR, seed


def test_two_worlds_of_one_lattice_are_still_two_worlds() -> None:
    # §10.6.1's provenance rule from the authored side: the lattice is a
    # property of the domain, so two worlds agree on their cells, and
    # the *target* and dataset are properties of the seed, so they
    # disagree on their labels — two pool entries, not two names for one
    # world.
    left = SymbolicRegressionWorld(SYMREG_WORLD_ID, seed=SYMREG_SEED)
    right = SymbolicRegressionWorld("bootstrap-symreg-other", seed=SYMREG_SEED + 1)
    assert left.cells() == right.cells()
    assert left.world_id != right.world_id
    assert left.dataset.features != right.dataset.features
