"""Feature 161: *quarantines a node together with its subtree after a seccomp violation*.

The sentence decomposes into three claims and the classes below follow it.  A
**seccomp violation** is the trigger, and the only one: feature 160's gate
publishes a :class:`~sandbox.syscalls.Commitment` on
:attr:`~sandbox.syscalls.SyscallDecision.violation` when a process reached for a
syscall the committed ceiling does not admit, and that value — taken from the
gate itself by :func:`~_documents.quarantine_violation_from_gate` rather than
re-spelled — is what these tests hand the law.  A **node together with its
subtree** is the subject, so the tree arrives as rows and the closure is checked
against a branch that has a sibling in it, because a tree that is one chain
cannot tell "the subtree" from "everything below the root".  A persisted
**``sandbox_escape`` fail class** is the write, and it lands on the failing node's
own class field while the halt lands on every node of the branch.

**What this suite deliberately does not do is open a database.**  The member's
one-provenance rule keeps the box stdlib-only and store-free, so the caller
fetches §9.1's ``node`` rows and hands them in; the same division
:mod:`sandbox.seed` and :mod:`sandbox.timeout` draw for the run and the record
they are given.  Nothing here imports ``sqlite3``, ``os`` or ``subprocess``, and
the last class below says so by checking the module's *own* imports — which is
the honest form of the claim, because a law that had grown a dependency would
have to grow an import to use it.
"""

from __future__ import annotations

import datetime as dt
from types import MappingProxyType

import pytest
import sandbox
from _documents import (
    DISALLOWED_NETWORK_SYSCALL,
    DISALLOWED_SYSCALL,
    ERRNO_ACTION,
    ESCAPE_CLASS,
    KILL_ACTION,
    OTHER_CAMPAIGN_CHILD_ID,
    OTHER_CAMPAIGN_ROOT_ID,
    OTHER_QUARANTINE_CAMPAIGN,
    QUARANTINE_CAMPAIGN,
    QUARANTINE_CHILD_ID,
    QUARANTINE_GRANDCHILD_ID,
    QUARANTINE_GREATGRANDCHILD_ID,
    QUARANTINE_ROOT_ID,
    QUARANTINE_SIBLING_ID,
    SIGNAL_SANDBOX,
    cyclic_rows,
    node_row,
    quarantine_record,
    quarantine_rows,
    quarantine_violation_from_gate,
    self_parented_rows,
    two_campaign_rows,
)
from sandbox.errors import (
    QuarantineTreeError,
    SandboxEscapeQuarantine,
    SandboxQuarantineError,
)
from sandbox.quarantine import (
    NODE_QUARANTINED_COLUMN,
    QUARANTINE_COLUMNS,
    QUARANTINE_COMPONENT_NAME,
    QUARANTINE_FAIL_CLASS,
    QUARANTINE_MISMATCH_CODE,
    QUARANTINE_REQUIRED_CODE,
    QUARANTINE_TABLE,
    QUARANTINE_TREE_CODE,
    NodeTree,
    Quarantine,
    QuarantineReason,
    QuarantineRecord,
    SandboxQuarantine,
    quarantine_violation,
    quarantines,
    sandbox_quarantine,
)


def _tree(*, depth: int = 3) -> NodeTree:
    """The default branch: root → child → grandchild → great-grandchild + sibling."""
    return NodeTree(quarantine_rows(depth=depth))


def _records(tree: NodeTree, **overrides: object) -> dict[str, dict[str, object]]:
    """A caller's record mapping for every node of ``tree``, fresh per call."""
    records: dict[str, dict[str, object]] = {
        node_id: quarantine_record(node_id) for node_id in tree.node_ids()
    }
    for node_id, record in overrides.items():
        records[node_id] = record  # type: ignore[assignment]
    return records


