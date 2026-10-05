"""Feature 1, the member — the orchestrator joins the workspace.

additions_spec_live_evaluation.xml, "Orchestrator Member", feature 1:
*System creates the orchestrator workspace member at
packages/orchestrator (project name orchestrator, import name
orchestrator).  Its pyproject declares workspace dependencies on
evaluator, nulloracle, ledger, artifacts, discovery, signal-agent,
providers and policy-runtime, each with a ``[tool.uv.sources]
workspace = true`` entry.  It adds no third-party package.*  And the
sentence's three bullet claims: ``uv.lock`` is regenerated and ``uv sync
--all-packages`` succeeds with the root pyproject.toml untouched;
``orchestrator/__init__.py`` holds a module docstring and an empty
``__all__`` and registers no component yet; this file imports
``orchestrator`` and asserts that ``create_app()`` still composes.

Five contracts, one per claim a member's first feature makes:

* **membership** — the member is discovered by convention, not by any
  central edit: ``workspace_members()`` resolves
  ``packages/orchestrator`` from the root's ``packages/*`` glob, so the
  scan the factory runs reaches this package's ``src/`` with no edit to
  the root pyproject.toml (the file claim asserts the same thing
  statically — this test holds it live).

* **the declaration** — the pyproject names exactly the eight members
  the spec sentence names, each with a ``workspace = true`` source and
  nothing else in ``[tool.uv.sources]``.  That "nothing else" is the
  whole of *it adds no third-party package*: a registry dependency
  would be a dependency with no workspace source, and the eight names
  are all members, so the dependencies list and the sources table cover
  one another exactly.

* **the module surface** — ``orchestrator`` imports, carries a module
  docstring, and answers an empty ``__all__``: the member's public
  surface at feature 1 is deliberately nothing, because the features
  that follow add their own exports as they add their subjects.

* **no component yet** — a scan of this member alone composes an empty
  application: the package joins the workspace without contributing a
  component, which is how a member lands before its first ``@register``
  without breaking any composition that predates it.

* **composition still composes** — the full default-roots
  ``create_app()`` answers an :class:`~app.module_loader.Application`
  whose registry still carries each dependency member's own component —
  one name per member of the eight declared, so the member's arrival
  removed nothing and hid nothing.  The names are pinned in this module
  rather than imported, the same discipline the sibling member suites
  state for theirs: a suite that read the name off the code it tests
  would follow the code instead of the spec.

No test in this file opens a network connection, reads a real
credential, or writes outside a pytest temporary directory.  The
composition builds every registered builder in a bare process, which is
exactly the environment the factory documents for the scan.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import orchestrator

from app.module_loader import Application, Registration, create_app, workspace_members

#: This member's ``src/`` — the scan root the factory derives from the
#: member's directory layout (``packages/orchestrator/src``).
MEMBER_SRC = Path(orchestrator.__file__).resolve().parent.parent

#: The member's own project file — the declaration this feature lands.
PYPROJECT = MEMBER_SRC.parent / "pyproject.toml"

#: The eight members the spec sentence names, in its own order.  Spelled
#: here rather than read back off the pyproject, so a dependency dropped
#: or reordered is a failing test about *the feature text*.
DEPENDENCIES = (
    "evaluator",
    "nulloracle",
    "ledger",
    "artifacts",
    "discovery",
    "signal-agent",
    "providers",
    "policy-runtime",
)

#: One component name per dependency member — each member's own first
#: component, pinned by member so "still composes" is asserted against
#: every member the declaration names, not against a count that could
#: hold while a name quietly vanished.
COMPONENTS_BY_MEMBER = {
    "evaluator": "evaluator",
    "nulloracle": "nulloracle-target-route",
    "ledger": "ledger",
    "artifacts": "artifacts",
    "discovery": "discovery",
    "signal-agent": "signal-agent",
    "providers": "providers",
    "policy-runtime": "policy-runtime",
}


def test_the_member_is_a_declared_workspace_member() -> None:
    # Membership by convention: the root glob declares this member, the
    # factory's own discovery resolves it, and the scan root it derives —
    # this member's src/ — is a directory the scan can walk.  No central
    # file was edited to make that true, and this test fails if the
    # member ever stops being discovered.
    members = workspace_members()
    assert MEMBER_SRC.parent in members
    assert MEMBER_SRC.is_dir()


def test_the_pyproject_declares_the_eight_workspace_dependencies() -> None:
    # The spec sentence's own list, exactly: the eight members it names,
    # every one with a workspace = true source, and no other dependency
    # and no other source.  A third-party package would be a dependency
    # without a workspace source — so the two sets covering each other
    # exactly *is* "it adds no third-party package".
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)

    assert project["project"]["name"] == "orchestrator"
    assert project["project"]["dependencies"] == list(DEPENDENCIES)

    sources = project["tool"]["uv"]["sources"]
    assert set(sources) == set(DEPENDENCIES)
    for name in DEPENDENCIES:
        assert sources[name] == {"workspace": True}, name


def test_the_module_holds_a_docstring_and_an_empty_all() -> None:
    # The sentence's bullet: a module docstring and an empty ``__all__``.
    # The docstring is this member's front page — the factory's scan
    # imports the package with nothing else to show for it — and the
    # empty ``__all__`` is the honest statement that feature 1 exports
    # nothing: the features that follow add their own names as they add
    # their subjects, and nothing imports `from orchestrator import *`
    # in the meantime.
    assert isinstance(orchestrator.__doc__, str)
    assert orchestrator.__doc__.strip()
    assert orchestrator.__all__ == []


def test_the_member_registers_no_component_yet() -> None:
    # "Registers no component yet" held precisely: a scan of this member
    # alone — its own src/ as the only root, a fresh registry so nothing
    # another member registered can mask the claim — composes the empty
    # application.  The member exists to the factory and contributes
    # nothing, which is what lets it land beside every composition that
    # predates it.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert isinstance(app, Application)
    assert app.components == {}
    assert app.order == ()


def test_create_app_still_composes() -> None:
    # The sentence's own assertion, over the default roots: the whole
    # declared workspace scans, the new member's package imports under
    # the loader's synthetic name without registering anything, and the
    # composed application still answers every dependency member's own
    # component — one name per member of the eight declared, so the
    # member's arrival removed nothing and hid nothing.
    app = create_app()
    assert isinstance(app, Application)
    assert app.order  # the workspace carries its components still
    for member, component in COMPONENTS_BY_MEMBER.items():
        assert component in app, member
        assert component in app.order, member
