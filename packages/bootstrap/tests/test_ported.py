"""Feature 190's ported world adapter — an external ground-truth environment.

app_spec.xml feature 190: *System exposes a ported world adapter presenting an
external ground-truth environment through the identical policy question
interface, which returns scores comparable with an authored bootstrap world.*
docs/nullius-tech-architecture.md §10.6 opens the phase this feature closes —
*"A replay world need not be a crypto campaign"*, and an external domain can
supply the held-out score a paired comparison needs — and §10.6.1's provenance
rule (*"An upstream that changes is a different world, not an updated one"*) is
the whole of what a ported world must carry, because unlike an authored world
it has an upstream to check. These tests hold the adapter to it, and they pin
five things:

* **a ported world is a client of feature 184's seam, not a modification of
  it.**  Feature 184's ``question_for`` duck-types the world it wraps, so a
  ported world — another object with the answer surface — is wrapped in the
  *identical* ``BootstrapQuestion`` with no change to that module.  The tests
  build the question through ``ported_question_for`` and check every answer
  against the shared lattice's own primitives, not against literals, so the
  ported world and the interface cannot drift.

* **the label is the external score, carried unchanged.**  The observation a
  reveal returns carries the environment's honest ``r2_holdout`` — the score
  the label function returned — and is the identical number the ported world's
  ``label`` returns, on the same scale the authored pool reports.  A payload
  that answered a different number would be the corruption the identical
  interface exists to prevent.

* **the lattice is shared, so the cells are the same cells.**  A ported node is
  addressed on the authored world's lattice — the same codec, the same four
  axes, the same canonical root — so ``d+1.i+1.s+0.a+0`` is the same cell
  whether the label on it was generated or ported, and two policies walking
  the authored world and the ported world walk the same space and are scored
  on the same ``R²`` scale.  The tests pin the ported world's addressing
  against the authored world's, cell for cell.

* **the provenance is the ported world's identity.**  A ported world's labels
  are read from an environment this member does not generate, so its identity
  is the pair of digests that pinned them — the source commit and the dataset
  manifest — held in a frozen :class:`Provenance`.  Two ported worlds with
  different provenance are different worlds, and a re-port of the same
  provenance is the same upstream — §10.6.1's rule seen from the ported side.

* **the adapter is a fact about the world, not a promise in a docstring.**
  Two ported worlds over one environment answer identical observations and
  cell meta to the last field, and a ported world with a non-callable label
  source, a blank id or a missing provenance is refused before it can hand a
  policy an interface that would answer differently from the world it claims
  to front.

The values pinned are structural rather than literal — which node is the root,
which cells are neighbours, that the meta's parent is one step toward the root
— for the reason ``test_label.py`` states: the exact numbers are §12's
canary's to pin, and pinning them here would mean this file failed every time
the arithmetic was legitimately improved.
"""

from __future__ import annotations

import dataclasses

import bootstrap as member
import pytest
from bootstrap import (
    BootstrapQuestion,
    BootstrapWorldError,
    FitResult,
    HyperparameterWorld,
    Observation,
    PortedWorld,
    Provenance,
    ported_question_for,
    ported_world,
    question_for,
)

# -- Provenance -------------------------------------------------------------------


def test_provenance_is_a_frozen_record_of_the_upstream() -> None:
    # A ported world's provenance is a recorded fact — the source commit the
    # upstream code was pinned to, and the dataset manifest the labels were
    # taken from — and a caller must not be able to move either. Frozen: two
    # callers holding one provenance hold the same upstream, and a re-port of
    # the same provenance is the same world.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    assert provenance.source_commit == "c0ffee"
    assert provenance.dataset_manifest == "deadbeef"
    with pytest.raises(dataclasses.FrozenInstanceError):
        provenance.source_commit = "abc123"  # type: ignore[misc]


def test_provenance_row_is_a_store_shaped_mapping() -> None:
    # The two digests a persistence layer writes down, keyed by the column
    # names feature 191 records them under, so the record and the row cannot
    # drift. A fresh dict per call, never a shared one.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    assert provenance.row() == {
        "source_commit": "c0ffee",
        "dataset_manifest": "deadbeef",
    }
    assert provenance.row() is not provenance.row()


