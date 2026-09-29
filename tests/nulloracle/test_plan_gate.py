"""Feature 122, end to end: the assembled system refuses a mixed campaign plan.

app_spec.xml, "Null Oracle & Planted Nulls", feature 122: *System rejects a
campaign plan that mixes Type-R and Type-D assignment within one tree, which
emits a heterogeneous_world error message.*

The member's own suite (``packages/nulloracle/tests``) pins each contract in
isolation — the plan as a value, the three shapes of the mix, the review, the
sidecar states, the component.  This suite pins the sentence those
contracts are *for*, through the assembled system: the planning gate composed
by the application factory, read through ``create_app().get``,
reading a campaign's declaration and its tree's flip depths from the
relational store the root conftest supplies and its root selections from
§7.1's sealed sidecar.

The integration questions, and why each is sharper here than in the member's
suite:

* **does the composed system carry the gate at all** — and, like feature
  118's selection, it needs *both* halves composed (the database and the
  sidecar), because a gate holding only the database could read the tree's
  flips but not the sidecar's selections and would answer ``homogeneous``
  for worlds it never looked at;
* **does the refusal arrive through the assembled write path that can
  actually produce a mixed world today** — a flip depth drawn onto a Type-R
  campaign by feature 119's composed writer, which confirms the campaign
  exists but not its type; that is not a synthetic state assembled by SQL,
  it is the one reachable mix, caught by the gate the writers answer to;
* **does the homogeneous world review cleanly both ways** — a Type-R
  campaign whose selection feature 118's composed writer sealed, and a
  Type-D campaign whose flips feature 119's composed writer drew — so the
  gate is shown refusing the mix and not merely refusing;
* **and do the refusals that are *not* the mix stay the store's** — a
  missing campaign row, an unknown regime, a corrupt depth — because a
  planner that caught the store's error where the design's belonged would
  retry a heterogeneous world as a database hiccup and plant exactly the
  tree §7.3 forbids.

Errors are asserted on the raised type's *name*, the convention this
suite's conftest documents: the composed gate's classes are the scanned
copies, structurally identical to a direct import's but not the same
objects, so ``pytest.raises(<canonical class>)`` cannot match them.
"""

from __future__ import annotations

import uuid

import pytest
from nulloracle import (
    DATABASE_URL_ENV,
    FLIP_DEPTH_COMPONENT_NAME,
    HETEROGENEOUS_WORLD,
    NODE_TABLE,
    PLAN_COMPONENT_NAME,
    TYPE_R_COMPONENT_NAME,
)

from app.module_loader import create_app

CAMPAIGN_TABLE = "campaign"

#: The 32-byte test key, the same constant this suite's conftest configures
#: ``key_ref`` with.  Restated here rather than imported from the conftest,
#: the way the member's suites each restate it: "the right key opened it" is
#: an assertion that the same bytes were used twice, and the bytes this file
#: uses should be visible in this file.
TEST_KEY_HEX = "0f" * 32

#: §7.3's Type-R fraction and well count, as a campaign is planned with them.
NULL_FRACTION = 0.1667
WORKSPACE_COUNT = 12


def campaign_row(**overrides) -> tuple:
    """A campaign's planning-time columns, as the migration spells them.

    The three ``NOT NULL`` columns with no default — the type, ``W`` and
    ``φ`` — in the shape ``0111_campaign_table.py`` describes a campaign as
    being planned with.  A campaign is written by its planner *before any
    node is expanded*, which is why this suite inserts the row itself rather
    than expecting the gate to: the gate reviews campaigns, it does not
    invent them.
    """
    fields = {
        "campaign_type": "Type-R",
        "workspace_count": WORKSPACE_COUNT,
        "null_fraction": NULL_FRACTION,
    }
    fields.update(overrides)
    return tuple(fields.values())


@pytest.fixture
def composed_app(sidecar_path, key_ref: str):
    """The application the factory composes for a two-halves deployment.

    Both fixtures are requested *before* the composition, because the gate's
    builder resolves both halves at ``create_app()`` time: the root conftest
    points the database at a per-test SQLite file, and this suite's fixtures
    point the sidecar into the test's temporary directory.  The application
    is returned rather than just the gate because the mixed-world tests need
    the *writers* too — feature 118's selection and feature 119's flip
    depth — from the same scanned copy, which is exactly the pairing an
    assembled campaign loop holds.
    """
    return create_app()


@pytest.fixture
def composed_gate(composed_app):
    """The planning gate the composed application carries."""
    return composed_app.get(PLAN_COMPONENT_NAME)


@pytest.fixture
def planned_campaign(composed_gate) -> str:
    """A campaign the orchestrator has planned, and its id.

    Inserted through the gate's own connection so the row lands in the same
    database the gate reads — one table, the orchestrator's, with this
    feature filling no column of it.
    """
    identifier = str(uuid.uuid4())
    with composed_gate._connect() as connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
            "null_fraction) VALUES (?, ?, ?, ?)",
            (identifier, *campaign_row()),
        )
    return identifier


