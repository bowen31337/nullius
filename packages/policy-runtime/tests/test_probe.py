"""Feature 220, ``probe_batch`` — the batch reveal and its reveal callback.

app_spec.xml, "Exploration Policy Runtime", feature 220 (``depends_on=217``):
*System exposes probe_batch accepting selected cells with a reveal callback,
which returns revealed observations.*  docs/nullius-tech-architecture.md §596
spells it in the identical ``question.*`` interface —

    question.probe_batch(cells, on_reveal=...)

— and prd §421 repeats it verbatim in §C4's listing, where the same section
states the constraint that makes the verb matter: *"must terminate when no
batch is selected"* (prd §436).  The batch is therefore the unit of a policy's
decision, and ``probe_batch`` is the one verb that extends the prefix a policy
is prefix-only over.

Three properties are what this suite exists to pin, and each is a place the
feature could quietly be wrong:

* **the batch is a batch** — deduplicated, in ascending node-id order (docs
  §12's ordering rule, already fixed for ``observed()``), and all-or-nothing:
  every cell is validated against the tree *before* any is revealed, so one
  bad cell refuses the whole call and the reveal set is never left
  half-applied (the shape feature 184's
  :meth:`bootstrap.BootstrapQuestion.probe_batch` already ships on the other
  pool, and the reason one policy runs unmodified across both);
* **the callback is the feature's second half** — ``on_reveal`` fires *once
  per newly revealed cell*, in that same ascending order, and never for a cell
  the question already held.  A re-probe is not a double-count, and the hook
  fires **after** the reveal set has grown, so a callback reading
  ``observed()`` sees the batch already applied.  A hook the question cannot
  call is refused *before* any cell is revealed, in this member's own
  vocabulary rather than as a bare :class:`TypeError`;
* **the return value is the newly revealed readings** — ``{node_id:
  Observation}`` for the cells revealed by *this* call, equal to the ones
  ``observed()`` reports for those cells, to the last field.  An
  already-revealed cell is not re-returned: the call is idempotent on the
  revealed set.

``reveal_many`` is pinned here too, because it and ``probe_batch`` are two
names for one act: the delegation is checked rather than assumed, so a second
implementation cannot grow behind the older spelling and drift.

The suite needs no fixture beyond the canonical tree every member suite
already builds, and no database: a probe is a pure function of the question's
reveal set and the tree it fronts.
"""

from __future__ import annotations

import pytest

from policy_runtime import (
    PolicyAddressError,
    PolicyObservation,
    PolicyQuestion,
    PolicyRuntimeError,
    PolicyTreeError,
    policy_question,
)

# ---------------------------------------------------------------------------
# The batch itself — what is revealed, and what is returned
# ---------------------------------------------------------------------------


def test_probe_batch_reveals_the_batch_and_returns_the_new_observations(
    question: PolicyQuestion,
) -> None:
    # The whole of the feature's sentence: a batch of selected cells is
    # revealed, and the revealed observations come back keyed by node id —
    # one PolicyObservation per cell, the tree's honest reading.
    revealed = question.probe_batch(["n1", "n2"])
    assert set(revealed) == {"n1", "n2"}
    assert all(isinstance(cell, PolicyObservation) for cell in revealed.values())
    assert set(question.revealed) == {"n1", "n2"}
    assert set(question.observed()) == {"n1", "n2"}


def test_probe_batch_is_ascending_whatever_order_the_cells_arrive_in(
    question: PolicyQuestion,
) -> None:
    # The ordering rule docs §12 states for a search frontier, applied to the
    # batch: the call is reduced to ``sorted(set(cells))`` before anything
    # happens, so the returned mapping, the reveal order and the callbacks all
    # run ascending — a policy that enumerates without sorting still sees a
    # deterministic order, and two probes of one batch agree.
    seen: list[str] = []
    revealed = question.probe_batch(["n2", "n1"], on_reveal=seen.append)
    assert list(revealed) == ["n1", "n2"]
    assert seen == ["n1", "n2"]


