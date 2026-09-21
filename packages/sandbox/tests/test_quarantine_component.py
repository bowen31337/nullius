"""Feature 161's plugin seam: the tenth component on the sandbox member.

This is the registration contract from the other side — the factory scans the
workspace members, imports this package, and the ``@register`` builder lands in
the composed application as the ``sandbox-quarantine`` component.  No registry,
router or factory was edited to make that true; this test exists to keep it
true.

The hazard the sibling suites name is the one this file re-checks for the tenth
seat: the factory's registry *replaces* a name's earlier registration, so a
control registered as ``sandbox``, ``sandbox-imports``, ``sandbox-transfer``,
``sandbox-seed``, ``sandbox-threads``, ``sandbox-timeout``, ``sandbox-failclass``,
``sandbox-budget`` or ``sandbox-syscalls`` would silently overwrite feature 157's
isolation law, 167's import allowlist, 166's payload channel, 165's node seed,
164's thread-pinning law, 163's wall-clock law, 168's fail-class vocabulary, 162's
cgroup-limits law or 160's seccomp allowlist — composition would look perfect and
a category root would be gone.  The tests below pin that the member now carries
exactly ten components, each under its own feature's name, and that the nine
earlier laws are still beside the tenth after it registered.

Placement and re-execution carry the same loader properties the other suites
pin: the builder lives in the package ``__init__`` (a ``@register`` in a
submodule fires on the first composition of a process and silently drops out of
every later one), and the composed component is pinned by class name and
behaviour across the loader's synthetic module-copy seam, where ``isinstance``
cannot hold.

**This seat is the second with no committed artifact behind it.**  Feature 168's
is the other, and the reading is the same one law over: §15 fixes the trigger,
the recovery and the class, and §9.1 fixes the vocabulary the class is read
against, so this law's subject is a *rule* rather than a deployment's setting —
the builder has nothing to compile and there is no file whose drift a ``None``
could report.  What a reviewer would want from an artifact comes back from the
law's own read side instead: ``fail_class()`` names the class a halt persists and
``mark_column()`` names the field it is written to, so the two facts a drifted
document would have decided are read rather than inferred.

**And this law's ``require`` raises for the pass-through too.**  Feature 160's
gate passes ``None`` through for an attempt inside the ceiling; this law's
subject is a *violation*, and a caller that called ``require`` has said it needs
a branch, so every case where no branch exists raises.  A caller running the
unattended loop §6.1 describes reads ``check`` instead, where the reason tells
the pass-through from the refusals.
"""

from __future__ import annotations

from pathlib import Path

import sandbox
from _documents import (
    ESCAPE_CLASS,
    QUARANTINE_CHILD_ID,
    QUARANTINE_ROOT_ID,
    QUARANTINE_SIBLING_ID,
    cyclic_rows,
    quarantine_rows,
    quarantine_violation_from_gate,
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


def _assert_is_the_quarantine_law(component: object) -> None:
    assert type(component).__name__ == "SandboxQuarantine"
    # The law's verbs, duck-checked across the loader's module copy seam: the
    # gate and the predicate, the launcher verb, the tree reader, and the three
    # read-side questions a deployment audits with.
    assert component.quarantines(
        quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID),
        component.tree(quarantine_rows()),
    ) is True
    assert component.tree(quarantine_rows()).size == 5
    assert component.fail_class() == ESCAPE_CLASS
    assert component.mark_column() == "quarantined_at"
    assert "node_id" in component.columns()


def test_the_seat_spells_the_component_name_the_member_registers() -> None:
    # The pair cannot drift into a silent ``None`` at the seat: the member's
    # constant is the spelling the builder registers under and the seat's is the
    # spelling the app namespace reads it back with.
    import app.modules.sandbox as seat

    assert seat.QUARANTINE_COMPONENT_NAME == sandbox.QUARANTINE_COMPONENT_NAME
    assert sandbox.QUARANTINE_COMPONENT_NAME == "sandbox-quarantine"


def test_the_component_name_is_not_any_earlier_laws() -> None:
    # The registry-replacement hazard at the constant: none of the nine earlier
    # names, and not the category spelling either.
    assert sandbox.QUARANTINE_COMPONENT_NAME not in {
        "sandbox",
        "sandbox-imports",
        "sandbox-transfer",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-failclass",
        "sandbox-budget",
        "sandbox-syscalls",
    }


def test_scanning_the_member_registers_the_ten_components_it_owns() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # create_app would otherwise leave this one asserting against a registry it
    # did not build.
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


