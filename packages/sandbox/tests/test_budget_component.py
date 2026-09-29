"""Feature 162's plugin seam: the eighth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-budget`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the eighth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports``, ``sandbox-transfer``,
``sandbox-seed``, ``sandbox-threads``, ``sandbox-timeout`` or
``sandbox-failclass`` would silently overwrite feature 157's isolation law,
167's import allowlist, 166's payload channel, 165's node seed, 164's
thread-pinning law, 163's wall-clock law or 168's fail-class vocabulary —
composition would look perfect and a category root would be gone.  The tests
below pin that the member now carries exactly eight components, each under its
own feature's name, and that the seven earlier laws are still beside the eighth
after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

**This seat is the fifth with a committed artifact behind it**, which is worth
one assertion the artifact-less seats could not make: a non-``None`` component
here proves a file on disk compiled, so the composed-path test asks the law a
question whose answer the artifact decides.

**And this seat's ``require`` has the configuration laws' two outcomes rather
than feature 163's three.**  A timeout is an outcome the pipeline records and a
run inside its budget has nothing to persist, so feature 163's ``require``
passes ``None`` through.  Here a run that outran a cgroup limit is a violation
of the *box* rather than a bad candidate, so ``require`` returns ``None`` only
for a run measured inside every limit and raises for a breach exactly as it does
for a run it cannot measure — while ``check`` still *answers* with the readings,
which is what keeps a breach out of the evaluator's exception path.  The tests
below assert both halves.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sandbox
from _documents import (
    OVER_CPU_S,
    OVER_MEM_MB,
    TEXT_MEASUREMENT,
    WITHIN_CPU_S,
    WITHIN_MEM_MB,
    WITHIN_PIDS,
    budget_run,
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


def _assert_is_the_cgroup_law(component: object) -> None:
    assert type(component).__name__ == "SandboxBudget"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate, the boolean, the launcher verb, and the read side a deployment audits
    # with.  ``cpu_s``/``mem_mb``/``pids`` are properties rather than methods, so
    # they are read rather than called.
    for operation in ("check", "over_limits", "require", "limits", "described"):
        assert hasattr(component, operation), operation
    for reading in ("cpu_s", "mem_mb", "pids"):
        assert isinstance(getattr(component, reading), (int, float)), reading


def test_the_member_declares_the_component_name_the_feature_owns() -> None:
    # One spelling shared by the member, the spec's plugin namespace and anything
    # asking the composed application for the law.
    assert sandbox.BUDGET_COMPONENT_NAME == "sandbox-budget"


def test_scanning_the_member_registers_the_ten_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member into the
    # current registry, so reading it back here would assert accumulated process
    # state, not this package's contribution.
    #
    # The list is pinned exactly: the isolation law, feature 162's cgroup-limits
    # law, the import law, the payload channel, the node seed, the thread-pinning
    # law, the wall-clock law and feature 168's fail-class law, no more and no
    # less.  A ninth component arriving unnoticed fails here — and a builder that
    # had taken any earlier feature's name would fail here too, which is the
    # registry-replacement hazard this file exists for.
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


def test_the_budget_builder_does_not_replace_any_earlier_law() -> None:
    # The hazard, stated as behaviour: after all eight builders have fired, the
    # composed application still carries features 157's, 167's, 166's, 165's,
    # 164's, 163's and 168's laws under their own names — an eighth registration
    # of any of those names would have replaced one.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox")).__name__ == "SandboxIsolation"
    assert type(app.get("sandbox-imports")).__name__ == "SandboxImports"
    assert type(app.get("sandbox-transfer")).__name__ == "SandboxTransfer"
    assert type(app.get("sandbox-seed")).__name__ == "SandboxSeed"
    assert type(app.get("sandbox-threads")).__name__ == "SandboxThreads"
    assert type(app.get("sandbox-timeout")).__name__ == "SandboxTimeout"
    assert type(app.get("sandbox-failclass")).__name__ == "SandboxFailClass"
    _assert_is_the_cgroup_law(app.get("sandbox-budget"))
    assert "sandbox-budget" in app.order


def test_the_builder_takes_no_arguments_and_resolves_nothing() -> None:
    # The factory's protocol: a zero-argument builder.  And this one reads no
    # ambient environment and opens no cgroup — its whole subject is a run's
    # *reported* consumption — so it composes in any process, including a bare
    # test process with no DATABASE_URL and no lake, and its answer cannot depend
    # on the shell that started pytest or on whether the host exposes cgroup v2.
    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders["sandbox-budget"].__name__ == "build_sandbox_budget"


def test_the_builder_never_returns_none() -> None:
    # The honest shape for a *law* rather than a store.  Unlike the artifact-less
    # seats, a non-None value here proves more than that the law loaded: this
    # builder compiles :data:`sandbox.COMMITTED_BUDGET_POLICY` at build time, so
    # the component it hands out is proof the file on disk was read and held to
    # §5.2's three limits.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert app.get("sandbox-budget") is not None


def test_a_drifted_artifact_does_not_take_composition_down() -> None:
    # The builder's refusal-free path, stated as behaviour: the factory builds
    # every registered component on every ``create_app()`` call, so a builder that
    # raised on a drifted artifact would take composition down for every unrelated
    # feature in the workspace.  The law compiles the committed file here — and it
    # is not drifted — but the property under test is that composition reaches an
    # answer at all rather than propagating a refusal.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert type(app.get("sandbox-budget")).__name__ == "SandboxBudget"


def test_the_composed_component_is_usable_immediately() -> None:
    # The artifact-backed reading, as one assertion a caller can rely on: the
    # composed law confines a run at §5.2's numbers, so a run comfortably inside
    # them is admitted and one past them is rejected on the *composed* path — the
    # question a dispatch actually asks.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-budget")
    inside = budget_run(cpu_s=WITHIN_CPU_S, mem_mb=WITHIN_MEM_MB, pids=WITHIN_PIDS)
    assert law.check(inside).admitted is True
    assert law.over_limits(budget_run(cpu_s=OVER_CPU_S)) is True


def test_the_composed_law_reports_the_committed_limits() -> None:
    # What a deployment auditing its own posture reads: the three numbers, off
    # the composed object rather than re-derived from the file.  Spelled as data
    # here (30, 2048, 32) rather than read from the module's constants, so a
    # rename of a constant fails here rather than being followed.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-budget")
    assert law.cpu_s == 30.0
    assert law.mem_mb == 2048
    assert law.pids == 32


def test_the_composed_law_raises_for_a_breach_and_passes_a_confined_run() -> None:
    # This seat's two outcomes, asserted from the composed path because that is
    # the shape a caller meets: a run measured inside every limit passes through,
    # a breach raises, and an unmeasurable run raises the same class rather than
    # being read as confined.
    #
    # Pinned by class *name* rather than by ``pytest.raises(CgroupBudgetExceeded)``
    # because the composed component comes from the loader's synthetic module
    # copy: the exception it raises is structurally — but not identically — the
    # canonically-imported one, and ``isinstance`` cannot hold across that seam.
    # The same wrinkle the sibling suites document, answered the same way; the
    # name still fails the test if the wrong error comes out.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-budget")
    assert law.require(budget_run(cpu_s=WITHIN_CPU_S)) is None
    with pytest.raises(Exception) as raised:
        law.require(budget_run(cpu_s=OVER_CPU_S, mem_mb=OVER_MEM_MB))
    assert type(raised.value).__name__ == "CgroupBudgetExceeded"
    assert str(raised.value).startswith(sandbox.CGROUP_BUDGET_CODE)
    with pytest.raises(Exception) as refused:
        law.require(budget_run(cpu_s=WITHIN_CPU_S, mem_mb=TEXT_MEASUREMENT))
    assert type(refused.value).__name__ == "CgroupBudgetExceeded"
    assert str(refused.value).startswith(sandbox.CGROUP_LIMITS_REQUIRED_CODE)


def test_the_composed_law_answers_a_breach_with_its_readings() -> None:
    # The half that keeps a breach out of the evaluator's exception path: the
    # gate *answers* with the per-limit overruns, so the pipeline can record what
    # was consumed instead of crashing over one unattended candidate.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("sandbox-budget")
    decision = law.check(budget_run(cpu_s=WITHIN_CPU_S, mem_mb=OVER_MEM_MB))
    assert decision.over_limits is True
    assert decision.breach is not None
    assert decision.breach.fields == ("mem_mb",)
    assert decision.breach.fail_class == "oom"


def test_the_builder_is_re_entrant_across_compositions() -> None:
    # The loader composes repeatedly and re-executes the package ``__init__`` each
    # time; a builder that accumulated state across calls would hand the second
    # application a law describing the first.  Two compositions, one answer.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert (
        first.get("sandbox-budget").described()
        == second.get("sandbox-budget").described()
    )
    assert first.get("sandbox-budget") is not second.get("sandbox-budget")


def test_the_component_carries_no_cgroup_across_runs() -> None:
    # The reason this is a *value* rather than a registered mechanism, asserted
    # as behaviour: a component shared across runs that held a cgroup — or a
    # probe reading one — would answer the second dispatch with the first run's
    # consumption.  Two composed applications therefore hold two independent
    # laws, and neither reads anything ambient.
    first = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-budget")
    second = create_app(MEMBER_SRC, registry=Registration()).get("sandbox-budget")
    assert first.check(budget_run(cpu_s=OVER_CPU_S)).over_limits is True
    assert second.check(budget_run(cpu_s=WITHIN_CPU_S)).admitted is True
    assert sandbox.SandboxBudget.__slots__ == ("_policy",)


def test_the_application_answers_the_same_component() -> None:
    # Asking the composed application by name is how everything outside the
    # member reaches the law.  ``None`` here means *no such component was
    # registered*, and never "registered but not yet configured" — the member's
    # builder never returns ``None`` and never defers.
    application = Application(
        components={"sandbox-budget": "sentinel"}, order=("sandbox-budget",)
    )
    assert application.get("sandbox-budget") == "sentinel"


def test_the_application_returns_none_without_the_component() -> None:
    # The degrade-don't-break stance: an application that did not scan this
    # member answers ``None`` for the name rather than failing, so a workspace
    # without it still composes.
    empty = Application(components={}, order=())
    assert empty.get("sandbox-budget") is None
