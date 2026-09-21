"""Feature 189's headline: *perfect sensitivity and specificity references*.

app_spec.xml feature 189: *System labels every bootstrap node with ground
truth, which returns perfect sensitivity and specificity references for
calibration.*  docs/nullius-tech-architecture.md §10.6 is the property the
sentence stands on — the bootstrap worlds *"give perfect labels"* — and
§10.3 is the payoff it names: *"sensitivity/specificity on planted nulls"*,
the base-rate-independent pair every research metric carries.  On a
financial world both rates are measured, with the sampling error a finite
pool of commits carries; on a bootstrap world they can be *known*.  These
tests hold the reference to that, and they pin five things:

* **every node is labelled, from the world's own honest score.**  The
  labeling covers the lattice exactly — the same set of node ids
  ``cells()`` enumerates, no more and no fewer — and each label's score
  is the world's own ``label(node).r2_holdout``, unchanged, attributed to
  the world it was earned on.  A reference that skipped a cell would
  misstate every denominator it reported, and one that rescored a node
  would be a second opinion rather than a ground truth.

* **the classes are populated on both sides, the §7.3 floor.**  §7.3:
  *"a tree needs ≥2 null and ≥2 real roots to contribute to both
  sensitivity and specificity"* — the floor problem, and the reason a bar
  that emptied either class would take the world out of calibration at
  once.  Pinned over a sweep of seeds (the way ``NOISE_SCALE`` is), not
  asserted for one: every pool world holds discoveries *and* nulls at
  the published bar, and the committed world's boundary sits where real
  out-of-sample skill sits — the degree-1 family that cannot express the
  truth's curvature is null, the lattice's best cell is a discovery.

* **the labeling is a pure function of ``(world, bar)``.**  Two calls
  answer one value; interleaving another world's labeling changes
  nothing; two world objects of one seed answer one ground truth.  The
  labels cannot depend on the order they were asked in, because nothing
  about a label ever did (§10.6: *"no dependence on market time"*, read
  for ask order) — the property that makes the reference replayable.

* **the references are perfect, exactly.**  The declaration naming
  exactly the discoveries scores sensitivity ``1.0`` and specificity
  ``1.0`` — not approximately, not on average, exactly — and a partial
  declaration scores counts that re-derive by hand from the labels.  The
  arithmetic is integers and single divisions, so the numbers are the
  same on every platform and in every process (§12): the calibration
  anchor a measured rate is checked against, not one more measurement.

* **the refusals guard the reference's honesty.**  A declaration naming
  a node the world does not hold, a rate whose class is empty, a score
  that is not a finite real number, a bar outside ``[0, 1]`` — each is
  refused, naming what was wrong, rather than defaulted: a reference
  whose whole value is that it never gives a stand-in number (§10.6.1's
  rule, the one the ported half's digests exist to enforce) must refuse
  exactly the inputs that would make it give one.

The values asserted are of two kinds, deliberately, the same split
``test_label.py`` states: the *structural* claims — which family is
null, that both classes hold, that the perfect declaration scores one —
are properties of the world's construction and are asserted with
reference to the labels themselves, not as literals, so they survive an
arithmetic refactor that does not change what the world *is*.  Exact
scores are never pinned as literals here; §12's canary holds the last
bits in its own suite.
"""

from __future__ import annotations

import math

import pytest
from bootstrap import (
    DISCOVERY_BAR,
    HYPERPARAMETER_WORLD_ID,
    POOL_SEED,
    PRICED_SEED,
    BootstrapScoringError,
    BootstrapWorldError,
    ConfusionMatrix,
    GroundTruth,
    HyperparameterWorld,
    NodeTruth,
    PortedWorld,
    Provenance,
    draw_world_seed,
    ground_truth,
)

# -- The labeling -----------------------------------------------------------------


def test_ground_truth_labels_every_node_of_the_lattice(world: HyperparameterWorld) -> None:
    # "Every" is the feature's own word, and it is checked as a set
    # equality rather than a count: a labeling that held 60 labels over
    # 59 cells and one cell twice would pass a count and misstate every
    # denominator it reported.
    truth = ground_truth(world)
    cells = world.cells()
    assert len(truth) == len(cells)
    assert set(truth.nodes) == set(cells)
    # The enumeration is the lattice's own ascending order, so two
    # callers reading the labels read them in one order (§12's ordering
    # rule, restated for a reference a report iterates).
    assert truth.nodes == tuple(sorted(cells))