def test_provenance_refuses_a_blank_source_commit() -> None:
    # A blank digest names no upstream, so a provenance with one is refused at
    # construction, before it can pin a ported world to a source it cannot
    # name — the same "named, not defaulted" discipline the authored world
    # applies to its id.
    with pytest.raises(BootstrapWorldError, match="source_commit"):
        Provenance(source_commit="   ", dataset_manifest="deadbeef")


def test_provenance_refuses_a_blank_dataset_manifest() -> None:
    # The manifest is the hash of the data the labels were ported from; a
    # blank one pins the labels to nothing, so a re-port could not be checked
    # against it. Refused, naming the field.
    with pytest.raises(BootstrapWorldError, match="dataset_manifest"):
        Provenance(source_commit="c0ffee", dataset_manifest="")


def test_two_provenances_are_equal_only_when_the_upstream_is() -> None:
    # §10.6.1's rule from the ported side: an upstream that changes is a
    # *different* world. Two provenances with the same digests are the same
    # upstream; two that differ in either digest are different worlds, not
    # updated versions of one another.
    assert Provenance("c0ffee", "deadbeef") == Provenance("c0ffee", "deadbeef")
    assert Provenance("c0ffee", "deadbeef") != Provenance("abc123", "deadbeef")
    assert Provenance("c0ffee", "deadbeef") != Provenance("c0ffee", "feedface")
    assert hash(Provenance("c0ffee", "deadbeef")) == hash(
        Provenance("c0ffee", "deadbeef")
    )


# -- Construction -----------------------------------------------------------------


def _constant_label(score: float):
    # A label function that answers one honest score for every node — the
    # minimal external environment. The tests that care about the score pin
    # it; the ones that care about the lattice do not.
    return lambda node_id: score  # the node is the environment's to read


def test_a_ported_world_carries_its_identity_and_its_provenance() -> None:
    # A ported world is built from a label function, a lattice, an id and a
    # provenance, and it holds all four. The id and the provenance are the
    # identity; the label function and the lattice are the answer surface.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    world = ported_world(
        label_fn=_constant_label(0.5),
        world_id="bootstrap-ported-test",
        provenance=provenance,
    )
    assert isinstance(world, PortedWorld)
    assert world.world_id == "bootstrap-ported-test"
    assert world.provenance is provenance
    assert world.provenance.source_commit == "c0ffee"


def test_a_ported_world_refuses_a_non_callable_label_source() -> None:
    # The label function is the one thing the ported world takes from the
    # external environment, and a source that cannot be called cannot answer
    # the honest score a node is labelled with. Refused, naming what was
    # wrong, before any node is labelled.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    with pytest.raises(BootstrapWorldError, match="callable"):
        ported_world(label_fn=0.5, provenance=provenance)  # type: ignore[arg-type]


def test_a_ported_world_refuses_a_blank_id() -> None:
    # The id is how a ported label is attributed to a world in the pool, and
    # §10.6's "report the two pools separately" needs that attribution. A
    # world with no id could not attribute its score, so a ported world over
    # one is refused — the same discipline the authored world applies.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    with pytest.raises(BootstrapWorldError, match="non-empty string"):
        ported_world(
            label_fn=_constant_label(0.5), world_id="  ", provenance=provenance
        )


def test_a_ported_world_requires_a_provenance() -> None:
    # A ported world's labels come from an upstream this member does not
    # generate, and a world with no provenance has no source a re-port could
    # be checked against. Refused, naming what was wrong — a ported world
    # without provenance is not a ported world, it is an unattributed score.
    with pytest.raises(BootstrapWorldError, match="provenance"):
        ported_world(label_fn=_constant_label(0.5), provenance="c0ffee")  # type: ignore[arg-type]


