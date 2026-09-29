"""Feature 245's component — how the replay path composes.

app_spec.xml, "Replay Engine", feature 245 carries ``plugin="replay"``, so the
member registers one component under that name and a caller reads it as
``create_app().get("replay")``.  These tests pin the composition, not the law —
the law is ``test_transition.py``'s:

* **the component is registered under its name and composed by the factory** —
  the ``@register`` seam the factory discovers, so ``create_app()`` carries a
  ``replay`` component among the components it composes;
* **the builder takes no arguments, returns the facade, and touches nothing** —
  the factory's protocol is ``builder() -> value``; this builder resolves no
  store, no tree and no file, which is the property that keeps the *pre-existing*
  resolution cycle (the policy-runtime tree builder reaching the artifact
  store, which composes the app again) from being widened into
  ``create_app()`` recursing.  A builder that resolved the tree would hang
  composition, so this is pinned rather than assumed;
* **the facade holds no state** — the composed value is a thing two callers can
  share without observing each other, and there is nothing about a deployment
  it could have been misconfigured with.

**Nothing here asserts ``isinstance`` against the member's own class.**  The
module loader imports each workspace member under a synthetic name
(``_nullius_scanned_<name>``) and re-executes it, so the ``ReplayEngine`` the
composed application carries is a *second* class object with the same name and
the same module path — an ``isinstance`` across that seam is False even though
nothing is wrong.  Every seam in this workspace duck-types for exactly this
reason; the checks below name the behaviour instead.
"""

from __future__ import annotations

import pytest
import replay
from conftest import StoredTree
from replay import (
    COMPONENT_NAME,
    ReplayEngine,
    build_replay_engine,
    recorded_child,
    replay_roots,
    replay_transition,
)


def _compose_with_tree(monkeypatch: pytest.MonkeyPatch, tree: object) -> None:
    """Make every ``create_app()`` answer ``tree`` as the ``policy-runtime`` component.

    ``resolve_tree`` imports ``create_app`` from :mod:`app.module_loader` at call
    time, so patching the loader's attribute substitutes the composed
    application it reads the tree from.
    """
    import app.module_loader as loader

    monkeypatch.setattr(
        loader,
        "create_app",
        lambda *roots, **kwargs: loader.Application(
            components={"policy-runtime": tree}, order=("policy-runtime",)
        ),
    )


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------


def test_builder_takes_no_arguments() -> None:
    # The factory's registration protocol is ``builder() -> value``: the
    # component is registered under a name and the factory calls it with no
    # arguments.  A builder that required one would not be a component the
    # factory could compose.
    assert build_replay_engine() is not None


def test_builder_returns_the_facade() -> None:
    # The composed value is the engine, whose one verb opens a transition.  Not
    # ``isinstance``: see the module docstring — the composed class object is a
    # second one.  The behaviour is what a caller depends on.
    engine = build_replay_engine()
    assert hasattr(engine, "transition")
    assert hasattr(engine, "over")
    assert hasattr(engine, "tree")


def test_builder_performs_no_io_and_resolves_no_tree() -> None:
    # The load-bearing property.  The campaign tree lives behind the
    # policy-runtime component, whose own resolution reaches the artifact
    # store, whose builder composes the application again — and since the factory
    # builds every registered component on every ``create_app()``, a builder
    # that resolved the tree here would walk that cycle from inside composition
    # and hang ``create_app()`` rather than return.  Pinned positively (the
    # builder returns, in reasonable time, with no store) and negatively (the
    # value it returns carries no tree): resolving is the caller's act.
    engine = build_replay_engine()
    assert engine is not None
    assert not hasattr(engine, "nodes")
    assert getattr(engine, "__slots__", None) == (), "the facade holds instance state"


def test_the_facade_holds_nothing() -> None:
    # No tree, no revealed set, no store: two callers sharing one composed
    # component cannot observe each other through it, and a replay's own state
    # is per-transition.  A facade with an attribute would be a second place the
    # walk's state could live, and the first one that could be stale.
    engine = ReplayEngine()
    assert not hasattr(engine, "__dict__")