class TestTheTriggerIsTheSeccompViolation:
    """Claim one: *after a seccomp violation* — and after nothing else."""

    def test_the_gates_own_commitment_halts_its_branch(self) -> None:
        # The handoff under test is the value feature 160 actually publishes, so
        # the subject is built by running the gate rather than by constructing a
        # Commitment — a stand-in would test a shape this law tolerates rather
        # than the one it is given in production.
        gate = quarantine_violation_from_gate()
        assert gate.violation is not None
        assert gate.violation.fail_class == ESCAPE_CLASS

        decision = quarantine_violation(gate, _tree())

        assert decision.reason is QuarantineReason.QUARANTINED
        assert decision.quarantined is True
        assert decision.refused is False
        assert decision.quarantine is not None
        assert decision.quarantine.fail_class == QUARANTINE_FAIL_CLASS == "sandbox_escape"

    def test_a_commitment_passed_directly_is_read_the_same_way(self) -> None:
        # A caller that already flattened the gate's answer into the Commitment
        # itself (a ledger row, an operator script) hands that in rather than
        # rebuilding a decision — the same tolerance `reject_syscall` shows for
        # an object carrying only a `syscall` attribute.
        commitment = quarantine_violation_from_gate().violation

        assert quarantines(commitment, _tree()) is True

    def test_a_mapping_carrying_the_three_fields_is_read_the_same_way(self) -> None:
        # The third accepted shape, and the one a store round trip produces: a
        # row with the class, the syscall and the action, and the node it names.
        row = {
            "fail_class": ESCAPE_CLASS,
            "syscall": DISALLOWED_SYSCALL,
            "action": KILL_ACTION,
            "node_id": QUARANTINE_CHILD_ID,
        }

        decision = quarantine_violation(row, _tree())

        assert decision.quarantined is True
        assert decision.quarantine is not None
        assert decision.quarantine.syscall == DISALLOWED_SYSCALL

    def test_the_errno_action_still_carries_the_class_the_gate_publishes(self) -> None:
        # `errno` is the other denying action: a call that failed and a process
        # that kept running.  The *fate* differs from `kill` and the class does
        # not — feature 160's commitment publishes `sandbox_escape` either way —
        # so this law quarantines for both and records which action it was.
        gate = quarantine_violation_from_gate(
            syscall=DISALLOWED_NETWORK_SYSCALL, default_action=ERRNO_ACTION
        )
        assert gate.violation.killed is False

        decision = quarantine_violation(gate, _tree())

        assert decision.quarantined is True
        assert decision.quarantine is not None
        assert decision.quarantine.action == ERRNO_ACTION

    def test_an_admitted_call_halts_nothing(self) -> None:
        # The gate answers `None` on its `violation` for a call inside the
        # ceiling.  That is the run continuing rather than a caller being told it
        # did something wrong, which is why this is not a refusal.
        from _documents import ADMITTED_SYSCALL, syscall_attempt
        from sandbox.syscalls import SandboxSyscalls, committed_syscalls_policy

        gate = SandboxSyscalls(committed_syscalls_policy()).check(
            syscall_attempt(syscall=ADMITTED_SYSCALL)
        )

        decision = quarantine_violation(gate, _tree())

        assert decision.reason is QuarantineReason.NOTHING_TO_QUARANTINE
        assert decision.quarantined is False
        assert decision.refused is False

    def test_an_unreadable_attempt_is_not_an_escape_attempt(self) -> None:
        # Feature 160 documents this case explicitly: an attempt whose syscall
        # cannot be read as a name at all comes back with no violation, and the
        # gate deliberately does not call it an escape attempt.  So there is no
        # branch to halt — the run continues, nothing raises, nothing is marked.
        from _documents import syscall_attempt
        from sandbox.syscalls import SandboxSyscalls, committed_syscalls_policy

        gate = SandboxSyscalls(committed_syscalls_policy()).check(
            syscall_attempt(syscall=None)
        )

        decision = quarantine_violation(gate, _tree())

        assert decision.reason is QuarantineReason.NOTHING_TO_QUARANTINE
        assert decision.refused is False

    def test_none_halts_nothing(self) -> None:
        # The degenerate form of the same case, and the one a caller reaches by
        # passing a variable that happened to be empty.
        assert quarantine_violation(None, _tree()).reason is (
            QuarantineReason.NOTHING_TO_QUARANTINE
        )

    def test_a_run_that_timed_out_is_refused_rather_than_quarantined(self) -> None:
        # §15's recovery column belongs to one row.  A timeout is feature 163's
        # fact and feature 163's record; halting a subtree for it would retire a
        # branch for a failure no ceiling was ever compared against.
        subject = {
            "fail_class": "timeout",
            "syscall": "wait4",
            "action": "kill",
            "node_id": QUARANTINE_CHILD_ID,
        }

        decision = quarantine_violation(subject, _tree())

        assert decision.reason is QuarantineReason.FOREIGN_CLASS
        assert decision.refused is True
        assert decision.quarantined is False

    @pytest.mark.parametrize("cls", ["ok", "error", "tripwire_fail", "crash", "oom"])
    def test_every_other_terminal_class_is_refused(self, cls: str) -> None:
        subject = {
            "fail_class": cls,
            "syscall": DISALLOWED_SYSCALL,
            "action": KILL_ACTION,
            "node_id": QUARANTINE_CHILD_ID,
        }

        decision = quarantine_violation(subject, _tree())

        assert decision.reason is QuarantineReason.FOREIGN_CLASS
        assert cls in decision.detail

    def test_a_subject_that_is_only_shaped_like_a_violation_is_refused(self) -> None:
        # A mapping carrying the class but not the syscall or the action is not
        # evidence a branch should be halted on: a violation is a *record of an
        # event*, and a record missing half the event is not one.
        subject = {"fail_class": ESCAPE_CLASS, "node_id": QUARANTINE_CHILD_ID}

        decision = quarantine_violation(subject, _tree())

        assert decision.reason is QuarantineReason.UNREADABLE_VIOLATION
        assert decision.refused is True

    def test_a_violation_carrying_no_node_is_refused(self) -> None:
        # Feature 160 lets an attempt carry an empty node id — the gate judges a
        # call, not a candidate — so this law has to refuse rather than close a
        # branch over the empty string.
        gate = quarantine_violation_from_gate(node_id="")

        decision = quarantine_violation(gate, _tree())

        assert decision.reason is QuarantineReason.UNKNOWN_NODE
        assert decision.refused is True

    def test_a_violation_naming_a_node_outside_the_fetch_is_refused(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_GRANDCHILD_ID)
        partial = NodeTree([node_row(QUARANTINE_ROOT_ID), node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_ROOT_ID, depth=1)])

        decision = quarantine_violation(gate, partial)

        assert decision.reason is QuarantineReason.UNKNOWN_NODE
        assert QUARANTINE_GRANDCHILD_ID in decision.detail

    def test_a_tree_this_law_cannot_walk_is_refused(self) -> None:
        gate = quarantine_violation_from_gate()

        decision = quarantine_violation(gate, quarantine_rows())  # type: ignore[arg-type]

        assert decision.reason is QuarantineReason.UNREADABLE_VIOLATION
        assert "NodeTree" in decision.detail


