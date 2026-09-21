"""Feature 160's gate: *rejects a process attempting a disallowed syscall*.

The subject of this feature is one **attempt**, so the tests below are about a
single call rather than a run: a process inside the box reached for a syscall
name, and the law answers with a :class:`~sandbox.syscalls.SyscallDecision` that
says whether the committed ceiling admits it, why, and — when it does not — what
the attempt met.  That decision is the *whole* return contract of the gate: it is
never raised per attempt, because §6.1 runs the sandbox unattended over thousands
of candidates and *"this candidate called ``openat``"* has to reach an operator as
a fact about a run rather than as a crashed evaluator.

**The refusal shape is feature 162's, and §15 is what decides it.**  A syscall
outside the ceiling is a *violation of the box* — §15's failure table entries it
as *"Sandbox escape attempt | seccomp violation | Kill, record ``fail_class``,
quarantine the node and its subtree"* — rather than an ordinary fate of a bad
candidate.  So the decision's ``violation`` carries a
:class:`~sandbox.syscalls.Commitment` naming the syscall, the action it met and
§15's ``sandbox_escape`` class, which is the value feature 161 quarantines a node
and its subtree for; and :meth:`SyscallDecision.require` raises on the launcher's
last line for a rejection *and* for an attempt this law cannot read.

**What this suite deliberately does not do is watch a process.**  Nothing in this
module calls ``prctl``, writes a BPF program or reads ``/proc``: the name arrives
as an argument, exactly as feature 157's law reads a run's *declared* isolation
rather than dialling a container runtime.  That is why these tests run on any
machine — one whose kernel was built without seccomp composes and answers exactly
as a hardened host does — and the tests at the bottom of this file say so by
checking that no ``/proc``, ``os`` or ``subprocess`` dependency exists at all.
"""

from __future__ import annotations

import enum

import pytest
import sandbox
from _documents import (
    ADMITTED_SYSCALL,
    DISALLOWED_ENTROPY_SYSCALL,
    DISALLOWED_ESCAPE_SYSCALL,
    DISALLOWED_FILTER_SYSCALL,
    DISALLOWED_FORK_SYSCALL,
    DISALLOWED_NETWORK_SYSCALL,
    DISALLOWED_SYSCALL,
    ERRNO_ACTION,
    ESCAPE_CLASS,
    KILL_ACTION,
    POLICY_RUNTIME,
    SIGNAL_SANDBOX,
    UPPERCASE_TERM,
    runner_result,
    syscall_attempt,
    syscalls_document,
)
from sandbox.syscalls import (
    COMMITTED_SYSCALLS_POLICY,
    DISALLOWED_SYSCALL_CODE,
    SYSCALLS_REQUIRED_CODE,
    SandboxSyscalls,
    SyscallAttempt,
    SyscallDecision,
    SyscallFilter,
    SyscallPolicy,
    SyscallReason,
    committed_syscalls_policy,
    compile_syscalls_policy,
    disallowed_syscall,
    reject_syscall,
    sandbox_syscalls,
)

#: The law under test, compiled once from the committed artifact.  A module-level
#: constant rather than a fixture because a compiled ceiling is *immutable*: the
#: fresh-object rule ``_documents`` states exists for mutable documents, and a
#: policy is a value.  Tests that need a *different* ceiling compile one.
LAW = committed_syscalls_policy()

#: The names of the member's own refusal classes, compared as strings because
#: the loader's synthetic module copy means a composed component's exception is
#: structurally but not identically the canonically-imported one.
_REFUSAL = "DisallowedSyscall"


def _refused(subject: object, policy: SyscallPolicy = LAW) -> str:
    with pytest.raises(Exception) as raised:
        reject_syscall(subject, policy).require()
    return f"{type(raised.value).__name__}: {raised.value}"