def test_every_label_is_read_off_the_worlds_own_honest_score(world: HyperparameterWorld) -> None:
    # The label's score is the world's honest held-out R², unchanged —
    # checked against the world's own label() for every cell, so the
    # reference and the world cannot drift. The class is one comparison
    # against the published bar, and nothing else: a caller auditing the
    # reference re-derives every class from the scores the world itself
    # answers.
    truth = ground_truth(world)
    for label in truth.labels:
        assert label.score == world.label(label.node_id).r2_holdout
        assert label.world_id == world.world_id
        assert label.is_discovery == (label.score >= DISCOVERY_BAR)
    assert truth.discovery_count + truth.null_count == len(truth)
    assert set(truth.discoveries()) | set(truth.nulls()) == set(truth.nodes)


def test_the_labels_split_the_pool_band_into_both_classes() -> None:
    # §7.3's floor: a world contributes to both sensitivity and
    # specificity only when it holds at least two nodes of each class.
    # Pinned over a sweep of seeds — the pool's own draw plus a band of
    # neighbours — because a bar that emptied a class on some world would
    # take that world out of calibration silently, and the sweep is where
    # that would show. This is the same defence NOISE_SCALE's tests make
    # for the world's difficulty: a property of the pool, not of one
    # draw.
    seeds = [POOL_SEED + offset for offset in range(8)]
    seeds += [draw_world_seed(POOL_SEED, index) for index in (0, 7, 23, 44)]
    for seed in seeds:
        world = HyperparameterWorld(f"bootstrap-hpo-{seed}", seed=seed)
        truth = ground_truth(world)
        assert truth.discovery_count >= 2, f"seed {seed} labels no discoveries"
        assert truth.null_count >= 2, f"seed {seed} labels no nulls"


def test_the_class_boundary_follows_real_out_of_sample_skill(world: HyperparameterWorld) -> None:
    # Where the boundary sits is a property of the world's construction:
    # a degree-1 design cannot express the truth's curvature at all, so
    # its held-out skill is noise-level and every degree-1 cell is a
    # null; the lattice's best-scoring cell clears the bar by a margin,
    # because it is the cell whose model family the truth was built to
    # reward. Asserted against the labels and the bar, never as literal
    # scores, so the claim survives an arithmetic refactor.
    truth = ground_truth(world)
    for node_id in world.cells():
        if world.setting(node_id).degree == 1:
            assert node_id in set(truth.nulls()), (
                f"a degree-1 cell cannot express the truth's curvature — "
                f"{node_id} scored {truth.score(node_id)!r} and should not "
                "clear the bar"
            )
    best = max(truth.labels, key=lambda label: label.score)
    assert best.is_discovery
    assert best.node_id == "d+1.i+1.s+0.a+3"  # the optimum test_label.py pins


def test_truth_is_a_pure_function_of_the_world(world: HyperparameterWorld, other_world: HyperparameterWorld) -> None:
    # Two calls answer one value, and interleaving another world's
    # labeling between them changes nothing — the property that lets a
    # calibration checkpoint replay the reference and get the same
    # numbers, and the reason nothing in the labeling may consult ask
    # order (which nothing about a label ever did).
    first = ground_truth(world)
    interleaved = ground_truth(other_world)
    second = ground_truth(world)
    assert first == second
    assert first.labels == second.labels
    assert interleaved != first  # a different seed is a different world
    assert interleaved.world_id == other_world.world_id


def test_two_worlds_of_one_seed_answer_one_ground_truth() -> None:
    # The world's identity is its (id, seed); two objects built from one
    # pair are interchangeable to the last label — §10.6.1's provenance
    # rule seen from the authored side, restated for the reference.
    left = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    right = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    assert ground_truth(left) == ground_truth(right)
    assert hash(ground_truth(left)) == hash(ground_truth(right))


# -- The perfect reference ----------------------------------------------------------


