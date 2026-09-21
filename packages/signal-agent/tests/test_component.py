"""Feature 205's plugin seam: composition, and the app-namespace seat.

Two contracts, both held from the side this member owns:

* **composition by convention** — the factory scans the workspace, imports
  this package, the ``@register("signal-agent")`` builder fires, and the
  composed application carries a ``signal-agent`` component.  No registry,
  router, entry-points table or app factory was edited to make that true, and
  this suite keeps it true under the two loader hazards the bootstrap and
  cost-model suites state for their own components: the synthetic-name copy
  (pin by name, module suffix and behaviour — never ``isinstance``) and the
  second composition (a ``@register`` outside ``__init__.py`` would fire once
  and silently drop out of every later ``create_app()``; the builder lives in
  ``__init__.py`` and the test asserts on the *second* application or it
  passes vacuously).

* **the seat** — ``app.modules.signal-agent`` answers exactly one question
  (*what is the composed authoring law?*), imports the member only under
  ``TYPE_CHECKING``, and answers ``None`` — not an exception — when nothing is
  registered.  Its ``None`` is a statement about *composition*, never about a
  proposal: the verdict on a proposal is the law's own returned value, and
  reading this ``None`` as "no signal was adopted" would collapse a
  deployment problem into a research result.

The seat's directory name carries a hyphen and so is not a valid dotted
import path; it is reached the way the factory reaches such a package —
``importlib.import_module`` with the hyphenated name.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import signal_agent as member

from app.module_loader import (
    Application,
    Registration,
    create_app,
    workspace_scan_roots,
)

MEMBER_SRC = Path(member.__file__).resolve().parent.parent

# The seat's directory name is hyphenated, so importlib loads it the way the
# factory's scan does.
seat = importlib.import_module("app.modules.signal-agent")

_CONFORMING = (
    "def signal(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))\n"
)


def _assert_is_the_authoring_law(component: object) -> None:
    """The composed component is the law, across the loader's copies.

    Name, then behaviour — the discipline the bootstrap member's component
    test states, because the loader imports the member under a synthetic name
    and ``isinstance`` across the two copies cannot hold.  The behaviour check
    is the decisive one and it is the feature's own subject: the composed law
    must *adopt* the source the canonically-imported law adopts, and refuse
    what it refuses, with the same code hash.
    """
    assert type(component).__name__ == "SignalContract"
    assert type(component).__module__.endswith("signal_agent._authoring")

    for verb in ("adopt", "validate", "signature", "declaration"):
        assert callable(getattr(component, verb)), verb

    composed = component.adopt(_CONFORMING)  # type: ignore[attr-defined]
    direct = member.signal_contract().adopt(_CONFORMING)
    assert composed.adopted == direct.adopted
    assert composed.reason == direct.reason
    assert composed.code_hash == direct.code_hash
    # Compared by value: the composed law's declaration is assembled from the
    # scanned copy's contract member, so the two mappings are equal but their
    # `accessors` tuples come from two module objects.  The values are the
    # claim; object identity across the boundary is not available.
    assert dict(component.declaration()) == dict(  # type: ignore[attr-defined]
        member.signal_contract().declaration()
    )


# -- Composition -------------------------------------------------------------


def test_the_member_registers_under_the_specs_plugin_name() -> None:
    # The spec's own spelling (``plugin="signal-agent"``) and the member's are
    # one string; three spellings of one name is exactly the drift a test is
    # cheaper than.
    assert member.COMPONENT_NAME == "signal-agent"


def test_the_member_is_declared_in_the_scanned_workspace() -> None:
    member_root = MEMBER_SRC.parent
    assert (member_root / "pyproject.toml").is_file()
    assert MEMBER_SRC in workspace_scan_roots()


def test_the_scanned_application_carries_the_authoring_law() -> None:
    registry = Registration()
    app = create_app(MEMBER_SRC, registry=registry)
    assert "signal-agent" in app
    assert "signal-agent" in app.order
    _assert_is_the_authoring_law(app.get("signal-agent"))


def test_the_whole_workspace_composes_the_component_too() -> None:
    # The member's own scan root is not a special case: the declared workspace
    # is what the production factory scans.
    app = create_app()
    assert "signal-agent" in app
    _assert_is_the_authoring_law(app.get("signal-agent"))


def test_the_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard: a ``@register`` outside ``__init__.py``
    # fires once, on the first import in the process, and silently drops out of
    # every later ``create_app()``.  Asserting on the *second* application is
    # what makes this test non-vacuous.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert "signal-agent" in first
    assert "signal-agent" in second
    _assert_is_the_authoring_law(second.get("signal-agent"))


def test_building_the_component_resolves_nothing() -> None:
    # The builder allocates one stateless law: the declared ABI is read out of
    # the contract member on the first question asked, not at composition time.
    # That is what keeps this component's presence independent of scan order,
    # and it is why holding the handle can fail at nothing.
    app = create_app(MEMBER_SRC, registry=Registration())
    law = app.get("signal-agent")
    assert law is not None
    assert type(law).__slots__ == ()
    # No contract attribute is cached on it, so there is nothing to go stale.
    assert not any(
        name in type(law).__dict__ for name in ("_contract", "contract", "_abi")
    )


# -- The seat ------------------------------------------------------------------


def test_the_seat_names_line_up() -> None:
    assert seat.COMPONENT_NAME == member.COMPONENT_NAME == "signal-agent"


def test_the_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    law = seat.signal_agent_component(app)
    _assert_is_the_authoring_law(law)


def test_the_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a proposal.
    empty = Application(components={}, order=())
    assert seat.signal_agent_component(empty) is None


def test_the_seat_does_not_import_the_member_at_module_scope() -> None:
    # The app package must not depend on any workspace member at import time;
    # the member's type appears only under ``TYPE_CHECKING``, which the
    # interpreter never evaluates.  Asserted on the *parse tree* rather than on
    # the source text, because the seat's own docstring names the module it
    # does not import, and the member's import must be *found* — under the
    # guard, and nowhere else.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(seat))
    live: list[str] = []
    guarded: list[str] = []

    def _collect(nodes, into: list[str]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test):
                for nested in node.body:
                    _collect([nested], guarded)
                continue
            if isinstance(node, ast.Import):
                into.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                into.append(node.module or "")
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    # The member's import is present, and it is under the guard: a reader and a
    # type checker see the type, the interpreter never imports it.  Both halves
    # are asserted, because a seat that dropped the import entirely would pass
    # the first line while losing the typing the guard exists to provide.
    assert "signal_agent" in guarded, guarded


def test_the_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # *growing* a re-export of the member's API, and a membership check cannot
    # see that.
    assert set(seat.__all__) == {"COMPONENT_NAME", "signal_agent_component"}


def test_the_seat_is_reachable_by_its_hyphenated_name() -> None:
    # Reached the way the factory reaches such a package.
    assert seat.__name__ == "app.modules.signal-agent"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent")
