"""Features 205, 212 and 213's plugin seam: composition, and the app-namespace seats.

Three contracts, all held from the side this member owns:

* **composition by convention** — the factory scans the workspace, imports
  this package, the ``@register`` builders fire, and the composed application
  carries a ``signal-agent`` component, a ``signal-agent-dead-territory`` one
  and a ``signal-agent-themes`` one under the member's own names.  No registry,
  router, entry-points table or app factory was edited to make that true, and
  this suite keeps it true under the three loader hazards the bootstrap,
  sandbox and cost-model suites state for their own components: the
  synthetic-name copy (pin by name, module suffix and behaviour — never
  ``isinstance``), the second composition (a ``@register`` outside
  ``__init__.py`` would fire once and silently drop out of every later
  ``create_app()``; all three builders live in ``__init__.py`` and the test
  asserts on the *second* application or it passes vacuously), and the
  **registry-replacement** hazard a second component introduces — the registry
  is keyed by name, so a builder that took ``signal-agent`` for itself would
  silently replace feature 205's law rather than sit beside it, which is why
  the three are asserted together and each law is checked *after* all three
  fired.

* **the seats** — ``app.modules.signal-agent`` answers *what is the composed
  authoring law?*, ``app.modules.signal-agent.themes`` answers *what is the
  composed legal theme gate?* and ``app.modules.signal-agent.dead_territory``
  answers *what is the composed dead-territory gate?*, each importing the member
  only under ``TYPE_CHECKING`` and answering ``None`` — not an exception — when
  nothing is registered.  A seat's ``None`` is a statement about *composition*,
  never about a proposal: the verdicts are the laws' own returned values, and
  reading one ``None`` as "no signal was adopted", "the agent opened in an
  illegal theme" or "the mechanism is live" would collapse a deployment problem
  into a research result.  The theme seat's ``None`` matters twice over,
  because a composed gate that *admits nothing* is the opposite complaint — a
  present component refusing every proposal — and an operator who could not tell
  them apart would not know whether to widen the document or re-prompt the
  agent.

Both seats' directory names carry a hyphen and so are not valid dotted import
paths; they are reached the way the factory reaches such a package —
``importlib.import_module`` with the hyphenated name.
"""

from __future__ import annotations

import importlib
import inspect
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

# The seats' directory names are hyphenated, so importlib loads them the way
# the factory's scan does.
seat = importlib.import_module("app.modules.signal-agent")
theme_seat = importlib.import_module("app.modules.signal-agent.themes")
dead_seat = importlib.import_module("app.modules.signal-agent.dead_territory")

_CONFORMING = (
    "def signal(ctx, seed):\n"
    "    return pl.Series([1.0] * len(ctx.universe))\n"
)

#: A root the committed set names, and one it does not.  Taken from the
#: artifact's own vocabulary rather than invented, so a claim about the
#: *composed* gate is a claim about the deployment's set.
_LEGAL_THEME = "order-flow-imbalance"
_ILLEGAL_THEME = "sub-30-minute-liquidity-taking"

#: A mechanism the committed denylist names as dead.  Taken from the artifact's
#: own vocabulary rather than invented, so a claim about the *composed* gate is
#: a claim about the deployment's denylist.
_DEAD_MECHANISM = "sub-30-minute-liquidity-taking"
_LIVE_MECHANISM = "order-flow-imbalance"


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


# -- Feature 212's component ---------------------------------------------------


def _assert_is_the_theme_law(component: object) -> None:
    """The composed gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the
    authoring law's check above is not.  The decisive check is feature 212's
    own subject: the composed gate must refuse what the canonically-imported
    one refuses, with the same ``illegal_theme`` message.
    """
    assert type(component).__name__ == "SignalThemeGate"
    assert type(component).__module__.endswith("signal_agent._themes")

    for verb in ("admit", "require", "covers", "legal", "title"):
        assert callable(getattr(component, verb)), verb

    composed = component.admit(_ILLEGAL_THEME)  # type: ignore[attr-defined]
    direct = member.signal_theme_gate().admit(_ILLEGAL_THEME)
    assert composed.admitted == direct.admitted is False
    assert composed.reason == direct.reason
    assert composed.detail == direct.detail
    # And the read side, compared by value: the composed gate's set comes from
    # the scanned copy's module, so the tuples are equal but are not the same
    # object across the loader's boundary.  The slugs are the claim.
    assert tuple(component.legal()) == tuple(  # type: ignore[attr-defined]
        member.signal_theme_gate().legal()
    )


