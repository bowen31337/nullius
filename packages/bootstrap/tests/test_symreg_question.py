"""Feature 184's identical interface, answered for feature 183's world.

§10.6's constraint on every bootstrap world: *"Each exposes the **same**
``question.*`` API as a financial campaign, so a policy is portable
without modification."*  Feature 184 built the adapter over the
hyperparameter lattice; feature 183's world is its second costumer, and
these tests hold the portability where it lives — not in a list of
method names but in a *policy that runs*:

* **one policy, two worlds** — a small greedy hill-climb, written once
  against the ``question.*`` vocabulary alone, runs unmodified against
  the hyperparameter question and the symbolic question, commits on
  both, and never touches a domain-specific name.  If the interfaces
  had drifted, this is the test that could not pass.

* **the family is the node's own** — §11.1 exposes ``theme_root`` in
  ``meta()`` because the overfit signature is only partly
  family-invariant and a policy writes family-conditional thresholds;
  a symreg node reports ``symreg``, and the one adapter method whose
  content is per-domain is the one re-answered by
  :class:`~bootstrap.SymbolicQuestion`.  Everything else is inherited
  from feature 184's adapter *unmodified*, and the strongest way to pin
  that is behaviour: probes reveal ascending and idempotently, the
  budget is whole, and the reveal bookkeeping lives in the question
  while the world stays stateless.

* **the seams behind the interface ride too** — feature 189's
  ``ground_truth`` labels the symreg lattice through the same
  duck-typed surface it reads off every bootstrap world, and the
  perfect declaration scores the perfect reference; feature 185's trial
  ledger records a symreg question's probes with ``charges_budget``
  false, because §10.6's zero-cost clause is a statement about the
  category and this world is in it.
"""

from __future__ import annotations

import pytest
from bootstrap import (
    BOOTSTRAP_THEME_ROOT,
    DISCOVERY_BAR,
    PRICED_SEED,
    SYMREG_THEME_ROOT,
    BootstrapQuestion,
    BootstrapTrialLedger,
    BootstrapWorldError,
    GroundTruth,
    HyperparameterWorld,
    SymbolicQuestion,
    SymbolicRegressionWorld,
    ground_truth,
    question_for,
    symreg_question_for,
)


@pytest.fixture
def question(symreg_world: SymbolicRegressionWorld) -> SymbolicQuestion:
    """The policy-facing question over the committed symbolic world."""
    return symreg_question_for(symreg_world)


def _greedy_walk(question: BootstrapQuestion, *, steps: int = 8) -> str:
    """A policy, written once against ``question.*`` and nothing else.

    Greedy hill-climb: start at the declared root, probe the frontier,
    move to the best held-out score the reveal shows, stop when no
    neighbour beats where it stands, commit.  Deliberately free of any
    domain vocabulary — no axis names, no node-id spellings, no
    ``isinstance`` — because §10.6's portability is exactly the claim
    that this function needs none: the same object runs against a
    financial campaign, the hyperparameter world and the symbolic one.
    """
    (root,) = question.legal_roots()
    question.probe_batch([root])
    current = root
    best = question.observed()[root].r2_holdout
    for _ in range(steps):
        frontier = [cell for cell in question.legal_actions(current)]
        question.probe_batch(frontier)
        observed = question.observed()
        scored = [(observed[cell].r2_holdout, cell) for cell in frontier]
        score, cell = max(scored)
        if score <= best:
            break
        current, best = cell, score
    return question.commit(current)


# -- One policy, two worlds --------------------------------------------------------


def test_one_policy_runs_unmodified_against_both_domains() -> None:
    # §10.6's own sentence, executed: the policy above is written once,
    # against the ``question.*`` vocabulary alone, and runs against the
    # hyperparameter question and the symbolic question without a single
    # domain-conditional line.  Both walks commit a node of their own
    # world, and the committed observations carry their own world ids —
    # the attribution §10.6's "report the two pools separately" reads.
    hpo_question = question_for(
        HyperparameterWorld("bootstrap-hpo-20260921", seed=PRICED_SEED)
    )
    symreg_question = symreg_question_for(
        SymbolicRegressionWorld("bootstrap-symreg-20260922")
    )

    hpo_commit = _greedy_walk(hpo_question)
    symreg_commit = _greedy_walk(symreg_question)

    assert hpo_commit in hpo_question.observed()
    assert symreg_commit in symreg_question.observed()
    assert hpo_question.observed()[hpo_commit].world_id == "bootstrap-hpo-20260921"
    assert symreg_question.observed()[symreg_commit].world_id == (
        "bootstrap-symreg-20260922"
    )
    # The greedy walk actually walked on the symbolic world: it moved off
    # the root (the target's structure is findable) and it charged no
    # budget doing so.
    assert symreg_commit != symreg_question.legal_roots()[0]
    assert symreg_question.budget_remaining() == float("inf")