class TestTheGateAnswers:
    """The decision is a value — the pipeline's contract."""

    def test_an_ordinary_call_is_admitted(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=ADMITTED_SYSCALL), LAW)
        assert decision.admitted is True
        assert decision.rejected is False
        assert decision.reason is SyscallReason.BY_ALLOWLIST
        assert decision.violation is None

    @pytest.mark.parametrize(
        "syscall",
        [
            DISALLOWED_SYSCALL,
            DISALLOWED_NETWORK_SYSCALL,
            DISALLOWED_FORK_SYSCALL,
            DISALLOWED_ENTROPY_SYSCALL,
            DISALLOWED_ESCAPE_SYSCALL,
            DISALLOWED_FILTER_SYSCALL,
        ],
    )
    def test_a_disallowed_call_is_rejected(self, syscall: str) -> None:
        decision = reject_syscall(syscall_attempt(syscall=syscall), LAW)
        assert decision.admitted is False
        assert decision.rejected is True
        assert decision.reason is SyscallReason.OUTSIDE_ALLOWLIST

    def test_a_rejection_is_returned_rather_than_raised(self) -> None:
        # The pipeline's contract, stated on its own: the gate *answers*, so an
        # evaluator running thousands of unattended candidates is not taken
        # down by the tenth one that escaped.  Only ``require`` raises.
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert isinstance(decision, SyscallDecision)
        assert decision.admitted is False

    def test_an_unreadable_attempt_is_rejected_rather_than_admitted(self) -> None:
        # "Unknown" is not "allowed": an attempt whose name this law cannot read
        # has not been compared against the ceiling, and waving it through would
        # be the escape this control exists to prevent.
        decision = reject_syscall(syscall_attempt(syscall=None), LAW)
        assert decision.admitted is False
        assert decision.rejected is True
        assert decision.reason is SyscallReason.UNNAMED_SYSCALL

    def test_the_three_reasons_are_three_distinct_values(self) -> None:
        # One acceptance and *two* rejections, because the repairs are different
        # things: a box that called something nobody configured, and a caller
        # that offered a name no filter could match.  A caller that conflated
        # them would go looking at a candidate's trace when its own recorder was
        # broken, or the reverse.
        assert len(set(SyscallReason)) == 3
        assert SyscallReason.BY_ALLOWLIST != SyscallReason.OUTSIDE_ALLOWLIST
        assert SyscallReason.OUTSIDE_ALLOWLIST != SyscallReason.UNNAMED_SYSCALL
        assert isinstance(SyscallReason.BY_ALLOWLIST, enum.StrEnum)

    def test_the_reason_a_caller_reads_is_the_string_a_ledger_stores(self) -> None:
        # StrEnum rather than plain Enum so a violation row can carry the reason
        # without a translation step, and a log-grepping operator sees the same
        # token the code compares.
        assert str(SyscallReason.OUTSIDE_ALLOWLIST) == "outside-allowlist"
        assert SyscallReason.BY_ALLOWLIST == "by-allowlist"