def _assert_is_the_dead_territory_law(component: object) -> None:
    """The composed dead-territory gate is the law, across the loader's copies.

    Name, then behaviour — never ``isinstance``, for the same reason the
    authoring law's check above is not.  The decisive check is feature 213's
    own subject: the composed gate must refuse what the canonically-imported
    one refuses, with the same ``dead_territory`` message.
    """
    assert type(component).__name__ == "DeadTerritoryGate"
    assert type(component).__module__.endswith("signal_agent._dead_territory")

    for verb in ("admit", "require", "covers", "dead", "title"):
        assert callable(getattr(component, verb)), verb

    composed = component.admit(_DEAD_MECHANISM)  # type: ignore[attr-defined]
    direct = member.dead_territory_gate().admit(_DEAD_MECHANISM)
    assert composed.admitted == direct.admitted is False
    assert composed.reason == direct.reason
    assert composed.detail == direct.detail
    # And the read side, compared by value: the composed gate's list comes from
    # the scanned copy's module, so the tuples are equal but are not the same
    # object across the loader's boundary.  The mechanisms are the claim.
    assert tuple(component.dead()) == tuple(  # type: ignore[attr-defined]
        member.dead_territory_gate().dead()
    )


def test_the_member_registers_the_theme_gate_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a second time would *replace* feature
    # 205's law rather than sit beside it.  Asserted against the spec's plugin
    # namespace — the feature belongs to ``signal-agent`` — and against the
    # unprefixed name, which must not be what this component took.
    assert member.THEMES_COMPONENT_NAME == "signal-agent-themes"
    assert member.THEMES_COMPONENT_NAME != member.COMPONENT_NAME


def test_the_scanned_application_carries_all_three_laws() -> None:
    # The three, in one composition: feature 205's law, feature 212's gate and
    # feature 213's gate, each under its own name, none having replaced another.
    app = create_app(MEMBER_SRC, registry=Registration())
    assert "signal-agent" in app
    assert member.DEAD_TERRITORY_COMPONENT_NAME in app
    assert member.THEMES_COMPONENT_NAME in app
    _assert_is_the_authoring_law(app.get("signal-agent"))
    _assert_is_the_dead_territory_law(app.get(member.DEAD_TERRITORY_COMPONENT_NAME))
    _assert_is_the_theme_law(app.get(member.THEMES_COMPONENT_NAME))


def test_the_three_laws_stay_contiguous_in_the_name_sorted_order() -> None:
    # ``app.order`` is name-sorted, so the prefixed names are what keep the
    # member's three components together in the category they belong to rather
    # than scattered by whatever the prefixes happened to be.  The three names
    # sort as ``signal-agent`` < ``signal-agent-dead-territory`` <
    # ``signal-agent-themes``, so the dead-territory gate lands between the
    # authoring law and the theme gate — and the three are contiguous, with no
    # unrelated component wedged between them.
    app = create_app(MEMBER_SRC, registry=Registration())
    order = list(app.order)
    positions = sorted(order.index(name) for name in (
        member.COMPONENT_NAME,
        member.DEAD_TERRITORY_COMPONENT_NAME,
        member.THEMES_COMPONENT_NAME,
    ))
    assert positions == [positions[0], positions[0] + 1, positions[0] + 2]
    assert order[positions[0]] == member.COMPONENT_NAME
    assert order[positions[1]] == member.DEAD_TERRITORY_COMPONENT_NAME
    assert order[positions[2]] == member.THEMES_COMPONENT_NAME


def test_the_theme_component_survives_a_second_composition() -> None:
    # The submodule-registration hazard, checked on the *second* application:
    # a ``@register`` outside ``__init__.py`` fires once and drops out.
    first = create_app(MEMBER_SRC, registry=Registration())
    second = create_app(MEMBER_SRC, registry=Registration())
    assert member.THEMES_COMPONENT_NAME in first
    assert member.THEMES_COMPONENT_NAME in second
    _assert_is_the_theme_law(second.get(member.THEMES_COMPONENT_NAME))


