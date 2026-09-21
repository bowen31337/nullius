"""The hyperparameter world's lattice — feature 181's space, and its edges.

app_spec.xml feature 181: *System exposes a hyperparameter search world
over a fixed model and dataset, which returns a ground-truth score per
node.*  These tests hold the *world* half of that sentence — what a node
is, which nodes exist, and which moves a policy may take — in the places
it can be read:

* **a node is a point of a rooted lattice** — the canonical setting is a
  cell like any other, every cell is reachable from it by legal moves, and
  a move is one axis by one position.  This is what makes the world
  addressable by docs/nullius-tech-architecture.md §10.6.1's
  ``question.meta`` / ``legal_actions`` / ``legal_roots`` vocabulary, and
  it is the property a policy's edge-only walk depends on;
* **the space is bounded** — a step past either end of an axis is refused
  by name, because an axis is a declaration of what the world answers for
  and a hyperparameter outside it names a model nobody agreed to score;
* **the address is a codec, not a convention** — the node id round-trips
  through encode and decode for every cell of the committed world, and
  every string the encoder cannot have produced is refused rather than
  read leniently.  A node id is the handle §10.6.1's ``question.commit``
  takes back, so a lenient decode would let a commit name a cell the
  policy was never shown;
* **two worlds of one lattice are still two worlds** — the lattice's shape
  is a property of the *domain*, not of the seed, so two worlds agree on
  their cells and disagree on their labels.

The metric is not imported here: what a coefficient of determination means
belongs to the evaluator and to ``test_label.py``, which pins the
arithmetic.  These tests assert only what the world owns — the shape of
the space and the discipline of its addresses.
"""

from __future__ import annotations

import pytest
from bootstrap import (
    AXIS_ORDER,
    HYPERPARAMETER_AXES,
    BootstrapWorldError,
    HyperparameterAxis,
    HyperparameterSetting,
    HyperparameterWorld,
    decode_node_id,
    encode_node_id,
    setting_dimensions,
)

# -- The lattice's shape -----------------------------------------------------------


def test_the_axes_are_the_four_hyperparameters_in_a_declared_order() -> None:
    # The order is load-bearing: it is the order a step vector is spelled
    # in, and therefore the order the node id encodes.  Pinned literally
    # here so a reordering cannot pass as a refactor.
    assert setting_dimensions() == ("degree", "interactions", "standardize", "alpha")
    assert tuple(axis.value for axis in AXIS_ORDER) == setting_dimensions()


def test_every_axis_first_value_is_the_canonical_default() -> None:
    # The root is a point of the space rather than a special case beside
    # it, which is what makes every cell reachable from it by monotone
    # moves.  If an axis ever declared its default other than first, the
    # step-count arithmetic that addresses nodes would quietly stop
    # matching the default the world actually uses.
    root = HyperparameterSetting()
    for axis in AXIS_ORDER:
        assert HYPERPARAMETER_AXES[axis][0] == root.value(axis), axis


def test_the_canonical_setting_is_the_root_and_addresses_itself(
    world: HyperparameterWorld, root_node: str
) -> None:
    assert world.canonical_node() == root_node
    assert world.setting(root_node) == world.canonical_setting
    assert world.steps(root_node) == (0, 0, 0, 0)
    assert world.depth(root_node) == 0


def test_the_lattice_is_the_product_of_the_declared_values(
    world: HyperparameterWorld,
) -> None:
    # Sixty cells: 3 degrees x 2 interaction flags x 2 standardisations x
    # 5 ridge strengths.  Pinned as a product rather than a literal so the
    # assertion states *why* the count is what it is.
    expected = 1
    for axis in AXIS_ORDER:
        expected *= len(HYPERPARAMETER_AXES[axis])
    assert len(world.cells()) == expected
    assert len(set(world.cells())) == expected  # one address per cell