class TestTheRejectionNamesItsSubject:
    """A refusal is only readable if it says which syscall was reached for."""

    def test_the_detail_names_the_syscall(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert DISALLOWED_SYSCALL in decision.detail
        assert decision.detail.startswith(DISALLOWED_SYSCALL_CODE)

    def test_the_detail_names_the_action_the_attempt_met(self) -> None:
        # The action is what makes the record actionable: §15's recovery is
        # "Kill, record fail_class, quarantine…", and an operator reading a
        # rejection has to know whether the box died or the call failed.
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert KILL_ACTION in decision.detail

    def test_the_detail_names_the_component_whose_box_it_was(self) -> None:
        decision = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL, component=SIGNAL_SANDBOX),
            LAW,
        )
        assert SIGNAL_SANDBOX in decision.detail

    def test_the_detail_quotes_the_ceiling_the_attempt_missed(self) -> None:
        # The single most useful thing in an operator's log: the ceiling itself,
        # so "what *is* this box allowed to call?" is answerable from the
        # rejection rather than from a second lookup that has since changed.
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        for term in (ADMITTED_SYSCALL, "exit", "exit_group", "mmap"):
            assert term in decision.detail, term

    def test_the_detail_says_which_feature_refused(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert "feature 160" in decision.detail

    def test_the_detail_cites_the_control_table_and_the_zone_map(self) -> None:
        # The law's provenance travels with the refusal, so an operator reading
        # a log in isolation can find §5.2's row and §3's zone map without
        # reading the module docstring.
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert "seccomp allowlist" in decision.detail
        assert "Z1" in decision.detail

    def test_the_detail_names_section_15s_row(self) -> None:
        # The handoff: what this event *is* in the spec's own words, and what
        # its recovery is — which is what makes the violation feature 161's
        # subject rather than this law's.
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert "sandbox escape" in decision.detail.lower()

    def test_an_unnamed_attempt_is_refused_by_its_own_code(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=None), LAW)
        assert decision.detail.startswith(SYSCALLS_REQUIRED_CODE)

    def test_an_unnamed_attempt_says_what_was_offered_instead(self) -> None:
        # The repair differs by *what the bad value was*: a caller that passed a
        # number looks at its recorder, one that passed nothing looks at its
        # call site — so a message saying only "no syscall" would send both to
        # the same wrong place.
        for offered in (None, 60, b"read", "", UPPERCASE_TERM, ["read"]):
            decision = reject_syscall(syscall_attempt(syscall=offered), LAW)
            assert repr(offered) in decision.detail, offered

    def test_an_unnamed_attempt_says_the_unknown_is_not_allowed(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=None), LAW)
        assert "unknown" in decision.detail.lower()

    def test_an_admitted_call_explains_itself_too(self) -> None:
        # The acceptance carries a detail for the same reason the rejection
        # does: a caller reading a trace of admitted calls wants the ceiling
        # named, and a decision whose detail was empty on success would force
        # every such caller to reconstruct the law's own sentence.
        decision = reject_syscall(syscall_attempt(syscall=ADMITTED_SYSCALL), LAW)
        assert ADMITTED_SYSCALL in decision.detail
        assert "feature 160" in decision.detail


