"""Feature 158's law: egress is rejected at the namespace level, not by rule.

app_spec.xml, "Untrusted Code Sandbox", feature 158: *System places the sandbox
in a network namespace with no interfaces, which rejects egress at the namespace
level rather than by firewall rule.*  This file tests that sentence clause by
clause, because a gate that admitted any two of them would be a different and
worse feature:

* **places the sandbox in a network namespace** — the mechanism half, modelled
  as a :class:`~sandbox.network.NetworkNamespace`: the box and the interfaces it
  was given, built by the caller from what a runtime reported.  Nothing here
  creates a namespace — the division feature 157 draws between its isolation
  policy and the ``runsc`` runtime that enforces it — so the tests pin the
  *description* a launcher writes (:meth:`NetworkNamespace.specification`)
  rather than an ``unshare`` this law never calls;
* **with no interfaces** — the configuration term, and the only thing an
  attempt is judged against.  The load-bearing read is
  :meth:`NetworkNamespace.egress_interfaces`, which is what makes the rejection
  a *consultation* rather than a hardcoded denial — the same property
  :meth:`infra.security.sandbox_egress.SandboxEgress.admits` has over its
  allowances;
* **which rejects egress at the namespace level** — the gate, and the answer
  every §5.2 placement produces: :func:`reject_egress` refuses an attempt whose
  box has no interface to leave by, and says so;
* **rather than by firewall rule** — the contrast clause as a value:
  :attr:`NetworkDecision.at_namespace` is ``True`` exactly when the namespace
  itself refused, ``False`` when something above it did.  A test that did not
  pin this would not tell this law apart from feature 149's.

The last class exercises the composed path an assembled system takes, through
:class:`~sandbox.network.SandboxNetwork` — because a facade that wired the
registration but not the gate would pass every module-level test here.
"""

from __future__ import annotations

import pytest
import sandbox
from sandbox import (
    EGRESS_REJECTED_CODE,
    LOOPBACK_NAMES,
    NAMESPACE_REQUIRED_CODE,
    NO_NETWORK_MODE,
    EgressPath,
    EgressRejected,
    NamespacePlacementError,
    NetworkDecision,
    NetworkNamespace,
    NetworkReason,
    SandboxNetwork,
    egress_rejected,
    isolated_namespace,
    reject_egress,
    sandbox_network,
)

#: The interfaces a runtime reports for a box §5.2 placed: the loopback the
#: kernel creates *with* a namespace and cannot remove, and nothing else.
KERNEL_LOOPBACK = ("lo",)


def _attempt(
    origin: str = "signal-runner",
    destination: str = "api.exchange.com",
    port: int = 443,
    interface: str = "",
) -> EgressPath:
    """One dial-out from inside the box, as the runtime would report it."""
    return EgressPath(
        origin=origin,
        destination=destination,
        port=port,
        protocol="tcp",
        interface=interface,
    )


def _placed() -> NetworkNamespace:
    """A box placed as §5.2 requires — the namespace every box here is in."""
    return isolated_namespace("signal-runner", KERNEL_LOOPBACK)


