"""Feature 157: the gate — every run answered, and the answer is derived.

The sentence's second tense, at the seam a *run* is offered: the pipeline
executes one signal per rebalance date (§6.1 step 2), unattended, over
thousands of candidates, so a gate that raised per run would turn a
configuration mistake into a crashed evaluator.  This one *answers*: every run
gets a :class:`~sandbox.isolation.RunDecision`, and only a run whose
component's compiled isolation is gVisor's is admitted.

The refusals are grouped by the reason each earns, because the reason is the
audit record — the run that was never named, the run whose box the policy
cannot speak about, and the run whose box is on another runtime are three
different facts about a deployment, and collapsing them into one "refused"
would leave an operator unable to tell which.

The last group proves the derivation is real: the gate admits *because the
consulted declaration is gVisor's*, not because it was told to — so a
hand-assembled policy carrying another pair is answered by the very same
consultation, which is exactly why a compiled policy can never hold one.
"""

from __future__ import annotations

import pytest
from _documents import (
    DEFAULT_OCI_RUNTIME,
    MICROVM_MECHANISM,
    POLICY_RUNTIME,
    SIGNAL_SANDBOX,
    UNLISTED_COMPONENT,
    committed_document,
)
from sandbox import (
    ISOLATION_REQUIRED_CODE,
    ComponentIsolation,
    GVisorIsolationRequired,
    IsolationPolicy,
    RunDecision,
    RunReason,
    SandboxRun,
    authorize_run,
    compile_isolation_policy,
)


@pytest.fixture()
def law() -> IsolationPolicy:
    """The committed document, compiled — the policy the gate answers for."""
    return compile_isolation_policy(committed_document())


def _run(component: object) -> SandboxRun:
    return SandboxRun(component=component)  # type: ignore[arg-type]


class TestTheAdmittedRun:
    """The run the law exists to let through."""

    def test_a_listed_component_under_gvisor_is_admitted(self, law) -> None:
        decision = authorize_run(_run(SIGNAL_SANDBOX), law)
        assert decision.admitted is True
        assert decision.reason is RunReason.BY_ISOLATION

    def test_the_admission_names_the_mechanism_it_was_admitted_on(self, law) -> None:
        """So 'we run under gVisor' is a fact the decision carries rather than
        a claim a reader has to take on trust."""
        decision = authorize_run(_run(POLICY_RUNTIME), law)
        assert "gvisor" in decision.detail
        assert "runsc" in decision.detail

    def test_a_payload_does_not_change_the_answer(self, law) -> None:
        """The gate is a subject-of-the-law check, not a content filter: what
        the run carries to the sandbox is not what the isolation law reads."""
        with_payload = SandboxRun(component=SIGNAL_SANDBOX, payload={"anything": 1})
        assert authorize_run(with_payload, law).admitted is True

    def test_the_decision_forms_a_stable_audit_record(self, law) -> None:
        """Two runs of one component compose the same reason; the reason is a
        closed enum, so an audit line is greppable."""
        first = authorize_run(_run(SIGNAL_SANDBOX), law)
        second = authorize_run(_run(SIGNAL_SANDBOX), law)
        assert first.reason == second.reason
        assert first.reason == "by-isolation"


class TestTheRefusalWithoutGVisor:
    """The feature's headline: a run configured without gVisor isolation."""

    def test_a_run_on_another_runtime_is_refused(self) -> None:
        """The policy in hand carries the drift, so the *run* meets it."""
        policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism="gvisor",
                    runtime=DEFAULT_OCI_RUNTIME,
                )
            },
        )
        decision = authorize_run(_run(SIGNAL_SANDBOX), policy)
        assert decision.admitted is False
        assert decision.reason is RunReason.WITHOUT_GVISOR

    def test_a_run_on_another_mechanism_is_refused(self) -> None:
        """The other half, independently: a policy that checked only the
        runtime would admit this one."""
        policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism=MICROVM_MECHANISM,
                    runtime="runsc",
                )
            },
        )
        decision = authorize_run(_run(SIGNAL_SANDBOX), policy)
        assert decision.admitted is False
        assert decision.reason is RunReason.WITHOUT_GVISOR

    def test_the_refusal_names_both_configured_halves(self) -> None:
        """An operator reading the answer learns what the deployment is
        configured with, not merely that it was refused."""
        policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism="runc",
                    runtime=DEFAULT_OCI_RUNTIME,
                )
            },
        )
        detail = authorize_run(_run(SIGNAL_SANDBOX), policy).detail
        assert DEFAULT_OCI_RUNTIME in detail
        assert "runc" in detail

    def test_the_refusal_carries_the_features_own_code(self) -> None:
        """The same greppable token the compile raises with — one feature, one
        spelling, whichever tense the refusal arrives in."""
        policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism="gvisor",
                    runtime=DEFAULT_OCI_RUNTIME,
                )
            },
        )
        decision = authorize_run(_run(SIGNAL_SANDBOX), policy)
        assert decision.detail.startswith(ISOLATION_REQUIRED_CODE)