def test_probe_batch_deduplicates_the_batch(question: PolicyQuestion) -> None:
    # A duplicate in the batch is one cell: the call reveals it once, returns
    # it once, and fires the callback once.  Deduplication is what makes "once
    # per newly revealed cell" well-defined for a batch that names a cell
    # twice — without it the callback's contract would depend on how the
    # caller spelled the batch rather than on what it revealed.
    seen: list[str] = []
    revealed = question.probe_batch(["n1", "n1", "n2", "n1"], on_reveal=seen.append)
    assert set(revealed) == {"n1", "n2"}
    assert seen == ["n1", "n2"]
    assert question.revealed == frozenset({"n1", "n2"})


def test_probe_batch_returns_the_new_readings_only(question: PolicyQuestion) -> None:
    # The call is idempotent on the revealed set: a second probe of cells the
    # question already holds returns nothing, so a policy that re-probes a cell
    # it holds does not see it as new — the property feature 184's pool states
    # in the same words, so a policy written against one pool behaves the same
    # in the other.
    question.probe_batch(["n1", "n2"])
    again = question.probe_batch(["n1", "n2"])
    assert again == {}
    assert question.revealed == frozenset({"n1", "n2"})


def test_probe_batch_returns_only_the_cells_it_newly_revealed(
    question: PolicyQuestion,
) -> None:
    # A batch mixing a held cell with a new one returns only the new one —
    # "revealed by this call" is the whole of the return value's contract.
    question.probe_batch(["n1"])
    second = question.probe_batch(["n1", "n2"])
    assert set(second) == {"n2"}


def test_probe_batch_of_an_empty_batch_reveals_nothing(question: PolicyQuestion) -> None:
    # The empty batch is the selection prd §436 names as termination, and this
    # verb's answer to it is the empty mapping: no reveal, no callback, no
    # error.  It is not a refusal — "the policy selected no batch" is a state
    # the caller judges, not a malformed ask.
    seen: list[str] = []
    assert question.probe_batch([], on_reveal=seen.append) == {}
    assert question.revealed == frozenset()
    assert seen == []


def test_probe_batch_reads_any_iterable_of_cells(question: PolicyQuestion) -> None:
    # ``cells`` is an iterable, spelled §11's way.  A tuple, a generator and a
    # set are all batches; the set case is worth pinning because it is the one
    # whose iteration order is not the caller's, and the ascending reduction is
    # what makes it deterministic anyway.
    from_tuple = question.probe_batch(("n1", "n2"))
    assert list(from_tuple) == ["n1", "n2"]
    fresh = policy_question(question.tree)
    from_generator = fresh.probe_batch(cell for cell in ["n2", "n1"])
    assert list(from_generator) == ["n1", "n2"]
    from_set = policy_question(question.tree).probe_batch({"n1", "n2"})
    assert list(from_set) == ["n1", "n2"]


# ---------------------------------------------------------------------------
# The reveal callback — the feature's second half
# ---------------------------------------------------------------------------


def test_probe_batch_calls_on_reveal_once_per_new_cell(question: PolicyQuestion) -> None:
    # ``on_reveal`` is called once per newly revealed cell, in ascending node
    # id order — the hook a replay uses to record what a policy looked at.  An
    # already-revealed cell does not fire it again, so a re-probe is not a
    # double-count and the hook's count is the prefix's growth.
    seen: list[str] = []
    question.probe_batch(["n1", "n2"], on_reveal=seen.append)
    assert seen == ["n1", "n2"]
    question.probe_batch(["n1"], on_reveal=seen.append)
    assert seen == ["n1", "n2"]  # unchanged: n1 was already held


def test_probe_batch_fires_on_reveal_only_for_the_new_cells(
    question: PolicyQuestion,
) -> None:
    # A mixed batch fires the hook for exactly the new cells, in ascending
    # order, so a hook's sequence is the growth of the prefix rather than the
    # batch's spelling.
    question.probe_batch(["n1"])
    seen: list[str] = []
    question.probe_batch(["n2", "n1"], on_reveal=seen.append)
    assert seen == ["n2"]


