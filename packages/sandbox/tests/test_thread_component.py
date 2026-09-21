"""Feature 164's plugin seam: the fifth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-threads`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the fifth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports``, ``sandbox-transfer`` or
``sandbox-seed`` would silently overwrite feature 157's isolation law, 167's
import allowlist, 166's payload channel or 165's node seed — composition would
look perfect and a category root would be gone.  The tests below pin that the
member now carries exactly seven components, each under its own feature's name,
and that the four earlier laws are still beside the fifth after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

**This seat is the third with a committed artifact behind it**, which is worth
one assertion the other two seats' suites could not make: a non-``None``
component here proves a file on disk compiled, so the composed-path test asks
the law a question whose answer the artifact decides.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import MKL, OMP, PIN, thread_pinned_env, unpinned_env

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
)

#: The member's ``src/`` — the package-parent the loader scans.  Derived from
#: the imported package rather than from this file's position, so the suite
#: gives the same answer wherever pytest is invoked from.
MEMBER_SRC = Path(sandbox.__file__).resolve().parent.parent


def _assert_is_the_thread_law(component: object) -> None:
    assert type(component).__name__ == "SandboxThreads"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate, the one boolean, the launcher verb that returns the environment, and
    # the three read-side questions a deployment audits with.
    for operation in ("check", "admits", "require", "required", "pins", "pool_floors"):
        assert callable(getattr(component, operation)), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.THREADS_COMPONENT_NAME == "sandbox-threads"


def test_scanning_the_member_registers_the_nine_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's
    # cgroup-limits law, the import law, the payload channel, the node seed,
    # the thread-pinning law, the wall-clock law and feature 168's fail-class
    # law, no more and no less.  A ninth component arriving unnoticed fails
    # here — and a builder that had taken any earlier feature's name would
    # fail here too, which is the registry-replacement hazard this file
    # exists for.
    components = scan_components(MEMBER_SRC, registry=Registration())
    assert sorted(component.name for component in components) == [
        "sandbox",
        "sandbox-budget",
        "sandbox-failclass",
        "sandbox-imports",
        "sandbox-seed",
        "sandbox-syscalls",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-transfer",
    ]


def test_the_thread_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all five builders have fired, the
    # composed application still carries features 157's, 167's, 166's and 165's
    # laws under their own names — a fifth registration of any of those names
    # would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    _assert_is_the_thread_law(app.get("sandbox-threads"))
    assert "sandbox-threads" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder.  And this one reads no
    # ambient environment — its whole subject is an environment handed *to* it —
    # so it composes in any process, including a bare test process with no
    # DATABASE_URL and no lake.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-threads"].__name__ == "build_sandbox_threads"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store — and here the stronger
    # of the two readings the seat's docstring distinguishes: the component is
    # backed by the committed pinning artifact, so a non-None value proves a
    # file compiled rather than merely that the law is loaded.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-threads") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish.  Asserting on the first application would pass either
    # way — the second is the test.
    #
    # This is the hazard the member's notes call out for a *submodule*'s
    # decorator, and it applies with extra force here: ``sandbox.threads``
    # exists as a module a caller imports directly, which is exactly the shape
    # that invites moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_thread_law(second.get("sandbox-threads"))
    assert "sandbox-threads" in second


def test_the_composed_law_admits_a_pinned_invocation() -> None:
    # Feature 164 through the composed application: the path an assembled system
    # actually takes.  A composition that carried a component whose ``require``
    # returned nothing would pass every wiring assertion above and fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-threads")
    env = law.require(thread_pinned_env())
    assert env[OMP] == PIN
    assert env[MKL] == PIN


def test_the_composed_law_refuses_an_unpinned_invocation() -> None:
    # The refusal, through the composed path rather than a hand-built law.
    # Pinned by class *name* rather than by ``pytest.raises(ThreadPinningRequired)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically — the
    # canonically-imported one, and ``isinstance`` cannot hold across that seam.
    # The same wrinkle the sibling suites document, answered the same way; the
    # name still fails the test if the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-threads")
    with pytest.raises(Exception) as raised:
        law.require(unpinned_env())
    assert type(raised.value).__name__ == "ThreadPinningRequired"
    assert str(raised.value).startswith(sandbox.THREAD_PINNING_CODE)


def test_the_composed_law_reads_the_committed_artifact() -> None:
    # The composer-artifact half of this seat's contract: the composed law's
    # answer about *which* variables it requires is the committed file's, so a
    # builder that composed an empty or hand-built policy would fail here rather
    # than at the first dispatch.  Asserted against the canonically-imported
    # law's own reading, which is the artifact's compiled truth.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-threads")
    assert tuple(sorted(law.required())) == tuple(sorted(sandbox.sandbox_threads().required()))
    assert law.pins() == sandbox.sandbox_threads().pins()


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            THREADS_COMPONENT_NAME,
            sandbox_threads_component,
        )

        assert THREADS_COMPONENT_NAME == "sandbox-threads"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_thread_law(sandbox_threads_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other four
        # seats'.
        from app.modules.sandbox import sandbox_threads_component

        assert sandbox_threads_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_threads_component

        application = Application(
            components={"sandbox-threads": "sentinel"}, order=("sandbox-threads",)
        )
        assert sandbox_threads_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not re-export
        # the law's types.  A caller who has the component calls its verbs; a
        # second spelling of the policy, the decision or the cap here would be a
        # second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxThreads",
            "ThreadDecision",
            "ThreadReason",
            "ThreadPinningPolicy",
            "ThreadCap",
            "REQUIRED_CAPS",
            "SINGLE_THREADED",
            "classify_cap",
            "check_thread_pinning",
            "THREAD_PINNING_CODE",
        ):
            assert not hasattr(seat, leaked), leaked