class TestTheNamespaceWithNoInterfaces:
    """The configuration term: what a box was placed with, and what it holds."""

    def test_a_placement_reports_no_egress_interface(self) -> None:
        namespace = _placed()
        assert namespace.egress_interfaces() == ()
        assert namespace.is_isolated is True

    def test_loopback_is_not_an_egress_interface(self) -> None:
        # A namespace is created *with* loopback and it cannot be removed, so
        # §5.2's row read literally would refuse every namespace a kernel can
        # build.  A packet sent to ``lo`` never leaves the box, which is why the
        # law counts *egress-capable* interfaces — and why the runtime's own
        # spelling of the row is ``NetworkMode: "none"``, which creates exactly
        # this shape.
        for spelling in ("lo", "lo0", "LO", " lo "):
            assert NetworkNamespace(interfaces=(spelling,)).egress_interfaces() == ()
        assert LOOPBACK_NAMES == frozenset({"lo", "lo0"})

    def test_a_bare_string_is_one_interface_name_not_its_characters(self) -> None:
        # ``interfaces="eth0"`` is the natural way for a caller to say *the one
        # interface I know about*, and iterating it would shatter the name into
        # four interfaces the box never held — a refusal sentence naming
        # nonsense, and a box that looks like it holds four things.
        namespace = NetworkNamespace(component="signal-runner", interfaces="eth0")
        assert namespace.interfaces == ("eth0",)
        assert namespace.egress_interfaces() == ("eth0",)
        assert namespace.is_isolated is False

    def test_a_bare_loopback_string_is_still_loopback(self) -> None:
        namespace = NetworkNamespace(component="signal-runner", interfaces="lo")
        assert namespace.interfaces == ("lo",)
        assert namespace.is_isolated is True

    def test_a_constructor_list_and_a_duck_typed_attribute_read_alike(self) -> None:
        # One normaliser, because two would be two answers to the same question:
        # a caller's ``interfaces`` is read identically whether it arrived as a
        # constructor argument or as an attribute on a stand-in placement.
        class StandIn:
            interfaces = "eth0"

        built = NetworkNamespace(component="signal-runner", interfaces="eth0")
        from sandbox.network import _egress_of, _interfaces_of

        assert _interfaces_of(StandIn()) == built.interfaces
        assert _egress_of(StandIn()) == built.egress_interfaces()
        assert reject_egress(_attempt(), StandIn()).reason is NetworkReason.BY_INTERFACE

    def test_any_iterable_of_names_is_read(self) -> None:
        # The normaliser accepts what a runtime's report is likely to arrive as
        # — a tuple, a list, a set, a generator — so a caller never has to know
        # which shape this law happened to want.
        for reported in (
            ("lo", "eth0"),
            ["lo", "eth0"],
            {"lo", "eth0"},
            (name for name in ("lo", "eth0")),
        ):
            assert set(NetworkNamespace(interfaces=reported).egress_interfaces()) == {
                "eth0"
            }

    def test_something_that_is_not_iterable_reports_no_interfaces(self) -> None:
        # Not a type error: this read is never the thing that errors, because
        # the gate's *placement* check is what refuses a subject that is not a
        # placement at all.
        assert NetworkNamespace(interfaces=7).interfaces == ()
        assert NetworkNamespace(interfaces=None).interfaces == ()

    def test_an_interface_the_law_has_never_heard_of_is_egress_capable(self) -> None:
        # Written as the exception rather than as a deny-list, deliberately and
        # in the conservative direction: a deployment adding ``veth``, ``tun0``
        # or a bridge of its own is caught by default rather than by someone
        # remembering to add it here.
        for name in ("eth0", "veth0", "tun0", "docker0", "wlan0", "en0"):
            namespace = NetworkNamespace(component="signal-runner", interfaces=(name,))
            assert namespace.egress_interfaces() == (name,), name
            assert namespace.is_isolated is False, name

    def test_the_egress_surface_is_derived_per_call_not_stored(self) -> None:
        # The emptiness is the *mechanism*, not a constant: the gate's answer is
        # the namespace arriving at its answer, so a placement handed an
        # interface reports it — which is what makes ``by-interface`` a reachable
        # audit finding rather than a decoration.
        namespace = _placed()
        assert namespace.egress_interfaces() == ()
        namespace.interfaces = ("lo", "eth0")
        assert namespace.egress_interfaces() == ("eth0",)

    def test_the_reported_interfaces_keep_the_order_they_arrived_in(self) -> None:
        namespace = NetworkNamespace(interfaces=("lo", "eth0", "veth0"))
        assert namespace.interfaces == ("lo", "eth0", "veth0")
        assert namespace.egress_interfaces() == ("eth0", "veth0")

    def test_holds_answers_for_a_name_the_namespace_carries(self) -> None:
        namespace = NetworkNamespace(interfaces=("lo",))
        assert namespace.holds("lo") is True
        assert namespace.holds("eth0") is False
        # A name that is not a string holds nothing — the read is a membership
        # question, not a place for untrusted input to raise.
        assert namespace.holds(None) is False

    def test_a_default_placement_is_the_stricter_reading(self) -> None:
        # No interfaces at all is §5.2's row at its most literal, and it is the
        # honest default for a caller that has not asked its runtime yet.
        assert isolated_namespace("signal-runner").is_isolated is True
        assert isolated_namespace("signal-runner").interfaces == ()


