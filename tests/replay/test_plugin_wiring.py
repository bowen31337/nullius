"""Feature 245 in the assembled system — the plugin, the seat, and the real tree.

app_spec.xml, "Replay Engine", feature 245: *System rejects any attempt to
generate a new child during replay, because a stored tree reveals only recorded
children.*  The member's own suite pins the law; this suite pins the **wiring
and the seam**, which is what a member's suite structurally cannot do:

* **the plugin is discovered** — the root ``pyproject.toml``'s ``packages/*``
  workspace resolves to this member, and scanning it registers the component
  under the spec's plugin name.  A component that is never scanned passes its
  own suite and contributes nothing to any deployment, which is exactly the
  failure placement invites;
* **the factory composes it** — ``create_app()`` over the declared workspace
  carries ``replay`` in ``order`` and in ``components``, so a deployment gets
  the replay path by being scanned: no central registry was edited and no
  entry-points table names this member;
* **the app seat fronts it** — ``app.modules.replay.replay_component(app)``
  answers ``app.get("replay")``, the one place a feature in this category asks
  the composed application for the replay path;
* **the duck-typed seam matches the document** — the transition is walked over
  the *real* ``policy_runtime.CampaignTree`` the deployment holds, which is the
  only test in the workspace where this member's restatement of the node model
  is checked against the class that actually carries it.

**Nothing here asserts ``isinstance`` or ``pytest.raises`` across the
composition seam.**  The module loader imports each member under a synthetic
name (``_nullius_scanned_<name>``) and re-executes it, so the ``ReplayEngine``
``create_app()`` hands out — and the ``ChildGenerationRefused`` its transition
raises — are *second* class objects with the same names and the same source.
They are not the ones ``import replay`` yields, so an ``isinstance`` or a
``pytest.raises(<canonical class>)`` against the composed value is False even
though nothing is wrong.  The checks below name the behaviour and compare
``type(exc).__name__``, the same answer ``tests/nulloracle/conftest.py`` and
``tests/feature-store/test_registration.py`` give for the same wrinkle.

The composed tree is read from a *frozen mapping*, not from the artifact
store: this environment names no campaign, and the question here is the seam
between two members, not the store's.  Feature 249's scoring and 255's
persistence are where a deployment's own tree enters.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import replay

from app.module_loader import (
    Registration,
    create_app,
    scan_components,
    workspace_members,
    workspace_scan_roots,
)

seat = importlib.import_module("app.modules.replay")

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_SRC = REPO_ROOT / "packages" / "replay" / "src"


@pytest.fixture(scope="module")
def app():
    """The composed application, built once — ``create_app()`` scans every member.

    Module-scoped because composition is a deployment-wide act, not a
    per-assertion one: the object it returns is read-only by convention, so
    sharing it across this suite's tests observes nothing either of them
    mutates.  Rebuilding it per test would also rebuild every other member's
    component, which is not what any assertion here is about.
    """
    return create_app()


@pytest.fixture
def campaign_tree():
    """The real campaign tree a deployment would hold — two themes, one branch.

    Built through the policy-runtime member's *public* constructor
    (``CampaignTree.freeze``, the seam feature 217 ships), never by hand-rolling
    a node model here: the point of the walk below is that this member's
    duck-typed restatement matches the class that actually carries it, which a
    hand-rolled fixture would prove nothing about.
    """
    policy_runtime = pytest.importorskip("policy_runtime")
    return policy_runtime.CampaignTree.freeze(
        {
            "r-mom": (None, 0, {"depth": 0, "r2_insample": None}),
            "m1": ("r-mom", 1, {"parent_id": "r-mom", "depth": 1, "r2_insample": 0.20}),
            "m1x": ("m1", 2, {"parent_id": "m1", "depth": 2, "r2_insample": 0.51}),
            "r-event": (None, 0, {"depth": 0, "r2_insample": None}),
        }
    )


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_replay_is_a_declared_workspace_member() -> None:
    # The root pyproject.toml declares ``members = ["packages/*"]``; this member
    # must satisfy uv's rule that a member directory carries a pyproject.toml.
    # A member that forgot it is not scanned, so no deployment ever carries the
    # replay path — the whole chain these tests pin starts here.
    members = {member.name for member in workspace_members()}
    assert "replay" in members
    assert (REPLAY_SRC.parent / "pyproject.toml").is_file()


def test_member_uses_a_scan_root_that_resolves_to_the_package() -> None:
    # The loader treats a member's ``src/`` as a *package-parent*: its immediate
    # children are the importable packages.  ``replay`` must be one of them,
    # which is why the package lives at ``src/replay/`` and not
    # ``src/nullius/replay/``.
    assert REPLAY_SRC in workspace_scan_roots()
    assert (REPLAY_SRC / "replay" / "__init__.py").is_file()


def test_scanning_the_member_registers_exactly_one_component() -> None:
    # A fresh registry, not the process default: composing the app above has
    # already imported every workspace member into the default one, so reading
    # it back would assert accumulated process state rather than this member's
    # contribution.  The question is exactly *what does this member register?* —
    # and the answer is one component, under the plugin name the spec states.
    components = scan_components(REPLAY_SRC, registry=Registration())
    assert [component.name for component in components] == ["replay"]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_the_declared_workspace_composes_the_replay_path(app) -> None:
    # The whole chain, over the workspace the root pyproject declares: the scan
    # imports the member, its ``@register`` fires, and ``create_app()`` carries
    # the component.  The factory's order is name-sorted; nothing in this member
    # is order-sensitive (it holds no state another component is built against).
    assert "replay" in app.components
    assert "replay" in app.order


def test_the_composed_component_is_the_members_facade(app) -> None:
    # Duck-checked, not ``isinstance``: the scan imports the member under a
    # synthetic module name, so the class object here is a second one with the
    # same source.  What a caller depends on is the behaviour — the three verbs
    # the replay path reaches it through.
    component = app.get("replay")
    assert component is not None
    for verb in ("transition", "over", "tree"):
        assert callable(getattr(component, verb)), verb


def test_composition_is_not_widened_by_this_member(app) -> None:
    # The component is stateless and its builder resolves nothing, which is what
    # keeps the pre-existing resolution cycle (the policy-runtime tree builder
    # reaching the artifact store's seat, which composes the app again) from
    # being walked from inside composition.  If this member's builder had
    # resolved a tree, this test would not *fail* — it would hang, since the
    # factory builds every registered component on every ``create_app()``.
    # Reaching here at all is half the assertion; the other half is that the
    # composed value carries no deployment state.
    component = app.get("replay")
    assert not hasattr(component, "__dict__"), "the facade must hold no instance state"
    assert getattr(component, "__slots__", None) == ()


def test_the_app_seat_answers_the_component_name(app) -> None:
    # The seat's single question — *what is the composed replay component?* —
    # answered over the application the factory composed, so a feature in this
    # category (246's and 247's dependency refusals, 248's round loop, 251's
    # resident-array reads) can ask the app namespace without importing the
    # member.  The seat decides nothing about a replay itself.
    assert seat.replay_component(app) is app.get(seat.COMPONENT_NAME)
    assert seat.COMPONENT_NAME == "replay"


def test_the_seats_constant_is_the_members_constant() -> None:
    # One name, two spellings — the app namespace's and the member's — so the
    # seat and the plugin cannot drift apart about what the component is called.
    assert seat.COMPONENT_NAME == replay.COMPONENT_NAME


# ---------------------------------------------------------------------------
# The walk over the real tree
# ---------------------------------------------------------------------------


def test_the_composed_component_walks_the_real_campaign_tree(
    app, campaign_tree
) -> None:
    # The one place this member's restatement of the node model meets the class
    # that actually carries it.  The tree is the policy-runtime member's own —
    # ``nodes``, ``node_id``, ``parent_id`` and the ``node()`` address verb —
    # and the composed component walks it, which proves the duck-typed seam
    # reads the document it was copied from rather than a shape the fixture
    # suite invented.
    component = app.get("replay")
    transition = component.transition(campaign_tree)
    assert transition.prefix() == ("r-event", "r-mom")
    assert transition.transition("r-mom") == "m1"
    assert transition.transition("m1") == "m1x"
    assert transition.transition("m1x") is None  # a leaf, §10.1's `if child:`
    assert transition.transition("r-event") is None  # an unexpanded root
    assert transition.prefix() == ("m1", "m1x", "r-event", "r-mom")


def test_the_walk_reaches_only_nodes_the_tree_recorded(app, campaign_tree) -> None:
    # Feature 245's load-bearing negative, over the real tree: every node a
    # replay can put in its prefix is one the stored tree holds, because the
    # only way into the prefix is a recorded edge.  A generated child would
    # appear here as a node the tree does not hold — which is why the refusal,
    # not this assertion, is what makes the claim true for a caller that tries.
    component = app.get("replay")
    transition = component.transition(campaign_tree)
    known = {node.node_id for node in campaign_tree.nodes}
    for selected in ("r-mom", "m1", "m1x", "r-event"):
        transition.transition(selected)
    assert set(transition.prefix()) <= known


def test_the_generation_attempt_is_refused_through_the_composed_component(
    app, campaign_tree
) -> None:
    # Feature 245's sentence, reached the way a runtime reaches it — through the
    # composed component, not the member's free functions — so a driver cannot
    # find a generatable spelling by holding the application instead of the
    # module.  The class is compared *by name*: the composed component's
    # transition was defined in a synthetic module, so its
    # ``ChildGenerationRefused`` is not the one ``import replay`` yields.
    component = app.get("replay")
    transition = component.transition(campaign_tree)
    calls: list[object] = []

    def generator(workspace: object) -> str:
        calls.append(workspace)
        return "invented"

    with pytest.raises(Exception) as raised:
        transition.transition("r-mom", generator=generator)
    assert type(raised.value).__name__ == "ChildGenerationRefused"
    assert calls == [], "the generator ran before the refusal"
    # And nothing was revealed: the refusal fired before the tree was read, so
    # the prefix is exactly the seed.
    assert transition.prefix() == ("r-event", "r-mom")


def test_the_real_trees_refusals_arrive_in_the_members_vocabulary(
    app, campaign_tree
) -> None:
    # The campaign tree refuses a node it does not hold with its own class
    # (``policy_runtime.PolicyAddressError``); a caller catching feature 245's
    # base class must still catch a position the replay cannot stand at, so the
    # seam translates it.  The message names the node, which is what an operator
    # reading a broken walk needs.
    component = app.get("replay")
    transition = component.transition(campaign_tree)
    with pytest.raises(Exception) as raised:
        transition.transition("never-recorded")
    assert type(raised.value).__name__ == "ReplayTreeError"
    assert "never-recorded" in str(raised.value)


def test_a_replay_over_the_real_tree_is_deterministic(app, campaign_tree) -> None:
    # §12's determinism contract (cq-15) over the real tree: two replays of one
    # policy on one stored tree produce one answer.  Here the "policy" is a
    # fixed selection order, which is the half of the loop this member owns —
    # the transition is a function of the tree and the selected nodes, never of
    # the order they were selected in or of anything outside the bytes.
    component = app.get("replay")
    left = component.transition(campaign_tree)
    right = component.transition(campaign_tree)
    for selected in ("r-mom", "m1"):
        left.transition(selected)
    for selected in ("m1", "r-mom"):
        right.transition(selected)
    assert left.prefix() == right.prefix() == ("m1", "m1x", "r-event", "r-mom")


def test_two_replays_do_not_share_a_prefix(app, campaign_tree) -> None:
    # The transition is the *episode's* object, not the deployment's: a second
    # replay opens its own prefix at the roots.  A shared prefix would make two
    # replays in one process observe each other, and the second would be scored
    # against a walk it did not take.
    component = app.get("replay")
    first = component.transition(campaign_tree)
    first.transition("r-mom")
    second = component.transition(campaign_tree)
    assert second.prefix() == ("r-event", "r-mom")
    assert "m1" not in second
