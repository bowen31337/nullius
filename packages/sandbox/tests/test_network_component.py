"""Feature 158's plugin seam: the twelfth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-network`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the
twelfth seat: the factory's registry *replaces* a name's earlier registration,
so a control registered as ``sandbox``, ``sandbox-isolation`` or
``sandbox-payload`` would silently overwrite feature 157's isolation law or
159's payload law — composition would look perfect and a control would be gone.
The tests below pin that the member now carries exactly twelve components, each
under its own feature's name, and that the eleven earlier laws are still beside
the twelfth after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

The composed law is exercised through the same path an assembled system takes —
an attempt handed to the component's ``require``, with the namespace the box was
placed in — so a builder that wired the registration but not the gate would pass
the wiring assertions and fail here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from sandbox import (
    EGRESS_REJECTED_CODE,
    EgressPath,
    NetworkNamespace,
    isolated_namespace,
)

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
)

#: The member's ``src/`` — the package-parent the loader scans. Derived from
#: the imported package rather than from this file's position, so the suite
#: gives the same answer wherever pytest is invoked from.
MEMBER_SRC = Path(sandbox.__file__).resolve().parent.parent


def _placed() -> NetworkNamespace:
    """A box placed as §5.2 requires — the namespace every box here is in."""
    return isolated_namespace("signal-runner", ("lo",))


def _attempt() -> EgressPath:
    """One dial-out from inside the box, as the runtime would report it."""
    return EgressPath(
        origin="signal-runner",
        destination="api.exchange.com",
        port=443,
        protocol="tcp",
        interface="eth0",
    )


def _assert_is_the_network_law(component: object) -> None:
    assert type(component).__name__ == "SandboxNetwork"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``check`` returns the gate's decision, ``require`` turns a refusal into the
    # exception a launcher calls, and the other three are the read side.
    for operation in ("check", "require", "namespace", "isolated", "interfaces"):
        assert callable(getattr(component, operation)), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.NETWORK_COMPONENT_NAME == "sandbox-network"


def test_the_component_name_is_not_any_earlier_laws() -> None:
    # The registry-replacement hazard at the constant: none of the eleven
    # earlier names, and not feature 149's spelling either — that law owns the
    # word *egress* for the written policy that denies by default, and this one
    # is the mechanism underneath it.
    assert sandbox.NETWORK_COMPONENT_NAME not in {
        "sandbox",
        "sandbox-imports",
        "sandbox-transfer",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-failclass",
        "sandbox-budget",
        "sandbox-syscalls",
        "sandbox-quarantine",
        "sandbox-payload",
        "sandbox-egress",
    }


def test_the_seat_declares_the_same_component_name() -> None:
    # The app namespace respells the member's constant rather than importing it
    # (the seat must not depend on the member at import time), so the two
    # spellings are pinned equal here: a drift would be a silent ``None`` at the
    # seat rather than a failure, which is the worst shape a wiring bug can take.
    import app.modules.sandbox as seat

    assert seat.NETWORK_COMPONENT_NAME == sandbox.NETWORK_COMPONENT_NAME


def test_scanning_the_member_registers_the_twelve_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's cgroup-limits
    # law, the import law, feature 158's network law, the payload delivery, the
    # quarantine, the node seed, the seccomp law, the thread-pinning law, the
    # wall-clock law, the payload channel and feature 168's fail-class law, no
    # more and no less.  A thirteenth component arriving unnoticed fails here —
    # and a builder that had taken any earlier feature's name would fail here
    # too, which is the registry-replacement hazard this file exists for.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-budget",
        "sandbox-failclass",
        "sandbox-imports",
        "sandbox-network",
        "sandbox-payload",
        "sandbox-quarantine",
        "sandbox-seed",
        "sandbox-syscalls",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-transfer",
    ]


def test_the_network_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all twelve builders have fired, the
    # composed application still carries features 157's, 167's, 166's, 165's,
    # 164's, 163's, 168's, 162's, 160's, 161's and 159's laws under their own
    # names — a twelfth registration of any of those names would have replaced
    # one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    assert type(app.get("sandbox-threads")).__name__ == "SandboxThreads"
    assert type(app.get("sandbox-timeout")).__name__ == "SandboxTimeout"
    assert type(app.get("sandbox-failclass")).__name__ == "SandboxFailClass"
    assert type(app.get("sandbox-budget")).__name__ == "SandboxBudget"
    assert type(app.get("sandbox-syscalls")).__name__ == "SandboxSyscalls"
    assert type(app.get("sandbox-quarantine")).__name__ == "SandboxQuarantine"
    assert type(app.get("sandbox-payload")).__name__ == "SandboxPayload"
    _assert_is_the_network_law(app.get("sandbox-network"))
    assert "sandbox-network" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one reads no
    # environment at all and compiles no artifact — its whole subject is an
    # attempt and the namespace the box was placed in, both handed in by the
    # caller — so it composes in any process, including a bare test process with
    # no DATABASE_URL and no lake.  The restraint is the feature one level up: a
    # builder that probed the host's interfaces to decide whether the box had
    # any would be this law consulting the *host's* namespace, not the box's.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-network"].__name__ == "build_sandbox_network"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store. Unlike the seats with a
    # committed artifact there is no file whose compilation a non-None value
    # would prove — but there is equally no unconfigured state for a None to
    # describe, because the box's network posture is §5.2's fixed structure, not
    # something a deployment could set.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-network") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish.  Asserting on the first application would pass either way
    # — the second is the test.
    #
    # This is the hazard the member's notes call out for a *submodule*'s
    # decorator, and it applies with extra force here: ``sandbox.network``
    # exists as a module a caller imports directly, which is exactly the shape
    # that invites moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_network_law(second.get("sandbox-network"))
    assert "sandbox-network" in second


def test_the_composed_law_refuses_an_attempt_in_a_placed_box() -> None:
    # Feature 158 through the composed application: the path an assembled system
    # actually takes.  A composition that carried a component whose ``require``
    # admitted an attempt would pass every wiring assertion above and fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-network")
    decision = law.check(_attempt(), _placed())

    assert decision.admitted is False
    # By value, not identity: the reason the loader's copy publishes is its own
    # enum member, which ``is`` cannot match across the seam.
    assert decision.reason == "at-namespace"
    assert decision.at_namespace is True

    with pytest.raises(Exception) as raised:
        law.require(_attempt(), _placed())
    assert type(raised.value).__name__ == "EgressRejected"
    assert str(raised.value).startswith(EGRESS_REJECTED_CODE)


def test_the_composed_law_reads_the_posture_the_box_was_placed_with() -> None:
    # The read side through the composed path: *what network posture is this box
    # in?* — the question a deployment audits its runtime configuration with,
    # answered without running a candidate to find out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-network")

    assert law.isolated(_placed()) is True
    assert law.interfaces(_placed()) == ()
    holding = law.namespace("signal-runner", ("lo", "eth0"))
    assert law.isolated(holding) is False
    assert law.interfaces(holding) == ("eth0",)


def test_the_composed_law_is_the_runtimes_specification_for_a_placed_box() -> None:
    # The mechanism half through the composed path: the description a launcher
    # hands its runtime, and the refusal for a placement that cannot be
    # described — the two outcomes of §5.2's row as a value.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-network")

    assert law.namespace("signal-runner", ("lo",)).specification() == {
        "NetworkMode": "none"
    }
    with pytest.raises(Exception) as raised:
        law.namespace("signal-runner", ("eth0",)).specification()
    assert type(raised.value).__name__ == "NamespacePlacementError"


class TestTheSeat:
    """src/app/modules/sandbox — the member's twelfth seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            NETWORK_COMPONENT_NAME,
            sandbox_network_component,
        )

        assert NETWORK_COMPONENT_NAME == "sandbox-network"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_network_law(sandbox_network_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other eleven
        # seats'.
        from app.modules.sandbox import sandbox_network_component

        assert sandbox_network_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_network_component

        application = Application(
            components={"sandbox-network": "sentinel"}, order=("sandbox-network",)
        )
        assert sandbox_network_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not re-export
        # the law's types.  A caller who has the component calls its verbs; a
        # second spelling of the network decision, the namespace or the reason
        # codes here would be a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxNetwork",
            "NetworkDecision",
            "NetworkReason",
            "NetworkNamespace",
            "EgressPath",
            "reject_egress",
            "egress_rejected",
            "isolated_namespace",
            "sandbox_network",
        ):
            assert not hasattr(seat, leaked), leaked