def test_a_ported_world_defaults_to_the_authored_lattice() -> None:
    # With no lattice named, a ported node is addressed on the committed
    # authored world's lattice, so ``ported_world(label_fn=...)`` names exactly
    # the cells the authored pool walks — the comparability the feature
    # promises. The ported world's root, neighbours and cells are the authored
    # world's, checked against the member's own world, not against literals.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    world = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    authored = member.hyperparameter_world()
    assert world.canonical_node() == authored.canonical_node()
    assert world.legal_roots() == authored.legal_roots()
    assert world.cells() == authored.cells()


def test_a_ported_world_refuses_a_lattice_that_cannot_address_a_node() -> None:
    # A caller-supplied lattice is checked for the addressing surface the
    # ported world reaches through, duck-typed like the question's own
    # constructor (the loader's synthetic-name copy makes isinstance across
    # the two world classes meaningless — see test_component.py). A lattice
    # that cannot name its root or address a node cannot front a walk.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")

    class NotALattice:
        pass

    with pytest.raises(BootstrapWorldError, match="canonical_node"):
        ported_world(
            label_fn=_constant_label(0.5), lattice=NotALattice(), provenance=provenance
        )


def test_a_ported_world_can_port_a_different_lattice() -> None:
    # A caller that ports a different lattice passes one in, and the ported
    # world fronts it — the same cells, the same codec, the same root. The
    # adapter delegates addressing to the lattice it is handed, so a ported
    # node is addressed by the lattice's own spelling.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    lattice = HyperparameterWorld("bootstrap-hpo-lattice", seed=member.PRICED_SEED + 7)
    world = ported_world(
        label_fn=_constant_label(0.5), lattice=lattice, provenance=provenance
    )
    assert world.canonical_node() == lattice.canonical_node()
    assert world.cells() == lattice.cells()
    assert world.legal_moves() == lattice.legal_moves()


# -- The shared lattice, fronted --------------------------------------------------


def test_a_ported_world_addresses_the_same_cells_as_the_authored_world(
    world: HyperparameterWorld,
) -> None:
    # The lattice is shared, so a ported node is addressed on the authored
    # world's lattice — the same codec, the same four axes, the same root —
    # and ``d+1.i+1.s+0.a+0`` is the same cell whether the label on it was
    # generated or ported. The ported world's addressing delegates to the
    # lattice, so it agrees with the authored world cell for cell.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    for node_id in world.cells():
        assert ported.setting(node_id) == world.setting(node_id)
        assert ported.steps(node_id) == world.steps(node_id)
        assert ported.depth(node_id) == world.depth(node_id)
    assert ported.node_id(world.canonical_setting) == world.canonical_node()


def test_a_ported_world_refuses_a_node_outside_the_shared_lattice() -> None:
    # The space a ported world answers for is the lattice's, not the port's,
    # so a ported node that addresses a cell outside the lattice is refused by
    # the same bound an authored node is — naming the node and the world. A
    # ported policy cannot label or address a node it was never shown.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    with pytest.raises(BootstrapWorldError, match="past the end"):
        ported.setting("d+9.i+0.s+0.a+0")
    with pytest.raises(BootstrapWorldError):
        ported.steps("d+9.i+0.s+0.a+0")


# -- The label --------------------------------------------------------------------


def test_a_ported_label_is_the_external_score_unchanged() -> None:
    # The ported world's label is the external environment's honest held-out
    # R², carried unchanged. The adapter does not rescore, narrow or re-derive
    # it: the score a policy reads off a ported node is the score the label
    # function returned, verbatim.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.42), provenance=provenance)
    node_id = "d+1.i+1.s+0.a+0"
    fit = ported.label(node_id)
    assert isinstance(fit, FitResult)
    assert fit.r2_holdout == 0.42


def test_a_ported_label_reads_the_node_the_environment_was_asked_about() -> None:
    # The label function is a pure callable mapping a node id to the score the
    # environment assigns that node, so the ported world hands the node id to
    # the environment, not a rewritten one. The test's label function records
    # which node it was asked about, and the ported world passes it through.
    seen: list[str] = []

    def label_fn(node_id: str) -> float:
        seen.append(node_id)
        return 0.0

    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=label_fn, provenance=provenance)
    node_id = "d+2.i+0.s+1.a+0"
    ported.label(node_id)
    assert seen == [node_id]


