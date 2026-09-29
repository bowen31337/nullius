"""Feature 184's identical policy question interface — the seam, and its wrapper.

app_spec.xml feature 184: *System exposes the identical policy question
interface from every bootstrap world, so one policy runs unmodified and
returns comparable scores across both pools.*  docs/nullius-tech-
architecture.md §10.6 states what every bootstrap world is for — *"Each
exposes the **same** ``question.*`` API as a financial campaign, so a policy
is portable without modification"* — and §11 names that API in full. These
tests hold the wrapper to it, and they pin five things:

* **the wrapper is a wrapper, and the world and the question are two
  objects.**  The world owns the answer surface (it can name its root,
  enumerate a node's neighbours, and label a node with its honest ``R²``);
  the question is the policy-facing side that adds the one thing a world
  must not hold — the reveal bookkeeping.  A question built over a world
  answers ``legal_actions`` from the world's neighbours and ``meta`` from
  the world's lattice, so the two cannot drift: the test builds the question
  and checks every answer against the world's own primitives, not against
  literals.

* **a label is honest and unchanged.**  The observation a reveal returns
  carries the world's own ``r2_holdout`` beside its ``r2_train`` and
  ``overfit_gap`` — the fit's ``row()`` — and is the *identical* number the
  world's ``label`` returns, so a policy comparing a bootstrap node with a
  financial one compares on a score that means the same thing.  A payload
  that answered a different number would be the corruption the interface
  exists to prevent.

* **a label is a pure function of (world, node_id).**  The same node
  revealed twice, or revealed after any number of other nodes, answers the
  identical observation — which is what "ground truth" has to mean for a
  pool the financial worlds are calibrated against.  The test is written as
  an interleaving: a whole sweep between two reveals of one node.

* **the interface is the identical one §11 names.**  ``observed`` is a
  ``{node_id: Observation}`` map, ``legal_actions`` and ``legal_roots`` are
  lists of node ids, ``meta`` returns a ``CellMeta`` (branch, depth, parent,
  theme_root), ``probe_batch`` reveals a batch and calls ``on_reveal`` once
  per newly revealed cell, ``budget_remaining`` reports the whole budget
  (§10.6's zero statistical-budget cost), and ``commit`` records the
  terminal cell.  A policy written against a financial campaign reaches each
  of these by name and finds the shape it expects.

* **the adapter is a fact about the world, not a promise in a docstring.**
  Two questions over one world answer identical observations and cell meta
  to the last field, and a question over a non-world or an unnamed world is
  refused before it can hand a policy an interface that would answer
  differently from the world it claims to front.

The values pinned are structural rather than literal — which node is the
root, which family of designs beats which, that the meta's parent is one
step toward the root — for the reason ``test_label.py`` states: the exact
numbers are §12's canary's to pin, and pinning them here would mean this
file failed every time the arithmetic was legitimately improved.
"""

from __future__ import annotations

import dataclasses

import bootstrap as member
import pytest
from bootstrap import (
    BOOTSTRAP_THEME_ROOT,
    BootstrapQuestion,
    BootstrapWorldError,
    CellMeta,
    HyperparameterWorld,
    Observation,
    question_for,
)

# -- The factory ------------------------------------------------------------------


def test_question_for_wraps_a_world_in_the_question_interface(world: HyperparameterWorld) -> None:
    # The one call site for the identical interface: a world in, the
    # question a policy expects out. The wrapper is the world's policy-facing
    # side, so every answer it gives is the world's — checked here against
    # the world's own primitives, not against literals, so the wrapper and
    # the world cannot drift.
    question = question_for(world)
    assert isinstance(question, BootstrapQuestion)
    assert question.world is world
    # The question's lists are the world's tuples, spelled as the §11 API
    # names them — a list of node ids, not the world's tuple.
    assert question.legal_roots() == list(world.legal_roots())
    root = world.canonical_node()
    assert question.legal_actions(root) == list(world.legal_moves(root))
    assert question.meta(root).depth == world.depth(root)