def test_perfect_declaration_scores_exactly_one_and_one(world: HyperparameterWorld) -> None:
    # The feature's own sentence, as a test: the declaration naming
    # exactly the world's discoveries scores sensitivity 1.0 and
    # specificity 1.0 — exactly, because the labels the declaration is
    # scored against are the same labels it was built from. On a
    # financial world this declaration lives behind the sidecar key and
    # its rates are still measured through a policy's behaviour; here
    # the answer key is published, so the perfect rates are computable
    # outright. 1.0 is compared for equality on purpose: the counts are
    # integers and the divisions are exact, so anything else would be a
    # floating-point story this arithmetic does not have.
    truth = ground_truth(world)
    matrix = truth.perfect()
    assert matrix.sensitivity == 1.0
    assert matrix.specificity == 1.0
    assert matrix == ConfusionMatrix(
        true_positives=truth.discovery_count,
        false_positives=0,
        true_negatives=truth.null_count,
        false_negatives=0,
    )


def test_calibrate_scores_a_partial_declaration_by_hand(world: HyperparameterWorld) -> None:
    # A partial declaration, scored by counts re-derived in the test from
    # the labels themselves: found some discoveries, declared some nulls,
    # missed the rest. The counts are the definition, and the rates are
    # the two divisions §10.3 names — so the test checks the arithmetic
    # against its own spelling of it, and a regression that moved either
    # would have to move both to hide.
    truth = ground_truth(world)
    discoveries = truth.discoveries()
    nulls = truth.nulls()
    declared = set(discoveries[:10]) | set(nulls[:3])
    matrix = truth.calibrate(declared)
    assert matrix.true_positives == 10
    assert matrix.false_positives == 3
    assert matrix.false_negatives == truth.discovery_count - 10
    assert matrix.true_negatives == truth.null_count - 3
    assert matrix.sensitivity == 10 / truth.discovery_count
    assert matrix.specificity == (truth.null_count - 3) / truth.null_count


def test_an_empty_declaration_finds_nothing_and_falsifies_nothing(world: HyperparameterWorld) -> None:
    # The policy that never commits: sensitivity zero (nothing was
    # found), specificity one (nothing was wrongly declared). A policy
    # scored only on sensitivity would love this corner, which is
    # exactly why the reference answers both — the pair §10.3 measures,
    # not one number a do-nothing policy could game.
    matrix = ground_truth(world).calibrate([])
    assert matrix.sensitivity == 0.0
    assert matrix.specificity == 1.0
    assert matrix.true_positives == 0
    assert matrix.false_positives == 0


def test_declaring_the_nulls_is_the_worst_declaration(world: HyperparameterWorld) -> None:
    # The anti-perfect declaration: name exactly the nodes the bar did
    # not clear. Sensitivity zero, specificity zero — every rate the
    # reference can state, minimised at once, which is the corner a
    # policy that has learned the wrong structure would occupy.
    truth = ground_truth(world)
    matrix = truth.calibrate(truth.nulls())
    assert matrix.sensitivity == 0.0
    assert matrix.specificity == 0.0
    assert matrix.false_positives == truth.null_count


def test_calibrate_is_order_free_and_deduplicates(world: HyperparameterWorld) -> None:
    # A declaration is a set: two callers naming the same nodes in
    # different orders, one naming a node twice, have made the same
    # declaration and score the same matrix — the order-independence
    # §12 asks of a reduction, restated at the reference's door.
    truth = ground_truth(world)
    declared = truth.discoveries()[:5] + truth.nulls()[:2]
    scrambled = list(reversed(declared)) + list(declared[:2])
    assert truth.calibrate(declared) == truth.calibrate(scrambled)


def test_calibrate_refuses_a_node_the_world_does_not_hold(world: HyperparameterWorld) -> None:
    # The same bound commit() and probe_batch() apply: a caller cannot
    # declare a node the world never showed, and the refusal is
    # all-or-nothing — a half-scored declaration would leave the caller
    # holding counts it could not attribute to any policy.
    truth = ground_truth(world)
    with pytest.raises(BootstrapWorldError, match="holds no node"):
        truth.calibrate(truth.discoveries()[:3] + ("d+9.i+0.s+0.a+0",))
    with pytest.raises(BootstrapWorldError, match="names node ids"):
        truth.calibrate([truth.discoveries()[0], 7])  # type: ignore[list-item]
    with pytest.raises(BootstrapWorldError, match="sequence of characters"):
        truth.calibrate(truth.discoveries()[0])  # type: ignore[arg-type]


