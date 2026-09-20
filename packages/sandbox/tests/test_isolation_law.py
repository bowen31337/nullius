"""Feature 157: the member's own surface — the facade over the law.

The component the factory composes (:class:`sandbox.SandboxIsolation`) is a
*stateless facade* over :mod:`sandbox.isolation` and the committed policy it
compiled, so it carries the value a later feature in this category attaches to
without importing the member's submodules by name.  This file pins that
surface: which verbs exist, that each delegates rather than re-implements, that
reading the isolation of a box answers a real deployment question, and that the
convenience constructor is the same call the builder makes minus composition.

The delegation matters more than it looks.  A facade that re-implemented the
gVisor comparison — say, by checking ``mechanism == "gvisor"`` and forgetting
the runtime — would pass every test in :mod:`test_gate` that goes through
:func:`authorize_run` while refusing nothing for a caller who used the
component's own verb.  So the tests below drive the *component* and assert on
the same law the module tests assert on.
"""

from __future__ import annotations

import pytest
from _documents import POLICY_RUNTIME, SIGNAL_SANDBOX, UNLISTED_COMPONENT
from sandbox import (
    GVISOR_MECHANISM,
    GVISOR_RUNTIME,
    ISOLATION_REQUIRED_CODE,
    GVisorIsolationRequired,
    SandboxIsolation,
    committed_isolation_policy,
    sandbox_isolation,
)


@pytest.fixture()
def law() -> SandboxIsolation:
    """The composed component's value — the committed policy, as a facade."""
    return sandbox_isolation()


class TestTheFacade:
    """The verbs the composed component carries, and what each answers."""

    def test_the_convenience_constructor_is_the_builders_call_minus_composition(
        self, law: SandboxIsolation
    ) -> None:
        """Both compile the committed artifact, so a caller reaching the law
        directly and a caller reaching it through the factory get the same
        policy rather than two that agree by luck."""
        assert law.policy.names() == committed_isolation_policy().names()
        assert type(law).__name__ == "SandboxIsolation"

    def test_admits_answers_the_gates_decision(self, law) -> None:
        """The value-shaped verb, for a caller that wants to branch."""
        decision = law.admits(SIGNAL_SANDBOX)
        assert decision.admitted is True
        assert decision.reason == "by-isolation"

    def test_require_is_silent_for_an_admitted_run(self, law) -> None:
        """The launcher's verb, usable unconditionally on the last line
        before a fork."""
        assert law.require(SIGNAL_SANDBOX) is None
        assert law.require(POLICY_RUNTIME) is None

    def test_require_refuses_an_unlisted_component(self, law) -> None:
        """The facade does not soften the law: an unlisted box is refused
        through the component exactly as it is through the module."""
        with pytest.raises(GVisorIsolationRequired) as raised:
            law.require(UNLISTED_COMPONENT)
        assert str(raised.value).startswith(ISOLATION_REQUIRED_CODE)

    def test_the_facade_reads_the_runtime_and_not_only_the_mechanism(self) -> None:
        """The collapse this file exists to catch: a facade that checked only
        the mechanism would admit a box on Docker's default runtime — the
        exact near-miss feature 157 is about."""
        from sandbox import ComponentIsolation, IsolationPolicy

        drifted = SandboxIsolation(
            IsolationPolicy(
                kind="sandbox-isolation",
                components={
                    SIGNAL_SANDBOX: ComponentIsolation(
                        name=SIGNAL_SANDBOX, mechanism="gvisor", runtime="runc"
                    )
                },
            )
        )
        assert drifted.is_gvisor(SIGNAL_SANDBOX) is False
        with pytest.raises(GVisorIsolationRequired):
            drifted.require(SIGNAL_SANDBOX)


class TestTheReadSide:
    """What a deployment can *ask* about itself, which is what makes the
    posture auditable rather than asserted."""

    def test_isolation_of_answers_the_real_pair(self, law) -> None:
        """*What mechanism does this box run under?* is a question an operator
        should be able to answer, and the answer is the compiled one."""
        component = law.isolation_of(SIGNAL_SANDBOX)
        assert component is not None
        assert component.mechanism == GVISOR_MECHANISM
        assert component.runtime == GVISOR_RUNTIME

    def test_isolation_of_an_unlisted_component_is_none(self, law) -> None:
        """A statement about the policy, not an admission — which is why
        ``admits`` refuses it instead of reading ``None`` as permission."""
        assert law.isolation_of(UNLISTED_COMPONENT) is None

    def test_is_gvisor_is_false_for_an_unlisted_component(self, law) -> None:
        """The conservative reading, matching the gate's: 'unknown' is not
        'gVisor's'."""
        assert law.is_gvisor(SIGNAL_SANDBOX) is True
        assert law.is_gvisor(UNLISTED_COMPONENT) is False

    def test_components_lists_the_membership_the_deployment_holds(self, law) -> None:
        """§3's two Z1 boxes — the same membership features 148 and 149
        carry."""
        assert set(law.components()) == {SIGNAL_SANDBOX, POLICY_RUNTIME}

    def test_the_read_side_and_the_gate_agree_on_every_component(self, law) -> None:
        """Two verbs, one law: a box reading as gVisor's must be admitted, and
        one that is not must be refused. A facade whose read side drifted from
        its gate would be a deployment auditing itself with a different answer
        than the one it enforces."""
        for name in (*law.components(), UNLISTED_COMPONENT):
            assert law.is_gvisor(name) is law.admits(name).admitted


class TestTheComponentShape:
    """The member owns its vocabulary and shares no hierarchy."""

    def test_the_error_vocabulary_is_the_members_own(self) -> None:
        """The sandbox is the box untrusted code goes inside, so its refusals
        must not share a hierarchy with anything a caller could confuse with
        them — the same one-way rule the other members state.

        Checked by the base the member actually ships rather than against
        another member's class: this suite imports no other member, which is
        itself the property (the sandbox law resolves nothing from the
        workspace), so the assertion is that the hierarchy stops at this
        member's base and reaches no further.
        """
        from sandbox.errors import SandboxError, SandboxIsolationError

        assert issubclass(GVisorIsolationRequired, SandboxIsolationError)
        assert issubclass(SandboxIsolationError, SandboxError)
        assert SandboxError.__bases__ == (Exception,)
        # And separately from the document contract, so a caller can tell the
        # two apart — which is the whole reason they are two classes.
        from sandbox.errors import IsolationDocumentError

        assert not issubclass(IsolationDocumentError, GVisorIsolationRequired)

    def test_the_law_exports_its_vocabulary_through_the_package(self) -> None:
        """A caller reaches the feature's terms from the member rather than
        from a submodule path, so the category's later features share one
        spelling."""
        import sandbox as member

        for name in (
            "SandboxIsolation",
            "SandboxRun",
            "RunDecision",
            "RunReason",
            "IsolationPolicy",
            "ComponentIsolation",
            "GVisorIsolationRequired",
            "IsolationDocumentError",
            "compile_isolation_policy",
            "authorize_run",
            "committed_isolation_policy",
            "GVISOR_MECHANISM",
            "GVISOR_RUNTIME",
            "ISOLATION_REQUIRED_CODE",
        ):
            assert name in member.__all__, name
            assert hasattr(member, name), name

    def test_the_law_carries_no_runtime_handle(self, law) -> None:
        """The feature is a law about *configuration*, so the component holds
        the policy and nothing else — no process, no daemon, no runner. That
        is what lets it compose in a bare test process, and it is checked here
        because a later feature adding a handle is exactly how that property
        would be lost silently."""
        assert law.__slots__ == ("_policy",)