class TestThePlacement:
    """``specification()`` — the description a launcher hands its runtime."""

    def test_a_placed_box_describes_the_runtimes_own_spelling_of_the_row(self) -> None:
        assert _placed().specification() == {"NetworkMode": NO_NETWORK_MODE}
        assert NO_NETWORK_MODE == "none"

    def test_the_specification_is_a_fresh_dict_each_call(self) -> None:
        # The copy-then-hand discipline every read side in this member applies:
        # a caller that mutated what it was handed must not widen the namespace
        # for the next one.
        namespace = _placed()
        first = namespace.specification()
        first["NetworkMode"] = "bridge"
        assert namespace.specification() == {"NetworkMode": "none"}

    def test_a_placement_holding_an_interface_cannot_be_described(self) -> None:
        # The refusal is the point rather than an inconvenience: the
        # specification is §5.2's row, so writing one from a placement holding
        # an interface would hand a runtime the row while the box being spawned
        # is in a namespace that does not hold it.
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        with pytest.raises(NamespacePlacementError) as raised:
            namespace.specification()
        assert str(raised.value).startswith(NAMESPACE_REQUIRED_CODE)
        assert "eth0" in str(raised.value)

    def test_loopback_alone_does_not_block_the_specification(self) -> None:
        # The other side of the same rule: a placement with loopback is placed,
        # because loopback cannot carry a packet off the box.
        assert _placed().specification() == {"NetworkMode": "none"}


class TestAtTheNamespace:
    """The feature firing: there was no interface to leave by."""

    def test_an_attempt_in_a_placed_box_is_rejected_at_the_namespace(self) -> None:
        decision = reject_egress(_attempt(), _placed())

        assert decision.admitted is False
        assert decision.rejected is True
        assert decision.reason is NetworkReason.AT_NAMESPACE
        assert decision.at_namespace is True

    def test_the_rejection_is_the_namespace_doing_the_refusing(self) -> None:
        # The refusal names the interfaces the namespace *holds*, so an operator
        # reads what the box was placed with rather than a rule that denied it.
        decision = reject_egress(_attempt(), _placed())
        assert "its interfaces are ['lo']" in decision.detail
        assert "cannot carry a packet off the box" in decision.detail

    def test_an_attempt_naming_an_interface_the_box_never_held_says_so(self) -> None:
        # An attempt inside a namespace with no egress interface names either
        # nothing or a name the box never held; the refusal says which, because
        # an operator repairing a dispatch needs to know what the box reached
        # *for* — the stance feature 160 takes toward a call's arguments.
        decision = reject_egress(_attempt(interface="eth0"), _placed())

        assert decision.reason is NetworkReason.AT_NAMESPACE
        assert "does not hold" in decision.detail
        assert "'eth0'" in decision.detail

    def test_the_attempt_is_carried_on_the_decision(self) -> None:
        attempt = _attempt(destination="evil.example", port=8080)
        decision = reject_egress(attempt, _placed())
        assert decision.path is attempt
        assert decision.namespace is not None
        assert decision.namespace.component == "signal-runner"

    def test_a_box_that_was_never_placed_is_refused_conservatively(self) -> None:
        # ``None`` is a state a caller can be in, and the honest answer to it is
        # a refusal rather than a traceback — the host's own network is not
        # §5.2's posture, and a gate that read the absence as permission would
        # be admitting egress on the strength of a placement nobody made.
        decision = reject_egress(_attempt(), None)

        assert decision.admitted is False
        assert decision.reason is NetworkReason.NOT_PLACED
        # The namespace did *not* do this refusing — that distinction is the
        # feature's contrast clause, and it survives the refusal.
        assert decision.at_namespace is False

    def test_an_attempt_attributed_to_another_box_is_refused(self) -> None:
        # One namespace answers for one box: an attempt attributed to another is
        # one this placement cannot speak about, and answering either way would
        # be reporting a decision made about a different box — the reading
        # feature 149 gives an origin its policy does not list.
        decision = reject_egress(_attempt(origin="another-runner"), _placed())

        assert decision.admitted is False
        assert decision.reason is NetworkReason.UNKNOWN_SANDBOX
        assert decision.at_namespace is False

    def test_an_attempt_with_no_origin_is_not_mismatched(self) -> None:
        # A path carrying no origin makes no claim about which box it came from,
        # so there is nothing to disagree with — the placement answers instead.
        decision = reject_egress(_attempt(origin=""), _placed())
        assert decision.reason is NetworkReason.AT_NAMESPACE