def test_the_callback_receives_the_node_id(question: PolicyQuestion) -> None:
    # The hook is handed the *node id*, not the observation: the id is the
    # address the reveal set is keyed by and the one fact a hook needs to act
    # on, while the readings are what the return value is for.  It is also
    # what the sibling pool's ``on_reveal`` passes, so a hook written against
    # one pool runs unmodified against the other — the identical-interface
    # requirement applied to the callback rather than to the verb.
    seen: list[object] = []
    question.probe_batch(["n1"], on_reveal=seen.append)
    assert seen == ["n1"]
    assert all(isinstance(cell, str) for cell in seen)


def test_the_callback_fires_after_the_batch_is_applied(question: PolicyQuestion) -> None:
    # The order of the acts is load-bearing: the whole batch is revealed
    # *first*, then the callbacks fire, then the mapping is returned.  A hook
    # that reads ``observed()`` inside ``on_reveal`` therefore sees the batch
    # already applied rather than a prefix caught mid-sweep — which is what
    # makes the hook usable for recording "what does the prefix look like
    # now?" rather than only "which cell was just added?".
    #
    # Note the weaker reading this is *not*: the callbacks are not interleaved
    # with the reveals, so the first hook already sees the second cell.  That
    # is the sibling pool's order too (bootstrap reveals its whole batch before
    # calling the hook), and matching it is what keeps a hook written against
    # one pool honest against the other.
    observed_at_hook: list[set[str]] = []
    question.probe_batch(
        ["n1", "n2"],
        on_reveal=lambda cell: observed_at_hook.append(set(question.observed())),
    )
    assert observed_at_hook == [{"n1", "n2"}, {"n1", "n2"}]


def test_probe_batch_with_no_hook_is_silent(question: PolicyQuestion) -> None:
    # ``on_reveal`` is optional — the default is no hook at all, and passing
    # ``None`` explicitly is the same call.  A policy that wants only the
    # readings pays nothing for a callback it did not ask for.
    assert set(question.probe_batch(["n1", "n2"])) == {"n1", "n2"}
    assert set(question.probe_batch(["n1", "n2"], on_reveal=None)) == set()


def test_a_callback_that_raises_leaves_the_reveal_set_correct(
    question: PolicyQuestion,
) -> None:
    # A hook that raises propagates its own exception — the member does not
    # swallow a caller's failure — but it does so *after* the whole batch was
    # revealed, so the reveal set is correct rather than half-written and a
    # replay reading it afterwards sees the honest prefix.  The hook is the
    # caller's code; the reveal is the question's.
    def boom(cell: str) -> None:
        raise RuntimeError(f"the caller's hook failed on {cell!r}")

    with pytest.raises(RuntimeError, match="the caller's hook failed"):
        question.probe_batch(["n1", "n2"], on_reveal=boom)
    assert question.revealed == frozenset({"n1", "n2"})


def test_probe_batch_refuses_a_hook_that_is_not_callable(
    question: PolicyQuestion,
) -> None:
    # A value the question cannot call is refused in this member's own
    # vocabulary rather than as a bare ``TypeError`` escaping the loop after
    # the reveal set had already grown — the error-vocabulary discipline every
    # seam in this member keeps, and the reason a caller's own ``except
    # PolicyRuntimeError`` catches it.  Refusing *up front* is what makes the
    # call all-or-nothing on the hook side too.
    for not_a_hook in ("n1", ["n1"], 7, object()):
        with pytest.raises(PolicyTreeError, match="on_reveal"):
            question.probe_batch(["n1"], on_reveal=not_a_hook)  # type: ignore[arg-type]
    assert question.revealed == frozenset()


def test_a_refused_hook_is_refused_before_anything_is_revealed(
    question: PolicyQuestion,
) -> None:
    # The hook is validated before the batch is touched, so a call carrying
    # both a bad hook and a cell outside the tree refuses on the *hook* — the
    # ask is judged as an ask, whole, before anything is read.  Either refusal
    # leaves the reveal set untouched; what this pins is that the hook's own
    # refusal is available without having revealed a single cell first.
    with pytest.raises(PolicyTreeError, match="on_reveal"):
        question.probe_batch(["ghost"], on_reveal="nope")  # type: ignore[arg-type]
    assert question.revealed == frozenset()
    assert question.observed() == {}