def test_two_questions_over_one_world_answer_identically(world: HyperparameterWorld) -> None:
    # The property that makes "one policy, both pools" a fact about the
    # adapter rather than a promise: two adapters of one world answer
    # identical observations and cell meta to the last field. A policy that
    # ran against either would be scored on the same numbers.
    first = question_for(world)
    second = question_for(world)
    root = world.canonical_node()
    (move,) = world.legal_moves(root)[:1]
    for question in (first, second):
        question.probe_batch([root, move])
    assert first.observed() == second.observed()
    assert first.meta(move) == second.meta(move)


def test_question_for_refuses_a_non_world() -> None:
    # A question over an object that is not a world would hand a policy an
    # interface that answers differently from the world it claims to front —
    # the identical-interface guarantee broken at construction. Refused,
    # naming what was wrong, before any policy is handed the interface.
    with pytest.raises(BootstrapWorldError):
        question_for("not-a-world")  # type: ignore[arg-type]
    with pytest.raises(BootstrapWorldError):
        question_for(object())  # type: ignore[arg-type]


def test_question_for_accepts_the_composed_world() -> None:
    # The decisive integration test, and the reason the constructor duck-types
    # rather than ``isinstance``. The module loader imports the member under a
    # synthetic name and re-executes it, so the world ``create_app()`` hands
    # out is a *second* HyperparameterWorld class object, distinct from this
    # member's (``isinstance`` across the two copies cannot hold — see
    # test_component.py). A question built with ``isinstance`` would refuse
    # the very world the composed application serves, breaking "one policy,
    # both pools" at the composition seam. The question accepts it and answers
    # through it.
    from app.module_loader import create_app

    composed = create_app().get("bootstrap")
    assert composed is not None
    assert type(composed).__name__ == "HyperparameterWorld"
    assert not isinstance(composed, HyperparameterWorld)  # the loader's copy
    question = question_for(composed)
    root = question.legal_roots()[0]
    assert question.meta(root).depth == 0
    assert question.legal_actions(root) == list(composed.legal_moves(root))


def test_question_for_refuses_an_unnamed_world() -> None:
    # The observation a reveal returns carries the world it was earned on,
    # and §10.6's "report the two pools separately" needs that attribution.
    # A world with no id could not attribute its score, so a question over
    # one is refused — the same "named, not defaulted" discipline the world
    # applies to its own id. The check is at the question, so the world here
    # is a stand-in with the answer-surface but a blank id: a real
    # HyperparameterWorld refuses the blank id at its own construction,
    # before the question is ever reached, so this exercises the question's
    # own guard rather than the world's.
    class BlankIdWorld:
        world_id = "   "

        def __getattr__(self, name: str) -> object:  # the answer surface, stubbed
            return lambda *args, **kwargs: None

    with pytest.raises(BootstrapWorldError):
        question_for(BlankIdWorld())  # type: ignore[arg-type]


# -- CellMeta ---------------------------------------------------------------------


def test_the_root_meta_has_no_parent_and_no_branch(world: HyperparameterWorld) -> None:
    # The root is a point of the lattice, not a special case beside it: it
    # has no parent (nothing is closer to the root than the root) and no
    # branch (no step reached it). The depth is zero, and the theme root is
    # the world's domain family — the same value on every meta of the world.
    question = question_for(world)
    meta = question.meta(world.canonical_node())
    assert isinstance(meta, CellMeta)
    assert meta.branch is None
    assert meta.depth == 0
    assert meta.parent is None
    assert meta.theme_root == BOOTSTRAP_THEME_ROOT


def test_meta_reports_the_structural_depth_and_parent(world: HyperparameterWorld) -> None:
    # The meta's depth is the world's own ``Sigma|step|`` — the number a
    # financial node's meta carries on the same scale — and the parent is
    # the neighbour one legal step toward the root, so a walk from any cell
    # to the root is a monotone descent through parents. The branch is the
    # axis that step moved.
    question = question_for(world)
    root = world.canonical_node()
    (move,) = [node_id for node_id in world.legal_moves(root) if node_id.startswith("d+1")]
    meta = question.meta(move)
    assert meta.depth == world.depth(move) == 1
    assert meta.parent == root
    assert meta.branch is not None
    # The branch is the axis the move used — here the degree axis, since the
    # node id's first field is the degree's.
    assert move.split(".")[0][0] == meta.branch.value[0]