def plant_roots(store, campaign: str, count: int = WORKSPACE_COUNT) -> list[str]:
    """Insert a campaign's root nodes — the wells a Type-R selection lands on.

    ``parent_id`` left ``NULL``, which is what makes each row a root; the
    same edge ``0118_node_table.py`` describes.
    """
    roots = [str(uuid.uuid4()) for _ in range(count)]
    with store._connect() as connection:
        for root in roots:
            connection.execute(
                f"INSERT INTO {NODE_TABLE} (id, campaign_id, theme_root, depth) "
                "VALUES (?, ?, 'macro', 0)",
                (root, campaign),
            )
    return roots


# -- The composed gate ----------------------------------------------------------


class TestTheGateComposes:
    def test_a_two_halves_deployment_carries_the_gate(self, composed_gate) -> None:
        # Not None, and the right store: the claim under test is about the
        # assembled system, so the gate is read out of the application the
        # factory built rather than constructed directly.
        assert composed_gate is not None
        assert type(composed_gate).__name__ == "CampaignPlanGate"

    def test_the_application_hands_back_the_composed_gate(
        self, composed_app, composed_gate
    ) -> None:
        # Reading the application by the component's name reaches the same
        # object the factory composed.
        assert composed_app.get(PLAN_COMPONENT_NAME) is composed_gate

    def test_a_database_with_no_sidecar_composes_no_gate(self) -> None:
        # The root conftest names a database; this deployment names no
        # sidecar.  Half a configuration is not a configuration, and for
        # this gate the missing half is the dangerous one: a gate that could
        # not read the sidecar would bless every mixed world as homogeneous.
        app = create_app()
        assert app.get(PLAN_COMPONENT_NAME) is None

    def test_no_database_composes_no_gate(
        self, sidecar_path, key_ref: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert create_app().get(PLAN_COMPONENT_NAME) is None


# -- The sentence, through the assembled write path ------------------------------


class TestTheMixedWorldIsRefused:
    def test_a_flip_drawn_onto_a_type_r_campaign_is_refused(
        self, composed_app, composed_gate, planned_campaign, sidecar_path
    ) -> None:
        # The reachable mix, end to end: feature 118's composed writer seals
        # the campaign's root selection into §7.1's file, feature 119's
        # composed writer — which confirms the campaign exists but not its
        # type — draws a flip depth onto one of its roots, and the composed
        # gate pronounces the refusal on the world the two jointly made.
        roots = plant_roots(composed_gate, planned_campaign)
        composed_app.get(TYPE_R_COMPONENT_NAME).persist(planned_campaign)
        composed_app.get(FLIP_DEPTH_COMPONENT_NAME).persist(roots[0], 0.4)
        assert sidecar_path.is_file()

        with pytest.raises(Exception) as raised:
            composed_gate.review(planned_campaign)
        assert type(raised.value).__name__ == "HeterogeneousWorldError"
        message = str(raised.value)
        assert message.startswith(HETEROGENEOUS_WORLD)
        assert planned_campaign in message
        assert roots[0] in message

    def test_a_flip_under_a_type_r_declaration_is_refused_before_any_sidecar_exists(
        self, composed_app, composed_gate, planned_campaign
    ) -> None:
        # The same hazard one step earlier: no selection was ever sealed —
        # the sidecar file has never existed — and the flip alone under the
        # 'Type-R' declaration is the mix.  A gate that waited for both
        # halves to be present would wave this world through.
        roots = plant_roots(composed_gate, planned_campaign)
        composed_app.get(FLIP_DEPTH_COMPONENT_NAME).persist(roots[3], 0.4)

        with pytest.raises(Exception) as raised:
            composed_gate.review(planned_campaign)
        assert type(raised.value).__name__ == "HeterogeneousWorldError"
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert roots[3] in str(raised.value)

    def test_a_selection_under_a_type_d_declaration_is_refused(
        self, composed_app, composed_gate, sidecar_path, key_ref: str
    ) -> None:
        # The mirror mix: a Type-D campaign whose roots appear in §7.1's
        # file.  Feature 118's writer refuses a Type-D campaign by name, so
        # the state arises the way it does in a real deployment — a loop
        # sealing entries against the wrong campaign — and the entries are
        # sealed with the deployment's own key, read back by the composed
        # gate through the same file.
        from nulloracle import NullAssignment, NullSidecar, SidecarKey

        campaign = str(uuid.uuid4())
        with composed_gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (campaign, *campaign_row(campaign_type="Type-D")),
            )
        roots = plant_roots(composed_gate, campaign)
        NullSidecar(sidecar_path, SidecarKey.from_hex(TEST_KEY_HEX)).write(
            {root: NullAssignment(node_id=root, is_null=True, perm_seed=1)
             for root in roots}
        )

        with pytest.raises(Exception) as raised:
            composed_gate.review(campaign)
        assert type(raised.value).__name__ == "HeterogeneousWorldError"
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)


# -- The homogeneous worlds review cleanly ----------------------------------------


