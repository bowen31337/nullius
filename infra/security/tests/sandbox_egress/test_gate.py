"""Feature 149: the gate — every attempt answered, every answer a denial.

The sentence's consequent, at the seam untrusted code actually meets:
*which rejects any attempt to reach the data lake over the network.*
An attempt is hostile input by definition — it comes from agent-authored
code inside the sandbox — so the gate answers with a decision for every
shape and raises for none, the same stance the access gate takes for
arrivals (``host_access``). What the tests below assert is which
*reason* each attempt earns, because the reason is the audit record:
the lake's own words for the lake, §17's words for everything else.

The last group proves the derivation is real: the gate denies *because
the compiled surface is empty*, not because the gate was told to — a
hand-built surface with an allowance is admitted by the very same
consultation, which is exactly why no compiled policy can hold one.
"""

from __future__ import annotations

import pytest

from infra.security.network_policy import IngressRule
from infra.security.sandbox_egress import (
    DataLake,
    EgressAttempt,
    EgressDecision,
    EgressReason,
    SandboxEgress,
    SandboxEgressPolicy,
    SandboxEgressRuleRejected,
    authorize_egress,
    compile_sandbox_egress_policy,
)
from infra.security.tests.sandbox_egress.helpers import (
    DATA_LAKE_ADDRESS,
    DATA_LAKE_NAME,
    EXTERNAL_ADDRESS,
    EXTERNAL_NAME,
    LAKE_RULE,
    POLICY_RUNTIME,
    SESSION_BROKER,
    SIGNAL_SANDBOX,
    document_with_egress_rule,
)


def _allowance_to(destination: str, port: int = 443) -> IngressRule:
    """One hand-built egress allowance, in the shared grammar.

    Built directly rather than compiled, because the point of every
    caller below is that the compiler refuses to issue anything like
    it — a hand-built surface is the only kind that can hold one, and
    that is the fact under test.
    """
    return IngressRule.from_document(
        {"port": port, "protocol": "tcp", "destinations": [destination]},
        "a hand-built allowance",
        endpoints="destinations",
    )


def _rogue_policy(destination: str) -> SandboxEgressPolicy:
    """A hand-assembled policy granting one sandbox one allowance.

    No compiled policy can look like this (the compile refuses any
    sandbox an allowance at all), which is precisely why the gate's
    behaviour on it is informative: it shows what the consultation
    alone would do, and therefore that the denial on compiled policies
    comes from the surface's emptiness rather than from the gate.
    """
    return SandboxEgressPolicy(
        kind="sandbox-egress",
        data_lake=DataLake(name=DATA_LAKE_NAME, networks=()),
        sandboxes={
            "rogue": SandboxEgress(
                name="rogue", allowances=(_allowance_to(destination),)
            )
        },
    )