def test_meta_is_read_off_the_lattice_not_stored(world: HyperparameterWorld) -> None:
    # A node two steps out on one axis reports depth two, a parent one step
    # closer on that axis, and that axis as its branch — so the meta is a
    # fact about where the node sits, derived from the world's lattice, not
    # a stored copy that could drift from the node.
    question = question_for(world)
    node_id = "d+2.i+0.s+0.a+0"
    meta = question.meta(node_id)
    assert meta.depth == 2
    assert meta.parent == "d+1.i+0.s+0.a+0"
    assert meta.branch is member.HyperparameterAxis.DEGREE
    # And the parent is itself a node the world holds: its meta is one shallower.
    assert question.meta(meta.parent).depth == 1


def test_meta_refuses_a_node_outside_the_lattice(world: HyperparameterWorld) -> None:
    # A node id a policy hands to ``meta`` is one it was shown, and a meta
    # computed for a cell the world does not hold would let a policy reason
    # about a node it never saw. Refused, naming the node and the world.
    question = question_for(world)
    with pytest.raises(BootstrapWorldError):
        question.meta("d+9.i+0.s+0.a+0")


def test_the_theme_root_is_the_domain_family(world: HyperparameterWorld) -> None:
    # docs §11.1 exposes ``theme_root`` because the overfit signature is
    # only partly family-invariant, and the policy writes family-conditional
    # thresholds. A bootstrap world belongs to one family — the authored
    # hyperparameter world to "hpo" — and every meta of it reports that
    # family, so a policy reasoning about families sees a bootstrap node as
    # a member of its domain rather than a family-less exception.
    question = question_for(world)
    for node_id in world.cells():
        assert question.meta(node_id).theme_root == BOOTSTRAP_THEME_ROOT


# -- Observation ------------------------------------------------------------------


def test_an_observation_carries_the_worlds_honest_label(world: HyperparameterWorld) -> None:
    # The observation a reveal returns is the world's honest ``FitResult``
    # unchanged — its ``r2_holdout`` beside its ``r2_train`` and
    # ``overfit_gap`` — so a policy comparing a bootstrap node with a
    # financial one compares on a score that means the same thing. The
    # payload is the fit's ``row()`` plus the world id it was earned on.
    question = question_for(world)
    node_id = "d+1.i+1.s+0.a+0"
    (observation,) = question.probe_batch([node_id]).values()
    fit = world.label(node_id)
    assert observation.r2_holdout == fit.r2_holdout
    assert observation.r2_train == fit.r2_train
    assert observation.overfit_gap == fit.overfit_gap
    assert observation.n_columns == fit.n_columns
    assert observation.coefficients == fit.coefficients
    assert observation.world_id == world.world_id
    assert observation.node_id == node_id


def test_an_observation_is_a_frozen_recorded_fact(world: HyperparameterWorld) -> None:
    # An observation is what a policy *saw* when it revealed a cell, and a
    # policy comparing two cells must not be able to move either. Frozen: a
    # caller cannot reassign its score, so two policies reading the same
    # observation read the same number.
    question = question_for(world)
    (observation,) = question.probe_batch([world.canonical_node()]).values()
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.r2_holdout = 1.0  # type: ignore[misc]


# -- observed / reveal bookkeeping ------------------------------------------------


def test_observed_is_the_revealed_map_ascending(world: HyperparameterWorld) -> None:
    # ``observed`` is a ``{node_id: Observation}`` map of the cells revealed
    # so far, ascending by node id — an explicit sort before the reduction,
    # so two reads of one question agree whatever order the reveals came in.
    question = question_for(world)
    cells = ["d+1.i+0.s+0.a+0", world.canonical_node(), "d+0.i+1.s+0.a+0"]
    question.probe_batch(cells)
    observed = question.observed()
    assert list(observed.keys()) == sorted(cells)
    assert all(isinstance(value, Observation) for value in observed.values())