class TestTheBranchIsTheNodeAndItsSubtree:
    """Claim two: *a node together with its subtree* — a branch, not a row."""

    def test_the_violating_node_and_every_descendant_are_halted(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert quarantine.nodes == (
            QUARANTINE_CHILD_ID,
            QUARANTINE_GRANDCHILD_ID,
            QUARANTINE_GREATGRANDCHILD_ID,
        )
        assert quarantine.size == 3
        assert quarantine.descendants == (
            QUARANTINE_GRANDCHILD_ID,
            QUARANTINE_GREATGRANDCHILD_ID,
        )

    def test_the_root_of_the_campaign_takes_the_whole_campaign(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_ROOT_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert quarantine.size == 5
        assert set(quarantine.nodes) == {
            QUARANTINE_ROOT_ID,
            QUARANTINE_CHILD_ID,
            QUARANTINE_GRANDCHILD_ID,
            QUARANTINE_GREATGRANDCHILD_ID,
            QUARANTINE_SIBLING_ID,
        }

    def test_a_leaf_takes_only_itself(self) -> None:
        # The narrow end: a violation at a leaf halts one node.  Without this the
        # closure could be returning "everything below the root" and every other
        # test here would still pass.
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_GREATGRANDCHILD_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert quarantine.nodes == (QUARANTINE_GREATGRANDCHILD_ID,)
        assert quarantine.descendants == ()

    def test_a_sibling_branch_is_not_halted(self) -> None:
        # The control.  The sibling hangs off the same root as the violating
        # node's ancestor, so a closure that walked *up* as well as down, or that
        # took everything in the campaign from the top, would sweep it in.
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert QUARANTINE_SIBLING_ID not in quarantine.nodes

    def test_a_branch_never_crosses_a_campaign(self) -> None:
        # A descendant reachable by `parent_id` but sitting in a different
        # campaign is not in the branch.  The tree the caller fetched happens to
        # hold two campaigns' rows, and the scope comes from the violating node's
        # own row rather than from a parameter — so the leak is caught here
        # rather than by a caller remembering to pass a campaign.
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)

        quarantine = quarantine_violation(gate, NodeTree(two_campaign_rows())).quarantine

        assert quarantine is not None
        assert OTHER_CAMPAIGN_CHILD_ID not in quarantine.nodes
        assert OTHER_CAMPAIGN_ROOT_ID not in quarantine.nodes
        assert quarantine.campaign_id == QUARANTINE_CAMPAIGN

    def test_the_campaign_of_the_violating_node_bounds_the_closure(self) -> None:
        # The same fact from the other side: a violation *in* the second campaign
        # halts that campaign's branch and nothing of the first's.
        rows = two_campaign_rows()
        rows.append(
            node_row(
                "7b8c9d0e-1f2a-4b3c-8d4e-5f6a7b8c9d0e",
                parent_id=OTHER_CAMPAIGN_CHILD_ID,
                campaign_id=OTHER_QUARANTINE_CAMPAIGN,
                depth=2,
            )
        )
        # A mapping rather than a gate decision, deliberately: the gate is
        # handed a node id it does not verify, so the row is what names the node
        # this branch is closed over.
        decision = quarantine_violation(
            {
                "fail_class": ESCAPE_CLASS,
                "syscall": DISALLOWED_SYSCALL,
                "action": KILL_ACTION,
                "node_id": OTHER_CAMPAIGN_ROOT_ID,
            },
            NodeTree(rows),
        )

        assert decision.quarantine is not None
        assert decision.quarantine.campaign_id == OTHER_QUARANTINE_CAMPAIGN
        assert QUARANTINE_CHILD_ID not in decision.quarantine.nodes

    def test_the_depth_is_measured_from_the_violating_node(self) -> None:
        # An operator reading a quarantine row asks how much of the branch the
        # escape retired, so the root of the *closure* is 0 — not the campaign's
        # tree root.
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert quarantine.depth_of(QUARANTINE_CHILD_ID) == 0
        assert quarantine.depth_of(QUARANTINE_GRANDCHILD_ID) == 1
        assert quarantine.depth_of(QUARANTINE_GREATGRANDCHILD_ID) == 2

    def test_the_depth_of_the_campaign_root_is_zero(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_ROOT_ID)

        quarantine = quarantine_violation(gate, _tree()).quarantine

        assert quarantine is not None
        assert quarantine.depth_of(QUARANTINE_ROOT_ID) == 0
        assert quarantine.depth_of(QUARANTINE_SIBLING_ID) == 1


class TestTheCyclicTreeIsRefused:
    """The walk is iterative and the cycle is named, so a malformed tree refuses."""

    def test_two_nodes_that_name_each_other_are_refused(self) -> None:
        # A `UNION ALL` recursion over these edges never terminates — the query
        # does not fail, it hangs — so a closure walked in SQL cannot produce
        # this refusal at all.  Walking in Python is what makes it reachable.
        decision = quarantine_violation(quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID), NodeTree(cyclic_rows()))

        assert decision.reason is QuarantineReason.CYCLIC_TREE
        assert decision.refused is True

    def test_a_node_that_is_its_own_parent_is_refused(self) -> None:
        decision = quarantine_violation(
            quarantine_violation_from_gate(node_id=QUARANTINE_ROOT_ID),
            NodeTree(self_parented_rows()),
        )

        assert decision.reason is QuarantineReason.CYCLIC_TREE

    def test_the_refusal_is_the_named_tree_error(self) -> None:
        # The closure raises `QuarantineTreeError`; the trigger translates it to a
        # reason rather than letting it escape, because §6.1 runs the sandbox
        # unattended and a law that killed the run on its tenth candidate would
        # take the run with it.
        tree = NodeTree(cyclic_rows())

        with pytest.raises(QuarantineTreeError) as raised:
            tree.subtree(QUARANTINE_CHILD_ID)

        assert QUARANTINE_TREE_CODE in str(raised.value)
        assert isinstance(raised.value, SandboxQuarantineError)

    def test_a_cyclic_tree_is_still_a_refusal_from_the_convenience(self) -> None:
        # `quarantines` never raises — a caller that only wants the predicate
        # gets `False` rather than a traceback, and one that needs to tell the
        # cases apart reads the decision.
        assert quarantines(
            quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID),
            NodeTree(cyclic_rows()),
        ) is False