def test_the_rates_refuse_a_world_with_an_empty_class() -> None:
    # §7.3's floor, seen from the other side: a world whose labels hold
    # no discoveries has nothing for a declaration to find, and
    # sensitivity is refused rather than defaulted — 0/0 is not a
    # sensitivity of zero but a world that cannot calibrate the rate.
    # Built by hand rather than by bar, because the published bar keeps
    # both classes populated on every world the pool draws; a hand-built
    # labeling is the test's way of asking about the corner the pool
    # keeps out of reach.
    null_only = GroundTruth(
        world_id="degenerate-null",
        labels=(
            NodeTruth("d+0.i+0.s+0.a+0", "degenerate-null", -0.25, False),
            NodeTruth("d+1.i+0.s+0.a+0", "degenerate-null", -0.75, False),
        ),
    )
    matrix = null_only.calibrate(["d+0.i+0.s+0.a+0"])
    with pytest.raises(BootstrapWorldError, match="hold no discoveries"):
        _ = matrix.sensitivity
    assert matrix.specificity == 0.5  # the other rate still answers

    discovery_only = GroundTruth(
        world_id="degenerate-discovery",
        labels=(
            NodeTruth("d+0.i+0.s+0.a+0", "degenerate-discovery", 0.9, True),
            NodeTruth("d+1.i+0.s+0.a+0", "degenerate-discovery", 0.8, True),
        ),
    )
    matrix = discovery_only.calibrate(["d+0.i+0.s+0.a+0"])
    with pytest.raises(BootstrapWorldError, match="hold no nulls"):
        _ = matrix.specificity
    assert matrix.sensitivity == 0.5


# -- The bar ------------------------------------------------------------------------


def test_the_bar_is_published_exactly_representable_and_inclusive() -> None:
    # 0.5 is a power of two, so score >= bar is bit-stable on every
    # platform that spells float64 the IEEE way — §12 met by the
    # construction of the constant. The comparison is inclusive: the bar
    # is the standard a score must meet, not exceed, and a boundary
    # score excluded would make the reference disagree with itself
    # between a bar of 0.5 and a score of 0.5.
    assert DISCOVERY_BAR == 0.5
    assert NodeTruth.from_score("n", "w", 0.5).is_discovery is True
    assert NodeTruth.from_score("n", "w", 0.49999999999999994).is_discovery is False
    assert NodeTruth.from_score("n", "w", -0.25).is_discovery is False
    # A sterner standard is speakable and yields a different reference
    # over the same world — two bars, two references, both exact.
    truth = ground_truth(
        HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED), bar=0.9
    )
    assert truth.bar == 0.9
    assert truth.discovery_count <= ground_truth(
        HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    ).discovery_count


def test_a_bar_outside_the_band_is_refused(world: HyperparameterWorld) -> None:
    # A bar below zero would classify nodes with negative out-of-sample
    # skill as discoveries; a bar above 1 names a standard no coefficient
    # of determination can meet; True is 1 in Python and would silently
    # name the strictest standard; a NaN names nothing. Each is refused
    # at every entrance the bar has, so the three cannot disagree.
    for bad in (True, "0.5", float("nan"), float("inf"), -0.1, 1.5):
        with pytest.raises(BootstrapWorldError):
            ground_truth(world, bar=bad)  # type: ignore[arg-type]
        with pytest.raises(BootstrapWorldError):
            NodeTruth.from_score("n", "w", 0.75, bar=bad)  # type: ignore[arg-type]
        with pytest.raises(BootstrapWorldError):
            GroundTruth("w", (NodeTruth("n", "w", 0.75, True),), bar=bad)  # type: ignore[arg-type]