def test_building_the_theme_gate_carries_the_committed_set() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = app.get(member.THEMES_COMPONENT_NAME)
    assert gate is not None
    # A non-None component carrying six slugs is proof the committed artifact
    # loaded — the member's builder compiles it, so there is no unconfigured
    # state a caller could confuse with a set that admits nothing.
    assert len(gate.themes) == 6
    assert gate.covers(_LEGAL_THEME) and not gate.covers(_ILLEGAL_THEME)


def test_a_drifted_artifact_does_not_take_composition_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder's documented contract, held to behaviour rather than to its
    # own prose: the factory builds every registered component on every
    # ``create_app()`` call, so a builder that *raised* on a drifted artifact
    # would take composition down for every unrelated feature in the workspace.
    # Instead it fails **closed** — an empty set admits no theme — and a caller
    # that must know why asks `committed_legal_themes()` for the named
    # refusal, which is the same division `build_sandbox_isolation` draws.
    monkeypatch.setattr(
        member,
        "committed_legal_themes",
        lambda: (_ for _ in ()).throw(member.ThemeSetError("drifted artifact")),
    )
    gate = member.build_signal_theme_gate()
    assert len(gate.themes) == 0
    refusal = gate.admit(_LEGAL_THEME)
    assert refusal.admitted is False
    assert "names no themes at all" in refusal.detail
    # And the named refusal is still reachable — the builder swallowed it into
    # a value, it did not lose it.
    with pytest.raises(member.ThemeSetError):
        member.committed_legal_themes()


def test_the_theme_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads a committed
    # artifact shipped inside the package and no environment at all, so it
    # composes in any process.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.THEMES_COMPONENT_NAME].__name__ == (
        "build_signal_theme_gate"
    )
    assert list(
        inspect.signature(builders[member.THEMES_COMPONENT_NAME]).parameters
    ) == []


# -- Feature 213's component --------------------------------------------------


def test_the_member_registers_the_dead_territory_gate_under_its_own_name() -> None:
    # The registry is keyed by name, so this prefix is not cosmetic: a builder
    # that registered "signal-agent" a third time would *replace* feature
    # 205's law rather than sit beside it.  Asserted against the spec's plugin
    # namespace — the feature belongs to ``signal-agent`` — and against the
    # unprefixed name, which must not be what this component took, and against
    # the theme gate's name, which it must not collide with either.
    assert member.DEAD_TERRITORY_COMPONENT_NAME == "signal-agent-dead-territory"
    assert member.DEAD_TERRITORY_COMPONENT_NAME != member.COMPONENT_NAME
    assert member.DEAD_TERRITORY_COMPONENT_NAME != member.THEMES_COMPONENT_NAME


def test_building_the_dead_territory_gate_carries_the_committed_list() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = app.get(member.DEAD_TERRITORY_COMPONENT_NAME)
    assert gate is not None
    # A non-None component carrying PRD §9.4's three mechanisms is proof the
    # committed artifact loaded — the member's builder compiles it, so there is
    # no unconfigured state a caller could confuse with a denylist that refuses
    # nothing.
    assert len(gate.territory) == 3
    assert gate.covers(_DEAD_MECHANISM) and not gate.covers(_LIVE_MECHANISM)


def test_a_drifted_dead_territory_artifact_does_not_take_composition_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The builder's documented contract, held to behaviour rather than to its
    # own prose: the factory builds every registered component on every
    # ``create_app()`` call, so a builder that *raised* on a drifted artifact
    # would take composition down for every unrelated feature in the workspace.
    # Instead it fails **open** — an empty denylist refuses no theme — and a
    # caller that must know why asks `committed_dead_territory()` for the named
    # refusal, which is the same division `build_sandbox_isolation` draws.  This
    # is the one asymmetry with feature 212's builder, and it is load-bearing:
    # a down guardrail refuses fewer proposals than a system that refuses them
    # all, and the space (feature 212) still judges it.
    monkeypatch.setattr(
        member,
        "committed_dead_territory",
        lambda: (_ for _ in ()).throw(
            member.DeadTerritorySetError("drifted artifact")
        ),
    )
    gate = member.build_dead_territory_gate()
    assert len(gate.territory) == 0
    admission = gate.admit(_DEAD_MECHANISM)
    assert admission.admitted is True
    # And the named refusal is still reachable — the builder swallowed it into
    # a value, it did not lose it.
    with pytest.raises(member.DeadTerritorySetError):
        member.committed_dead_territory()