def test_the_symbolic_question_is_the_identical_adapter_subclassed() -> None:
    # The interface is inherited whole, not rebuilt: the symbolic
    # question *is* a ``BootstrapQuestion`` — the type a policy is
    # handed — and the only method it re-answers is the one whose
    # content is per-domain.  Pinned as a surface comparison so a
    # well-meaning override of, say, ``probe_batch`` cannot slip in and
    # quietly fork the two domains' behaviour.
    inherited = {
        name for name in BootstrapQuestion.__dict__ if not name.startswith("_")
    }
    overridden = {
        name for name in SymbolicQuestion.__dict__ if not name.startswith("_")
    }
    assert overridden == {"meta"}
    assert inherited >= {
        "observed",
        "legal_actions",
        "legal_roots",
        "probe_batch",
        "budget_remaining",
        "commit",
        "committed",
    }


def test_a_world_without_a_family_is_refused_its_symbolic_question() -> None:
    # The hyperparameter world answers every method the parent duck-types
    # over and declares no ``theme_root`` — the family is a fact the
    # meta reports, and an adapter that silently answered one the world
    # never claimed would be writing family-conditional thresholds on
    # the world's behalf.  The refusal names what is missing.
    hpo_world = HyperparameterWorld("bootstrap-hpo-20260921", seed=PRICED_SEED)
    assert not hasattr(hpo_world, "theme_root")
    with pytest.raises(BootstrapWorldError, match="declares its family"):
        symreg_question_for(hpo_world)  # type: ignore[arg-type]


# -- The meta's family and structure ----------------------------------------------


def test_the_root_meta_reports_no_parent_and_the_symreg_family(
    question: SymbolicQuestion, symreg_root_node: str
) -> None:
    meta = question.meta(symreg_root_node)
    assert meta.branch is None
    assert meta.depth == 0
    assert meta.parent is None
    assert meta.theme_root == SYMREG_THEME_ROOT == "symreg"
    # The family is not the first domain's: a policy's family-conditional
    # thresholds see a symreg node as a member of its own family.
    assert meta.theme_root != BOOTSTRAP_THEME_ROOT


def test_every_cells_meta_derives_from_the_step_vector(
    question: SymbolicQuestion, symreg_world: SymbolicRegressionWorld
) -> None:
    # The parent rule, re-answered over this lattice: depth is Σ|step|
    # read off the world, the parent is the neighbour one step toward
    # the root, and both the parent and the branch are cells and axes of
    # *this* lattice — the parent id decodes through the symreg codec
    # and the branch is one of the four symbolic axes.
    from bootstrap import (
        SYMBOLIC_AXIS_ORDER,
        decode_symbolic_node_id,
    )

    for node_id in symreg_world.cells():
        meta = question.meta(node_id)
        steps = symreg_world.steps(node_id)
        assert meta.depth == sum(abs(step) for step in steps)
        assert meta.theme_root == "symreg"
        if meta.depth == 0:
            assert meta.parent is None and meta.branch is None
            continue
        parent_steps = decode_symbolic_node_id(meta.parent)
        assert sum(abs(a - b) for a, b in zip(steps, parent_steps)) == 1
        assert max(abs(step) for step in parent_steps) < max(abs(s) for s in steps) or (
            meta.branch is not None
        )
        assert meta.branch in set(SYMBOLIC_AXIS_ORDER) or meta.branch is None
        assert meta.parent in set(symreg_world.cells())


# -- The reveal bookkeeping --------------------------------------------------------