class TestTheTreeReader:
    """`NodeTree` reads the caller's rows; the faults it refuses are its own."""

    def test_it_reads_the_three_columns_it_needs(self) -> None:
        tree = _tree()

        assert tree.size == 5
        assert QUARANTINE_CHILD_ID in tree.node_ids()
        assert tree.parent_of(QUARANTINE_CHILD_ID) == QUARANTINE_ROOT_ID
        assert tree.parent_of(QUARANTINE_ROOT_ID) is None
        assert tree.campaign_of(QUARANTINE_CHILD_ID) == QUARANTINE_CAMPAIGN
        assert tree.holds(QUARANTINE_CHILD_ID) is True
        assert tree.holds("not-a-node") is False
        assert tree.campaigns() == (QUARANTINE_CAMPAIGN,)

    def test_the_node_ids_keep_the_callers_arrival_order(self) -> None:
        # Re-ordering them here would hide a fetch that returned two campaigns or
        # two overlapping pages, so the reader preserves what it was handed.
        rows = [node_row(QUARANTINE_ROOT_ID), node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_ROOT_ID, depth=1)]
        assert NodeTree(rows).node_ids() == (QUARANTINE_ROOT_ID, QUARANTINE_CHILD_ID)
        assert NodeTree(reversed(rows)).node_ids() == (QUARANTINE_CHILD_ID, QUARANTINE_ROOT_ID)

    def test_a_row_that_is_not_a_mapping_is_refused(self) -> None:
        with pytest.raises(QuarantineTreeError) as raised:
            NodeTree([["not", "a", "mapping"]])
        assert QUARANTINE_TREE_CODE in str(raised.value)

    def test_a_node_with_no_id_is_refused(self) -> None:
        with pytest.raises(QuarantineTreeError):
            NodeTree([{"parent_id": None, "campaign_id": QUARANTINE_CAMPAIGN}])
        with pytest.raises(QuarantineTreeError):
            NodeTree([{"id": "", "campaign_id": QUARANTINE_CAMPAIGN}])

    def test_a_row_with_no_campaign_is_refused(self) -> None:
        # The campaign is what bounds the closure, so a node that does not say
        # which campaign it is in is one this law cannot scope.
        with pytest.raises(QuarantineTreeError):
            NodeTree([{"id": QUARANTINE_ROOT_ID, "parent_id": None}])

    def test_an_unreadable_parent_is_refused(self) -> None:
        with pytest.raises(QuarantineTreeError):
            NodeTree([node_row(QUARANTINE_ROOT_ID), {"id": QUARANTINE_CHILD_ID, "parent_id": 7, "campaign_id": QUARANTINE_CAMPAIGN}])

    def test_the_same_node_twice_with_agreeing_rows_is_deduped(self) -> None:
        # A join that fanned out is not a fault; the closure is the same either
        # way, so it is read once rather than refused.
        rows = quarantine_rows()
        rows.append(node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_ROOT_ID, depth=1))
        tree = NodeTree(rows)

        assert tree.size == 5
        assert tree.subtree(QUARANTINE_CHILD_ID)[0] == QUARANTINE_CHILD_ID

    def test_the_same_node_twice_with_disagreeing_rows_is_refused(self) -> None:
        # Which edge this law read would then depend on the caller's row order,
        # and a branch halted on a fetch accident is worse than one not halted.
        rows = quarantine_rows()
        rows.append(node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_SIBLING_ID, depth=1))

        with pytest.raises(QuarantineTreeError) as raised:
            NodeTree(rows)

        assert QUARANTINE_TREE_CODE in str(raised.value)

    def test_a_child_naming_an_absent_parent_still_closes(self) -> None:
        # The parent is not in the fetch, so the closure cannot walk past it —
        # which is a refusal about *that node*, not a crash on the edge.
        tree = NodeTree([node_row(QUARANTINE_CHILD_ID, parent_id=QUARANTINE_ROOT_ID, depth=1)])

        assert tree.subtree(QUARANTINE_CHILD_ID) == (QUARANTINE_CHILD_ID,)

    def test_an_unknown_node_has_no_subtree(self) -> None:
        with pytest.raises(QuarantineTreeError):
            _tree().subtree("not-a-node")
        with pytest.raises(QuarantineTreeError):
            _tree().campaign_of("not-a-node")
        with pytest.raises(QuarantineTreeError):
            _tree().parent_of("not-a-node")

    def test_from_rows_is_the_constructor_spelled_for_a_chained_caller(self) -> None:
        assert NodeTree.from_rows(quarantine_rows()).size == _tree().size