def test_the_earlier_nine_laws_are_still_beside_the_tenth() -> None:
    # The point of registering under its own name: the ninth seat registering
    # must not have retired any of the eight before it.
    application = create_app(MEMBER_SRC, registry=Registration())

    for name in (
        "sandbox",
        "sandbox-imports",
        "sandbox-transfer",
        "sandbox-seed",
        "sandbox-threads",
        "sandbox-timeout",
        "sandbox-failclass",
        "sandbox-budget",
        "sandbox-syscalls",
        "sandbox-quarantine",
    ):
        assert application.get(name) is not None, name


def test_the_builder_is_the_packages_own() -> None:
    components = scan_components(MEMBER_SRC, registry=Registration())
    builders = {component.name: component.builder for component in components}

    assert builders["sandbox-quarantine"].__name__ == "build_sandbox_quarantine"


def test_the_builder_takes_no_arguments_and_never_raises() -> None:
    # The factory builds every registered component on every ``create_app()``, so
    # a builder that raised would take composition down for every unrelated
    # feature in the workspace.
    from sandbox import build_sandbox_quarantine

    assert build_sandbox_quarantine() is not None
    assert type(build_sandbox_quarantine()).__name__ == "SandboxQuarantine"


class TestTheComposedApplication:
    """The seat read back from a composed app, by name."""

    def test_the_component_is_reachable_by_its_name(self) -> None:
        application = create_app(MEMBER_SRC, registry=Registration())

        assert application.get("sandbox-quarantine") is not None
        assert "sandbox-quarantine" in application.order

    def test_the_component_is_the_law(self) -> None:
        application = create_app(MEMBER_SRC, registry=Registration())

        _assert_is_the_quarantine_law(application.get("sandbox-quarantine"))

    def test_the_seat_accessor_reads_it_back(self) -> None:
        from app.modules.sandbox import (
            QUARANTINE_COMPONENT_NAME,
            sandbox_quarantine_component,
        )

        application = Application(
            components={QUARANTINE_COMPONENT_NAME: "sentinel"},
            order=(QUARANTINE_COMPONENT_NAME,),
        )

        assert sandbox_quarantine_component(application) == "sentinel"

    def test_the_seat_accessor_answers_none_for_an_absent_component(self) -> None:
        # An absent component is a discoverable state rather than an exception.
        from app.modules.sandbox import sandbox_quarantine_component

        assert sandbox_quarantine_component(Application()) is None


class TestTheComposedLawAnswers:
    """Behaviour through the composition path, not just the class name."""

    def test_the_composed_law_halts_a_branch(self) -> None:
        law = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )
        tree = law.tree(quarantine_rows())

        quarantine = law.require(
            quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID), tree
        )

        assert quarantine.size == 3
        assert quarantine.fail_class == ESCAPE_CLASS
        assert QUARANTINE_SIBLING_ID not in quarantine.nodes

    def test_the_composed_law_refuses_a_cyclic_tree(self) -> None:
        law = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )

        decision = law.check(
            quarantine_violation_from_gate(node_id=QUARANTINE_CHILD_ID),
            law.tree(cyclic_rows()),
        )

        assert decision.refused is True
        assert decision.quarantined is False

    def test_the_composed_law_marks_the_branch_it_halts(self) -> None:
        # End to end: the gate's commitment in, the mark and the class out —
        # which is the whole feature reachable from a composed application
        # without importing the member's submodules by name.
        law = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )
        tree = law.tree(quarantine_rows())
        quarantine = law.require(
            quarantine_violation_from_gate(node_id=QUARANTINE_ROOT_ID), tree
        )
        records = {node_id: {"id": node_id} for node_id in tree.node_ids()}

        written = quarantine.mark(records)

        assert len(written) == quarantine.size
        assert records[QUARANTINE_ROOT_ID]["fail_class"] == ESCAPE_CLASS
        assert all(
            records[node_id][law.mark_column()] for node_id in quarantine.nodes
        )

    def test_the_composed_law_reads_the_gates_own_class(self) -> None:
        # The handoff is the value feature 160 publishes, so the two laws must
        # agree on the spelling without either importing the other's constant.
        from sandbox import VIOLATION_CLASS

        law = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )

        assert law.fail_class() == VIOLATION_CLASS == ESCAPE_CLASS

    def test_the_composed_law_carries_no_state(self) -> None:
        # Two compositions give two distinguishable components that answer
        # identically — a facade, not an armed halt.
        first = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )
        second = create_app(MEMBER_SRC, registry=Registration()).get(
            "sandbox-quarantine"
        )

        assert first.columns() == second.columns()
        assert first is not second