def test_the_hook_refusal_is_a_policy_runtime_error(question: PolicyQuestion) -> None:
    # Caught by the member's one base class, so a caller wrapping an episode in
    # ``except PolicyRuntimeError`` hears about a bad hook the same way it
    # hears about every other refusal on this path.
    with pytest.raises(PolicyRuntimeError):
        question.probe_batch(["n1"], on_reveal="nope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# All-or-nothing — a bad cell refuses the whole batch
# ---------------------------------------------------------------------------


def test_probe_batch_refuses_a_cell_the_tree_does_not_hold(
    question: PolicyQuestion,
) -> None:
    # A policy cannot reveal a cell it was never shown, and a reveal that
    # silently skipped a bad cell would let the policy think it had seen one.
    # The refusal is the tree's own — the same class ``reveal`` refuses
    # through — so one contract is read at every verb that names a node.
    with pytest.raises(PolicyAddressError):
        question.probe_batch(["n1", "ghost"])
    assert question.revealed == frozenset()


def test_a_refused_batch_reveals_none_of_its_cells(question: PolicyQuestion) -> None:
    # All-or-nothing: the whole batch is validated against the tree *before*
    # any cell is revealed, so a batch that names one cell outside the tree
    # reveals none of them.  A half-applied batch would leave the reveal set in
    # a state the policy did not ask for, and no reveal would have earned it.
    cells = ["n1", "n2", "ghost"]
    with pytest.raises(PolicyAddressError):
        question.probe_batch(cells)
    assert question.revealed == frozenset()
    assert question.observed() == {}


def test_a_refused_batch_fires_no_callback(question: PolicyQuestion) -> None:
    # The hook is downstream of the validation, so a refused batch is silent:
    # a replay recording what a policy looked at records nothing for a batch
    # that revealed nothing.
    seen: list[str] = []
    with pytest.raises(PolicyAddressError):
        question.probe_batch(["n1", "ghost"], on_reveal=seen.append)
    assert seen == []


def test_an_already_held_cell_does_not_rescue_a_bad_batch(
    question: PolicyQuestion,
) -> None:
    # A held cell does not make the batch legal: the refusal is about the cell
    # the tree does not hold, and a policy cannot slip one invalid reveal past
    # a batch of cells it already has — including a batch that is *entirely*
    # held cells plus one bad one.
    question.probe_batch(["n1"])
    with pytest.raises(PolicyAddressError):
        question.probe_batch(["n1", "ghost"])
    assert question.revealed == frozenset({"n1"})


def test_probe_batch_refuses_a_misspelled_cell_naming_it(question: PolicyQuestion) -> None:
    # The refusal names the node, so an operator reading a replay's failure can
    # tell which cell refused — the "name the subject in the refusal" discipline
    # the tree's own address seam keeps.
    with pytest.raises(PolicyAddressError, match="ghost"):
        question.probe_batch(["ghost"])


# ---------------------------------------------------------------------------
# The readings — the return value and observed() are one reading
# ---------------------------------------------------------------------------


def test_probe_batch_readings_match_the_observed_mapping(
    question: PolicyQuestion,
) -> None:
    # One implementation of the reading: the observations a probe returns are
    # the ones ``observed()`` reports for those cells, to the last field — so a
    # policy reading the return value and a policy reading the accessor are
    # reading one thing, and a second derivation cannot drift in.
    returned = question.probe_batch(["n1", "n2"])
    observed = question.observed()
    assert returned == observed
    assert returned["n1"].row() == observed["n1"].row()


def test_probe_batch_carries_the_trees_honest_reading(question: PolicyQuestion) -> None:
    # The observation a probe returns is the tree's honest payload-derived
    # reading, unchanged — the in-sample metrics the node carries, attributed
    # to the node id they were earned on.  Nothing is rescored or narrowed on
    # the way through the batch.
    returned = question.probe_batch(["n1"])["n1"]
    assert returned.node_id == "n1"
    assert returned.r2_insample == 0.20
    assert returned.ic_insample == 0.05
    assert returned.n_periods == 500
    assert returned.n_features == 12


def test_a_probe_makes_a_structural_node_answer_none(question: PolicyQuestion) -> None:
    # A node whose payload carries no in-sample reading is a structural node,
    # not a scored leaf, and its observation says so rather than inventing a
    # number — the same honesty ``observed()`` shows, reached through the batch.
    returned = question.probe_batch(["n0"])["n0"]
    assert returned.node_id == "n0"
    assert returned.r2_insample is None


def test_probe_batch_is_prefix_only_after_the_probe(question: PolicyQuestion) -> None:
    # The batch grows the prefix and nothing else: after a probe the question
    # still answers only the cells it has revealed, and the unrevealed node is
    # absent from the mapping rather than filtered out of it (docs §10.2,
    # cq-16).  A batch verb that widened what a policy could *read* would be a
    # reveal by other means.
    question.probe_batch(["n1"])
    assert set(question.observed()) == {"n1"}
    assert "n2" not in question.observed()


# ---------------------------------------------------------------------------
# reveal_many — the older spelling, delegated rather than reimplemented
# ---------------------------------------------------------------------------


def test_reveal_many_is_the_same_act_as_probe_batch(question: PolicyQuestion) -> None:
    # Two names, one behaviour: ``reveal_many`` is what feature 217 shipped the
    # batch under and ``probe_batch`` is what §11 calls it, so the second is a
    # delegation to the first rather than a second body free to drift.  Pinned
    # by running each over its own question and comparing every field.
    by_probe = question.probe_batch(["n2", "n1"])
    fresh = policy_question(question.tree)
    by_reveal_many = fresh.reveal_many(["n2", "n1"])
    assert by_probe == by_reveal_many
    assert set(by_probe) == set(by_reveal_many) == {"n1", "n2"}
    assert [cell.row() for cell in by_probe.values()] == [
        cell.row() for cell in by_reveal_many.values()
    ]


def test_reveal_many_is_idempotent_the_same_way(question: PolicyQuestion) -> None:
    # The older spelling inherits the newer one's contract, idempotence
    # included — the delegation is the point, so a caller of either name gets
    # one set of guarantees.
    question.reveal_many(["n1", "n2"])
    assert question.probe_batch(["n1", "n2"]) == {}
    assert question.reveal_many(["n1", "n2"]) == {}


def test_reveal_many_refuses_a_bad_cell_the_same_way(question: PolicyQuestion) -> None:
    # And the all-or-nothing refusal, from either spelling: one contract read
    # at two verbs, which is what the delegation buys.
    with pytest.raises(PolicyAddressError):
        question.reveal_many(["n1", "ghost"])
    assert question.revealed == frozenset()


# ---------------------------------------------------------------------------
# One policy, both pools — the identical-interface claim
# ---------------------------------------------------------------------------


def test_probe_batch_signature_matches_the_documented_call() -> None:
    # §11's line is ``question.probe_batch(cells, on_reveal=...)``, and this
    # pins the *shape* of that call rather than only its behaviour: two
    # parameters, the second with a default, so a policy written against the
    # documented signature calls the verb the documented way — and a hook can
    # be passed positionally or by keyword, as the sibling pool's does.
    import inspect

    signature = inspect.signature(PolicyQuestion.probe_batch)
    parameters = list(signature.parameters.values())
    assert [parameter.name for parameter in parameters] == ["self", "cells", "on_reveal"]
    assert parameters[2].default is None
    assert parameters[2].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["on_reveal"].annotation != inspect.Parameter.empty


def test_the_canonical_policy_walk_runs_against_a_campaign_question(
    question: PolicyQuestion,
) -> None:
    # §10.6's own sentence — *"each exposes the same ``question.*`` API as a
    # financial campaign, so a policy is portable without modification"* —
    # executed against the verb this feature adds.  The walk a bootstrap policy
    # is written as (probe the root, probe the frontier, move to the best
    # reading, commit) runs here over a ``PolicyQuestion`` with no
    # domain-conditional line, which is the property `probe_batch` existing
    # under this name is for.
    seen: list[str] = []
    (root,) = ["n0"]  # this tree's root, the node a walk starts from
    question.probe_batch([root], on_reveal=seen.append)
    frontier = ["n1", "n2"]
    question.probe_batch(frontier, on_reveal=seen.append)
    observed = question.observed()
    best = max(frontier, key=lambda cell: observed[cell].r2_insample)
    assert best == "n2"
    assert seen == ["n0", "n1", "n2"]
    assert set(observed) == {"n0", "n1", "n2"}