def test_the_dead_territory_builder_takes_no_arguments() -> None:
    # The factory's protocol: a zero-argument builder.  It reads a committed
    # artifact shipped inside the package and no environment at all, so it
    # composes in any process.
    from app.module_loader import scan_components

    builders = {
        component.name: component.builder
        for component in scan_components(MEMBER_SRC, registry=Registration())
    }
    assert builders[member.DEAD_TERRITORY_COMPONENT_NAME].__name__ == (
        "build_dead_territory_gate"
    )
    assert list(
        inspect.signature(builders[member.DEAD_TERRITORY_COMPONENT_NAME]).parameters
    ) == []


# -- The seats -----------------------------------------------------------------



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


def test_the_theme_seat_names_line_up() -> None:
    assert theme_seat.COMPONENT_NAME == member.THEMES_COMPONENT_NAME == (
        "signal-agent-themes"
    )


def test_the_theme_seat_answers_the_composed_gate() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = theme_seat.theme_gate_component(app)
    _assert_is_the_theme_law(gate)


def test_the_theme_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a theme.  This is the
    # distinction that matters most here: a *composed* gate that admits nothing
    # is a present component refusing every proposal, which is the opposite
    # complaint and a different repair.
    empty = Application(components={}, order=())
    assert theme_seat.theme_gate_component(empty) is None


def test_the_theme_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the authoring seat gets, for the same
    # reason: the app package must not depend on any workspace member at import
    # time, and the member's type must still be *present* under the guard or
    # the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(theme_seat))
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
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_theme_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's set, admission value or reasons.
    assert set(theme_seat.__all__) == {"COMPONENT_NAME", "theme_gate_component"}


def test_the_theme_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert theme_seat.__name__ == "app.modules.signal-agent.themes"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.themes")


# -- The dead-territory seat --------------------------------------------------


def test_the_dead_territory_seat_names_line_up() -> None:
    assert dead_seat.COMPONENT_NAME == member.DEAD_TERRITORY_COMPONENT_NAME == (
        "signal-agent-dead-territory"
    )


def test_the_dead_territory_seat_answers_the_composed_law() -> None:
    app = create_app(MEMBER_SRC, registry=Registration())
    gate = dead_seat.dead_territory_component(app)
    _assert_is_the_dead_territory_law(gate)


def test_the_dead_territory_seat_returns_none_when_nothing_is_registered() -> None:
    # An absent component is a discoverable state, not an exception — and it is
    # a statement about composition, never about a mechanism.  This is the
    # distinction that matters most here: a *composed* gate that refuses nothing
    # (an empty denylist, which fails open) is a present component admitting
    # every proposal, which is the opposite complaint and a different repair.
    empty = Application(components={}, order=())
    assert dead_seat.dead_territory_component(empty) is None


def test_the_dead_territory_seat_does_not_import_the_member_at_module_scope() -> None:
    # The same two-sided assertion the authoring and theme seats get, for the
    # same reason: the app package must not depend on any workspace member at
    # import time, and the member's type must still be *present* under the guard
    # or the typing the guard exists for was lost.
    import ast

    tree = ast.parse(inspect.getsource(dead_seat))
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
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    _collect(child.body, into)

    _collect(tree.body, live)

    assert not any(name.startswith("signal_agent") for name in live), live
    assert "signal_agent" in guarded, guarded


def test_the_dead_territory_seat_exports_only_the_component_accessor() -> None:
    # Asserted as an exact set: the failure this guards against is the seat
    # growing a re-export of the member's list, verdict value or reasons.
    assert set(dead_seat.__all__) == {"COMPONENT_NAME", "dead_territory_component"}


def test_the_dead_territory_seat_is_reachable_by_its_hyphenated_path() -> None:
    assert dead_seat.__name__ == "app.modules.signal-agent.dead_territory"
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.modules.signal_agent.dead_territory")