def test_a_ported_label_is_a_pure_function_of_the_node() -> None:
    # The label of a ported node is a pure function of the label function and
    # the node — no method mutates anything, no answer depends on which ask
    # came before it — so the same node labelled twice, or labelled after any
    # number of other nodes, answers the identical score. Which is what
    # "ground truth" has to mean for a world the authored pool is calibrated
    # against.
    calls = {"n": 0}

    def label_fn(node_id: str) -> float:  # the node is the environment's
        calls["n"] += 1
        return 0.3

    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=label_fn, provenance=provenance)
    node_id = "d+1.i+1.s+0.a+0"
    first = ported.label(node_id)
    ported.label("d+0.i+1.s+0.a+0")
    ported.label("d+0.i+0.s+1.a+0")
    second = ported.label(node_id)
    assert first.r2_holdout == second.r2_holdout == 0.3


def test_a_ported_label_carries_the_score_only_fit_fields() -> None:
    # A pure external score carries the held-out R² and nothing beside it, so
    # the fit-pair fields that are an authored-fit artifact — the training
    # score, the overfit gap, the fitted coefficients, the column width — are
    # the score-only defaults. A port that invented a training score it never
    # measured would be reporting a fact it did not have; the caller comparing
    # a ported node with an authored one compares on r2_holdout, the score the
    # environment earned.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.42), provenance=provenance)
    fit = ported.label("d+1.i+1.s+0.a+0")
    assert fit.r2_train == 0.0
    # overfit_gap is the fit's derived r2_train - r2_holdout; with no training
    # score measured, it is -r2_holdout, not a stored zero — the score-only
    # defaults are the stored fields (r2_train, n_columns, coefficients), and
    # the gap follows from them.
    assert fit.overfit_gap == 0.0 - 0.42
    assert fit.n_columns == 0
    assert fit.coefficients == ()


# -- The identical interface ------------------------------------------------------


def test_ported_question_for_returns_the_identical_bootstrap_question() -> None:
    # ported_question_for wraps the ported world in the identical BootstrapQuestion
    # feature 184 built — no change to that module, because the ported world
    # is just another object with the answer surface question_for calls
    # through. The question's answers are the ported world's, checked against
    # the shared lattice's own primitives, not against literals.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    question = ported_question_for(ported)
    assert isinstance(question, BootstrapQuestion)
    authored = member.hyperparameter_world()
    assert question.legal_roots() == [authored.canonical_node()]
    root = question.legal_roots()[0]
    assert question.legal_actions(root) == list(authored.legal_moves(root))
    assert question.meta(root).depth == 0


def test_a_ported_question_reveals_the_external_score_unchanged() -> None:
    # The observation a reveal returns carries the environment's honest
    # r2_holdout — the score the label function returned — and is the
    # identical number the ported world's label returns, on the same scale the
    # authored pool reports. A payload that answered a different number would
    # be the corruption the identical interface exists to prevent.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.37), provenance=provenance)
    question = ported_question_for(ported)
    node_id = "d+1.i+1.s+0.a+0"
    (observation,) = question.probe_batch([node_id]).values()
    assert isinstance(observation, Observation)
    assert observation.r2_holdout == 0.37
    assert observation.world_id == ported.world_id
    assert observation.node_id == node_id


def test_a_ported_question_exposes_the_whole_interface() -> None:
    # The identical interface is the point: a ported world exposes the same
    # question.* API a financial campaign and an authored bootstrap world do,
    # so one policy runs unmodified against it. observed is the ascending map,
    # budget_remaining reports the whole budget (§10.6's zero
    # statistical-budget cost for a bootstrap world), and commit records the
    # terminal cell — all unchanged from feature 184.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    question = ported_question_for(ported)
    cells = ["d+1.i+0.s+0.a+0", ported.canonical_node(), "d+0.i+1.s+0.a+0"]
    question.probe_batch(cells)
    assert list(question.observed().keys()) == sorted(cells)
    assert question.budget_remaining() == float("inf")
    node_id = "d+1.i+1.s+0.a+0"
    assert question.commit(node_id) == node_id
    assert question.committed == node_id