def test_every_cell_is_reachable_from_the_root_by_legal_moves(
    world: HyperparameterWorld, root_node: str
) -> None:
    # The property a policy's edge-only walk depends on: nothing in the
    # lattice is an island.  Breadth-first from the root, following only
    # moves the world itself returns.
    seen = {root_node}
    frontier = [root_node]
    while frontier:
        node = frontier.pop()
        for neighbour in world.legal_moves(node):
            if neighbour not in seen:
                seen.add(neighbour)
                frontier.append(neighbour)
    assert seen == set(world.cells())


def test_a_move_moves_exactly_one_axis_by_one_position(
    world: HyperparameterWorld, wide_node: str
) -> None:
    # The structural rule §10.6.1's CellMeta describes.  A diagonal move
    # would make the space a grid rather than a lattice and the depth
    # figure meaningless.
    origin = world.steps(wide_node)
    for move in world.legal_moves(wide_node):
        step = world.steps(move)
        difference = [after - before for before, after in zip(origin, step)]
        assert max(abs(delta) for delta in difference) == 1
        assert sum(1 for delta in difference if delta != 0) == 1, move


def test_legal_moves_answers_the_roots_neighbours_without_being_told(
    world: HyperparameterWorld, root_node: str
) -> None:
    # ``node_id=None`` is the "start here" spelling, so a caller beginning
    # a walk does not have to spell the root first.
    assert world.legal_moves() == world.legal_moves(root_node)
    assert world.legal_moves(root_node) == (
        "d+0.i+0.s+0.a+1",
        "d+0.i+0.s+1.a+0",
        "d+0.i+1.s+0.a+0",
        "d+1.i+0.s+0.a+0",
    )


def test_no_cell_is_a_dead_end(world: HyperparameterWorld) -> None:
    # A walk can never get stuck: every axis of this lattice declares at
    # least two values, so even the fully saturated corner — every axis at
    # its last declared value — still has a step *down* available.  This is
    # the property that lets a policy walk until its own stopping rule
    # fires rather than until the world runs out of edges, and it is why
    # ``legal_moves`` has no empty case to document here: a one-valued axis
    # would produce one, and no axis has one.
    corner = "d+2.i+1.s+1.a+4"
    assert world.setting(corner).row() == {
        "degree": 3,
        "interactions": True,
        "standardize": True,
        "alpha": 100.0,
    }
    assert world.setting(corner).depth == 2 + 1 + 1 + 4
    assert world.legal_moves(corner) == (
        "d+1.i+1.s+1.a+4",
        "d+2.i+0.s+1.a+4",
        "d+2.i+1.s+0.a+4",
        "d+2.i+1.s+1.a+3",
    )
    for node_id in world.cells():
        assert world.legal_moves(node_id), node_id


def test_a_move_may_step_down_as_well_as_up(world: HyperparameterWorld) -> None:
    # Moves are bidirectional — the space is connected, not directed, so a
    # policy that overshoots can come back and a greedy walk that steps
    # past the optimum is not stranded there.
    below = world.legal_moves("d+1.i+0.s+0.a+0")
    assert "d+0.i+0.s+0.a+0" in below
    assert "d+2.i+0.s+0.a+0" in below


def test_legal_roots_is_the_single_declared_root(world: HyperparameterWorld) -> None:
    # A one-root lattice: this is *why* a policy needs no external hint
    # about where to begin, and why two policies compared on this world
    # begin from the same place (§10.3.1's paired comparison).
    assert world.legal_roots() == (world.canonical_node(),)


# -- Boundedness -------------------------------------------------------------------


def test_a_step_past_the_end_of_an_axis_is_refused_by_name(
    world: HyperparameterWorld,
) -> None:
    # ``degree`` declares three values, so a +9 step addresses a model the
    # world has not agreed to score.  The refusal names the axis and the
    # attempted position, so an operator reads *what* overshot.
    with pytest.raises(BootstrapWorldError, match="past the end of the 'degree' axis"):
        world.setting("d+9.i+0.s+0.a+0")