class TestByInterface:
    """The one acceptance, and why reading it is itself a finding."""

    def test_a_placement_holding_an_interface_admits_the_attempt(self) -> None:
        namespace = NetworkNamespace(
            component="signal-runner", interfaces=("lo", "eth0")
        )
        decision = reject_egress(_attempt(), namespace)

        assert decision.admitted is True
        assert decision.reason is NetworkReason.BY_INTERFACE
        # Admitted — and emphatically *not* a namespace-level rejection.
        assert decision.at_namespace is False

    def test_the_acceptance_names_the_interface_as_the_finding(self) -> None:
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        decision = reject_egress(_attempt(), namespace)

        assert "eth0" in decision.detail
        assert "audit finding" in decision.detail

    def test_no_placement_built_as_the_row_requires_can_produce_it(self) -> None:
        # The reason this spelling is reachable at all is the reason it is
        # valuable: under every namespace §5.2 describes the egress surface is
        # empty, so an admitted attempt is proof the placement was hand-built or
        # reported wrong — the exact role ``by-allowance`` plays for feature 149.
        assert (
            reject_egress(_attempt(), _placed()).reason
            is not NetworkReason.BY_INTERFACE
        )
        assert reject_egress(_attempt(), isolated_namespace("x")).reason is not (
            NetworkReason.BY_INTERFACE
        )

    def test_the_boolean_read_side_reports_the_same_thing(self) -> None:
        assert egress_rejected(_attempt(), _placed()) is True
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        assert egress_rejected(_attempt(), namespace) is False


class TestTheContrastClause:
    """``at-namespace`` — the sentence's last clause, pinned as a value."""

    def test_at_namespace_is_true_only_for_the_namespaces_own_refusal(self) -> None:
        assert reject_egress(_attempt(), _placed()).at_namespace is True
        assert reject_egress(_attempt(), None).at_namespace is False
        assert reject_egress(_attempt("other"), _placed()).at_namespace is False
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        assert reject_egress(_attempt(), namespace).at_namespace is False

    def test_every_reason_every_spelling_names_an_interface_not_a_rule(self) -> None:
        # The clause written as vocabulary: no reason here is about an allowance
        # or a rule, which is what keeps this law's audit lines tellable apart
        # from feature 149's at a glance.
        for reason in NetworkReason:
            assert "rule" not in reason.value
            assert "allowance" not in reason.value
        assert {reason.value for reason in NetworkReason} == {
            "at-namespace",
            "not-placed",
            "unknown-sandbox",
            "by-interface",
        }

    def test_the_decision_reported_as_a_namespace_rejection_is_the_only_one(
        self,
    ) -> None:
        # A caller that read a bare falsy as "the box was fine" must not mistake
        # an unplaced box for an admitted one — the distinction the other gates
        # in this member keep for theirs.
        for decision in (
            reject_egress(_attempt(), _placed()),
            reject_egress(_attempt(), None),
            reject_egress(_attempt("other"), _placed()),
        ):
            assert decision.rejected is (not decision.admitted)