def test_the_facade_opens_a_transition_over_a_handed_tree(
    stored_tree: StoredTree,
) -> None:
    # What the facade *is* for: a caller holding the composed component and a
    # tree (from its own walk, or from ``engine.tree()``) opens a transition
    # without importing the member's free functions.
    transition = ReplayEngine().transition(stored_tree)
    assert transition.prefix() == ("r-event", "r-mom")
    assert transition.transition("r-mom") == "m1"


def test_the_facade_reads_no_replay_law_of_its_own(
    stored_tree: StoredTree,
) -> None:
    # The facade is a spelling of the member's free function, not a second
    # implementation: a caller reaching the component and a caller reaching
    # ``replay_transition`` get the same walk, and there is one place feature
    # 245's refusal lives.
    engine = ReplayEngine()
    handed = engine.transition(stored_tree, ["m1"])
    direct = replay_transition(stored_tree, ["m1"])
    assert handed.prefix() == direct.prefix() == ("m1",)


def test_the_facade_refuses_what_the_transition_refuses(
    stored_tree: StoredTree,
) -> None:
    # The refusal is reachable through the composed component too — the callable
    # shape a runtime would go through — and the tree-handing verb is the same
    # verb, so a caller cannot reach a generatable spelling by holding the
    # component instead of the module.
    from replay import ChildGenerationRefused

    transition = ReplayEngine().transition(stored_tree)
    with pytest.raises(ChildGenerationRefused):
        transition.transition("r-mom", generator=lambda workspace: "m1")


# -- the deployment's own tree, resolved at call time ------------------------


def test_the_facade_refuses_by_name_when_the_deployment_holds_no_campaign() -> None:
    # The refusal `resolve_tree` exists for, and the *reason* resolution is at
    # call time rather than in the builder: this environment names no committed
    # campaign, so a caller asking for the deployment's tree is refused by name
    # rather than handed ``None``.  A builder that resolved here would instead
    # have walked the policy-runtime -> artifact-store -> ``create_app``
    # cycle from inside composition and hung the factory.
    from replay import ReplayTreeError

    with pytest.raises(ReplayTreeError) as raised:
        ReplayEngine().tree()
    message = str(raised.value)
    assert "no campaign tree is composed" in message
    assert "feature 245" in message


def test_over_refuses_by_name_too(stored_tree: StoredTree) -> None:
    # `over()` is the composed spelling of "replay the campaign this process is
    # pointed at", so with no campaign it is the same refusal rather than a
    # second, differently-shaped failure.  The two verbs differ only in what
    # they do *after* a tree resolves.
    from replay import ReplayTreeError

    with pytest.raises(ReplayTreeError):
        ReplayEngine().over()