class TestTheViolationHandoff:
    """§15's ``sandbox_escape`` — the value feature 161 quarantines for."""

    def test_a_disallowed_call_publishes_a_commitment(self) -> None:
        decision = reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert decision.violation is not None
        assert decision.violation.syscall == DISALLOWED_SYSCALL

    def test_the_commitment_carries_section_15s_class(self) -> None:
        # Spelled as data on both sides: ``ESCAPE_CLASS`` in the documents
        # module and the law's own constant, pinned here so a rename on either
        # side is caught rather than followed.
        violation = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW
        ).violation
        assert violation.fail_class == ESCAPE_CLASS == "sandbox_escape"

    def test_the_commitment_carries_the_action_and_the_ceiling_size(self) -> None:
        violation = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW
        ).violation
        assert violation.action == KILL_ACTION
        assert violation.ceiling_terms == len(LAW.allowed())

    def test_the_commitment_carries_the_node_and_component_identity(self) -> None:
        # What feature 161 needs to quarantine: *which* node, and which box it
        # was in — the subtree is found from the node id, not re-derived.
        violation = reject_syscall(
            syscall_attempt(
                syscall=DISALLOWED_SYSCALL,
                node_id="node-abc",
                component=POLICY_RUNTIME,
            ),
            LAW,
        ).violation
        assert violation.node_id == "node-abc"
        assert violation.component == POLICY_RUNTIME

    def test_the_commitment_knows_the_box_no_longer_exists(self) -> None:
        # ``kill`` is §15's committed action, so a violation is a process the
        # kernel destroyed on SIGSYS — which is what makes quarantine the right
        # recovery rather than a retry.
        violation = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW
        ).violation
        assert violation.killed is True

    def test_an_errno_ceiling_publishes_a_violation_that_did_not_kill(self) -> None:
        # The other legal ceiling, and the reason the action travels *with* the
        # refusal rather than being looked up by the reader: with ``errno`` the
        # offending call fails and the process keeps running, so a record that
        # said only "disallowed" would leave an operator unable to tell a box
        # that was breached from a box that behaved.
        errno_law = compile_syscalls_policy(
            syscalls_document(default_action=ERRNO_ACTION)
        )
        violation = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL), errno_law
        ).violation
        assert violation.killed is False
        assert violation.action == ERRNO_ACTION
        assert violation.fail_class == ESCAPE_CLASS

    def test_an_admitted_call_publishes_no_violation(self) -> None:
        assert (
            reject_syscall(syscall_attempt(syscall=ADMITTED_SYSCALL), LAW).violation
            is None
        )

    def test_an_unreadable_attempt_publishes_no_violation(self) -> None:
        # Deliberately ``None``: an attempt no ceiling could be compared against
        # is not an escape attempt, it is a caller that offered a name this law
        # cannot read — and quarantining a node for that would be acting on a
        # fabricated violation, taking a subtree out of the campaign for a
        # recorder's bug.  A caller that wants *every* rejection raised calls
        # ``require``.
        decision = reject_syscall(syscall_attempt(syscall=None), LAW)
        assert decision.rejected is True
        assert decision.violation is None

    def test_the_violation_describes_itself_in_one_phrase(self) -> None:
        # ``openat → kill``: which syscall a process tried and what happened
        # when it did.  A line naming only the first would read identically for
        # a box that died and one that was allowed to carry on.
        violation = reject_syscall(
            syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW
        ).violation
        assert violation.describe() == f"{DISALLOWED_SYSCALL} → {KILL_ACTION}"

    def test_the_violation_publishes_a_store_shaped_row(self) -> None:
        # What a ledger row, a §9.1 record or feature 161's quarantine decision
        # is written from — and note that the row carries ``fail_class``, not
        # one of §9.1's four: ``sandbox_escape`` is a genuine seccomp verdict,
        # and feature 168's table is what translates it to ``error``.
        row = reject_syscall(
            syscall_attempt(
                syscall=DISALLOWED_SYSCALL, node_id="n1", component=SIGNAL_SANDBOX
            ),
            LAW,
        ).violation.row()
        assert row["syscall"] == DISALLOWED_SYSCALL
        assert row["action"] == KILL_ACTION
        assert row["fail_class"] == ESCAPE_CLASS
        assert row["killed"] is True
        assert row["node_id"] == "n1"
        assert row["component"] == SIGNAL_SANDBOX

    def test_the_row_omits_identity_a_subject_did_not_carry(self) -> None:
        # A box with no node id yet is a real case (the dispatch has not landed
        # the row), and a row carrying ``"node_id": ""`` would be a quarantine
        # decision looking for the empty string's subtree.  ``syscall_attempt``
        # names a component by default, so this one is built with neither.
        row = reject_syscall(
            SyscallAttempt(syscall=DISALLOWED_SYSCALL), LAW
        ).violation.row()
        assert "node_id" not in row
        assert "component" not in row

    def test_the_violation_class_is_not_one_of_the_four(self) -> None:
        # §9.1's column is ``ok | timeout | error | tripwire_fail`` and this is
        # deliberately none of them — the reading feature 163's suite states and
        # feature 168 owns.  Pinned against feature 168's own vocabulary rather
        # than restated, so the handoff cannot drift.
        from sandbox.failclass import (
            ERROR_FAIL_CLASS,
            FAIL_CLASS_TABLE,
            SANDBOX_ESCAPE_CLASS,
        )

        assert ESCAPE_CLASS == SANDBOX_ESCAPE_CLASS
        assert ESCAPE_CLASS not in ("ok", "timeout", "error", "tripwire_fail")
        assert FAIL_CLASS_TABLE[ESCAPE_CLASS] == ERROR_FAIL_CLASS

    def test_feature_168_translates_the_violation_to_error(self) -> None:
        # The one law above this one: a violation recorded under this class is
        # placed under ``error`` by feature 168's table, which is why this law
        # leaves the class at its own spelling rather than folding it itself —
        # folding it here would be a second, disagreeing translation.  The
        # round trip is asserted through feature 168's *own* two functions, so
        # the handoff is proved rather than re-stated.
        from sandbox.failclass import (
            ERROR_FAIL_CLASS,
            classify_fail_class,
            classify_run,
        )

        assert classify_fail_class(ESCAPE_CLASS) == ERROR_FAIL_CLASS
        # And through the law's own subject type, which is the path an assembled
        # system takes: a runner result reporting the seccomp verdict is placed
        # under ``error``, with the finer spelling kept as the translation's
        # provenance rather than discarded.
        decision = classify_run(runner_result(fail_class=ESCAPE_CLASS))
        assert decision.fail_class.fail_class == ERROR_FAIL_CLASS
        assert decision.fail_class.fail_class == "error"