def test_a_ported_question_refuses_a_node_the_lattice_does_not_hold() -> None:
    # A ported policy cannot reveal, meta or commit a node it was never shown:
    # the shared lattice's bound, so a ported question refuses a node outside
    # the lattice, naming the node and the world. The refusal propagates from
    # the ported world's steps through question_for unchanged.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    question = ported_question_for(ported)
    with pytest.raises(BootstrapWorldError):
        question.meta("d+9.i+0.s+0.a+0")
    with pytest.raises(BootstrapWorldError):
        question.probe_batch(["d+9.i+0.s+0.a+0"])
    with pytest.raises(BootstrapWorldError):
        question.commit("d+9.i+0.s+0.a+0")


def test_a_ported_world_is_accepted_by_question_for_without_isinstance() -> None:
    # The decisive integration test, and the reason feature 184's constructor
    # duck-types rather than isinstance. A PortedWorld is not a
    # HyperparameterWorld, and an isinstance gate would refuse the very world
    # a policy receives. question_for accepts it — the ported world is a
    # client of the identical interface, and one policy runs unmodified
    # against it.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    assert not isinstance(ported, HyperparameterWorld)
    question = question_for(ported)
    root = question.legal_roots()[0]
    assert question.meta(root).depth == 0
    assert question.legal_actions(root) == list(ported.legal_moves(root))


# -- Comparability ----------------------------------------------------------------


def test_a_ported_world_and_an_authored_world_share_the_interface_but_not_the_labels(
    world: HyperparameterWorld,
) -> None:
    # The identical interface is the point: a ported world and an authored
    # world of one lattice expose the same questions — the same roots, the
    # same legal actions, the same meta shape — but their own labels, so one
    # policy runs unmodified against either and is scored on that world's own
    # ground truth, on the same R² scale. The interface is shared; the scores
    # are the world's.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    ported = ported_world(label_fn=_constant_label(0.33), provenance=provenance)
    authored = question_for(world)
    ported_q = ported_question_for(ported)
    assert authored.legal_roots() == ported_q.legal_roots()
    root = authored.legal_roots()[0]
    (move,) = authored.legal_actions(root)[:1]
    assert authored.meta(move).depth == ported_q.meta(move).depth
    (authored_obs,) = authored.probe_batch([move]).values()
    (ported_obs,) = ported_q.probe_batch([move]).values()
    assert authored_obs.r2_holdout == world.label(move).r2_holdout
    assert ported_obs.r2_holdout == 0.33
    assert authored_obs.r2_holdout != ported_obs.r2_holdout


def test_two_ported_worlds_over_one_environment_answer_identically() -> None:
    # The property that makes "one policy, both pools" a fact about the adapter
    # rather than a promise: two ported worlds over one environment answer
    # identical observations and cell meta to the last field. A policy that
    # ran against either would be scored on the same numbers.
    provenance = Provenance(source_commit="c0ffee", dataset_manifest="deadbeef")
    first = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    second = ported_world(label_fn=_constant_label(0.5), provenance=provenance)
    q1 = ported_question_for(first)
    q2 = ported_question_for(second)
    root = q1.legal_roots()[0]
    (move,) = q1.legal_actions(root)[:1]
    for question in (q1, q2):
        question.probe_batch([root, move])
    assert q1.observed() == q2.observed()
    assert q1.meta(move) == q2.meta(move)


def test_two_ported_worlds_with_different_provenance_are_different_worlds() -> None:
    # §10.6.1's rule from the ported side: the provenance is the ported
    # world's identity, so two ported worlds over the same environment but
    # pinned to different upstreams are different worlds — different ids to
    # attribute their labels to, different rows to persist. The labels may be
    # the same; the provenance is not.
    labels = _constant_label(0.5)
    first = ported_world(label_fn=labels, provenance=Provenance("c0ffee", "deadbeef"))
    second = ported_world(label_fn=labels, provenance=Provenance("abc123", "deadbeef"))
    assert first.world_id == second.world_id  # same default id
    assert first.provenance != second.provenance
    assert first.provenance.row() != second.provenance.row()