def test_probes_reveal_ascending_and_idempotently(
    question: SymbolicQuestion, symreg_world: SymbolicRegressionWorld
) -> None:
    order: list[str] = []
    root = symreg_world.canonical_node()
    corner = "l+2.c+2.p+2.s+2"
    revealed = question.probe_batch([corner, root], on_reveal=order.append)
    assert order == sorted([root, corner]) == [root, corner]
    assert set(revealed) == {root, corner}
    # A re-probe of a held cell is not new: the call is idempotent on
    # the revealed set, and the observation is the world's own label.
    again = question.probe_batch([root])
    assert again == {}
    assert question.observed()[root].r2_holdout == (
        symreg_world.label(root).r2_holdout
    )


def test_a_batch_naming_a_cell_the_world_does_not_hold_refuses_whole(
    question: SymbolicQuestion,
) -> None:
    # All-or-nothing: a probe that named a cell outside the lattice
    # reveals nothing, because a half-applied batch would leave the
    # reveal set in a state the policy did not ask for.
    with pytest.raises(BootstrapWorldError, match="past the end"):
        question.probe_batch(["l+0.c+0.p+0.s+0", "l+0.c+0.p+9.s+0"])
    assert question.observed() == {}


def test_commit_answers_the_node_and_the_committed_reading(
    question: SymbolicQuestion, symreg_root_node: str
) -> None:
    assert question.committed is None
    assert question.commit(symreg_root_node) == symreg_root_node
    assert question.committed == symreg_root_node
    with pytest.raises(BootstrapWorldError, match="past the end"):
        question.commit("l+0.c+0.p+3.s+0")


# -- The seams behind the interface ------------------------------------------------


def test_ground_truth_labels_the_symbolic_lattice_and_scores_perfectly(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # Feature 189's labeling is duck-typed over the same surface the
    # question calls through, so the symbolic world joins it without a
    # third code path: every cell labelled, and the declaration naming
    # exactly the discoveries scores the perfect reference — 1.0/1.0,
    # the calibration anchor a measured rate is checked against.
    truth = ground_truth(symreg_world)
    assert isinstance(truth, GroundTruth)
    assert {label.node_id for label in truth.labels} == set(symreg_world.cells())
    discoveries = [label.node_id for label in truth.labels if label.is_discovery]
    nulls = [label.node_id for label in truth.labels if not label.is_discovery]
    assert len(discoveries) >= 2  # §7.3's floor, both sides
    assert len(nulls) >= 2
    matrix = truth.calibrate(discoveries)
    assert matrix.sensitivity == 1.0
    assert matrix.specificity == 1.0


def test_a_discovery_on_the_symbolic_world_clears_the_published_bar(
    symreg_world: SymbolicRegressionWorld,
) -> None:
    # The class the labels split on is the same class everywhere in the
    # category: a discovery is a held-out R² at or above the published
    # evidential bar, inclusive, whatever domain drew the score.
    truth = ground_truth(symreg_world)
    for label in truth.labels:
        assert label.is_discovery == (label.score >= DISCOVERY_BAR), label.node_id


def test_the_trial_ledger_records_a_symbolic_questions_probes_free(
    database_url: str, symreg_world: SymbolicRegressionWorld
) -> None:
    # §10.6's zero statistical-budget cost is a statement about the
    # category, and feature 185's ledger is where it reaches the
    # accounting: the ledger duck-types over ``probe_batch``, so the
    # symbolic question records through it like any other, one row per
    # newly revealed cell, each carrying ``charges_budget`` false.
    ledger = BootstrapTrialLedger(database_url)
    question = symreg_question_for(symreg_world)
    cells = ["l+1.c+0.p+0.s+0", "l+0.c+1.p+0.s+0"]
    recorded = ledger.record_trials(question, cells)
    # Rows land in probe order — ascending — not in the order the caller
    # spelled the batch, the same contract the hpo suite pins.
    assert [trial.node_id for trial in recorded] == sorted(cells)
    assert all(trial.charges_budget is False for trial in recorded)
    assert {trial.world_id for trial in recorded} == {symreg_world.world_id}
    # The record and the reveal cannot drift apart: the ledger revealed
    # through the question's own probe_batch.
    assert set(question.observed()) == set(cells)