def test_ground_truth_construction_refuses_incoherent_labelings() -> None:
    # A labeling with no nodes calibrates every rate against nothing;
    # two labels for one node is a contradiction rather than a labeling;
    # labels drawn from two worlds straddle the §10.6 line that reports
    # the pools separately. Each is refused at construction, naming the
    # world, before any rate could be computed over it.
    with pytest.raises(BootstrapWorldError, match="no labels"):
        GroundTruth("w", ())
    with pytest.raises(BootstrapWorldError, match="two labels for node"):
        GroundTruth(
            "w",
            (
                NodeTruth("d+0.i+0.s+0.a+0", "w", 0.9, True),
                NodeTruth("d+0.i+0.s+0.a+0", "w", 0.9, True),
            ),
        )
    with pytest.raises(BootstrapWorldError, match="earned on"):
        GroundTruth(
            "w",
            (
                NodeTruth("d+0.i+0.s+0.a+0", "w", 0.9, True),
                NodeTruth("d+1.i+0.s+0.a+0", "other", 0.9, True),
            ),
        )
    with pytest.raises(BootstrapWorldError, match="world's id"):
        GroundTruth("   ", (NodeTruth("n", "w", 0.9, True),))
    with pytest.raises(BootstrapWorldError, match="made of node truths"):
        GroundTruth("w", ("not-a-truth",))  # type: ignore[arg-type]
    # The labels handed in as a list come back as the lattice's own
    # ascending order — a labeling is a set of labels, and the order
    # they were handed in is no fact of the world.
    shuffled = GroundTruth(
        "w",
        [
            NodeTruth("d+1.i+0.s+0.a+0", "w", 0.8, True),
            NodeTruth("d+0.i+0.s+0.a+0", "w", -0.2, False),
        ],
    )
    assert shuffled.nodes == ("d+0.i+0.s+0.a+0", "d+1.i+0.s+0.a+0")


# -- The seam: ported worlds, the composed world, and the refusals -------------------


def test_ground_truth_labels_a_ported_world() -> None:
    # "Every bootstrap node" includes the ported half of the pool: a
    # PortedWorld exposes the same answer surface (cells, label,
    # world_id), so one duck-typed code path labels it — the authored
    # world and the ported world are two clients of the same seam, and
    # the reference is a third. The external scores are carried
    # unchanged and classed by the same published bar, on the one R²
    # scale both pools report on.
    lattice = HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED)
    cells = lattice.cells()

    def external_score(node_id: str) -> float:
        # A deterministic stand-in environment: strong cells and weak
        # cells, so both classes are populated at the published bar.
        return 0.8 if cells.index(node_id) % 3 == 0 else 0.1

    world = PortedWorld(
        label_fn=external_score,
        world_id="bootstrap-ported-test",
        provenance=Provenance("a" * 40, "b" * 64),
    )
    truth = ground_truth(world)
    assert set(truth.nodes) == set(cells)
    assert truth.world_id == "bootstrap-ported-test"
    for label in truth.labels:
        assert label.score == external_score(label.node_id)
        assert label.is_discovery == (label.score >= DISCOVERY_BAR)
    assert truth.discovery_count >= 2 and truth.null_count >= 2
    assert truth.perfect().sensitivity == 1.0


def test_ground_truth_refuses_a_non_finite_score() -> None:
    # A NaN compared against the bar classifies as a null, and a null
    # that is merely a missing number is a stand-in wearing a class —
    # the exact corruption §10.6.1's rule exists to keep out of the
    # pool. Refused, naming the node and the world, before any count
    # could absorb it; the same refusal stands at the value's own
    # constructor for a hand-built label.
    world = PortedWorld(
        label_fn=lambda node_id: float("nan"),
        world_id="bootstrap-ported-nan",
        provenance=Provenance("a" * 40, "b" * 64),
    )
    with pytest.raises(BootstrapScoringError, match="not finite"):
        ground_truth(world)
    with pytest.raises(BootstrapScoringError, match="not finite"):
        NodeTruth("n", "w", float("inf"), False)
    with pytest.raises(BootstrapScoringError, match="not a real number"):
        NodeTruth("n", "w", "0.9", False)  # type: ignore[arg-type]


