"""The plugin seam: composition via the module loader.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox`` component.  No registry, router or
factory was edited to make that true; this test exists to keep it true.

Placement is the risky part of a plugin-shaped feature, and it is *especially*
risky for this one: every sibling feature in the category (158 through 168)
declares ``depends_on="157"``, so a member that never composed would leave the
whole "Untrusted Code Sandbox" category sitting on a component the factory
does not carry.  The assertions below deliberately go through the factory's
public discovery functions rather than importing the package directly, because
importing it would bypass the very mechanism under test.

Two properties of the loader shape these tests:

* It imports each member under a synthetic module name
  (``_nullius_scanned_sandbox``), so a package this suite also imported
  canonically as ``sandbox`` exists in the process twice, with two distinct
  class objects.  ``isinstance`` across the copies cannot hold, so the composed
  component is pinned by class name and by behaviour.
* It re-executes a package's ``__init__`` on **every** ``create_app()`` but does
  not re-execute an already-cached submodule.  So a ``@register`` that lived in
  a submodule would fire on the first composition of a process and silently
  drop out of every later one —
  :func:`test_the_component_survives_a_second_composition` is what catches
  that, and it must assert on the *second* application or it passes vacuously.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
    workspace_members,
    workspace_scan_roots,
)

#: The member's ``src/`` — the package-parent the loader scans. Derived from
#: the imported package rather than from this file's position, so the suite
#: gives the same answer wherever pytest is invoked from.
MEMBER_SRC = Path(sandbox.__file__).resolve().parent.parent


def _assert_is_the_isolation_law(component: object) -> None:
    assert type(component).__name__ == "SandboxIsolation"
    # The law's verbs, duck-checked across the loader's module copy seam:
    # ``admits`` returns the gate's decision, ``require`` turns a refusal into
    # the exception a launcher calls, and ``isolation_of``/``is_gvisor`` are
    # the read side a deployment audits with.
    for operation in ("admits", "require", "isolation_of", "is_gvisor", "components"):
        assert callable(getattr(component, operation)), operation
    # It carries a compiled policy, so a non-None component is proof the
    # committed artifact loaded.
    assert component.policy.kind == "sandbox-isolation"


def test_the_member_is_declared_in_the_scanned_workspace() -> None:
    # The registration chain starts here: the member's own pyproject.toml is
    # what makes it a workspace member and therefore scannable.
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()
    assert "sandbox" in {member.name for member in workspace_members()}
    # ...and the package the loader will look for actually exists.
    assert (MEMBER_SRC / "sandbox" / "__init__.py").is_file()


def test_the_member_owns_the_plugin_name_the_spec_gives_it() -> None:
    # app_spec.xml's category is ``plugin="sandbox"``; the component name is
    # that word, so the spec's plugin name and the composed component are one
    # spelling rather than two that happen to agree today.
    assert sandbox.COMPONENT_NAME == "sandbox"


def test_scanning_the_member_registers_exactly_the_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called
    # a bare ``create_app()`` has already imported every workspace member into
    # the current registry, so reading it back here would assert accumulated
    # process state, not this package's contribution.
    #
    # The list is pinned exactly rather than by membership, so a *ninth*
    # component arriving unnoticed fails here — which is the property this
    # test is for. Feature 157 contributed the first: the isolation law.
    # Feature 167 added the second: the import allowlist, under its own name
    # because the registry replaces a name's earlier registration. Feature
    # 166 added the third, the payload channel, on the same terms, feature
    # 165 the fourth, the node seed, feature 164 the fifth, the
    # thread-pinning law, feature 163 the sixth, the wall-clock law, and
    # feature 168 the seventh, the fail-class vocabulary — the category is
    # closed, so that was the whole of it until feature 162's cgroup-limits
    # law, the eighth, arrived: the one control whose subject is what a run
    # *consumed* — a quantity §5.2's call site states in the same ``Limits(…)``
    # clause feature 163 reads its wall clock from, and which neither the
    # isolation law nor the wall-clock law has a claim about.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-budget",
        "sandbox-failclass",
        "sandbox-imports",
        "sandbox-payload",
        "sandbox-quarantine",
        "sandbox-seed",
        "sandbox-syscalls",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-transfer",
    ]


def test_the_composed_application_carries_the_isolation_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    _assert_is_the_isolation_law(app.get("sandbox"))
    assert "sandbox" in app
    assert "sandbox" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder. And this one resolves
    # no environment at all — its only input beyond the run is the committed
    # artifact shipped inside the package — so it composes in any process,
    # including a bare test process with no DATABASE_URL and no lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox"].__name__ == "build_sandbox_isolation"


def test_an_unconfigured_environment_still_composes() -> None:
    # The load-bearing property for a component that must never take
    # composition down: the factory builds every registered component on
    # every create_app(), so the builder must not require an environment.
    # This one reads none, so a bare process composes it — and the other
    # members are still composed alongside it.
    app = create_app()
    _assert_is_the_isolation_law(app.get("sandbox"))
    for component in ("contract", "snapshot", "ingest"):
        assert component in app, component


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store: the committed artifact
    # ships inside the package, so there is no unconfigured state for a None
    # to describe. A caller reading a non-None component here is entitled to
    # the stronger conclusion that the deployment's isolation policy compiled.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish. Asserting on the first application would pass either
    # way — the second is the test.
    create_app()
    second = create_app()
    _assert_is_the_isolation_law(second.get("sandbox"))
    assert "sandbox" in second


def test_the_composed_law_refuses_a_run_without_gvisor() -> None:
    # Feature 157 through the composed application: the path an assembled
    # system actually takes. A composition that carried a component whose
    # `require` did nothing would pass every wiring assertion above and fail
    # here.
    #
    # The refusal is pinned by class *name* rather than by `pytest.raises`,
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically —
    # the canonically-imported one, and `isinstance` cannot hold across that
    # seam. That is the same wrinkle `tests/nulloracle/conftest.py` documents
    # and answers the same way; the name still fails the test if the wrong
    # error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox")
    assert law.admits("signal-sandbox").admitted is True
    with pytest.raises(Exception) as raised:
        law.require("not-a-box")
    assert type(raised.value).__name__ == "GVisorIsolationRequired"
    assert str(raised.value).startswith("gvisor_isolation_required")


def test_the_seat_exposes_the_composed_component() -> None:
    # src/app/modules/sandbox is the member's seat in the app namespace: it
    # names the component and asks the factory for it without the app package
    # depending on any member at import time.
    from app.modules.sandbox import (
        COMPONENT_NAME,
        sandbox_isolation_component,
    )

    assert COMPONENT_NAME == "sandbox"
    app = create_app(MEMBER_SRC, registry=Registration())
    _assert_is_the_isolation_law(sandbox_isolation_component(app))


def test_the_seat_returns_none_when_nothing_registered() -> None:
    # An application with no component registered is a discoverable state, not
    # an exception — mirroring the factory's stance.
    from app.modules.sandbox import sandbox_isolation_component

    assert sandbox_isolation_component(Application(components={}, order=())) is None


def test_the_seat_reads_from_an_application_it_is_handed() -> None:
    from app.modules.sandbox import sandbox_isolation_component

    application = Application(components={"sandbox": "sentinel"}, order=("sandbox",))
    assert sandbox_isolation_component(application) == "sentinel"


def test_the_app_seat_is_not_a_second_vocabulary() -> None:
    # The seat answers questions — which component? — and does not re-export
    # the member's types. A caller who has the component calls its verbs; a
    # second spelling of the run decision or the reason codes here would be a
    # second thing to keep in sync. Feature 167 added its own name and
    # accessor beside feature 157's, feature 166 a third, feature 165 a
    # fourth, feature 164 a fifth, feature 163 a sixth, feature 168 the
    # seventh, feature 162 the eighth and feature 160 the ninth, and nothing
    # else.
    import app.modules.sandbox as seat

    assert set(seat.__all__) == {
        "BUDGET_COMPONENT_NAME",
        "COMPONENT_NAME",
        "FAIL_CLASS_COMPONENT_NAME",
        "IMPORTS_COMPONENT_NAME",
        "PAYLOAD_COMPONENT_NAME",
        "QUARANTINE_COMPONENT_NAME",
        "SEED_COMPONENT_NAME",
        "SYSCALLS_COMPONENT_NAME",
        "THREADS_COMPONENT_NAME",
        "TIMEOUT_COMPONENT_NAME",
        "TRANSFER_COMPONENT_NAME",
        "sandbox_budget_component",
        "sandbox_fail_class_component",
        "sandbox_imports_component",
        "sandbox_isolation_component",
        "sandbox_payload_component",
        "sandbox_quarantine_component",
        "sandbox_seed_component",
        "sandbox_syscalls_component",
        "sandbox_threads_component",
        "sandbox_timeout_component",
        "sandbox_transfer_component",
    }
    for leaked in (
        "RunDecision",
        "RunReason",
        "SandboxRun",
        "IsolationPolicy",
        "ModuleDecision",
        "ModuleReason",
        "ImportsAllowlist",
        "ScoreVector",
        "TransferChannel",
        "WindowFacts",
        "SeedDecision",
        "SeedReason",
        "SandboxInvocation",
        "SeedRecord",
        "ThreadDecision",
        "ThreadReason",
        "ThreadPinningPolicy",
        "SandboxThreads",
        "SyscallDecision",
        "SyscallReason",
        "SyscallPolicy",
        "SyscallAttempt",
        "SyscallFilter",
        "Commitment",
        "SandboxSyscalls",
    ):
        assert not hasattr(seat, leaked), leaked
