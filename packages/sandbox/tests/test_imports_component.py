"""Feature 167's plugin seam: the second component on the sandbox member.

This is the registration contract from the other side — the factory scans
the workspace members, imports this package, and the ``@register`` builder
lands in the composed application as the ``sandbox-imports`` component.  No
registry, router or factory was edited to make that true; this test exists
to keep it true.

The risky part for this feature is *which name* the builder takes.  The
factory's registry replaces a name's earlier registration, so a second
control registered as ``sandbox`` would silently overwrite feature 157's
isolation law — composition would look perfect and the category's root
would be gone.  The tests below pin that the member now carries exactly two
components, each under its own feature's name, and that the isolation law
is still beside the import law after the second one registered.

Placement and re-execution carry the same loader properties feature 157's
suite pins: the builder lives in the package ``__init__`` (a ``@register``
in a submodule fires on the first composition of a process and silently
drops out of every later one), and the composed component is pinned by
class name and behaviour across the loader's synthetic module-copy seam,
where ``isinstance`` cannot hold.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import SOURCE_WITH_TIME

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


def _assert_is_the_import_law(component: object) -> None:
    assert type(component).__name__ == "SandboxImports"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``screen`` returns the gate's decision, ``require`` turns a refusal
    # into the exception a launcher calls, and ``covers``/``terms`` are the
    # read side a deployment audits with.
    for operation in ("screen", "require", "covers", "terms"):
        assert callable(getattr(component, operation)), operation
    # It carries a compiled ceiling, so a non-None component is proof the
    # committed allowlist artifact loaded.
    assert component.allowlist.kind == "sandbox-imports"


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.IMPORTS_COMPONENT_NAME == "sandbox-imports"


def test_scanning_the_member_registers_the_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that
    # called a bare ``create_app()`` has already imported every workspace
    # member into the current registry, so reading it back here would
    # assert accumulated process state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's
    # cgroup-limits law, the import law, the payload channel, the node seed,
    # the thread-pinning law, the wall-clock law and feature 168's fail-class
    # law, no more and no less. A ninth component arriving unnoticed fails
    # here — and a builder that had taken feature 157's name would fail here
    # too, which is the registry-replacement hazard this file exists for.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-budget",
        "sandbox-failclass",
        "sandbox-imports",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-transfer",
    ]


def test_the_imports_builder_does_not_replace_the_isolation_law() -> None:
    # The hazard, stated as behaviour: after both builders have fired, the
    # composed application carries feature 157's law under its own name —
    # a second registration of "sandbox" would have replaced it.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    _assert_is_the_import_law(app.get("sandbox-imports"))
    assert "sandbox-imports" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one reads
    # no environment at all — its only input beyond the submission is the
    # committed artifact shipped inside the package — so it composes in any
    # process, including a bare test process with no DATABASE_URL and no
    # lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-imports"].__name__ == "build_sandbox_imports"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store: the committed
    # artifact ships inside the package, so there is no unconfigured state
    # for a None to describe. A caller reading a non-None component here is
    # entitled to the stronger conclusion that the deployment's ceiling
    # compiled.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-imports") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a
    # submodule: the loader re-executes ``__init__`` on every composition
    # but not an already-cached submodule, so a builder that drifted into
    # one would fire once and vanish. Asserting on the first application
    # would pass either way — the second is the test.
    create_app()
    second = create_app()
    _assert_is_the_import_law(second.get("sandbox-imports"))
    assert "sandbox-imports" in second


def test_the_composed_law_refuses_a_module_importing_time() -> None:
    # Feature 167 through the composed application: the path an assembled
    # system actually takes. A composition that carried a component whose
    # ``require`` did nothing would pass every wiring assertion above and
    # fail here.
    #
    # The refusal is pinned by class *name* rather than by `pytest.raises`,
    # because the composed component comes from the loader's synthetic
    # module copy: the exception it raises is structurally — but not
    # identically — the canonically-imported one, and `isinstance` cannot
    # hold across that seam. That is the same wrinkle feature 157's suite
    # documents and answers the same way; the name still fails the test if
    # the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-imports")
    assert law.screen("import math\n").admitted is True
    with pytest.raises(Exception) as raised:
        law.require(SOURCE_WITH_TIME)
    assert type(raised.value).__name__ == "DisallowedImportError"
    assert str(raised.value).startswith("disallowed_import")


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            IMPORTS_COMPONENT_NAME,
            sandbox_imports_component,
        )

        assert IMPORTS_COMPONENT_NAME == "sandbox-imports"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_import_law(sandbox_imports_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable
        # state, not an exception — mirroring the factory's stance and the
        # isolation seat's.
        from app.modules.sandbox import sandbox_imports_component

        assert sandbox_imports_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_imports_component

        application = Application(
            components={"sandbox-imports": "sentinel"}, order=("sandbox-imports",)
        )
        assert sandbox_imports_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not
        # re-export the law's types. A caller who has the component calls
        # its verbs; a second spelling of the module decision or the reason
        # codes here would be a second thing to keep in sync.
        import app.modules.sandbox as seat

        assert set(seat.__all__) == {
            "BUDGET_COMPONENT_NAME",
            "COMPONENT_NAME",
            "FAIL_CLASS_COMPONENT_NAME",
            "IMPORTS_COMPONENT_NAME",
            "SEED_COMPONENT_NAME",
            "THREADS_COMPONENT_NAME",
            "TIMEOUT_COMPONENT_NAME",
            "TRANSFER_COMPONENT_NAME",
            "sandbox_budget_component",
            "sandbox_fail_class_component",
            "sandbox_imports_component",
            "sandbox_isolation_component",
            "sandbox_seed_component",
            "sandbox_threads_component",
            "sandbox_timeout_component",
            "sandbox_transfer_component",
        }
        for leaked in ("ModuleDecision", "ModuleReason", "ImportsAllowlist", "SandboxImports"):
            assert not hasattr(seat, leaked), leaked