class TestTheRefusalBeforeTheLaw:
    """Runs the policy cannot hold to anything, kept apart from the headline."""

    def test_a_run_naming_no_component_is_refused(self, law) -> None:
        """A run that cannot say which box it belongs to cannot be held to
        that box's isolation — and the check is not something a caller may
        skip by leaving a field out."""
        decision = authorize_run(_run(""), law)
        assert decision.admitted is False
        assert decision.reason is RunReason.UNNAMED_COMPONENT

    def test_a_run_naming_a_non_string_is_refused(self, law) -> None:
        """The same reading for a value of the wrong type entirely."""
        decision = authorize_run(_run(None), law)
        assert decision.admitted is False
        assert decision.reason is RunReason.UNNAMED_COMPONENT

    def test_a_run_in_an_unlisted_component_is_refused(self, law) -> None:
        """An unlisted box is not a box with a permissive isolation; it is one
        the policy vouches for nothing, and 'unknown' is not 'gVisor's'."""
        decision = authorize_run(_run(UNLISTED_COMPONENT), law)
        assert decision.admitted is False
        assert decision.reason is RunReason.UNKNOWN_COMPONENT

    def test_the_unlisted_refusal_lists_what_is_covered(self, law) -> None:
        """So an operator can see the membership the run missed."""
        detail = authorize_run(_run(UNLISTED_COMPONENT), law).detail
        assert SIGNAL_SANDBOX in detail
        assert POLICY_RUNTIME in detail

    def test_the_three_refusals_are_three_distinct_facts(self, law) -> None:
        """Collapsing them into one 'refused' would leave a deployment unable
        to tell a typo from a drift from a missing box."""
        policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism="gvisor",
                    runtime=DEFAULT_OCI_RUNTIME,
                )
            },
        )
        reasons = {
            authorize_run(_run(""), policy).reason,
            authorize_run(_run(UNLISTED_COMPONENT), policy).reason,
            authorize_run(_run(SIGNAL_SANDBOX), policy).reason,
        }
        assert len(reasons) == 3


class TestTheDerivedAnswer:
    """The admission is computed from the consulted declaration."""

    def test_the_gate_consults_the_component_it_was_handed(self) -> None:
        """The mechanism is the policy's, not a constant: the same run against
        two policies carrying different declarations gets two answers."""
        gvisor_policy = compile_isolation_policy(committed_document())
        other_policy = IsolationPolicy(
            kind="sandbox-isolation",
            components={
                SIGNAL_SANDBOX: ComponentIsolation(
                    name=SIGNAL_SANDBOX,
                    mechanism="gvisor",
                    runtime=DEFAULT_OCI_RUNTIME,
                )
            },
        )
        assert authorize_run(_run(SIGNAL_SANDBOX), gvisor_policy).admitted is True
        assert authorize_run(_run(SIGNAL_SANDBOX), other_policy).admitted is False

    def test_an_unlisted_lookup_is_none_and_not_a_permissive_default(self, law) -> None:
        """The lookup decides nothing — an unknown component is answered by
        the gate, which is what keeps ``None`` from reading as permission."""
        assert law.isolation_of(UNLISTED_COMPONENT) is None

    def test_a_hand_built_isolation_pair_is_read_as_it_is(self) -> None:
        """``is_gvisor`` is the law's own comparison, so a caller never
        re-implements it — and a hand-assembled pair that no compiler would
        issue still reads as what it is."""
        assert ComponentIsolation(
            name="x", mechanism="gvisor", runtime="runsc"
        ).is_gvisor is True
        assert ComponentIsolation(
            name="x", mechanism="runc", runtime="runsc"
        ).is_gvisor is False
        assert ComponentIsolation(
            name="x", mechanism="gvisor", runtime="runc"
        ).is_gvisor is False


class TestRequire:
    """The bridge from the gate's answer to the exception a launcher wants."""

    def test_require_on_an_admitted_run_is_a_no_op(self) -> None:
        """So a launcher can call it unconditionally on the last line before
        it forks, rather than branching and remembering."""
        from sandbox import SandboxIsolation, committed_isolation_policy

        law = SandboxIsolation(committed_isolation_policy())
        assert law.require(SIGNAL_SANDBOX) is None

    def test_require_raises_the_members_own_error(self) -> None:
        """One error type across both tenses of the feature, so a caller
        never has to catch two."""
        from sandbox import SandboxIsolation, committed_isolation_policy

        law = SandboxIsolation(committed_isolation_policy())
        with pytest.raises(GVisorIsolationRequired):
            law.require(UNLISTED_COMPONENT)

    def test_require_carries_the_gates_own_sentence(self) -> None:
        """The exception is the decision's detail, so the raised message and
        the returned one cannot say different things."""
        from sandbox import SandboxIsolation, committed_isolation_policy

        law = SandboxIsolation(committed_isolation_policy())
        decision = law.admits(UNLISTED_COMPONENT)
        with pytest.raises(GVisorIsolationRequired) as raised:
            decision.require()
        assert str(raised.value) == decision.detail

    def test_a_decision_refusing_is_not_the_same_object_as_one_admitting(self) -> None:
        """Two decisions are two records, so an audit keeps both."""
        from sandbox import SandboxIsolation, committed_isolation_policy

        law = SandboxIsolation(committed_isolation_policy())
        admitted = law.admits(SIGNAL_SANDBOX)
        refused = law.admits(UNLISTED_COMPONENT)
        assert isinstance(admitted, RunDecision) and isinstance(refused, RunDecision)
        assert admitted.admitted is not refused.admitted