def test_a_step_below_the_start_of_an_axis_is_refused_by_name(
    world: HyperparameterWorld,
) -> None:
    # Below the root is the same bound from the other side; there is no
    # extrapolation in either direction.
    with pytest.raises(BootstrapWorldError, match="past the end of the 'alpha' axis"):
        world.setting("d+0.i+0.s+0.a-1")


def test_the_refusal_states_the_axes_declared_values(
    world: HyperparameterWorld,
) -> None:
    # The repair is "ask a cell this world holds", so the message carries
    # the values it does hold rather than only the one it does not.
    with pytest.raises(BootstrapWorldError) as refusal:
        world.setting("d+0.i+0.s+2.a+0")
    assert "False, True" in str(refusal.value)
    assert "standardize" in str(refusal.value)


def test_a_setting_outside_the_lattice_is_refused_at_construction() -> None:
    # The value type refuses too, and *before* a fit: a setting that holds
    # is a setting the world has agreed to score.
    with pytest.raises(BootstrapWorldError, match="not a value of the 'degree' axis"):
        HyperparameterSetting(degree=7)
    with pytest.raises(BootstrapWorldError, match="not a value of the 'alpha' axis"):
        HyperparameterSetting(alpha=0.5)


def test_a_flag_where_a_degree_belongs_is_refused() -> None:
    # ``True`` is ``1`` in Python, so a flag would silently ask for the
    # world's shallowest model instead of failing — a plausible number
    # rather than an error, which is the failure mode the refusal is for.
    # ``interactions`` legitimately *is* a flag, so the check is per-axis.
    with pytest.raises(BootstrapWorldError, match="is a flag"):
        HyperparameterSetting(degree=True)
    assert HyperparameterSetting(interactions=True).interactions is True


def test_a_flag_where_the_ridge_belongs_is_refused() -> None:
    with pytest.raises(BootstrapWorldError, match="is a flag"):
        HyperparameterSetting(alpha=False)


# -- The address codec -------------------------------------------------------------


def test_the_codec_round_trips_every_cell_of_the_committed_world(
    world: HyperparameterWorld,
) -> None:
    # The whole space, both directions.  The node id is the handle a
    # policy hands back at commit, so this is the property that keeps an
    # address from being one thing going in and another coming out.
    for node_id in world.cells():
        assert encode_node_id(decode_node_id(node_id)) == node_id
        assert world.node_id(world.setting(node_id)) == node_id


def test_the_root_encodes_as_the_all_zero_step_vector() -> None:
    # No special case: the root is spelled by the same encoder every other
    # node is, which is what keeps it from drifting away from the lattice.
    assert encode_node_id((0, 0, 0, 0)) == "d+0.i+0.s+0.a+0"