class TestTheClassIsPersisted:
    """Claim three: *persisting a ``sandbox_escape`` fail class*."""

    def test_the_class_lands_on_the_failing_nodes_own_field(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, _tree()).quarantine
        assert quarantine is not None
        records = _records(_tree())

        quarantine.mark(records)

        assert records[QUARANTINE_CHILD_ID]["fail_class"] == QUARANTINE_FAIL_CLASS

    def test_the_class_does_not_land_on_the_descendants(self) -> None:
        # The asymmetry the feature is built on.  §15 says to *record* a class
        # and to *quarantine* a subtree; a grandchild that never called anything
        # did not fail, and writing `sandbox_escape` onto its field would make it
        # report a violation of its own that it never committed.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(tree)

        quarantine.mark(records)

        assert "fail_class" not in records[QUARANTINE_GRANDCHILD_ID]
        assert "fail_class" not in records[QUARANTINE_GREATGRANDCHILD_ID]

    def test_the_halt_lands_on_every_node_of_the_branch(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(tree)

        quarantine.mark(records)

        for node_id in quarantine.nodes:
            assert records[node_id][NODE_QUARANTINED_COLUMN]

    def test_nothing_outside_the_branch_is_marked(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(tree)

        quarantine.mark(records)

        for node_id in (QUARANTINE_ROOT_ID, QUARANTINE_SIBLING_ID):
            assert NODE_QUARANTINED_COLUMN not in records[node_id]
            assert "fail_class" not in records[node_id]

    def test_a_node_already_carrying_another_class_is_not_overwritten(self) -> None:
        # A node whose row already names `timeout` is one feature 163 recorded,
        # and this law replacing it would translate one failure into another —
        # the restraint `timed_out_record` documents for its own write.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(tree, **{QUARANTINE_CHILD_ID: quarantine_record(QUARANTINE_CHILD_ID, fail_class="timeout")})

        quarantine.mark(records)

        assert records[QUARANTINE_CHILD_ID]["fail_class"] == "timeout"
        # The halt is still written: the node is halted, it just does not report
        # this law's class as its own.
        assert records[QUARANTINE_CHILD_ID][NODE_QUARANTINED_COLUMN]

    def test_a_node_already_carrying_the_class_is_rewritten_in_place(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(
            tree,
            **{QUARANTINE_CHILD_ID: quarantine_record(QUARANTINE_CHILD_ID, fail_class=ESCAPE_CLASS)},
        )

        quarantine.mark(records)

        assert records[QUARANTINE_CHILD_ID]["fail_class"] == QUARANTINE_FAIL_CLASS

    def test_the_class_is_written_to_the_field_the_record_already_uses(self) -> None:
        # A row that carries the class under `outcome` or `terminal_class` keeps
        # it there rather than growing a second class field beside the first.
        for field in ("outcome", "terminal_class"):
            tree = _tree()
            gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
            quarantine = quarantine_violation(gate, tree).quarantine
            assert quarantine is not None
            record = quarantine_record(QUARANTINE_CHILD_ID)
            record[field] = ESCAPE_CLASS
            records = _records(tree, **{QUARANTINE_CHILD_ID: record})

            quarantine.mark(records)

            assert records[QUARANTINE_CHILD_ID][field] == QUARANTINE_FAIL_CLASS
            assert "fail_class" not in records[QUARANTINE_CHILD_ID]

    def test_a_missing_record_makes_the_write_all_or_nothing(self) -> None:
        # A branch whose root is halted and whose child is not is a state
        # nothing in this member can produce, and a store left in it would read
        # as a child still being evaluated under a parent that is not.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(tree)
        del records[QUARANTINE_GRANDCHILD_ID]

        with pytest.raises(SandboxEscapeQuarantine) as raised:
            quarantine.mark(records)

        assert QUARANTINE_MISMATCH_CODE in str(raised.value)
        # Nothing was written, including on the nodes that *were* supplied.
        assert NODE_QUARANTINED_COLUMN not in records[QUARANTINE_CHILD_ID]
        assert "fail_class" not in records[QUARANTINE_CHILD_ID]

    def test_a_record_this_law_cannot_write_to_is_refused(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        frozen = MappingProxyType({"id": QUARANTINE_CHILD_ID})
        records = _records(tree, **{QUARANTINE_CHILD_ID: frozen})

        with pytest.raises(SandboxEscapeQuarantine) as raised:
            quarantine.mark(records)

        assert QUARANTINE_MISMATCH_CODE in str(raised.value)

    def test_a_rerun_keeps_the_original_instant(self) -> None:
        # Replaying a violation on a branch that is already halted is an
        # idempotent read rather than a second event: an event that happened once
        # keeps the time it happened.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        first = quarantine_violation(gate, tree).quarantine
        assert first is not None
        records = _records(tree)
        first.mark(records, quarantined_at="2025-01-02T03:04:05+00:00")
        held = records[QUARANTINE_CHILD_ID][NODE_QUARANTINED_COLUMN]

        second = quarantine_violation(gate, tree).quarantine
        assert second is not None
        rows = second.mark(records, quarantined_at="2026-09-09T09:09:09+00:00")

        assert records[QUARANTINE_CHILD_ID][NODE_QUARANTINED_COLUMN] == held
        assert rows[0]["quarantined_at"] == held

    def test_a_second_instant_on_one_node_is_refused(self) -> None:
        # Two instants mean two violations reached the node, and keeping one
        # silently would lose the earlier halt.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(
            tree,
            **{
                QUARANTINE_CHILD_ID: quarantine_record(
                    QUARANTINE_CHILD_ID, quarantined_at="2020-01-01T00:00:00+00:00"
                ),
                QUARANTINE_GRANDCHILD_ID: quarantine_record(
                    QUARANTINE_GRANDCHILD_ID, quarantined_at="2021-02-02T00:00:00+00:00"
                ),
            },
        )

        with pytest.raises(SandboxEscapeQuarantine) as raised:
            quarantine.mark(records, quarantined_at="2025-06-07T08:09:10+00:00")

        assert QUARANTINE_MISMATCH_CODE in str(raised.value)

    def test_an_unparseable_existing_mark_is_repaired_rather_than_refused(self) -> None:
        # This law is being asked to *write* a mark, and a row whose existing
        # text no reader can parse is repaired by writing one.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        records = _records(
            tree,
            **{
                QUARANTINE_GRANDCHILD_ID: quarantine_record(
                    QUARANTINE_GRANDCHILD_ID, quarantined_at="whenever"
                )
            },
        )

        quarantine.mark(records, quarantined_at="2025-01-02T03:04:05+00:00")

        assert records[QUARANTINE_GRANDCHILD_ID][NODE_QUARANTINED_COLUMN] == (
            "2025-01-02T03:04:05+00:00"
        )

    def test_an_unparseable_stamp_is_refused(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        with pytest.raises(QuarantineTreeError):
            quarantine.mark(_records(tree), quarantined_at="not-a-time")

    def test_a_datetime_stamp_is_carried_as_iso_text(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None
        instant = dt.datetime(2025, 3, 4, 5, 6, 7, tzinfo=dt.UTC)

        rows = quarantine.mark(_records(tree), quarantined_at=instant)

        assert rows[0]["quarantined_at"] == instant.isoformat()


class TestTheRows:
    """The store-shaped read side: one row per halted node, and one for the branch."""

    def test_every_row_carries_the_branchs_full_identity(self) -> None:
        # A single row read alone still answers *why*, which is the reason this
        # law exists as a record rather than as a log line that has since
        # rotated.
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        rows = quarantine.rows(quarantined_at="2025-01-02T03:04:05+00:00")

        assert len(rows) == quarantine.size
        for row in rows:
            assert tuple(row) == QUARANTINE_COLUMNS
            assert row["root_node_id"] == QUARANTINE_CHILD_ID
            assert row["campaign_id"] == QUARANTINE_CAMPAIGN
            assert row["fail_class"] == QUARANTINE_FAIL_CLASS
            assert row["syscall"] == DISALLOWED_SYSCALL
            assert row["action"] == KILL_ACTION
            assert row["component"] == SIGNAL_SANDBOX

    def test_the_depth_column_distinguishes_the_root_from_the_rest(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        rows = quarantine.rows(quarantined_at="2025-01-02T03:04:05+00:00")

        assert [row["subtree_depth"] for row in rows] == [0, 1, 2]

    def test_the_rows_are_fresh_per_call(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        first = quarantine.rows(quarantined_at="2025-01-02T03:04:05+00:00")
        second = quarantine.rows(quarantined_at="2025-01-02T03:04:05+00:00")

        assert first == second
        assert first[0] is not second[0]

    def test_the_branch_record_is_one_row_for_the_whole_branch(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        record = QuarantineRecord.of(quarantine, quarantined_at="2025-01-02T03:04:05+00:00")

        assert record.node_id == QUARANTINE_CHILD_ID
        assert record.root_node_id == QUARANTINE_CHILD_ID
        assert record.subtree_depth == 0
        assert record.subtree_size == 3
        assert record.fail_class == QUARANTINE_FAIL_CLASS
        assert record.row()["subtree_size"] == 3

    def test_describe_names_the_attempt_and_the_width(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        phrase = quarantine.describe()

        assert f"{DISALLOWED_SYSCALL} → {KILL_ACTION}" in phrase
        assert QUARANTINE_FAIL_CLASS in phrase
        assert "3 node(s)" in phrase

    def test_the_branch_record_describes_the_descendant_count(self) -> None:
        tree = _tree()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        quarantine = quarantine_violation(gate, tree).quarantine
        assert quarantine is not None

        assert "2 descendant(s)" in QuarantineRecord.of(
            quarantine, quarantined_at="2025-01-02T03:04:05+00:00"
        ).describe()


class TestTheRefusalShape:
    """The decision answers; `require` raises — the split every violation law draws."""

    def test_require_returns_the_quarantine_when_there_is_one(self) -> None:
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)

        quarantine = quarantine_violation(gate, _tree()).require()

        assert isinstance(quarantine, Quarantine)
        assert quarantine.size == 3

    def test_require_raises_for_a_foreign_class(self) -> None:
        subject = {
            "fail_class": "timeout",
            "syscall": DISALLOWED_SYSCALL,
            "action": KILL_ACTION,
            "node_id": QUARANTINE_CHILD_ID,
        }

        with pytest.raises(SandboxEscapeQuarantine) as raised:
            quarantine_violation(subject, _tree()).require()

        assert QUARANTINE_REQUIRED_CODE in str(raised.value)
        assert isinstance(raised.value, SandboxQuarantineError)

    def test_require_raises_for_the_pass_through_too(self) -> None:
        # A caller that called `require` has said it needs a branch, so the case
        # where no branch exists raises rather than returning `None` — the two
        # are told apart by the code, not by the class.
        with pytest.raises(SandboxEscapeQuarantine) as raised:
            quarantine_violation(None, _tree()).require()

        assert QuarantineReason.NOTHING_TO_QUARANTINE.value in str(raised.value)

    def test_every_refusal_names_a_greppable_code(self) -> None:
        # An operator grepping a log finds the refusal by the feature's own
        # words — the discipline every other law in this member follows.
        refusals = [
            quarantine_violation(
                {"fail_class": "ok", "syscall": "read", "action": "kill", "node_id": QUARANTINE_CHILD_ID},
                _tree(),
            ),
            quarantine_violation({"fail_class": ESCAPE_CLASS}, _tree()),
            quarantine_violation(
                quarantine_violation_from_gate(node_id=""), _tree()
            ),
        ]

        for decision in refusals:
            assert decision.refused is True
            assert QUARANTINE_REQUIRED_CODE in decision.detail


class TestTheComponentAndTheConstants:
    """The seat, the artifact-less reading, and the vocabulary as data."""

    def test_the_component_name_is_the_categorys_tenth(self) -> None:
        # The registry replaces a name's earlier registration, so this must be
        # its own name and not any of the other seats'.
        assert QUARANTINE_COMPONENT_NAME == "sandbox-quarantine"
        assert QUARANTINE_COMPONENT_NAME not in {
            "sandbox",
            "sandbox-imports",
            "sandbox-transfer",
            "sandbox-seed",
            "sandbox-threads",
            "sandbox-timeout",
            "sandbox-failclass",
            "sandbox-budget",
            "sandbox-syscalls",
        }

    def test_the_class_is_section_15s_and_not_one_of_section_9_1s(self) -> None:
        # §9.1's column holds `ok | timeout | error | tripwire_fail`; §15 names
        # `sandbox_escape`.  Feature 168's table is the one place it is
        # translated, so this law persists the class §15 names and says so.
        assert QUARANTINE_FAIL_CLASS == "sandbox_escape"
        assert QUARANTINE_FAIL_CLASS not in ("ok", "timeout", "error", "tripwire_fail")

    def test_the_codes_are_greppable(self) -> None:
        assert QUARANTINE_REQUIRED_CODE == "quarantine_required"
        assert QUARANTINE_MISMATCH_CODE == "quarantine_mismatch"
        assert QUARANTINE_TREE_CODE == "quarantine_tree_invalid"

    def test_the_ledger_shape_is_declared_once(self) -> None:
        assert QUARANTINE_TABLE == "sandbox_quarantine"
        assert QUARANTINE_COLUMNS == (
            "node_id",
            "root_node_id",
            "campaign_id",
            "subtree_depth",
            "fail_class",
            "syscall",
            "action",
            "component",
            "quarantined_at",
        )
        assert NODE_QUARANTINED_COLUMN == "quarantined_at"
        assert NODE_QUARANTINED_COLUMN in QUARANTINE_COLUMNS

    def test_the_module_level_convenience_is_the_law(self) -> None:
        assert isinstance(sandbox_quarantine(), SandboxQuarantine)
        assert sandbox_quarantine() is not sandbox_quarantine()

    def test_the_verbs_are_one_call_into_the_module(self) -> None:
        law = SandboxQuarantine()
        gate = quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID)
        tree = _tree()

        assert law.quarantines(gate, tree) is True
        assert law.check(gate, tree).quarantined is True
        assert law.require(gate, tree).size == 3
        assert law.tree(quarantine_rows()).size == 5
        assert law.columns() == QUARANTINE_COLUMNS
        assert law.fail_class() == QUARANTINE_FAIL_CLASS
        assert law.mark_column() == NODE_QUARANTINED_COLUMN

    def test_the_law_carries_no_state(self) -> None:
        # Artifact-less, like feature 168's: §15 fixes the trigger, the recovery
        # and the class, so there is nothing for a deployment to set and no file
        # whose drift a `None` could report.
        assert SandboxQuarantine.__slots__ == ()
        assert SandboxQuarantine.__dict__.get("fail_class") is not None

    def test_the_class_is_exported_from_the_package(self) -> None:
        assert sandbox.QUARANTINE_COMPONENT_NAME == QUARANTINE_COMPONENT_NAME
        assert sandbox.QUARANTINE_FAIL_CLASS == QUARANTINE_FAIL_CLASS
        for name in ("SandboxQuarantine", "Quarantine", "NodeTree", "QuarantineDecision"):
            assert name in sandbox.__all__, name


class TestTheMemberStaysStdlibAndStoreFree:
    """The one-provenance rule, checked as a property of the module rather than assumed."""

    def test_the_law_imports_no_store_and_no_environment(self) -> None:
        # A law that had grown a database or read a variable would have to grow
        # an import to do it, so checking the imports is the honest form of the
        # claim — and it is why the caller fetches the rows and hands them in.
        import sandbox.quarantine as module

        source = module.__dict__
        for banned in ("sqlite3", "subprocess", "os", "socket"):
            assert banned not in source, banned

    def test_the_law_imports_no_sibling_workspace_member(self) -> None:
        # The box untrusted code is put inside must not depend on anything handed
        # to it, so this member restates shared vocabulary as data rather than
        # importing a sibling's spelling of it.
        import inspect

        import sandbox.quarantine as module

        text = inspect.getsource(module)
        for member in ("tripwires", "nulloracle", "ledger", "artifacts"):
            assert f"import {member}" not in text, member
        assert "from .errors import" in text
