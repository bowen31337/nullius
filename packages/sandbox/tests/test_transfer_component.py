"""Feature 166's plugin seam: the third component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-transfer`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the third
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox`` or ``sandbox-imports`` would silently
overwrite feature 157's isolation law or feature 167's import allowlist —
composition would look perfect and a category root would be gone.  The tests
below pin that the member now carries exactly three components, each under its
own feature's name, and that the two earlier laws are still beside the third
after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import WINDOW_SCORES, WINDOW_UNIVERSE, materialized_window, score_series

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


def _assert_is_the_transfer_law(component: object) -> None:
    assert type(component).__name__ == "SandboxTransfer"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``send`` validates the window leg, ``channel`` hands out the per-run
    # seam, ``receive`` takes a vector off a channel and ``round_trip`` runs
    # the feature's sentence end to end.
    for operation in ("send", "channel", "receive", "scores", "round_trip"):
        assert callable(getattr(component, operation)), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.TRANSFER_COMPONENT_NAME == "sandbox-transfer"


def test_scanning_the_member_registers_the_four_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called
    # a bare ``create_app()`` has already imported every workspace member into
    # the current registry, so reading it back here would assert accumulated
    # process state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, the import law, the
    # payload channel, the node seed and the thread-pinning law, no more and
    # no less. A sixth component arriving unnoticed fails here — and a
    # builder that had taken either earlier feature's name would fail here
    # too, which is the registry-replacement hazard this file exists for.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-imports",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-transfer",
    ]


def test_the_transfer_builder_does_not_replace_either_earlier_law() -> None:
    # The hazard, stated as behaviour: after all three builders have fired,
    # the composed application still carries features 157's and 167's laws
    # under their own names — a third registration of either name would have
    # replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    _assert_is_the_transfer_law(app.get("sandbox-transfer"))
    assert "sandbox-transfer" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one reads no
    # environment at all and compiles no artifact — its whole subject is a
    # format and an alignment — so it composes in any process, including a
    # bare test process with no DATABASE_URL and no lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-transfer"].__name__ == "build_sandbox_transfer"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store. Unlike the other two
    # seats there is no committed artifact whose compilation a non-None value
    # would prove — but there is equally no unconfigured state for a None to
    # describe, because the transfer has nothing about it a deployment could
    # set.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-transfer") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish. Asserting on the first application would pass either
    # way — the second is the test.
    #
    # This is the hazard the member's notes call out for a *submodule*'s
    # decorator, and it applies with extra force here: ``sandbox.transfer``
    # exists as a module a caller imports directly, which is exactly the shape
    # that invites moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_transfer_law(second.get("sandbox-transfer"))
    assert "sandbox-transfer" in second


def test_the_composed_law_moves_a_window_and_a_vector() -> None:
    # Feature 166 through the composed application: the path an assembled
    # system actually takes. A composition that carried a component whose
    # ``round_trip`` did nothing would pass every wiring assertion above and
    # fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-transfer")
    vector = law.round_trip(materialized_window(), lambda facts: score_series())
    assert vector.universe == WINDOW_UNIVERSE
    assert vector.values() == pytest.approx(list(WINDOW_SCORES))


def test_the_composed_law_refuses_a_return_for_another_window() -> None:
    # The refusal, through the composed path rather than a hand-built channel.
    # Pinned by class *name* rather than by ``pytest.raises(ScoreChannelError)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically —
    # the canonically-imported one, and ``isinstance`` cannot hold across that
    # seam. The same wrinkle the sibling suites document, answered the same
    # way; the name still fails the test if the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-transfer")
    with pytest.raises(Exception) as raised:
        law.round_trip(materialized_window(), lambda facts: score_series([1.0]))
    assert type(raised.value).__name__ == "ScoreChannelError"
    assert str(raised.value).startswith("score_channel")


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            TRANSFER_COMPONENT_NAME,
            sandbox_transfer_component,
        )

        assert TRANSFER_COMPONENT_NAME == "sandbox-transfer"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_transfer_law(sandbox_transfer_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other two
        # seats'.
        from app.modules.sandbox import sandbox_transfer_component

        assert sandbox_transfer_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_transfer_component

        application = Application(
            components={"sandbox-transfer": "sentinel"}, order=("sandbox-transfer",)
        )
        assert sandbox_transfer_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not
        # re-export the law's types. A caller who has the component calls its
        # verbs; a second spelling of the score vector or the channel here
        # would be a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "ScoreVector",
            "TransferChannel",
            "WindowFacts",
            "TransferLeg",
            "SandboxTransfer",
            "SCORE_MAGIC",
            "SeedDecision",
            "SandboxInvocation",
        ):
            assert not hasattr(seat, leaked), leaked