class TestRequire:
    """The bridge from the answer to the exception."""

    def test_require_raises_for_a_disallowed_call(self) -> None:
        message = _refused(syscall_attempt(syscall=DISALLOWED_SYSCALL))
        assert message.startswith(_REFUSAL), message
        assert DISALLOWED_SYSCALL in message
        assert DISALLOWED_SYSCALL_CODE in message

    def test_require_raises_for_an_unreadable_attempt(self) -> None:
        # Both rejection reasons raise the *one* class: feature 160's two halves
        # are one error type, and a caller never has to catch two — the same
        # restraint feature 157's ``GVisorIsolationRequired`` states for its
        # several spellings of one fact.
        message = _refused(syscall_attempt(syscall=None))
        assert message.startswith(_REFUSAL), message
        assert SYSCALLS_REQUIRED_CODE in message

    def test_require_is_a_no_op_for_an_admitted_call(self) -> None:
        # So a launcher can call it unconditionally on the last line after the
        # filter is armed, without branching on the decision it just read.
        assert (
            reject_syscall(syscall_attempt(syscall=ADMITTED_SYSCALL), LAW).require()
            is None
        )

    def test_the_refusal_is_the_members_own_type(self) -> None:
        from sandbox.errors import (
            DisallowedSyscall,
            SandboxError,
            SandboxSyscallError,
        )

        with pytest.raises(DisallowedSyscall):
            reject_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW).require()
        with pytest.raises(SandboxSyscallError):
            reject_syscall(syscall_attempt(syscall=None), LAW).require()
        with pytest.raises(SandboxError):
            reject_syscall(syscall_attempt(syscall=None), LAW).require()

    def test_the_refusal_is_not_a_permission_error(self) -> None:
        # Deliberately not ``PermissionError``/``OSError`` though the event is
        # about permissions a kernel would enforce: those are what a subprocess
        # or ``os`` call raises, and the box must not carry a refusal a caller
        # could confuse with its own.
        for subject in (
            syscall_attempt(syscall=DISALLOWED_SYSCALL),
            syscall_attempt(syscall=None),
        ):
            with pytest.raises(Exception) as raised:
                reject_syscall(subject, LAW).require()
            assert not isinstance(raised.value, (OSError, PermissionError, ValueError))

    def test_the_refusal_never_claims_an_argument_was_judged(self) -> None:
        # What the law *does not* decide, stated in the message: seccomp filters
        # can match argument values, this law names syscalls, and a refusal that
        # implied it had inspected ``openat``'s path would be asserting a
        # decision this seam did not make.
        message = _refused(
            syscall_attempt(syscall=DISALLOWED_SYSCALL, component="c"), LAW
        )
        assert "attempted the syscall" in message