def test_an_unlabelable_cell_refuses_the_whole_reference() -> None:
    # "Every" is a precondition, not a best effort: a world with one
    # cell it cannot label has no reference to give, and the refusal
    # propagates naming the cell rather than silently labelling 59 of
    # 60 — a partial labeling would misstate every denominator the
    # reference ever reported. The committed world's ridge floor keeps
    # every cell answerable, so the corner is reached through a ported
    # world whose environment refuses one node.
    def refusing_score(node_id: str) -> float:
        if node_id == "d+2.i+1.s+1.a+4":
            raise BootstrapScoringError("the environment refuses this cell")
        return 0.8

    world = PortedWorld(
        label_fn=refusing_score,
        world_id="bootstrap-ported-refusing",
        provenance=Provenance("a" * 40, "b" * 64),
    )
    with pytest.raises(BootstrapScoringError, match="the environment refuses"):
        ground_truth(world)


def test_ground_truth_refuses_a_non_world_and_an_unnamed_world(world: HyperparameterWorld) -> None:
    # The reference is read off the answer surface the question
    # interface calls through; an object without it names no cells a
    # calibration could be scored over, and an unnamed world could not
    # attribute its counts to a pool (§10.6's report-per-pool rule).
    with pytest.raises(BootstrapWorldError, match="has no cells, label"):
        ground_truth("not-a-world")  # type: ignore[arg-type]
    with pytest.raises(BootstrapWorldError, match="has no cells, label"):
        ground_truth(world.setting)  # type: ignore[arg-type]

    class Unnamed:
        cells = world.cells
        label = world.label
        world_id = "   "

    with pytest.raises(BootstrapWorldError, match="named world"):
        ground_truth(Unnamed())  # type: ignore[arg-type]


def test_ground_truth_accepts_the_composed_world() -> None:
    # The decisive integration test, and the reason the factory duck-types
    # rather than ``isinstance``: the module loader imports the member
    # under a synthetic name and re-executes it, so the world
    # ``create_app()`` hands out is a second HyperparameterWorld class
    # object, and an isinstance gate would refuse the very world the
    # composed application serves (see test_component.py). The reference
    # labels it — and because the composed world is the committed (id,
    # seed) pair, its labels are the committed world's labels, to the
    # last field.
    from app.module_loader import create_app
    from app.modules import bootstrap as seat

    composed = seat.hyperparameter_world_component(create_app())
    assert composed is not None
    assert not isinstance(composed, HyperparameterWorld)  # the loader's copy
    truth = ground_truth(composed)
    committed = ground_truth(HyperparameterWorld(HYPERPARAMETER_WORLD_ID, seed=PRICED_SEED))
    assert truth == committed
    assert truth.perfect().sensitivity == 1.0


# -- The store shapes ---------------------------------------------------------------


def test_row_shapes_are_store_shaped_and_fresh(world: HyperparameterWorld) -> None:
    # The rows a calibration report writes down: one per node, one per
    # matrix, one summary per world — each a fresh dict, so a caller
    # editing a row is editing the report and not the reference. The
    # matrix's row carries the counts only; the rates are derived, so a
    # persisted row cannot hold a sensitivity the counts do not
    # recompute to.
    truth = ground_truth(world)
    label_row = truth.labels[0].row()
    assert set(label_row) == {"node_id", "world_id", "score", "is_discovery"}
    assert label_row["is_discovery"] == truth.labels[0].is_discovery

    matrix = truth.calibrate(truth.discoveries()[:4])
    matrix_row = matrix.row()
    assert set(matrix_row) == {
        "true_positives",
        "false_positives",
        "true_negatives",
        "false_negatives",
    }
    assert matrix_row["true_positives"] == 4

    summary = truth.row()
    assert set(summary) == {"world_id", "bar", "nodes", "discoveries", "nulls"}
    assert summary["nodes"] == len(truth)
    assert summary["discoveries"] == truth.discovery_count
    assert summary["nulls"] == truth.null_count
    assert math.isfinite(summary["bar"])

    # Mutating a returned row must not touch the value it came from: the
    # next call answers the full row again, from the labels.
    for row in (label_row, matrix_row, summary):
        row.clear()
    assert truth.row() == {
        "world_id": truth.world_id,
        "bar": truth.bar,
        "nodes": len(truth),
        "discoveries": truth.discovery_count,
        "nulls": truth.null_count,
    }
    assert truth.calibrate(truth.discoveries()[:4]).row() == {
        "true_positives": 4,
        "false_positives": 0,
        "false_negatives": truth.discovery_count - 4,
        "true_negatives": truth.null_count,
    }
