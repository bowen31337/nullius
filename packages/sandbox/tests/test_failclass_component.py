"""Feature 168's plugin seam: the seventh component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-failclass`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it true.

The hazard the sibling suites name is the one this file re-checks for the seventh
— and last — seat: the factory's registry *replaces* a name's earlier
registration, so a control registered as ``sandbox``, ``sandbox-imports``,
``sandbox-transfer``, ``sandbox-seed``, ``sandbox-threads`` or
``sandbox-timeout`` would silently overwrite feature 157's isolation law, 167's
import allowlist, 166's payload channel, 165's node seed, 164's thread-pinning law
or 163's wall-clock law — composition would look perfect and a category root would
be gone.  The tests below pin that the member now carries exactly seven
components, each under its own feature's name, and that the six earlier laws are
still beside the seventh after it registered.

Placement and re-execution carry the same loader properties the other suites pin:
the builder lives in the package ``__init__`` (a ``@register`` in a submodule
fires on the first composition of a process and silently drops out of every later
one), and the composed component is pinned by class name and behaviour across the
loader's synthetic module-copy seam, where ``isinstance`` cannot hold.

**This seat has no committed artifact, and the composed-path tests still ask the
law a real question.**  Features 166's and 165's seats state the same missing-file
reading: the subject is a vocabulary and a mapping, neither of which a deployment
could set differently, so a non-``None`` component here proves only that the law
is loaded.  What the composed-path tests below check is the *behaviour* that the
artifact-less seats cannot lean on a file for — that a crash, an ``ok`` and a
feature-163 kill all come back classified through the composed application.

**And this seat's ``require`` returns a value for ``ok``**, the one place the
member's verb shape does that.  The composed-path tests assert it explicitly: a
composition carrying a stub whose ``require`` passed ``None`` through for ``ok``
would pass every wiring assertion above and fail here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import (
    ESCAPE_CLASS,
    RUNNER_CLASSES,
    SEED_NODE_ID,
    UNKNOWN_CLASS,
    node_fail_class_record,
    runner_result,
    timeout_run,
    tripwire_outcome,
)

from app.module_loader import (
    Application,
    Registration,
    create_app,
    scan_components,
)

#: The member's ``src/`` — the package-parent the loader scans.  Derived from the
#: imported package rather than from this file's position, so the suite gives the
#: same answer wherever pytest is invoked from.
MEMBER_SRC = Path(sandbox.__file__).resolve().parent.parent


def _assert_is_the_fail_class_law(component: object) -> None:
    assert type(component).__name__ == "SandboxFailClass"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate, the launcher verb that returns a class for every run, and the two
    # read-side questions a deployment audits with.
    for operation in ("check", "require", "classes", "sources"):
        assert hasattr(component, operation), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and anything
    # asking the composed application for the law.
    assert sandbox.FAIL_CLASS_COMPONENT_NAME == "sandbox-failclass"


def test_scanning_the_member_registers_the_eight_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, the cgroup-limits law, the
    # import law, the payload channel, the node seed, the thread-pinning law, the
    # wall-clock law and the fail-class law, no more and no less.  A ninth
    # component arriving unnoticed fails here — and a builder that had taken any
    # earlier feature's name would fail here too, which is the
    # registry-replacement hazard this file exists for.
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


def test_the_fail_class_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all eight builders have fired, the
    # composed application still carries features 157's, 162's, 167's, 166's,
    # 165's, 164's and 163's laws under their own names — an eighth registration
    # of any of those names would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-budget")).__name__ == "SandboxBudget"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    assert type(app.get("sandbox-threads")).__name__ == "SandboxThreads"
    assert type(app.get("sandbox-timeout")).__name__ == "SandboxTimeout"
    _assert_is_the_fail_class_law(app.get("sandbox-failclass"))
    assert "sandbox-failclass" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder.  And this one reads no
    # ambient environment *and no clock* — its whole subject is a run's reported
    # outcome — so it composes in any process, including a bare test process with
    # no DATABASE_URL and no lake, and its answer cannot depend on the shell that
    # started pytest.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-failclass"].__name__ == "build_sandbox_fail_class"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store.  Unlike the four
    # artifact-backed seats, a non-None value here proves only that the law is
    # loaded — there is no file to compile — which is the reading features 165's
    # and 166's seats established.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-failclass") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire once
    # and vanish.  Asserting on the first application would pass either way — the
    # second is the test.
    #
    # The hazard applies with extra force here: ``sandbox.failclass`` exists as a
    # module a caller imports directly, which is exactly the shape that invites
    # moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_fail_class_law(second.get("sandbox-failclass"))
    assert "sandbox-failclass" in second


def test_the_composed_law_classifies_a_crash_as_an_error() -> None:
    # Feature 168 through the composed application: the path an assembled system
    # actually takes.  A composition that carried a stub answering every subject
    # with a constant would pass every wiring assertion above and fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    decision = law.check(runner_result(fail_class="crash"))
    assert decision.fail_class.fail_class == sandbox.ERROR_FAIL_CLASS == "error"
    assert decision.fail_class.source == "crash"


def test_the_composed_law_returns_a_class_for_ok_too() -> None:
    # The one place this law's verb differs from its six siblings': `ok` is one of
    # the four the feature's sentence names, so `require` returns an object for a
    # scored run rather than passing ``None`` through the way feature 163's does.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    value = law.require(runner_result(fail_class=None))
    assert value.fail_class == sandbox.OK_FAIL_CLASS == "ok"
    assert value.ok is True


def test_the_composed_law_classifies_feature_163s_kill() -> None:
    # The handoff, through the composed path: 163 hands this law a kill carrying
    # `fail_class`, and it comes back as §9.1's own `timeout` with no provenance
    # claimed — nothing was translated.
    app = create_app(MEMBER_SRC, registry=Registration())
    kill = app.get("sandbox-timeout").require(
        timeout_run(elapsed_s=90.0, node_id=SEED_NODE_ID)
    )
    decision = app.get("sandbox-failclass").check(kill)
    assert decision.fail_class.fail_class == "timeout"
    assert decision.fail_class.translated is False


def test_the_composed_law_reads_every_class_the_box_reports() -> None:
    # Totality through the composed path: a composition carrying a table that had
    # lost a row would fail here rather than at the first crashed node.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    for cls in RUNNER_CLASSES + (ESCAPE_CLASS,):
        value = law.require(cls)
        assert value.fail_class in sandbox.NODE_FAIL_CLASSES, cls
    assert law.require(tripwire_outcome(rejected=True)).fail_class == "tripwire_fail"


def test_the_composed_law_refuses_an_unknown_class() -> None:
    # The refusal, through the composed path rather than a hand-built law.  Pinned
    # by class *name* rather than by ``pytest.raises(UnknownFailClassError)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically — the
    # canonically-imported one, and ``isinstance`` cannot hold across that seam.
    # The same wrinkle the sibling suites document, answered the same way; the
    # name still fails the test if the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    with pytest.raises(Exception) as raised:
        law.require(UNKNOWN_CLASS)
    assert type(raised.value).__name__ == "UnknownFailClassError"
    assert str(raised.value).startswith(sandbox.FAIL_CLASS_UNKNOWN_CODE)


def test_the_composed_law_refuses_a_record_that_says_nothing() -> None:
    # The other refusal, told apart by name as well as by class: a §9.1 row with
    # no class is an unevaluated node, not a scored one.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    with pytest.raises(Exception) as raised:
        law.require(node_fail_class_record(fail_class=None))
    assert type(raised.value).__name__ == "UnclassifiedRunError"
    assert str(raised.value).startswith(sandbox.FAIL_CLASS_REQUIRED_CODE)


def test_the_composed_law_reads_the_laws_own_vocabulary() -> None:
    # The read side through the composition: a deployment checking what this law
    # stores and what it accepts gets the member's own answers, not a stub's.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-failclass")
    assert law.classes() == sandbox.NODE_FAIL_CLASSES
    assert law.sources() == sandbox.SOURCE_CLASSES


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            FAIL_CLASS_COMPONENT_NAME,
            sandbox_fail_class_component,
        )

        assert FAIL_CLASS_COMPONENT_NAME == "sandbox-failclass"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_fail_class_law(sandbox_fail_class_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other six
        # seats'.
        from app.modules.sandbox import sandbox_fail_class_component

        assert sandbox_fail_class_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_fail_class_component

        application = Application(
            components={"sandbox-failclass": "sentinel"},
            order=("sandbox-failclass",),
        )
        assert sandbox_fail_class_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not re-export
        # the law's types.  A caller who has the component calls its verbs; a
        # second spelling of the table, the value or the reason codes here would
        # be a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxFailClass",
            "FailClass",
            "FailClassDecision",
            "FailClassReason",
            "FAIL_CLASS_TABLE",
            "SOURCE_CLASSES",
            "SANDBOX_RUNNER_CLASSES",
            "SANDBOX_ESCAPE_CLASS",
            "OK_FAIL_CLASS",
            "ERROR_FAIL_CLASS",
            "TRIPWIRE_FAIL_CLASS",
            "classify_fail_class",
            "classify_run",
        ):
            assert not hasattr(seat, leaked), leaked