def test_resolution_reads_the_composed_policy_runtime_component(
    stored_tree: StoredTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `resolve_tree` reads the component named in the spec's own plugin table —
    # ``policy-runtime`` — from the composed application.  Pinned by
    # substituting the composition: whatever the application answers under
    # that name is what a caller gets, which is what makes the two members
    # agree about which campaign is the deployment's.
    from replay import resolve_tree

    _compose_with_tree(monkeypatch, stored_tree)
    assert resolve_tree() is stored_tree


def test_a_resolved_tree_is_walked_at_its_roots(
    stored_tree: StoredTree, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The composed path end to end: a deployment whose composed application
    # answers a tree gets a transition opened at that tree's *roots* —
    # §10.1's `revealed = {tree.root}` — so `over()` is one verb from "the
    # deployment's campaign" to "a walk standing at its beginning", with no
    # separate seed for a caller to spell wrongly.
    _compose_with_tree(monkeypatch, stored_tree)

    transition = ReplayEngine().over()
    assert transition.prefix() == ("r-event", "r-mom")
    assert transition.transition("r-mom") == "m1"


def test_the_facade_repr_names_itself() -> None:
    # A debugging aid on a stateless value; it reads nothing, so it cannot fail
    # while an operator is looking at something else that did.
    assert repr(ReplayEngine()) == "ReplayEngine()"


# ---------------------------------------------------------------------------
# Registration and composition
# ---------------------------------------------------------------------------


def test_component_name_is_the_plugin_name() -> None:
    # app_spec.xml feature 245 carries ``plugin="replay"``, and the component
    # key and the spec are one spelling — so a later feature cannot register under a name
    # the spec does not know, and the app cannot look up a component nothing
    # composed.
    assert COMPONENT_NAME == "replay"


def test_the_builder_is_the_registered_component() -> None:
    # The component the factory composes under ``replay`` and the builder a
    # script calls are one *contribution* — registered exactly once, under the
    # plugin name, building the facade.
    #
    # Deliberately not `is build_replay_engine`, and the reason is the rule this
    # suite's docstring states: once ``create_app()`` has scanned the member,
    # the registration in the process registry is the one the loader made by
    # importing the member under its synthetic name
    # (``_nullius_scanned_replay``), so it is a *second* function object with
    # the same source — `is` against the canonical import is False and always
    # will be.  Measured: before a scan the registry holds the canonical
    # builder, after one it holds the synthetic copy, and the count stays 1
    # (the later registration replaces, which is the loader's documented
    # "silently wins" behaviour rather than a duplicate).
    #
    # Invoked rather than compared, so this pins what a caller depends on: that
    # the registry's builder is this member's builder, whatever module object it
    # was defined in.
    from app.module_loader import registered_components

    registered = {c.name: c for c in registered_components()}
    assert COMPONENT_NAME in registered
    assert registered[COMPONENT_NAME].builder.__name__ == "build_replay_engine"
    assert callable(registered[COMPONENT_NAME].builder)
    # And it builds the facade — the property the identity check was reaching
    # for, asserted directly.
    assert hasattr(registered[COMPONENT_NAME].builder(), "transition")


def test_the_member_registers_one_component_however_it_is_imported() -> None:
    # Whether the member is reached by its canonical name (``import replay``) or
    # by the loader's synthetic one, one component lands under ``replay`` — the
    # plugin name cannot accumulate duplicates, which would let a later import
    # silently win over an earlier feature's registration.
    from app.module_loader import create_app, registered_components

    create_app()
    assert sum(1 for c in registered_components() if c.name == COMPONENT_NAME) == 1


def test_component_is_registered_under_its_name() -> None:
    # The ``@register`` seam the factory discovers: ``create_app()`` composes a
    # ``replay`` component among the components it carries, so a deployment gets
    # the replay path by being scanned — no central registry was edited and no
    # entry-points table names this member.
    from app.module_loader import create_app

    app = create_app()
    assert COMPONENT_NAME in app.components


def test_composition_carries_the_replay_component() -> None:
    # And the composed value is the member's facade, reached by name.  The
    # factory's own ordering is name-sorted, so the component simply appears
    # among its siblings; nothing about the replay path is order-sensitive
    # (feature 245 holds no state another component could be built against).
    from app.module_loader import create_app

    app = create_app()
    assert COMPONENT_NAME in app.order
    assert app.get(COMPONENT_NAME) is not None


# ---------------------------------------------------------------------------
# Plugin wiring — placement is the risky part of a plugin-shaped feature
# ---------------------------------------------------------------------------


def test_member_is_declared_in_the_scanned_workspace() -> None:
    # The member's own pyproject.toml is what makes it a workspace member and
    # therefore scannable — the registration chain starts here.  A member that
    # forgot it passes its own suite (imported by path) and contributes nothing
    # to any deployment, which is exactly the failure these tests exist for.
    from pathlib import Path

    from app.module_loader import workspace_scan_roots

    member_src = Path(replay.__file__).resolve().parent.parent
    assert (member_src.parent / "pyproject.toml").is_file()
    assert member_src in workspace_scan_roots()


def test_scan_of_the_member_registers_exactly_one_component() -> None:
    # A fresh registry, not the process default: any earlier test that called a
    # bare ``create_app()`` has already imported every workspace member, so
    # reading the default back would assert accumulated process state rather
    # than this member's contribution.  The question is exactly *what does this
    # member register?* — and the answer is one component, under the plugin's
    # own name, because a second registration under one name lets the later
    # import silently win.
    from pathlib import Path

    from app.module_loader import Registration, scan_components

    member_src = Path(replay.__file__).resolve().parent.parent
    components = scan_components(member_src, registry=Registration())
    assert [component.name for component in components] == [COMPONENT_NAME]


def test_composed_app_carries_the_replay_path_and_its_siblings() -> None:
    # The whole chain, composed from an isolated registry so the assertion is
    # about this member's scan: registered, built, in ``order``, and reachable
    # by name.  The component is duck-checked (see the module docstring) and the
    # ordering is the factory's name-sorted one, which nothing here depends on.
    from pathlib import Path

    from app.module_loader import Application, Registration, create_app

    member_src = Path(replay.__file__).resolve().parent.parent
    app = create_app(member_src, registry=Registration())
    assert isinstance(app, Application)
    assert COMPONENT_NAME in app.order
    assert app.get(COMPONENT_NAME) is not None


# ---------------------------------------------------------------------------
# The composed campaign tree — the real cross-member seam
# ---------------------------------------------------------------------------


def test_the_transition_walks_the_members_real_campaign_tree() -> None:
    # The one place the real cross-member tree is exercised: this member never
    # imports the policy-runtime member (a member never imports another member),
    # so every other test in this suite walks the fixture shape.  Here the
    # canonical ``CampaignTree`` is reached the way a deployment reaches it —
    # through the member's public constructor — and walked end to end, which is
    # what proves the duck-typed seam matches the document it was copied from:
    # ``nodes``, ``node_id``, ``parent_id`` and the ``node()`` address verb all
    # read the way this module assumes.
    policy_runtime = pytest.importorskip("policy_runtime")
    tree = policy_runtime.CampaignTree.freeze(
        {
            "r-mom": (None, 0, {"depth": 0, "r2_insample": None}),
            "m1": ("r-mom", 1, {"parent_id": "r-mom", "depth": 1, "r2_insample": 0.20}),
            "r-event": (None, 0, {"depth": 0, "r2_insample": None}),
        }
    )
    transition = replay_transition(tree)
    assert transition.prefix() == ("r-event", "r-mom")
    assert transition.transition("r-mom") == "m1"
    assert transition.transition("m1") is None
    assert transition.transition("r-event") is None
    assert transition.prefix() == ("m1", "r-event", "r-mom")


def test_the_real_trees_address_refusal_reaches_this_members_vocabulary() -> None:
    # The campaign tree refuses an unknown node with its own error class
    # (``policy_runtime.PolicyAddressError``), and a caller catching *this*
    # member's base class must still catch a position the replay cannot stand
    # at: the seam translates whatever the tree raises into
    # ``ReplayTreeError`` rather than letting a sibling's class escape.  This is
    # the error-vocabulary rule the two members' suites both state, pinned here
    # against the document that actually raises.
    policy_runtime = pytest.importorskip("policy_runtime")
    from replay import ReplayTreeError

    tree = policy_runtime.CampaignTree.freeze(
        {"r-mom": (None, 0, {"depth": 0}), "m1": ("r-mom", 1, {"depth": 1})}
    )
    transition = replay_transition(tree)
    with pytest.raises(ReplayTreeError) as raised:
        transition.transition("never-recorded")
    assert "never-recorded" in str(raised.value)


def test_the_real_trees_node_model_is_the_duck_typed_one() -> None:
    # The restatement kept honest: the campaign node's four fields are the ones
    # this module reads and no others, so a node model that renamed ``parent_id``
    # would fail here rather than silently walking a tree whose edges it could
    # not see (which would answer every node as a root — a replay that walked
    # nowhere while reporting progress).
    policy_runtime = pytest.importorskip("policy_runtime")
    tree = policy_runtime.CampaignTree.freeze(
        {"r-mom": (None, 0, {"depth": 0}), "m1": ("r-mom", 1, {"depth": 1})}
    )
    node = tree.node("m1")
    assert node.node_id == "m1"
    assert node.parent_id == "r-mom"
    assert replay_roots(tree) == ("r-mom",)
    assert recorded_child(tree, "r-mom") == "m1"