class TestTheHomogeneousWorldsReview:
    def test_a_planted_type_r_world_reviews_to_its_plan(
        self, composed_app, composed_gate, planned_campaign
    ) -> None:
        # The lawful Type-R world through the assembled writers: the
        # selection sealed, the tree carrying no flip, and the review
        # returning the plan as a value rather than a refusal.
        plant_roots(composed_gate, planned_campaign)
        selection = composed_app.get(TYPE_R_COMPONENT_NAME).persist(planned_campaign)
        plan = composed_gate.review(planned_campaign)
        assert plan.campaign_type == "Type-R"
        assert len(plan.root_selections) == WORKSPACE_COUNT
        assert set(plan.root_selections) >= set(selection.null_roots)
        assert plan.flip_branches == ()

    def test_a_planted_type_d_world_reviews_to_its_plan(
        self, composed_app, composed_gate
    ) -> None:
        # The lawful Type-D world: all roots real, flips drawn onto two
        # branches by feature 119's composed writer, no entry anywhere in
        # §7.1's file for this campaign's nodes.
        campaign = str(uuid.uuid4())
        with composed_gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (campaign, *campaign_row(campaign_type="Type-D")),
            )
        roots = plant_roots(composed_gate, campaign)
        flips = composed_app.get(FLIP_DEPTH_COMPONENT_NAME)
        flips.persist(roots[0], 0.4)
        flips.persist(roots[1], 0.4)
        plan = composed_gate.review(campaign)
        assert plan.campaign_type == "Type-D"
        assert plan.root_selections == ()
        assert set(plan.flip_branches) == {roots[0], roots[1]}

    def test_an_unplanted_campaign_is_not_a_mix(
        self, composed_gate, planned_campaign
    ) -> None:
        # The gate refuses mixing, not emptiness: a campaign nothing has
        # landed on yet is the honest shape of a world between planning and
        # planting — "has this been drawn?" is the writers' question.
        plant_roots(composed_gate, planned_campaign)
        plan = composed_gate.review(planned_campaign)
        assert plan.unplanted is True


# -- The refusals that are not the mix ---------------------------------------------


class TestTheStoresRefusalsStayTheStores:
    def test_a_campaign_the_table_does_not_hold(
        self, composed_gate
    ) -> None:
        # The plan is a fact about a campaign, and a gate that invented the
        # row would be inventing the declaration it exists to check.
        with pytest.raises(Exception) as raised:
            composed_gate.review(str(uuid.uuid4()))
        assert type(raised.value).__name__ == "KsGuardError"
        assert "no row" in str(raised.value)

    def test_a_regime_the_spec_does_not_have(self, composed_gate) -> None:
        # 'Type-X' is not a mix — it is a declaration §7.3 does not have,
        # and logging it under the mix's code would send an operator
        # hunting a second assignment that does not exist.
        campaign = str(uuid.uuid4())
        with composed_gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (campaign, *campaign_row(campaign_type="Type-X")),
            )
        with pytest.raises(Exception) as raised:
            composed_gate.review(campaign)
        assert type(raised.value).__name__ == "KsGuardError"
        assert type(raised.value).__name__ != "HeterogeneousWorldError"
        assert "Type-R" in str(raised.value) and "Type-D" in str(raised.value)

    def test_a_corrupt_flip_depth_is_refused_with_the_node_named(
        self, composed_gate
    ) -> None:
        # A geometric's support cannot produce 0; the row is corrupt, and is
        # refused as a store failure naming the node rather than counted as
        # a flipped branch.
        campaign = str(uuid.uuid4())
        with composed_gate._connect() as connection:
            connection.execute(
                f"INSERT INTO {CAMPAIGN_TABLE} (id, campaign_type, workspace_count, "
                "null_fraction) VALUES (?, ?, ?, ?)",
                (campaign, *campaign_row(campaign_type="Type-D")),
            )
        roots = plant_roots(composed_gate, campaign, count=1)
        with composed_gate._connect() as connection:
            connection.execute(
                f"UPDATE {NODE_TABLE} SET flip_depth = 0 WHERE id = ?",
                (roots[0],),
            )
        with pytest.raises(Exception) as raised:
            composed_gate.review(campaign)
        assert type(raised.value).__name__ == "KsGuardError"
        assert roots[0] in str(raised.value)

    def test_an_unopenable_sidecar_is_never_a_verdict(
        self, composed_gate, planned_campaign, sidecar_path
    ) -> None:
        # §7's failure table makes a sidecar that will not authenticate
        # *unrecoverable*; the taxonomy's rule is that it must never read as
        # "no selections recorded", because that reading would bless every
        # mixed world as homogeneous.  The hand-made file must reproduce the
        # whole mode tree NullSidecar.write would have built — the 0o700
        # directories and the 0o600 file — or the permission gate refuses it
        # one layer earlier as SidecarAccessError, which is the two-layer
        # gate doing its job, not the decryption refusal this test is after.
        directory = sidecar_path.parent
        for created in (directory.parent, directory):
            created.mkdir(parents=True, exist_ok=True)
            created.chmod(0o700)
        sidecar_path.write_bytes(b"not-an-envelope")
        sidecar_path.chmod(0o600)
        with pytest.raises(Exception) as raised:
            composed_gate.review(planned_campaign)
        assert type(raised.value).__name__ == "SidecarDecryptionError"