class TestTheRefusal:
    """Every refusal carries the greppable code and §5.2's row, and ``require`` raises."""

    def test_every_refusal_message_starts_with_the_egress_code(self) -> None:
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        refusals = [
            reject_egress(_attempt(), _placed()).detail,
            reject_egress(_attempt(), None).detail,
            reject_egress(_attempt("other"), _placed()).detail,
            # The acceptance does not start with the code — it is not a refusal.
            reject_egress(_attempt(), namespace).detail,
        ]
        for message in refusals[:3]:
            assert message.startswith(EGRESS_REJECTED_CODE), message
        assert EGRESS_REJECTED_CODE == "egress_rejected"
        assert not refusals[3].startswith(EGRESS_REJECTED_CODE)

    def test_every_refusal_message_carries_the_control_table_row(self) -> None:
        # One body rather than several literals: each refusal names the law it
        # enforces in the architecture's own words, so a reader of any one of
        # them can find the row the others cite without grep.
        message = reject_egress(_attempt(), _placed()).detail
        assert "Network | Namespace with no interfaces. Not a firewall rule." in message

    def test_the_refusal_says_it_was_not_a_firewall_rule(self) -> None:
        message = reject_egress(_attempt(), _placed()).detail
        assert "not a firewall rule" in message
        assert "feature 158" in message

    def test_require_raises_the_nested_error(self) -> None:
        # The raise lives on the decision's ``require``, the launcher's last
        # line before the spawn — and a launcher must hear about the unplaced
        # box too, because an unplaced box is a box whose egress nothing
        # rejected.
        with pytest.raises(EgressRejected) as raised:
            reject_egress(_attempt(), _placed()).require()
        assert str(raised.value).startswith(EGRESS_REJECTED_CODE)

        with pytest.raises(EgressRejected):
            reject_egress(_attempt(), None).require()

    def test_require_on_an_admitted_attempt_is_a_no_op(self) -> None:
        namespace = NetworkNamespace(component="signal-runner", interfaces=("eth0",))
        assert reject_egress(_attempt(), namespace).require() is None

    def test_all_three_refusals_raise_the_one_class(self) -> None:
        # The two halves of the sentence carry one error type, so a caller never
        # has to catch two — the division feature 157's and feature 159's
        # decisions make for their own pairs.
        for decision in (
            reject_egress(_attempt(), _placed()),
            reject_egress(_attempt(), None),
            reject_egress(_attempt("other"), _placed()),
        ):
            with pytest.raises(EgressRejected):
                decision.require()

    def test_egress_rejected_is_not_the_isolation_error(self) -> None:
        # A sibling, not a subclass: *which runtime executed the box* and *what
        # network surface it was placed with* are separate rows of §5.2's table,
        # and a deployment can be running runsc with a box that has a way out.
        from sandbox.errors import SandboxIsolationError, SandboxNetworkError

        assert issubclass(EgressRejected, SandboxNetworkError)
        assert not issubclass(EgressRejected, SandboxIsolationError)
        assert not issubclass(NamespacePlacementError, SandboxIsolationError)

    def test_the_placement_error_is_not_the_gates_error(self) -> None:
        # Two codes rather than one, because the repairs are on opposite sides
        # of the seam: one means a *placement* is wrong, the other that an
        # *attempt* was refused.
        assert NamespacePlacementError is not EgressRejected
        assert NAMESPACE_REQUIRED_CODE != EGRESS_REJECTED_CODE


class TestTheDuckTypedSubject:
    """The gate reads an attempt by its fields, not by its class."""

    def test_a_stand_in_attempt_carrying_the_fields_is_read(self) -> None:
        # Feature 149's ``EgressAttempt`` carries exactly these four names, so a
        # deployment's own attempt type — or that one — is answered without
        # being re-described.
        class EgressAttempt:
            def __init__(self, origin: str, destination: str, port: int) -> None:
                self.origin = origin
                self.destination = destination
                self.port = port
                self.protocol = "tcp"

        decision = reject_egress(
            EgressAttempt("signal-runner", "api.exchange.com", 443), _placed()
        )

        assert decision.admitted is False
        assert decision.reason is NetworkReason.AT_NAMESPACE

    def test_an_attempt_missing_every_field_is_still_answered(self) -> None:
        # An attempt is untrusted input and this law's job is to answer it — not
        # to be the second thing that can go wrong with it.
        class Bare:
            pass

        decision = reject_egress(Bare(), _placed())

        assert decision.admitted is False
        assert decision.reason is NetworkReason.AT_NAMESPACE

    def test_an_origin_that_is_not_a_string_makes_no_claim(self) -> None:
        class Odd:
            origin = 17

        decision = reject_egress(Odd(), _placed())
        assert decision.reason is NetworkReason.AT_NAMESPACE

    def test_a_thing_that_is_not_a_placement_is_a_caller_error(self) -> None:
        # Raised rather than returned: a placement is trusted host code, and a
        # gate handed something else has no egress surface to consult — which is
        # a fact about the caller rather than about the attempt.
        with pytest.raises(NamespacePlacementError) as raised:
            reject_egress(_attempt(), {"NetworkMode": "none"})
        assert str(raised.value).startswith(NAMESPACE_REQUIRED_CODE)


class TestTheSubjectAsAValue:
    """``EgressPath`` — what the runtime reported, never a probe."""

    def test_describe_names_where_the_box_reached_for(self) -> None:
        attempt = _attempt(destination="api.exchange.com", port=443)
        assert attempt.describe() == "'api.exchange.com':443/tcp"

    def test_the_row_carries_the_attempt_for_a_ledger(self) -> None:
        attempt = _attempt(interface="eth0")
        row = attempt.row()
        assert row == {
            "origin": "signal-runner",
            "destination": "api.exchange.com",
            "port": 443,
            "protocol": "tcp",
            "interface": "eth0",
        }
        # Fresh per call, never a shared one.
        row["port"] = 0
        assert attempt.row()["port"] == 443

    def test_the_row_omits_an_interface_that_was_never_named(self) -> None:
        assert "interface" not in _attempt(interface="").row()


