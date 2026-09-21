"""Feature 160's plugin seam: the ninth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-syscalls`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the ninth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports``, ``sandbox-transfer``,
``sandbox-seed``, ``sandbox-threads``, ``sandbox-timeout``, ``sandbox-failclass``
or ``sandbox-budget`` would silently overwrite feature 157's isolation law,
167's import allowlist, 166's payload channel, 165's node seed, 164's
thread-pinning law, 163's wall-clock law, 168's fail-class vocabulary or 162's
cgroup-limits law — composition would look perfect and a category root would be
gone.  The tests below pin that the member now carries exactly nine components,
each under its own feature's name, and that the eight earlier laws are still
beside the ninth after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

**This seat is the sixth with a committed artifact behind it**, which is worth
one assertion the artifact-less seats could not make: a non-``None`` component
here proves a file on disk compiled, so the composed-path test asks the law
questions whose answers the artifact decides.  Note *which* questions: unlike
feature 162's three numbers, §5.2 fixes no syscall names, so the artifact's
*content* is reviewed rather than pinned — what the compiler holds is that the
default action denies, so the composed-path tests read the ceiling rather than
asserting a term list against a spec number.

**And this seat's ``require`` has the configuration laws' two outcomes rather
than feature 163's three.**  A syscall outside the ceiling is §15's sandbox
escape attempt — a violation of the *box* rather than a bad candidate — so
``require`` passes ``None`` through only for an attempt inside the ceiling and
raises for a rejection exactly as it does for an attempt this law cannot read,
while ``check`` still *answers* so the pipeline can record the violation and
hand its node to feature 161.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import (
    ADMITTED_SYSCALL,
    DISALLOWED_SYSCALL,
    ESCAPE_CLASS,
    KILL_ACTION,
    SIGNAL_SANDBOX,
    syscall_attempt,
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


def _assert_is_the_seccomp_law(component: object) -> None:
    assert type(component).__name__ == "SandboxSyscalls"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate, the boolean read side, the launcher verb, the filter a launcher arms,
    # and the two read-side questions a deployment audits with.  ``policy`` and
    # ``default_action`` are properties rather than methods, so they are read
    # rather than called.
    for operation in ("check", "allows", "allowed", "require", "filter"):
        assert hasattr(component, operation), operation
    assert isinstance(component.default_action, str)
    assert hasattr(component.policy, "admits")


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and anything
    # asking the composed application for the law.
    assert sandbox.SYSCALLS_COMPONENT_NAME == "sandbox-syscalls"


def test_the_seat_declares_the_same_component_name() -> None:
    # The app namespace respells the member's constant rather than importing it
    # (the seat must not depend on the member at import time), so the two
    # spellings are pinned equal here: a drift would be a silent ``None`` at the
    # seat rather than a failure, which is the worst shape a wiring bug can take.
    import app.modules.sandbox as seat

    assert seat.SYSCALLS_COMPONENT_NAME == sandbox.SYSCALLS_COMPONENT_NAME


def test_the_component_name_is_not_any_earlier_laws() -> None:
    # The registry-replacement hazard at the constant: none of the eight earlier
    # names, and not the mechanism spelling either.
    assert sandbox.SYSCALLS_COMPONENT_NAME not in {
        "sandbox",
        "sandbox-imports",
        "sandbox-transfer",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-failclass",
        "sandbox-budget",
        "sandbox-seccomp",
    }


def test_scanning_the_member_registers_the_nine_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's cgroup-limits
    # law, the import law, the payload channel, the node seed, the thread-pinning
    # law, the wall-clock law, feature 168's fail-class law and feature 160's
    # seccomp law, no more and no less.  A tenth component arriving unnoticed
    # fails here — and a builder that had taken any earlier feature's name would
    # fail here too, which is the registry-replacement hazard this file exists
    # for.
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


def test_the_syscalls_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all nine builders have fired, the
    # composed application still carries features 157's, 167's, 166's, 165's,
    # 164's, 163's, 168's and 162's laws under their own names — a ninth
    # registration of any of those names would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    assert type(app.get("sandbox-threads")).__name__ == "SandboxThreads"
    assert type(app.get("sandbox-timeout")).__name__ == "SandboxTimeout"
    assert type(app.get("sandbox-failclass")).__name__ == "SandboxFailClass"
    assert type(app.get("sandbox-budget")).__name__ == "SandboxBudget"
    _assert_is_the_seccomp_law(app.get("sandbox-syscalls"))
    assert "sandbox-syscalls" in app.order


def test_the_eight_earlier_laws_still_answer_their_own_questions() -> None:
    # Naming the classes is not quite the same as the laws still *working*: each
    # earlier component is asked one question its own subject answers, so a
    # replacement that happened to reuse a class name would still fail here.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox").is_gvisor(SIGNAL_SANDBOX) is True
    assert app.get("sandbox-imports").covers("math") is True
    assert app.get("sandbox-transfer").round_trip is not None
    assert app.get("sandbox-seed").seeded is not None
    assert app.get("sandbox-threads").pool_floors() is not None
    assert app.get("sandbox-timeout").wall_s > 0
    assert app.get("sandbox-budget").mem_mb == 2048
    assert "ok" in app.get("sandbox-failclass").classes()
    assert app.get("sandbox-syscalls").allows(ADMITTED_SYSCALL) is True


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder.  And this one reads no
    # ambient environment and opens no kernel handle — its whole subject is a
    # syscall *name a runtime reported* — so it composes in any process,
    # including a bare test process with no DATABASE_URL and no lake, and its
    # answer cannot depend on the shell that started pytest or on whether the
    # running kernel was built with seccomp.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-syscalls"].__name__ == "build_sandbox_syscalls"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store.  And like feature 162's
    # seat, a non-None value here proves more than that the law loaded: this
    # builder compiles :data:`sandbox.COMMITTED_SYSCALLS_POLICY` at build time,
    # so the component it hands out is proof the file on disk was read *and* held
    # to a denying default action.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-syscalls") is not None


def test_a_drifted_artifact_does_not_take_composition_down() -> None:
    # The builder's refusal-free path, stated as behaviour: the factory builds
    # every registered component on every ``create_app()`` call, so a builder
    # that raised on a drifted artifact — a widened ``default_action``, say —
    # would take composition down for every unrelated feature in the workspace.
    # The law compiles the committed file here, and it is not drifted; the
    # property under test is that composition reaches an answer at all rather
    # than propagating a refusal.  A caller that *must* know the file still
    # declares a denying ceiling asks ``committed_syscalls_policy``, where a
    # named refusal is the right answer.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox-syscalls")).__name__ == "SandboxSyscalls"


def test_the_composed_component_is_usable_immediately() -> None:
    # The artifact-backed reading, as one assertion a caller can rely on: the
    # composed ceiling admits an ordinary call and rejects a disallowed one —
    # the question a runtime actually asks on the *composed* path.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-syscalls")
    assert law.check(syscall_attempt(syscall=ADMITTED_SYSCALL)).admitted is True
    assert law.check(syscall_attempt(syscall=DISALLOWED_SYSCALL)).admitted is False


def test_the_composed_law_reports_the_committed_posture() -> None:
    # What a deployment auditing its own posture reads: the default action and
    # the ceiling, off the composed object rather than re-derived from the file.
    # The action is spelled here as data ("kill") rather than read from the
    # module's constant, so a rename fails here rather than being followed —
    # while the *terms* are compared against the file's own compiled ceiling,
    # because §5.2 fixes no syscall names and a term list is reviewed content
    # rather than a spec number.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-syscalls")
    assert law.default_action == KILL_ACTION == "kill"
    assert law.filter().denies_by_default is True
    assert law.filter().kills is True
    assert law.allowed() == sandbox.committed_syscalls_policy().allowed()
    assert law.allows(ADMITTED_SYSCALL) is True
    assert law.allows(DISALLOWED_SYSCALL) is False


def test_the_composed_law_raises_for_a_rejection_and_passes_an_admitted_call() -> None:
    # This seat's two outcomes, asserted from the composed path because that is
    # the shape a caller meets: an attempt inside the ceiling passes through, a
    # disallowed one raises, and an unreadable attempt raises the same class
    # rather than being read as admitted.
    #
    # Pinned by class *name* rather than by ``pytest.raises(DisallowedSyscall)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically — the
    # canonically-imported one, and ``isinstance`` cannot hold across that seam.
    # The same wrinkle the sibling suites document, answered the same way; the
    # name still fails the test if the wrong error comes out.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-syscalls")
    assert law.require(syscall_attempt(syscall=ADMITTED_SYSCALL)) is None
    with pytest.raises(Exception) as raised:
        law.require(syscall_attempt(syscall=DISALLOWED_SYSCALL))
    assert type(raised.value).__name__ == "DisallowedSyscall"
    assert str(raised.value).startswith(sandbox.DISALLOWED_SYSCALL_CODE)
    with pytest.raises(Exception) as refused:
        law.require(syscall_attempt(syscall=None))
    assert type(refused.value).__name__ == "DisallowedSyscall"
    assert str(refused.value).startswith(sandbox.SYSCALLS_REQUIRED_CODE)


def test_the_composed_law_answers_a_rejection_with_the_violation() -> None:
    # The half that keeps an escape attempt out of the evaluator's exception
    # path *and* hands it to the law that owns it: the gate answers with a
    # decision whose violation carries §15's class, the syscall, the action it
    # met and the node's identity — which is what feature 161 quarantines for.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-syscalls")
    decision = law.check(
        syscall_attempt(
            syscall=DISALLOWED_SYSCALL, node_id="n1", component=SIGNAL_SANDBOX
        )
    )
    assert decision.rejected is True
    assert decision.violation is not None
    assert decision.violation.fail_class == ESCAPE_CLASS
    assert decision.violation.syscall == DISALLOWED_SYSCALL
    assert decision.violation.node_id == "n1"
    assert decision.violation.row()["fail_class"] == "sandbox_escape"


def test_the_composed_law_hands_out_a_filter_specification() -> None:
    # Feature 160's word is *applies*, and the composed path is where a launcher
    # gets the thing it applies — a specification in the runtime's own spelling,
    # built fresh so a caller cannot widen the ceiling for the next one.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-syscalls")
    specification = law.filter().specification()
    assert specification["defaultAction"] == "kill"
    assert specification["syscalls"][0]["names"] == list(law.allowed())
    specification["syscalls"][0]["names"].append("openat")
    assert "openat" not in law.filter().specification()["syscalls"][0]["names"]


def test_the_builder_is_re_entrant_across_compositions() -> None:
    # The loader composes repeatedly and re-executes the package ``__init__`` each
    # time; a builder that accumulated state across calls would hand the second
    # application a law describing the first.  Two compositions, one answer.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert first.get("sandbox-syscalls").allowed() == (
        second.get("sandbox-syscalls").allowed()
    )
    assert first.get("sandbox-syscalls") is not second.get("sandbox-syscalls")


def test_the_component_carries_no_process_across_runs() -> None:
    # The reason this is a *value* rather than a registered mechanism, asserted
    # as behaviour: a component shared across runs that had armed a filter — or
    # held a ``prctl`` handle — would be one box's ceiling applied to another's
    # process.  Two composed applications therefore hold two independent laws,
    # and neither reads anything ambient.
    first = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-syscalls")
    second = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-syscalls")
    assert first.check(syscall_attempt(syscall=DISALLOWED_SYSCALL)).rejected is True
    assert second.check(syscall_attempt(syscall=ADMITTED_SYSCALL)).admitted is True
    assert sandbox.SandboxSyscalls.__slots__ == ("_policy",)


def test_the_seat_answers_the_same_component() -> None:
    # The app namespace's accessor, which is how everything outside the member
    # reaches the law.  ``None`` here means *no such component was registered*,
    # and never "registered but not yet configured" — the member's builder never
    # returns ``None`` and never defers.
    from app.modules.sandbox import sandbox_syscalls_component

    application = Application(
        components={"sandbox-syscalls": "sentinel"}, order=("sandbox-syscalls",)
    )
    assert sandbox_syscalls_component(application) == "sentinel"


def test_the_seat_returns_none_for_an_application_without_the_component() -> None:
    # The degrade-don't-break stance: a module that cannot reach the component
    # returns ``None`` rather than failing import, so a workspace that did not
    # scan this member still composes.
    from app.modules.sandbox import sandbox_syscalls_component

    empty = Application(components={}, order=())
    assert sandbox_syscalls_component(empty) is None