class TestEveryAttemptAtTheLakeIsRejected:
    """The named asset, in the lake's own words."""

    def test_an_attempt_at_the_lake_by_name(self, policy: SandboxEgressPolicy) -> None:
        """The headline case: the destination is the lake, and the
        answer is the feature's own reason, not the default's."""
        decision = authorize_egress(
            EgressAttempt(
                origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=443
            ),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    def test_an_attempt_at_the_lake_by_address(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The attempt that never says the lake's name: an address
        inside the networks the policy says are the lake's is
        recognized by containment and rejected in the same words."""
        decision = authorize_egress(
            EgressAttempt(
                origin=SIGNAL_SANDBOX, destination=DATA_LAKE_ADDRESS, port=9000
            ),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    @pytest.mark.parametrize("port", [1, 22, 80, 443, 5432, 65535])
    def test_an_attempt_at_the_lake_on_every_port(
        self, policy: SandboxEgressPolicy, port: int
    ) -> None:
        """'Any attempt' includes any port: the lake's rejection is of
        the path, not of a service, so no port spells it differently."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=port),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    @pytest.mark.parametrize("protocol", ["tcp", "udp", "sctp", "icmp"])
    def test_an_attempt_at_the_lake_on_every_protocol(
        self, policy: SandboxEgressPolicy, protocol: str
    ) -> None:
        """...and any protocol: a UDP probe at the lake is the same
        attempt wearing a different header."""
        decision = authorize_egress(
            EgressAttempt(
                origin=SIGNAL_SANDBOX,
                destination=DATA_LAKE_NAME,
                port=0,
                protocol=protocol,
            ),
            policy,
        )
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    def test_the_rejection_names_the_lake(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The detail is the finding an operator reads: it names the
        asset the attempt reached for."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=443),
            policy,
        )
        assert DATA_LAKE_NAME in decision.detail

    def test_the_rejection_names_the_channel(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """'Over the network' is the channel the sentence is about, and
        the rejection says so — the sandbox's data path is a payload
        channel, never a dial-out."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=443),
            policy,
        )
        assert "network" in decision.detail

    def test_the_attempt_is_answered_not_adopted(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """Refusing is repeatable: the same attempt answered three times
        is rejected three times, in the same words — there is no state
        to wear down and no partial admit between refusals."""
        attempt = EgressAttempt(
            origin=SIGNAL_SANDBOX, destination=DATA_LAKE_NAME, port=443
        )
        decisions = [authorize_egress(attempt, policy) for _ in range(3)]
        assert all(d.allowed is False for d in decisions)
        assert {d.reason for d in decisions} == {
            EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE
        }


class TestEveryOtherAttemptFallsToTheDefault:
    """§17's words for everything the lake claim does not name."""

    def test_an_external_address_is_denied_by_default(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The law is broader than its named asset: exfiltration to an
        unrelated host is denied too, by the posture itself."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=EXTERNAL_ADDRESS, port=443),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_an_external_name_is_denied_by_default(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The default catches the name spelling too — an exchange API
        the live zone may dial is not one the sandbox may."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=EXTERNAL_NAME, port=443),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_the_session_broker_is_denied_by_default(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The sharpest contrast in the vocabulary: the one destination
        the *trusted* zone's law insists on reaching (feature 156) is
        denied on the sandbox's side — an allowance earned elsewhere is
        not inherited here."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=SESSION_BROKER, port=443),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_loopback_is_denied_by_default(self, policy: SandboxEgressPolicy) -> None:
        """Even the sandbox dialing itself is denied: 'all egress' is
        not a claim about far-away destinations, it is a claim about
        the sandbox's surface."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination="127.0.0.1", port=8080),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_a_neighbouring_private_range_is_denied_by_default(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """Recognition is containment, not prefix: an address one octet
        away from the lake's network is not the lake, and it earns the
        default's words rather than the lake's."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination="10.9.0.5", port=443),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_an_ipv6_destination_is_denied_by_default(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The address families are both covered: an IPv6 dial-out that
        is not the lake falls to the default like any other."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination="2001:db8::1", port=443),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT

    def test_the_default_cites_the_clause(self, policy: SandboxEgressPolicy) -> None:
        """The detail quotes §17's posture and points at the surface it
        consulted, so the denial is traceable to the sentence."""
        decision = authorize_egress(
            EgressAttempt(origin=SIGNAL_SANDBOX, destination=EXTERNAL_ADDRESS, port=443),
            policy,
        )
        assert "by default" in decision.detail
        assert "empty" in decision.detail

    def test_the_policy_runtime_falls_to_the_default_too(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """Membership, not name: the second Z1 box gets the same answers
        the first does."""
        decision = authorize_egress(
            EgressAttempt(origin=POLICY_RUNTIME, destination=EXTERNAL_NAME, port=443),
            policy,
        )
        assert decision.reason is EgressReason.EGRESS_DENIED_BY_DEFAULT


class TestUnknownOrigins:
    """The gate answers for the compiled policy's sandboxes and nothing
    else — an unlisted origin is not a gift of egress."""

    def test_an_origin_the_policy_does_not_list(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """A box the policy does not vouch for has no surface to be
        evaluated against, and is denied as unknown rather than judged
        as covered."""
        decision = authorize_egress(
            EgressAttempt(origin="unlisted-sandbox", destination=EXTERNAL_ADDRESS, port=443),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.UNKNOWN_SANDBOX

    def test_an_empty_origin_is_answered_not_crashed(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """Hostile shapes included: a garbled origin still gets a
        decision, never an exception."""
        decision = authorize_egress(
            EgressAttempt(origin="", destination=DATA_LAKE_NAME, port=443),
            policy,
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.UNKNOWN_SANDBOX

    def test_an_unknown_origin_at_the_lake_is_still_denied(
        self, policy: SandboxEgressPolicy
    ) -> None:
        """The two rejections compose: unknown origin, lake destination
        — denied, whichever check fires first."""
        decision = authorize_egress(
            EgressAttempt(origin="unlisted-sandbox", destination=DATA_LAKE_NAME, port=443),
            policy,
        )
        assert decision.allowed is False


class TestHostileShapesGetDecisions:
    """A gate that answers untrusted code cannot be crashed by it."""

    @pytest.mark.parametrize(
        ("destination", "port", "protocol"),
        [
            (DATA_LAKE_NAME, 443, "tcp"),
            (None, 443, "tcp"),
            (23, "not-a-port", "tcp"),
            ("", -1, 7),
            (DATA_LAKE_ADDRESS, 0, ""),
        ],
        ids=[
            "well-formed",
            "null-destination",
            "non-string-destination-and-port",
            "blank-destination-negative-port-int-protocol",
            "zero-port-blank-protocol",
        ],
    )
    def test_every_attempt_shape_is_answered(
        self, policy: SandboxEgressPolicy, destination, port, protocol
    ) -> None:
        """Whatever the attempt carries, the gate returns a decision
        and never raises — the denial is computed over an empty surface,
        which is shape-proof by construction."""
        decision = authorize_egress(
            EgressAttempt(
                origin=SIGNAL_SANDBOX,
                destination=destination,
                port=port,
                protocol=protocol,
            ),
            policy,
        )
        assert isinstance(decision, EgressDecision)
        assert decision.allowed is False


class TestTheDenialIsDerivedNotHardcoded:
    """The consultation is real: the gate reads the compiled surface,
    and the law — not the gate — is what makes it empty."""

    def test_the_default_surface_admits_nothing(self) -> None:
        """A sandbox's default surface is the empty tuple — 'by
        default' is literally the constructor's posture — and the
        consultation over it admits nothing."""
        surface = SandboxEgress(name="some-sandbox")
        assert surface.allowances == ()
        assert not surface.admits(443, "tcp", EXTERNAL_NAME)
        assert surface.egress_spans() == ()

    def test_a_hand_built_surface_admits_what_it_holds(self) -> None:
        """The proof the consultation is real: give a surface an
        allowance by hand and it admits exactly that dial-out. The
        gate's denial on compiled policies is therefore the emptiness
        of the surface, not a rule inside the gate."""
        surface = SandboxEgress(
            name="rogue", allowances=(_allowance_to(EXTERNAL_NAME),)
        )
        assert surface.admits(443, "tcp", EXTERNAL_NAME)
        assert not surface.admits(445, "tcp", EXTERNAL_NAME)
        assert surface.egress_spans() == ((443, 443),)

    def test_the_gate_reads_the_surface_not_its_own_rule(self) -> None:
        """On a hand-built policy the gate admits what the surface
        holds — the very same call that denies every compiled surface
        — which is what 'derived, not hardcoded' means operationally."""
        decision = authorize_egress(
            EgressAttempt(origin="rogue", destination=EXTERNAL_NAME, port=443),
            _rogue_policy(EXTERNAL_NAME),
        )
        assert decision.allowed is True
        assert decision.reason is EgressReason.BY_ALLOWANCE

    def test_the_by_allowance_detail_says_what_it_means(self) -> None:
        """The unreachable branch explains itself for the one audience
        that can ever see it: an auditor reading a decision that could
        not have come from a compiled policy."""
        decision = authorize_egress(
            EgressAttempt(origin="rogue", destination=EXTERNAL_NAME, port=443),
            _rogue_policy(EXTERNAL_NAME),
        )
        assert decision.allowed is True
        assert "not" in decision.detail and "compiled" in decision.detail

    def test_the_lake_rejection_outranks_a_rogue_allowance(self) -> None:
        """The ordering that keeps the named asset absolute: even a
        hand-built allowance to the lake's own name cannot read as
        permission — the lake check runs before the surface is
        consulted, §1 P1 outranks everything."""
        decision = authorize_egress(
            EgressAttempt(origin="rogue", destination=DATA_LAKE_NAME, port=443),
            _rogue_policy(DATA_LAKE_NAME),
        )
        assert decision.allowed is False
        assert decision.reason is EgressReason.NO_NETWORK_PATH_TO_DATA_LAKE

    def test_no_compiled_policy_can_hold_an_allowance(self) -> None:
        """The other half of the derivation: surfaces with allowances
        can only be hand-built, because the compile refuses to issue
        one — which is why 'by-allowance' on an audit line is itself
        the finding."""
        with pytest.raises(SandboxEgressRuleRejected):
            compile_sandbox_egress_policy(document_with_egress_rule(LAKE_RULE))
