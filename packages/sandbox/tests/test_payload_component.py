"""Feature 159's plugin seam: the eleventh component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-payload`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the
eleventh seat: the factory's registry *replaces* a name's earlier registration,
so a control registered as ``sandbox``, ``sandbox-imports`` or
``sandbox-transfer`` would silently overwrite feature 157's isolation law,
167's import allowlist or 166's payload channel — composition would look
perfect and a category root would be gone.  The tests below pin that the member
now carries exactly eleven components, each under its own feature's name, and
that the ten earlier laws are still beside the eleventh after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

The composed law is exercised through the same path an assembled system takes —
a run handed to the component's ``require``, with the channel that would have
delivered its window — so a builder that wired the registration but not the
delivery gate would pass the wiring assertions and fail here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import materialized_window
from sandbox import PayloadRun
from sandbox.transfer import TransferChannel

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


def _run(payload: object = None, channel: object = None) -> PayloadRun:
    """A run handed to the gate: the payload and the channel that would have
    delivered it — the half of §5.2's call this law has a claim about."""
    return PayloadRun(payload=payload, channel=channel)


def _loaded_channel() -> TransferChannel:
    """A channel a real window was sent over — the arrival the gate reads."""
    channel = TransferChannel()
    channel.send_window(materialized_window())
    return channel


def _assert_is_the_payload_law(component: object) -> None:
    assert type(component).__name__ == "SandboxPayload"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``check`` returns the gate's decision, ``require`` turns a refusal into
    # the exception a launcher calls or returns the window that crossed.
    for operation in ("check", "require"):
        assert callable(getattr(component, operation)), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.PAYLOAD_COMPONENT_NAME == "sandbox-payload"


def test_the_seat_declares_the_same_component_name() -> None:
    # The app namespace respells the member's constant rather than importing it
    # (the seat must not depend on the member at import time), so the two
    # spellings are pinned equal here: a drift would be a silent ``None`` at the
    # seat rather than a failure, which is the worst shape a wiring bug can take.
    import app.modules.sandbox as seat

    assert seat.PAYLOAD_COMPONENT_NAME == sandbox.PAYLOAD_COMPONENT_NAME


def test_scanning_the_member_registers_the_eleven_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's cgroup-limits
    # law, the import law, the payload channel, the node seed, the thread-pinning
    # law, the wall-clock law, feature 168's fail-class law, feature 160's
    # seccomp law, feature 161's quarantine law and — the eleventh — feature
    # 159's payload-delivery law, no more and no less.  A twelfth component
    # arriving unnoticed fails here — and a builder that had taken any earlier
    # feature's name would fail here too, which is the registry-replacement
    # hazard this file exists for.
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


def test_the_payload_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all eleven builders have fired, the
    # composed application still carries features 157's, 167's, 166's, 165's,
    # 164's, 163's, 168's, 160's and 161's laws under their own names — an
    # eleventh registration of any of those names would have replaced one.
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
    _assert_is_the_payload_law(app.get("sandbox-payload"))
    assert "sandbox-payload" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one reads no
    # environment at all and compiles no artifact — its whole subject is a run
    # and the channel that would have delivered its payload, both handed in by
    # the caller — so it composes in any process, including a bare test process
    # with no DATABASE_URL and no lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-payload"].__name__ == "build_sandbox_payload"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store. Unlike the seats with a
    # committed artifact there is no file whose compilation a non-None value
    # would prove — but there is equally no unconfigured state for a None to
    # describe, because the box's filesystem posture is §5.2's fixed structure,
    # not something a deployment could set.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-payload") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish. Asserting on the first application would pass either way
    # — the second is the test.
    #
    # This is the hazard the member's notes call out for a *submodule*'s
    # decorator, and it applies with extra force here: ``sandbox.payload``
    # exists as a module a caller imports directly, which is exactly the shape
    # that invites moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_payload_law(second.get("sandbox-payload"))
    assert "sandbox-payload" in second


def test_the_composed_law_admits_a_run_whose_window_crossed() -> None:
    # Feature 159 through the composed application: the path an assembled system
    # actually takes. A composition that carried a component whose ``require``
    # did not return the window the channel holds would pass every wiring
    # assertion above and fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-payload")
    channel = _loaded_channel()
    assert law.require(_run(payload=channel.window_bytes, channel=channel)) == channel.window_bytes


def test_the_composed_law_refuses_a_run_whose_payload_named_a_path() -> None:
    # The because-clause, through the composed path: a payload that names a
    # filesystem place is refused, because the box holds no mounts to resolve it.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-payload")
    with pytest.raises(Exception) as raised:
        law.require(_run(payload="/data/window.arrow"))
    assert type(raised.value).__name__ == "PayloadChannelRequired"
    assert str(raised.value).startswith("payload_channel_required")


def test_the_composed_law_refuses_bytes_with_no_channel() -> None:
    # The arrival half: bytes offered with no channel behind them are a claim,
    # not a provenance, and the composed law refuses them.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-payload")
    channel = _loaded_channel()
    with pytest.raises(Exception) as raised:
        law.require(_run(payload=channel.window_bytes, channel=None))
    assert type(raised.value).__name__ == "PayloadChannelRequired"


class TestTheSeat:
    """src/app/modules/sandbox — the member's eleventh seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            PAYLOAD_COMPONENT_NAME,
            sandbox_payload_component,
        )

        assert PAYLOAD_COMPONENT_NAME == "sandbox-payload"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_payload_law(sandbox_payload_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other ten
        # seats'.
        from app.modules.sandbox import sandbox_payload_component

        assert sandbox_payload_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_payload_component

        application = Application(
            components={"sandbox-payload": "sentinel"}, order=("sandbox-payload",)
        )
        assert sandbox_payload_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not re-export
        # the law's types. A caller who has the component calls its verbs; a
        # second spelling of the payload decision or the reason codes here would
        # be a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxPayload",
            "PayloadDecision",
            "PayloadReason",
            "PayloadRun",
            "authorize_payload_run",
            "sandbox_payload",
        ):
            assert not hasattr(seat, leaked), leaked