class TestTheFacade:
    """``SandboxNetwork`` — the law as the value a composed application carries."""

    def test_check_answers_and_require_raises(self) -> None:
        law = sandbox_network()

        assert law.check(_attempt(), _placed()).admitted is False
        with pytest.raises(EgressRejected):
            law.require(_attempt(), _placed())

    def test_the_facade_is_stateless_and_carries_no_namespace(self) -> None:
        # A namespace belongs to one box; a component shared across runs that
        # carried one would be a component letting two boxes share a network
        # posture.
        first = sandbox_network()
        second = sandbox_network()
        assert first is not second
        assert SandboxNetwork.__slots__ == ()
        with pytest.raises(AttributeError):
            first.interfaces = ("eth0",)

    def test_the_facade_builds_the_namespace_a_caller_needs(self) -> None:
        law = sandbox_network()
        namespace = law.namespace("signal-runner", ("lo",))
        assert namespace.is_isolated is True
        assert law.check(_attempt(), namespace).reason is NetworkReason.AT_NAMESPACE

    def test_the_read_side_answers_what_posture_a_box_is_in(self) -> None:
        law = sandbox_network()
        assert law.isolated(_placed()) is True
        assert law.interfaces(_placed()) == ()
        assert law.isolated(NetworkNamespace(interfaces=("eth0",))) is False
        assert law.interfaces(NetworkNamespace(interfaces=("lo", "eth0"))) == ("eth0",)

    def test_the_read_side_is_conservative_about_what_it_cannot_read(self) -> None:
        # "Unknown" is not "isolated": a box nobody placed is not a box with no
        # network, it is one whose network nobody has spoken about.
        law = sandbox_network()
        assert law.isolated(None) is False
        assert law.isolated("sandbox-network") is False
        assert law.interfaces(None) == ()

    def test_the_decision_is_a_value_a_caller_can_inspect(self) -> None:
        decision = NetworkDecision(
            admitted=False,
            reason=NetworkReason.AT_NAMESPACE,
            detail=f"{EGRESS_REJECTED_CODE}: ...",
        )
        assert decision.path is None
        assert decision.namespace is None
        assert decision.at_namespace is True
        assert decision.rejected is True

    def test_the_module_convenience_is_the_composed_laws_verb_set(self) -> None:
        component = sandbox.sandbox_network()
        for operation in ("check", "require", "namespace", "isolated", "interfaces"):
            assert callable(getattr(component, operation)), operation


class TestTheComposedLaw:
    """Feature 158 through the composed application — the path an assembled system
    actually takes.  A wiring that registered a component whose gate did not
    refuse would pass every module-level test above and fail here."""

    def test_the_composed_law_refuses_an_attempt_in_a_placed_box(self) -> None:
        from pathlib import Path

        from app.module_loader import Registration, create_app

        member_src = Path(sandbox.__file__).resolve().parent.parent
        law = create_app(member_src, registry=Registration()).get("sandbox-network")

        assert type(law).__name__ == "SandboxNetwork"
        decision = law.check(_attempt(), _placed())
        assert decision.admitted is False
        # Compared by *value*, not by identity: the loader imports the member
        # under a scan alias, so the reason the composed law publishes is a
        # ``NetworkReason`` from another copy of this module and ``is`` cannot
        # hold across that seam.  The spelling is what the audit line carries,
        # so the spelling is what is pinned.
        assert decision.reason.value == NetworkReason.AT_NAMESPACE.value
        assert decision.reason == "at-namespace"
        assert decision.at_namespace is True

        # The error class is compared by *name* rather than by identity, for the
        # same seam: the composed law raises an ``EgressRejected`` from the
        # loader's copy of the member, which is not this test's class object.
        with pytest.raises(Exception) as raised:
            law.require(_attempt(), _placed())
        assert type(raised.value).__name__ == "EgressRejected"
        assert str(raised.value).startswith(EGRESS_REJECTED_CODE)