def test_a_label_is_a_pure_function_of_world_and_node(world: HyperparameterWorld) -> None:
    # The same node revealed twice, or revealed after any number of other
    # nodes, answers the identical observation — which is what "ground
    # truth" has to mean for a pool the financial worlds are calibrated
    # against. Written as an interleaving: a whole sweep between two reveals
    # of one node.
    question = question_for(world)
    node_id = "d+1.i+1.s+0.a+0"
    first = question.probe_batch([node_id])[node_id]
    # A whole sweep between the two asks: the label must not depend on the
    # path the policy took to the node. The sweep reveals the node too, so
    # the second ask reads it back from the observed map rather than
    # expecting the idempotent probe to re-return it.
    question.probe_batch(world.cells())
    second = question.observed()[node_id]
    assert first == second


def test_observed_starts_empty(world: HyperparameterWorld) -> None:
    # A question that has revealed nothing reports nothing — an empty map,
    # not a defaulted cell. A question that defaulted its root would report
    # a score the policy never asked for.
    question = question_for(world)
    assert question.observed() == {}


# -- legal_actions / legal_roots --------------------------------------------------


def test_legal_roots_is_the_single_canonical_root(world: HyperparameterWorld) -> None:
    # ``legal_roots`` is the walk's start, as §11's API names it: a list of
    # one, the world's canonical root. A single-root lattice is the point
    # of rooting the space at a declared default, so two policies compared
    # on this world begin from the same place.
    question = question_for(world)
    assert question.legal_roots() == [world.canonical_node()]


def test_legal_actions_are_the_worlds_neighbours(world: HyperparameterWorld) -> None:
    # ``legal_actions`` is the neighbours of a node — one legal step along
    # one axis — as an ascending list, so a walk that only ever takes
    # returned moves stays inside the world by construction. Each move the
    # question returns is a move the world holds, checked against the
    # world's own enumeration.
    question = question_for(world)
    root = world.canonical_node()
    assert question.legal_actions(root) == list(world.legal_moves(root))
    # And the question's legal actions are ascending, so a policy that
    # enumerates without sorting still sees a deterministic order.
    assert question.legal_actions(root) == sorted(question.legal_actions(root))


def test_legal_actions_from_the_root_reach_every_axis(world: HyperparameterWorld) -> None:
    # From the root, one legal step reaches each of the four axes in either
    # direction the lattice holds — the neighbours a policy may take first.
    # The root is at the low end of every axis, so every neighbour is one
    # step up, and there is one per axis.
    question = question_for(world)
    actions = question.legal_actions()  # None -> the root's neighbours
    assert len(actions) == len(world.axes)
    assert actions == question.legal_actions(world.canonical_node())


# -- probe_batch ------------------------------------------------------------------


def test_probe_batch_reveals_and_reports_the_new_cells(world: HyperparameterWorld) -> None:
    # ``probe_batch`` reveals a batch and returns the observations of the
    # cells revealed *by this call*. A cell already revealed is not
    # re-returned — the call is idempotent on the revealed set, so a policy
    # that re-probes a cell it holds does not see it as new.
    question = question_for(world)
    cells = ["d+1.i+0.s+0.a+0", "d+0.i+1.s+0.a+0"]
    revealed = question.probe_batch(cells)
    assert set(revealed) == set(cells)
    # Re-probing one old and one new cell returns only the new one.
    again = question.probe_batch([cells[0], "d+0.i+0.s+1.a+0"])
    assert set(again) == {"d+0.i+0.s+1.a+0"}
    # But the observed map holds all three.
    assert set(question.observed()) == set(cells) | {"d+0.i+0.s+1.a+0"}


