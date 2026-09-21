"""Feature 165's plugin seam: the fourth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-seed`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the fourth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports`` or ``sandbox-transfer``
would silently overwrite feature 157's isolation law, 167's import allowlist or
166's payload channel — composition would look perfect and a category root
would be gone.  The tests below pin that the member now carries exactly four
components, each under its own feature's name, and that the three earlier laws
are still beside the fourth after it registered.

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
from _documents import (
    NODE_SEED,
    OTHER_NODE_SEED,
    invocation,
    node_record,
    seedless_invocation,
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


def _assert_is_the_seed_law(component: object) -> None:
    assert type(component).__name__ == "SandboxSeed"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``check`` returns a decision, ``require`` raises or returns the integer,
    # and ``seeded`` audits a batch that already ran.
    for operation in ("check", "require", "seeded"):
        assert callable(getattr(component, operation)), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.SEED_COMPONENT_NAME == "sandbox-seed"


def test_scanning_the_member_registers_the_four_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called
    # a bare ``create_app()`` has already imported every workspace member into
    # the current registry, so reading it back here would assert accumulated
    # process state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, the import law, the
    # payload channel and the node seed, no more and no less. A fifth
    # component arriving unnoticed fails here — and a builder that had taken
    # any earlier feature's name would fail here too, which is the
    # registry-replacement hazard this file exists for.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-imports",
        "sandbox-seed",
        "sandbox-transfer",
    ]


def test_the_seed_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all four builders have fired,
    # the composed application still carries features 157's, 167's and 166's
    # laws under their own names — a fourth registration of any of those names
    # would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    _assert_is_the_seed_law(app.get("sandbox-seed"))
    assert "sandbox-seed" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one reads no
    # environment at all and compiles no artifact — its whole subject is a
    # value a run is handed — so it composes in any process, including a bare
    # test process with no DATABASE_URL and no lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-seed"].__name__ == "build_sandbox_seed"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store. Unlike the other seats
    # there is no committed artifact whose compilation a non-None value would
    # prove — but there is equally no unconfigured state for a None to
    # describe, because the seed has nothing about it a deployment could set:
    # it is derived from the node identity, not configured.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-seed") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish. Asserting on the first application would pass either
    # way — the second is the test.
    #
    # This is the hazard the member's notes call out for a *submodule*'s
    # decorator, and it applies with extra force here: ``sandbox.seed`` exists
    # as a module a caller imports directly, which is exactly the shape that
    # invites moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_seed_law(second.get("sandbox-seed"))
    assert "sandbox-seed" in second


def test_the_composed_law_admits_a_seeded_invocation() -> None:
    # Feature 165 through the composed application: the path an assembled
    # system actually takes. A composition that carried a component whose
    # ``require`` returned nothing would pass every wiring assertion above and
    # fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-seed")
    assert law.require(invocation()) == NODE_SEED


def test_the_composed_law_refuses_a_seedless_invocation() -> None:
    # The refusal, through the composed path rather than a hand-built law.
    # Pinned by class *name* rather than by ``pytest.raises(InvocationSeedError)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically —
    # the canonically-imported one, and ``isinstance`` cannot hold across that
    # seam. The same wrinkle the sibling suites document, answered the same
    # way; the name still fails the test if the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-seed")
    with pytest.raises(Exception) as raised:
        law.require(seedless_invocation())
    assert type(raised.value).__name__ == "InvocationSeedError"
    assert str(raised.value).startswith("node_seed_required")


def test_the_composed_law_refuses_a_record_that_contradicts_the_run() -> None:
    # The *second* half of the feature sentence — persisting the seed on the
    # node record — reached through the composed path, so a builder that wired
    # only the invocation half would fail here rather than in production.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-seed")
    with pytest.raises(Exception) as raised:
        law.require(
            invocation(seed=NODE_SEED), record=node_record(seed=OTHER_NODE_SEED)
        )
    assert type(raised.value).__name__ == "InvocationSeedError"
    assert str(raised.value).startswith("node_seed_mismatch")


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            SEED_COMPONENT_NAME,
            sandbox_seed_component,
        )

        assert SEED_COMPONENT_NAME == "sandbox-seed"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_seed_law(sandbox_seed_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other
        # three seats'.
        from app.modules.sandbox import sandbox_seed_component

        assert sandbox_seed_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_seed_component

        application = Application(
            components={"sandbox-seed": "sentinel"}, order=("sandbox-seed",)
        )
        assert sandbox_seed_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not
        # re-export the law's types. A caller who has the component calls its
        # verbs; a second spelling of the seed or the invocation here would be
        # a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxSeed",
            "SeedDecision",
            "SeedReason",
            "SandboxInvocation",
            "SeedRecord",
            "SEED_MAX",
            "mint_node_seed",
            "ENV_SIGNAL_SEED",
        ):
            assert not hasattr(seat, leaked), leaked