class TestTheSubjectArrivesInManyShapes:
    """The gate reads a name off whatever carries one."""

    def test_a_bare_attempt_is_the_canonical_subject(self) -> None:
        assert (
            reject_syscall(SyscallAttempt(syscall=ADMITTED_SYSCALL), LAW).admitted
            is True
        )

    def test_any_object_carrying_a_syscall_attribute_is_judged(self) -> None:
        # The caller's own record type must not have to be re-described to be
        # judged — the same tolerance feature 162's ``_subject_measurement``
        # extends to the shapes its own subjects arrive in.
        class CallerRecord:
            def __init__(self, name: str) -> None:
                self.syscall = name

        assert reject_syscall(CallerRecord(ADMITTED_SYSCALL), LAW).admitted is True
        assert reject_syscall(CallerRecord(DISALLOWED_SYSCALL), LAW).admitted is False

    def test_an_object_with_no_syscall_attribute_is_refused(self) -> None:
        # Not an ``AttributeError``: an attempt that carries no name is a caller
        # bug this law reports as a rejection rather than a crash, because the
        # pipeline must not be taken down by a malformed recorder.
        class Empty:
            pass

        decision = reject_syscall(Empty(), LAW)
        assert decision.rejected is True
        assert decision.reason is SyscallReason.UNNAMED_SYSCALL

    def test_a_non_string_identity_is_reported_as_none_rather_than_crashing(
        self,
    ) -> None:
        # The identity is read while building a sentence, so a subject carrying
        # a node id that is not a string is reported as carrying none instead of
        # crashing the refusal that was about to describe it.
        decision = reject_syscall(
            SyscallAttempt(syscall=DISALLOWED_SYSCALL, node_id=7, component=None), LAW
        )
        assert decision.rejected is True
        assert decision.violation.node_id == ""
        assert decision.violation.component == ""

    def test_a_well_formed_name_this_ceiling_omits_is_still_judged(self) -> None:
        # The membership question is about *this* ceiling, so a name no document
        # ever listed is rejected on the ceiling it missed rather than on its
        # spelling — which is what makes the refusal readable.
        decision = reject_syscall(syscall_attempt(syscall="zzz_nothing"), LAW)
        assert decision.reason is SyscallReason.OUTSIDE_ALLOWLIST
        assert "zzz_nothing" in decision.detail

    def test_the_gate_refuses_a_policy_that_was_not_compiled(self) -> None:
        # The ceiling is a *validated* value, not a loose sequence a gate would
        # have to re-validate mid-refusal: a caller that handed a raw list is
        # told so loudly rather than being quietly served a second, disagreeing
        # membership rule.
        for policy in (
            [ADMITTED_SYSCALL],
            {ADMITTED_SYSCALL},
            "sandbox-syscalls",
            None,
        ):
            with pytest.raises(Exception) as raised:
                reject_syscall(syscall_attempt(), policy)  # type: ignore[arg-type]
            assert type(raised.value).__name__ == "SyscallsDocumentError"
            assert "SyscallPolicy" in str(raised.value)


class TestTheBoolean:
    """``disallowed_syscall`` — the one-line convenience."""

    def test_it_answers_the_membership_question(self) -> None:
        assert disallowed_syscall(syscall_attempt(syscall=DISALLOWED_SYSCALL), LAW)
        assert not disallowed_syscall(syscall_attempt(syscall=ADMITTED_SYSCALL), LAW)

    def test_an_unreadable_attempt_is_false_here(self) -> None:
        # The caveat the law's docstring states: this asks only the membership
        # question, so a caller that branches on it alone has not heard about an
        # attempt it cannot read — which is what ``reject_syscall`` is for.
        assert disallowed_syscall(syscall_attempt(syscall=None), LAW) is False
        assert reject_syscall(syscall_attempt(syscall=None), LAW).rejected is True

    def test_it_never_raises_for_a_rejection(self) -> None:
        for subject in (
            syscall_attempt(syscall=DISALLOWED_SYSCALL),
            syscall_attempt(syscall=None),
            object(),
        ):
            assert isinstance(disallowed_syscall(subject, LAW), bool)

    def test_it_agrees_with_the_decision_it_reads(self) -> None:
        for name in (ADMITTED_SYSCALL, DISALLOWED_SYSCALL, "mmap", "getrandom"):
            subject = syscall_attempt(syscall=name)
            assert disallowed_syscall(subject, LAW) is (
                reject_syscall(subject, LAW).commitment is not None
            )