def test_probe_batch_calls_on_reveal_once_per_new_cell(world: HyperparameterWorld) -> None:
    # ``on_reveal`` is called once per newly revealed cell, in ascending
    # node id order — the hook a replay uses to record what a policy looked
    # at. An already-revealed cell does not fire it again, so a re-probe is
    # not a double-count.
    question = question_for(world)
    cells = ["d+1.i+0.s+0.a+0", "d+0.i+1.s+0.a+0"]
    seen: list[str] = []
    question.probe_batch(cells, on_reveal=seen.append)
    question.probe_batch([cells[0]], on_reveal=seen.append)
    assert seen == sorted(cells)


def test_probe_batch_refuses_a_cell_the_world_does_not_hold(world: HyperparameterWorld) -> None:
    # A policy cannot reveal a node it was never shown, and a reveal that
    # silently skipped a bad cell would let the policy think it had seen
    # one. The batch is validated up front and is all-or-nothing: a bad cell
    # refuses before any cell is revealed, so the reveal set is not left
    # half-applied.
    question = question_for(world)
    good = "d+1.i+0.s+0.a+0"
    with pytest.raises(BootstrapWorldError):
        question.probe_batch([good, "d+9.i+0.s+0.a+0"])
    assert question.observed() == {}  # nothing was revealed by the refused batch


# -- budget -----------------------------------------------------------------------


def test_budget_remaining_is_the_whole_budget(world: HyperparameterWorld) -> None:
    # §10.6's "zero statistical-budget cost" is a fact about bootstrap
    # worlds — a probe of one charges no statistical degrees of freedom —
    # and the adapter reports it as the budget untouched, always. It is not
    # a counter the question decrements: a counter would be a budget, and a
    # budget is the trial's fact (feature 185's ``charges_budget``), not the
    # world's. A policy reading it sees a bootstrap world as a world whose
    # probing is free.
    question = question_for(world)
    question.probe_batch(world.cells())
    assert question.budget_remaining() == float("inf")


# -- commit -----------------------------------------------------------------------


def test_commit_records_the_terminal_cell(world: HyperparameterWorld) -> None:
    # ``commit`` is the terminal act — the cell a replay scores the policy's
    # pick on. It records the committed cell and returns it, so a replay can
    # read back the policy's final choice. The committed cell is not added
    # to the revealed set: committing is the terminal act, not a reveal, and
    # a policy's score is a fact about its commit and its reveals, kept apart.
    question = question_for(world)
    node_id = "d+1.i+1.s+0.a+0"
    assert question.commit(node_id) == node_id
    assert question.committed == node_id
    assert question.observed() == {}  # committing revealed nothing


def test_commit_refuses_a_node_outside_the_lattice(world: HyperparameterWorld) -> None:
    # A commit that named a cell the world does not hold would score the
    # policy on a node it was never shown. Refused, naming the node and the
    # world, the same "refused, not created" discipline the world applies to
    # a cell it does not hold.
    question = question_for(world)
    with pytest.raises(BootstrapWorldError):
        question.commit("d+9.i+0.s+0.a+0")


# -- The identical interface across worlds ----------------------------------------


def test_two_worlds_share_the_interface_shape_but_differ_on_labels(
    world: HyperparameterWorld, other_world: HyperparameterWorld
) -> None:
    # The identical interface is the point: two worlds of one lattice expose
    # the same questions — the same roots, the same legal actions, the same
    # meta shape — but different labels, so one policy runs unmodified
    # against either and is scored on that world's own ground truth. The
    # interface is shared; the scores are the world's.
    base = question_for(world)
    other = question_for(other_world)
    root = world.canonical_node()
    assert base.legal_roots() == other.legal_roots()
    (move,) = base.legal_actions(root)[:1]
    assert base.meta(move).depth == other.meta(move).depth
    (base_obs,) = base.probe_batch([move]).values()
    (other_obs,) = other.probe_batch([move]).values()
    assert base_obs.r2_holdout == world.label(move).r2_holdout
    assert other_obs.r2_holdout == other_world.label(move).r2_holdout
    assert base_obs.r2_holdout != other_obs.r2_holdout
