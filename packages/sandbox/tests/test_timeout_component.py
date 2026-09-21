"""Feature 163's plugin seam: the sixth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-timeout`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the sixth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports``, ``sandbox-transfer``,
``sandbox-seed`` or ``sandbox-threads`` would silently overwrite feature 157's
isolation law, 167's import allowlist, 166's payload channel, 165's node seed or
164's thread-pinning law — composition would look perfect and a category root
would be gone.  The tests below pin that the member now carries exactly seven
components, each under its own feature's name, and that the six earlier laws
are still beside the sixth after it registered — feature 168's fail-class law is
the seventh and last, and it took its own seat rather than widening this one.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

**This seat is the fourth with a committed artifact behind it**, which is worth
one assertion the two artifact-less seats could not make: a non-``None``
component here proves a file on disk compiled, so the composed-path test asks
the law a question whose answer the artifact decides.

**And this seat's ``require`` has three outcomes rather than the other five
laws' two.**  Features 157, 164, 165 and 167 refuse a run *before* it executes,
so a refusal is an exception; a timeout is an outcome the pipeline records
(§5.2's "Timeout | Hard kill, recorded as ``fail_class=timeout``").  The
composed-path tests below therefore assert both halves: a kill comes *back*, and
only an unreadable run raises.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import (
    OVERRUN_S,
    SEED_NODE_ID,
    TEXT_DURATION,
    WALL_S,
    WITHIN_S,
    node_fail_class_record,
    timeout_run,
)

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


def _assert_is_the_timeout_law(component: object) -> None:
    assert type(component).__name__ == "SandboxTimeout"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate, the one boolean, the launcher verb that returns the kill, the write
    # half of the feature's sentence, and the two read-side questions a
    # deployment audits with.
    for operation in (
        "check",
        "killed",
        "require",
        "record",
        "exceeds",
        "wall_s",
        "policy",
    ):
        assert hasattr(component, operation), operation


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and
    # anything asking the composed application for the law.
    assert sandbox.TIMEOUT_COMPONENT_NAME == "sandbox-timeout"


def test_scanning_the_member_registers_the_nine_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's
    # cgroup-limits law, the import law, the payload channel, the node seed,
    # the thread-pinning law and the wall-clock law, no more and no less.  A
    # ninth component arriving unnoticed fails here — and a builder that had
    # taken any earlier feature's name would fail here too, which is the
    # registry-replacement hazard this file exists for.
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


def test_the_timeout_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all six builders have fired, the
    # composed application still carries features 157's, 167's, 166's, 165's and
    # 164's laws under their own names — a sixth registration of any of those
    # names would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    assert type(app.get("sandbox-threads")).__name__ == "SandboxThreads"
    _assert_is_the_timeout_law(app.get("sandbox-timeout"))
    assert "sandbox-timeout" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder.  And this one reads no
    # ambient environment *and no clock* — its whole subject is a duration
    # handed to it — so it composes in any process, including a bare test
    # process with no DATABASE_URL and no lake, and its answer cannot depend on
    # how fast the machine that started pytest is.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-timeout"].__name__ == "build_sandbox_timeout"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store — and here the stronger
    # of the two readings the seat's docstring distinguishes: the component is
    # backed by the committed budget artifact, so a non-None value proves a file
    # compiled rather than merely that the law is loaded.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-timeout") is not None


def test_the_component_survives_a_second_composition() -> None:
    # The registration must live in the package ``__init__``, not a submodule:
    # the loader re-executes ``__init__`` on every composition but not an
    # already-cached submodule, so a builder that drifted into one would fire
    # once and vanish.  Asserting on the first application would pass either
    # way — the second is the test.
    #
    # The hazard applies with extra force here: ``sandbox.timeout`` exists as a
    # module a caller imports directly, which is exactly the shape that invites
    # moving the registration into it.
    create_app()
    second = create_app()
    _assert_is_the_timeout_law(second.get("sandbox-timeout"))
    assert "sandbox-timeout" in second


def test_the_composed_law_records_a_kill_as_a_value() -> None:
    # Feature 163 through the composed application: the path an assembled system
    # actually takes, and the feature's own headline.  A composition that carried
    # a component whose ``require`` raised on a kill would pass every wiring
    # assertion above and fail here.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-timeout")
    kill = law.require(timeout_run(elapsed_s=OVERRUN_S, node_id=SEED_NODE_ID))
    assert kill is not None
    assert kill.fail_class == "timeout"
    assert kill.node_id == SEED_NODE_ID
    # The kill reaches the store in §9.1's own shape, through the composed path
    # rather than through the module the test imported.
    assert kill.row()["fail_class"] == "timeout"


def test_the_composed_law_returns_nothing_for_a_run_inside_its_budget() -> None:
    # The commonest answer through the composed path, and the second of the
    # three outcomes: §6.1 step 2 dispatches thousands of these for every one
    # that hangs, and ``None`` is how the law says "nothing to persist".
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-timeout")
    assert law.require(timeout_run(elapsed_s=WITHIN_S)) is None
    assert law.killed(timeout_run(elapsed_s=WITHIN_S)) is False


def test_the_composed_law_refuses_an_unreadable_run() -> None:
    # The refusal, through the composed path rather than a hand-built law — and
    # the *only* input that raises here, which is the third outcome.  Pinned by
    # class *name* rather than by ``pytest.raises(SandboxTimeoutError)`` because
    # the composed component comes from the loader's synthetic module copy: the
    # exception it raises is structurally — but not identically — the
    # canonically-imported one, and ``isinstance`` cannot hold across that seam.
    # The same wrinkle the sibling suites document, answered the same way; the
    # name still fails the test if the wrong error comes out.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-timeout")
    with pytest.raises(Exception) as raised:
        law.require(timeout_run(elapsed_s=TEXT_DURATION))
    assert type(raised.value).__name__ == "SandboxTimeoutError"
    assert str(raised.value).startswith(sandbox.TIMEOUT_FAIL_CLASS)


def test_the_composed_law_writes_the_class_the_feature_names() -> None:
    # The second half of the feature's sentence through the composed path: the
    # run outruns, the kill comes back, and the class lands on §9.1's row.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-timeout")
    record = node_fail_class_record()
    law.record(record, node_id=SEED_NODE_ID)
    assert record["fail_class"] == sandbox.TIMEOUT_FAIL_CLASS == "timeout"


def test_the_composed_law_reads_the_committed_artifact() -> None:
    # The composer-artifact half of this seat's contract: the composed law's
    # answer about *what it kills past* is the committed file's, so a builder
    # that composed an empty or hand-built policy would fail here rather than at
    # the first dispatch.  Asserted against the canonically-imported law's own
    # reading, which is the artifact's compiled truth.
    law = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-timeout")
    assert law.wall_s == sandbox.sandbox_timeout().wall_s == WALL_S
    assert law.exceeds(OVERRUN_S) is True
    assert law.exceeds(WITHIN_S) is False


class TestTheSeat:
    """src/app/modules/sandbox — the member's seat in the app namespace."""

    def test_the_seat_exposes_the_composed_component(self) -> None:
        from app.modules.sandbox import (
            TIMEOUT_COMPONENT_NAME,
            sandbox_timeout_component,
        )

        assert TIMEOUT_COMPONENT_NAME == "sandbox-timeout"
        app = create_app(MEMBER_SRC, registry=Registration())
        _assert_is_the_timeout_law(sandbox_timeout_component(app))

    def test_the_seat_returns_none_when_nothing_registered(self) -> None:
        # An application with no component registered is a discoverable state,
        # not an exception — mirroring the factory's stance and the other five
        # seats'.
        from app.modules.sandbox import sandbox_timeout_component

        assert sandbox_timeout_component(Application(components={}, order=())) is None

    def test_the_seat_reads_from_an_application_it_is_handed(self) -> None:
        from app.modules.sandbox import sandbox_timeout_component

        application = Application(
            components={"sandbox-timeout": "sentinel"}, order=("sandbox-timeout",)
        )
        assert sandbox_timeout_component(application) == "sentinel"

    def test_the_seat_is_not_a_second_vocabulary(self) -> None:
        # The seat answers questions — which component? — and does not re-export
        # the law's types.  A caller who has the component calls its verbs; a
        # second spelling of the policy, the decision, the kill or the reason
        # codes here would be a second thing to keep in sync.
        import app.modules.sandbox as seat

        for leaked in (
            "SandboxTimeout",
            "TimeoutDecision",
            "TimeoutKill",
            "TimeoutPolicy",
            "TimeoutReason",
            "TimeoutRecord",
            "TimeoutRun",
            "DEFAULT_WALL_S",
            "TIMEOUT_FAIL_CLASS",
            "NODE_FAIL_CLASSES",
            "classify_duration",
            "kill_timeout",
            "exceeded_budget",
            "timed_out_record",
        ):
            assert not hasattr(seat, leaked), leaked