def test_a_malformed_node_id_is_refused_with_what_is_wrong(
    world: HyperparameterWorld,
) -> None:
    # Strict in both directions: a value the encoder cannot have produced
    # is refused rather than read leniently, so a commit cannot name a
    # cell the policy was never shown.
    with pytest.raises(BootstrapWorldError, match="carries 2 field"):
        world.setting("d+0.i+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        world.setting("x+0.i+0.s+0.a+0")
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_node_id("d0.i0.s0.a0")
    with pytest.raises(BootstrapWorldError, match="non-numeric magnitude"):
        decode_node_id("d+0.i+0.s+0.a+x")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_node_id("")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        decode_node_id(7)  # type: ignore[arg-type]


def test_a_misspelled_axis_initial_is_not_quietly_read_as_its_neighbour() -> None:
    # ``degree`` and ``standardize`` both exist; only ``degree``'s initial
    # is ``d``.  A lenient decode that matched on position alone would
    # accept a ``s`` field in the first slot and address a different cell
    # than the one written.
    with pytest.raises(BootstrapWorldError, match="malformed field"):
        decode_node_id("s+0.i+0.s+0.a+0")


def test_a_negative_step_round_trips() -> None:
    # The sign is always written, so the encoding is injective in the
    # obvious way and a step below the root is representable — even though
    # *this* lattice's first values are its defaults and so no legal cell
    # has one.  The codec is a codec; the bound is the world's.
    assert encode_node_id((-1, 0, 2, 0)) == "d-1.i+0.s+2.a+0"
    assert decode_node_id("d-1.i+0.s+2.a+0") == (-1, 0, 2, 0)


# -- The value type ----------------------------------------------------------------


def test_settings_that_name_one_point_are_equal_and_hash_alike() -> None:
    # Ordered values, so a set of settings is a set of *cells* and a
    # keyword order cannot make two spellings of one point distinct.
    left = HyperparameterSetting(degree=2, interactions=True, alpha=1.0)
    right = HyperparameterSetting(alpha=1.0, interactions=True, degree=2)
    assert left == right
    assert hash(left) == hash(right)
    assert len({left, right}) == 1


def test_a_setting_is_not_equal_to_a_bare_mapping() -> None:
    # The value type does not impersonate its own ``row()``: an equality
    # that accepted a dict would let a caller compare a *cell* against a
    # store row and conclude they were the same kind of thing.
    assert HyperparameterSetting() != {"degree": 1}


def test_with_value_moves_one_axis_and_leaves_the_original_alone() -> None:
    # A fresh setting per call: two callers holding one must not be able
    # to move each other's, which a mutating builder would allow.
    original = HyperparameterSetting(degree=1, interactions=False)
    moved = original.with_value(HyperparameterAxis.DEGREE, 3)
    assert moved.degree == 3
    assert original.degree == 1
    assert moved != original


def test_with_value_refuses_a_move_outside_the_lattice() -> None:
    with pytest.raises(BootstrapWorldError, match="not a value of the 'degree' axis"):
        HyperparameterSetting().with_value(HyperparameterAxis.DEGREE, 9)


def test_depth_is_the_sum_of_the_absolute_steps() -> None:
    # ``Σ|step|`` — the structural depth §10.6.1's CellMeta reports, read
    # off the lattice rather than stored, so a stored copy cannot disagree
    # with the coordinates it was taken from.
    setting = HyperparameterSetting(degree=3, interactions=True, alpha=10.0)
    assert setting.steps() == (2, 1, 0, 3)
    assert setting.depth == 6


def test_row_hands_out_the_shape_the_store_wants() -> None:
    row = HyperparameterSetting(degree=2, interactions=True, alpha=0.1).row()
    assert row == {
        "degree": 2,
        "interactions": True,
        "standardize": False,
        "alpha": 0.1,
    }
    assert row is not HyperparameterSetting().row()  # a fresh dict per call


# -- Two worlds of one lattice -----------------------------------------------------


def test_the_lattice_is_a_property_of_the_domain_not_the_seed(
    world: HyperparameterWorld, other_world: HyperparameterWorld
) -> None:
    # §10.6.1's provenance rule from the authored side: a changed world is
    # a *different* world.  Two worlds may share the space a policy walks
    # and still be two pool entries, which is what lets feature 188 author
    # 40-50 of them without inventing 40-50 lattices.
    assert world.cells() == other_world.cells()
    assert world.world_id != other_world.world_id


def test_a_world_id_is_required_and_a_seed_is_an_integer() -> None:
    # The id is how a label is attributed to a pool entry (§10.6's "report
    # the two pools separately"), and the seed *is* the world's identity,
    # so neither can be defaulted into something unnameable.
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        HyperparameterWorld("")
    with pytest.raises(BootstrapWorldError, match="world id is a non-empty string"):
        HyperparameterWorld("   ")
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        HyperparameterWorld("w", seed=1.5)  # type: ignore[arg-type]
    with pytest.raises(BootstrapWorldError, match="seed is an integer"):
        HyperparameterWorld("w", seed=True)


def test_node_id_refuses_something_that_is_not_a_setting(
    world: HyperparameterWorld,
) -> None:
    with pytest.raises(BootstrapWorldError, match="addresses a HyperparameterSetting"):
        world.node_id("d+0.i+0.s+0.a+0")  # type: ignore[arg-type]