class TestTheFilter:
    """Feature 160's word is *applies* — and this is what is applied."""

    def test_the_policy_builds_a_filter_specification(self) -> None:
        filter_ = LAW.filter()
        assert isinstance(filter_, SyscallFilter)
        assert filter_.default_action == KILL_ACTION
        assert filter_.names() == LAW.allowed()

    def test_the_filter_denies_by_default(self) -> None:
        # The one field a reviewer checks first, exposed as a boolean because it
        # is the difference between a ceiling and a wishlist and a reader should
        # not have to know both denying spellings to ask.
        assert LAW.filter().denies_by_default is True

    def test_the_filter_knows_a_violation_would_kill(self) -> None:
        # The distinction §15's recovery column turns on: this deployment
        # commits ``kill``, so an escape attempt is a process the kernel
        # destroyed rather than a call that failed.
        assert LAW.filter().kills is True

    def test_an_errno_filter_denies_without_killing(self) -> None:
        errno_law = compile_syscalls_policy(
            syscalls_document(default_action=ERRNO_ACTION)
        )
        assert errno_law.filter().denies_by_default is True
        assert errno_law.filter().kills is False

    def test_the_specification_is_written_in_the_runtimes_own_spelling(self) -> None:
        # ``defaultAction``/``syscalls[].names`` is the OCI seccomp shape the
        # runtime reads, and it is deliberately *not* this member's spelling: a
        # filter translated by each launcher would be a second place for the two
        # vocabularies to diverge.
        specification = LAW.filter().specification()
        assert specification["defaultAction"] == KILL_ACTION
        assert specification["syscalls"][0]["action"] == "SCMP_ACT_ALLOW"
        assert specification["syscalls"][0]["names"] == list(LAW.allowed())

    def test_the_specification_is_a_fresh_object_each_call(self) -> None:
        # A caller that mutated what it was handed must not widen the ceiling
        # for the next one — the copy-then-hand discipline every other read side
        # in this member applies.
        first = LAW.filter().specification()
        first["defaultAction"] = "SCMP_ACT_ALLOW"
        first["syscalls"][0]["names"].append("openat")
        second = LAW.filter().specification()
        assert second["defaultAction"] == KILL_ACTION
        assert "openat" not in second["syscalls"][0]["names"]

    def test_the_filter_admits_what_the_policy_admits(self) -> None:
        filter_ = LAW.filter()
        assert filter_.admits(ADMITTED_SYSCALL) is True
        assert filter_.admits(DISALLOWED_SYSCALL) is False
        assert filter_.admits(None) is False
        assert len(filter_) == len(LAW)

    def test_the_filter_is_a_value_not_an_armed_filter(self) -> None:
        # Nothing in this module has called ``prctl`` and the class holds no
        # process to call it on — the division feature 157 states between its
        # isolation policy and the ``runsc`` runtime that enforces it.
        assert SyscallFilter.__slots__ == ("_allowed", "default_action", "kind")
        with pytest.raises(AttributeError):
            LAW.filter().process = object()


class TestTheFacade:
    """``SandboxSyscalls`` — feature 160's law as the composed value."""

    def test_it_carries_the_committed_ceiling(self) -> None:
        law = sandbox_syscalls()
        assert isinstance(law, SandboxSyscalls)
        assert law.allowed() == committed_syscalls_policy().allowed()
        assert law.default_action == KILL_ACTION

    def test_it_carries_no_process_and_no_armed_filter(self) -> None:
        # A component shared across runs that had installed a filter — or held
        # a ``prctl`` handle — would be one box's ceiling applied to another's
        # process.  Pinned as slots so it cannot grow one.
        assert SandboxSyscalls.__slots__ == ("_policy",)

    def test_check_answers_with_a_decision(self) -> None:
        law = sandbox_syscalls()
        assert law.check(syscall_attempt(syscall=ADMITTED_SYSCALL)).admitted is True
        assert law.check(syscall_attempt(syscall=DISALLOWED_SYSCALL)).admitted is False

    def test_allows_answers_the_read_side(self) -> None:
        # *May the box call this?* is a question a deployment should be able to
        # answer without running a candidate to find out — and answering it from
        # the compiled artifact is what makes the ceiling a fact about the
        # deployment rather than a claim in a runbook.
        law = sandbox_syscalls()
        assert law.allows(ADMITTED_SYSCALL) is True
        assert law.allows(DISALLOWED_SYSCALL) is False
        assert law.allows(60) is False

    def test_require_raises_only_for_a_rejection(self) -> None:
        law = sandbox_syscalls()
        assert law.require(syscall_attempt(syscall=ADMITTED_SYSCALL)) is None
        with pytest.raises(Exception) as raised:
            law.require(syscall_attempt(syscall=DISALLOWED_SYSCALL))
        assert type(raised.value).__name__ == _REFUSAL
        with pytest.raises(Exception) as raised:
            law.require(syscall_attempt(syscall=None))
        assert type(raised.value).__name__ == _REFUSAL

    def test_filter_hands_out_the_specification(self) -> None:
        law = sandbox_syscalls()
        assert law.filter().specification()["defaultAction"] == KILL_ACTION

    def test_the_policy_it_carries_is_readable(self) -> None:
        # Reading it widens nothing: the policy holds no capability, which is
        # the point of the component being a facade rather than an armed filter.
        law = sandbox_syscalls()
        assert isinstance(law.policy, SyscallPolicy)
        assert law.policy.kind == "sandbox-syscalls"

    def test_two_facades_over_one_ceiling_are_independent(self) -> None:
        # Statelessness stated as behaviour: nothing a caller does through one
        # facade is visible through another, because neither holds state.
        first, second = sandbox_syscalls(), sandbox_syscalls()
        first.check(syscall_attempt(syscall=DISALLOWED_SYSCALL))
        assert second.allows(DISALLOWED_SYSCALL) is False
        assert first.allowed() == second.allowed()

    def test_the_convenience_compiles_the_committed_artifact(self) -> None:
        # It is the same call the builder makes minus the composition, so an
        # operator script and a composed application are held to one ceiling.
        assert sandbox_syscalls().allowed() == committed_syscalls_policy().allowed()
        assert sandbox_syscalls().allowed() == LAW.allowed()
        assert sandbox_syscalls().default_action == LAW.default_action

    def test_it_reaches_the_same_verdict_as_the_module_function(self) -> None:
        # The facade delegates rather than re-implementing: a second copy of the
        # membership rule or the refusal sentence would be a second thing to
        # keep in sync, which the member's one-provenance rule forbids.
        law = sandbox_syscalls()
        for name in (ADMITTED_SYSCALL, DISALLOWED_SYSCALL, None, 60, "mmap"):
            subject = syscall_attempt(syscall=name)
            assert law.check(subject).admitted is reject_syscall(subject, LAW).admitted


class TestTheLawIsNotAMechanism:
    """Nothing here watches a process, and that is the design."""

    def test_the_module_imports_no_process_or_kernel_machinery(self) -> None:
        # The honest limit, asserted: this law is the *configuration* of the
        # filter, not the filter.  It never calls ``prctl``, never writes a BPF
        # program, never spawns a process and cannot see a syscall a kernel has
        # already refused — so it composes and answers on any machine, including
        # one whose kernel was built without seccomp.
        import sandbox.syscalls as law_module

        source = law_module.__file__
        assert source is not None
        with open(source, "r", encoding="utf-8") as handle:
            text = handle.read()
        for forbidden in ("import subprocess", "import ctypes", "import resource"):
            assert forbidden not in text, forbidden
        assert "prctl(" not in text

    def test_the_module_reads_no_environment(self) -> None:
        # Composition cannot depend on the shell that started the process: the
        # law's subject is a name a runtime reported, never a probe.
        import sandbox.syscalls as law_module

        with open(law_module.__file__, "r", encoding="utf-8") as handle:
            text = handle.read()
        assert "os.environ" not in text
        assert "getenv" not in text

    def test_the_ceiling_names_syscalls_rather_than_numbers(self) -> None:
        # A seccomp filter matches on syscall *number*; this law names names,
        # because a name is what a deployment reviews and what a refusal can
        # print, and the number table is the runtime's to hold.  Stated as
        # behaviour: every term is a string, and the policy has no number map.
        for term in LAW.allowed():
            assert isinstance(term, str)
        assert not hasattr(LAW, "numbers")
        assert not hasattr(LAW, "syscall_numbers")

    def test_the_artifact_is_the_offset_of_the_committed_ceiling(self) -> None:
        # A deployment's posture is a file in the repository, so a checkout can
        # be audited without running anything.
        assert COMMITTED_SYSCALLS_POLICY.is_file()
        assert COMMITTED_SYSCALLS_POLICY.name == "syscalls_allowlist.json"

    def test_the_module_is_exported_from_the_member(self) -> None:
        # Reached through the package rather than by importing a submodule: what
        # a caller of the member is entitled to cite.
        for name in (
            "SandboxSyscalls",
            "SyscallAttempt",
            "SyscallDecision",
            "SyscallFilter",
            "SyscallPolicy",
            "SyscallReason",
            "Commitment",
            "reject_syscall",
            "disallowed_syscall",
            "sandbox_syscalls",
            "committed_syscalls_policy",
            "compile_syscalls_policy",
            "load_syscalls_policy",
        ):
            assert hasattr(sandbox, name), name
            assert name in sandbox.__all__, name
