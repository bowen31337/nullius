"""Feature 122: the planning gate — one tree, one regime.

app_spec.xml, "Null Oracle & Planted Nulls", feature 122: *System rejects a
campaign plan that mixes Type-R and Type-D assignment within one tree, which
emits a heterogeneous_world error message.*  This suite pins the gate's
three contracts:

* **the value** — :class:`nulloracle.plan.CampaignPlan` is the plan as a
  gate: a homogeneous plan constructs, canonicalizes and freezes, and a
  mixed one refuses to exist at all.  The refusal is the feature, not a
  side effect of it — a mixed plan that constructed and *then* had to be
  checked would be a value a writer could act on in the gap between
  construction and check;
* **the message** — every mix refusal is a
  :class:`nulloracle.errors.HeterogeneousWorldError` whose message
  *begins* with ``heterogeneous_world``, the spec's own word, so the
  rejection is greppable by the feature that defines it.  Pinned as a
  prefix rather than a substring: a log line must not be able to carry the
  code by accident;
* **the review** — :class:`nulloracle.plan.CampaignPlanGate` reads the plan
  the writers left behind (flip depths off the node rows, root selections
  off §7.1's sealed sidecar) and hands it to the same value, so a world
  that went mixed by any path — including the one this workspace can reach
  today, a flip drawn onto a Type-R campaign, which feature 119's writer
  does not type-check — is caught by the one decision.

Three properties get their own sections because they are the ones a
plausible-looking implementation gets wrong:

* the campaign's *declared type* is one side of the comparison — a Type-R
  campaign carrying flip depths is mixed **even with an empty sidecar**,
  and a Type-D campaign whose roots appear in the sidecar is mixed even
  with no flip drawn;
* an **absent** sidecar file is not an unopenable one — absent means no
  selections are recorded anywhere (true, the file is the only place they
  could be), while a file that will not authenticate raises unwrapped and
  is never translated into a verdict;
* the refusal that is *not* the mix — an unknown regime, a malformed id, a
  corrupt flip depth, a missing campaign row — stays a ``KsGuardError``,
  because a planner that caught the store's error would treat a
  heterogeneous world as a database hiccup to retry rather than a design
  to fix.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from nulloracle import (
    CAMPAIGN_TABLE,
    CAMPAIGN_TYPE_COLUMN,
    DATABASE_URL_ENV,
    FLIP_DEPTH_COLUMN,
    HETEROGENEOUS_WORLD,
    NODE_TABLE,
    NULL_FRACTION_COLUMN,
    TYPE_D_CAMPAIGN_TYPE,
    TYPE_R_CAMPAIGN_TYPE,
    WORKSPACE_COUNT_COLUMN,
    CampaignPlan,
    CampaignPlanGate,
    FlipDepth,
    HeterogeneousWorldError,
    KsGuardError,
    NullAssignment,
    NullOracleError,
    NullSidecar,
    SidecarDecryptionError,
    SidecarKey,
    TypeRSelection,
    review_campaign_plan,
)

#: The 32-byte test key, the same constant the member's conftest uses.
TEST_KEY_HEX = "0f" * 32

#: A campaign id that is a canonical UUID, so a test about the *gate* is
#: never accidentally about id validation.
CAMPAIGN = "7c2e1a40-0000-4000-8000-000000000122"

#: A node id in the same spirit.
NODE = "7c2e1a40-0000-4000-8000-000000000119"


# -- Helpers ---------------------------------------------------------------------


def _sidecar(tmp_path: Path, name: str = "z0/null/sidecar.enc") -> NullSidecar:
    """A sidecar at a path under this test's tmpdir, sealed with the test key."""
    return NullSidecar(tmp_path / name, SidecarKey.from_hex(TEST_KEY_HEX))


def _gate(tmp_path: Path, sidecar: NullSidecar | None = None, name: str = "plan.db"):
    """A planning gate over a fresh SQLite file and the sidecar it reads."""
    url = f"sqlite:///{tmp_path / name}"
    return CampaignPlanGate(url, sidecar or _sidecar(tmp_path))


def _campaign(
    gate: CampaignPlanGate,
    campaign_id: str | None = None,
    *,
    campaign_type: str = TYPE_R_CAMPAIGN_TYPE,
) -> str:
    """Insert a campaign row the way its planner would, and return its id.

    The three ``NOT NULL`` planning-time columns plus the type — the shape
    ``migrations/versions/0111_campaign_table.py`` describes a campaign as
    being planned with.  This suite inserts the row itself rather than
    expecting the gate to: a campaign is written by its planner *before any
    node is expanded*, and the gate reviews campaigns, it does not invent
    them.
    """
    identifier = campaign_id or str(uuid.uuid4())
    with gate._connect() as connection, connection:
        connection.execute(
            f"INSERT INTO {CAMPAIGN_TABLE} (id, {CAMPAIGN_TYPE_COLUMN}, "
            f"{WORKSPACE_COUNT_COLUMN}, {NULL_FRACTION_COLUMN}) "
            "VALUES (?, ?, 12, 0.1667)",
            (identifier, campaign_type),
        )
    return identifier


def _node(
    gate: CampaignPlanGate,
    campaign_id: str,
    node_id: str | None = None,
    *,
    parent_id: str | None = None,
    flip_depth: int | None = None,
) -> str:
    """Insert a node row the way the discovery loop would, and return its id.

    ``parent_id`` defaults to ``None``, which is what makes the row a *root*;
    ``flip_depth`` is written only where a test means to leave a drawn flip
    behind, the state feature 119's writer produces.
    """
    identifier = node_id or str(uuid.uuid4())
    with gate._connect() as connection, connection:
        connection.execute(
            f"INSERT INTO {NODE_TABLE} (id, parent_id, campaign_id, theme_root, "
            f"depth, {FLIP_DEPTH_COLUMN}) VALUES (?, ?, ?, 'macro', 0, ?)",
            (identifier, parent_id, campaign_id, flip_depth),
        )
    return identifier


@pytest.fixture(autouse=True)
def _database_url_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with no ``DATABASE_URL`` in the environment.

    Autouse and unconditional, mirroring the member's other suites: the
    default state of a test is a deployment that names no relational store,
    and each test that wants a gate builds its own over ``tmp_path``, so no
    test here can reach a real database.
    """
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)


# -- The plan as a value ---------------------------------------------------------


class TestThePlanIsAGate:
    def test_a_type_r_plan_constructs(self) -> None:
        # §7.3's first regime as a plan: the wells a selection lands on, and
        # nothing of the other half.
        plan = CampaignPlan(
            campaign_id=CAMPAIGN,
            campaign_type=TYPE_R_CAMPAIGN_TYPE,
            root_selections=(NODE,),
        )
        assert plan.campaign_id == CAMPAIGN
        assert plan.campaign_type == TYPE_R_CAMPAIGN_TYPE
        assert plan.root_selections == (NODE,)
        assert plan.flip_branches == ()
        assert plan.unplanted is False

    def test_a_type_d_plan_constructs(self) -> None:
        # The mirror: the branches a flip lands on, and no selection.
        plan = CampaignPlan(
            campaign_id=CAMPAIGN,
            campaign_type=TYPE_D_CAMPAIGN_TYPE,
            flip_branches=(NODE,),
        )
        assert plan.flip_branches == (NODE,)
        assert plan.root_selections == ()
        assert plan.unplanted is False

    def test_an_undrawn_campaign_is_a_valid_plan(self) -> None:
        # The gate refuses mixing, not emptiness: a campaign nothing has
        # landed on yet is the honest shape of a world between planning and
        # planting, and "has this been drawn?" is the writers' and readers'
        # question, not the gate's.
        plan = CampaignPlan(
            campaign_id=CAMPAIGN, campaign_type=TYPE_R_CAMPAIGN_TYPE
        )
        assert plan.unplanted is True
        assert plan.root_selections == () and plan.flip_branches == ()

    def test_the_node_sets_are_canonicalized_and_sorted(self) -> None:
        # A plan depends on the *set* of nodes each half covers, not on the
        # order a caller built its collection in — the same
        # order-independence the Type-R draw states for the wells.
        raw = [str(uuid.uuid4()) for _ in range(3)]
        plan = CampaignPlan(
            campaign_id=CAMPAIGN.upper(),
            campaign_type=TYPE_R_CAMPAIGN_TYPE,
            root_selections=reversed(raw),
        )
        assert plan.campaign_id == CAMPAIGN
        assert plan.root_selections == tuple(sorted(raw))

    def test_the_plan_is_frozen(self) -> None:
        # A plan that has passed the gate can never be edited into a mixed
        # one by a caller who kept a reference — the value is a record of a
        # decision, and a mutable handle to it would be a mutable handle to
        # "this tree measures one thing".
        plan = CampaignPlan(
            campaign_id=CAMPAIGN, campaign_type=TYPE_R_CAMPAIGN_TYPE
        )
        with pytest.raises(AttributeError, match="cannot assign"):
            plan.campaign_type = TYPE_D_CAMPAIGN_TYPE  # type: ignore[misc]

    def test_the_plan_renders_its_own_fields(self) -> None:
        plan = CampaignPlan(
            campaign_id=CAMPAIGN,
            campaign_type=TYPE_R_CAMPAIGN_TYPE,
            root_selections=(NODE,),
        )
        payload = plan.to_payload()
        assert payload["campaign_id"] == CAMPAIGN
        assert payload["campaign_type"] == TYPE_R_CAMPAIGN_TYPE
        assert payload["root_selections"] == [NODE]
        assert payload["flip_branches"] == []
        assert "1 selected root" in repr(plan)


# -- The three shapes of the mix ---------------------------------------------------


class TestTheMixedPlanIsRefused:
    def test_both_halves_in_one_tree_is_refused(self) -> None:
        # The mix the feature's sentence names outright: a root selection
        # and a flip depth in one tree.
        with pytest.raises(HeterogeneousWorldError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                root_selections=(str(uuid.uuid4()),),
                flip_branches=(NODE,),
            )
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert CAMPAIGN in str(raised.value)
        assert TYPE_R_CAMPAIGN_TYPE in str(raised.value)
        assert TYPE_D_CAMPAIGN_TYPE in str(raised.value)

    def test_a_flip_under_a_type_r_declaration_is_refused(self) -> None:
        # The declared type is one side of the comparison: a Type-R campaign
        # whose branches carry flips is mixed even with an empty sidecar,
        # which is exactly the state a mis-scripted loop leaves behind.
        with pytest.raises(HeterogeneousWorldError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                flip_branches=(NODE,),
            )
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert NODE in str(raised.value)

    def test_a_selection_under_a_type_d_declaration_is_refused(self) -> None:
        # The mirror: a Type-D campaign keeps every root real, so a root
        # selection in its tree is the second regime §7.3 holds out of it.
        with pytest.raises(HeterogeneousWorldError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_D_CAMPAIGN_TYPE,
                root_selections=(NODE,),
            )
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert NODE in str(raised.value)

    def test_the_code_is_the_specs_own_word(self) -> None:
        # "heterogeneous_world", verbatim — the one spelling the spec names,
        # so an operator grepping a log for the rejection finds it by the
        # feature's word.  Pinned as a constant so two writers cannot spell
        # it two ways.
        assert HETEROGENEOUS_WORLD == "heterogeneous_world"

    def test_the_refusal_is_not_a_store_failure(self) -> None:
        # The vocabulary is the point: a planner catching this refusal is
        # rejecting a document, not handling a broken store.  If the mix
        # arrived as the store's error, a caller would retry it as a
        # database hiccup and plant exactly the tree §7.3 forbids.
        with pytest.raises(HeterogeneousWorldError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_D_CAMPAIGN_TYPE,
                root_selections=(NODE,),
            )
        assert isinstance(raised.value, NullOracleError)
        assert not isinstance(raised.value, KsGuardError)

    def test_the_refusal_names_more_than_three_nodes_as_a_count(self) -> None:
        # A refusal that pasted a thousand UUIDs into a log line is a
        # refusal nobody reads; one that names the first few and counts the
        # rest is a refusal an operator can act on.
        many = tuple(str(uuid.uuid4()) for _ in range(5))
        with pytest.raises(HeterogeneousWorldError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                flip_branches=many,
            )
        message = str(raised.value)
        # The set is sorted at construction, so the refusal names the first
        # few in canonical order — which ids those are is the plan's own
        # canonicalization, not the caller's collection order.
        assert min(many) in message
        assert f"+{len(many) - 3} more" in message


# -- The refusals that are not the mix ---------------------------------------------


class TestTheRefusalsThatAreNotTheMix:
    def test_an_unknown_regime_is_a_store_refusal(self) -> None:
        # An unknown regime is not a *mix* — it is a declaration §7.3 does
        # not have, and logging it under the mix's code would send an
        # operator looking for a second assignment that does not exist.
        with pytest.raises(KsGuardError) as raised:
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type="Type-X",
                root_selections=(NODE,),
            )
        assert not isinstance(raised.value, HeterogeneousWorldError)
        assert "Type-R" in str(raised.value) and "Type-D" in str(raised.value)

    def test_a_malformed_campaign_id_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="not a UUID"):
            CampaignPlan(campaign_id="not-a-uuid", campaign_type=TYPE_R_CAMPAIGN_TYPE)

    def test_a_malformed_node_id_is_refused_with_the_field_named(self) -> None:
        with pytest.raises(KsGuardError, match="flip_branches"):
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_D_CAMPAIGN_TYPE,
                flip_branches=("not-a-uuid",),
            )

    def test_a_duplicate_node_is_refused(self) -> None:
        # One node is one assignment; a plan that named it twice would
        # misstate the world it describes.
        with pytest.raises(KsGuardError, match="duplicate"):
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_D_CAMPAIGN_TYPE,
                flip_branches=(NODE, NODE),
            )

    def test_a_non_iterable_half_is_refused(self) -> None:
        with pytest.raises(KsGuardError, match="root_selections"):
            CampaignPlan(
                campaign_id=CAMPAIGN,
                campaign_type=TYPE_R_CAMPAIGN_TYPE,
                root_selections=42,
            )


# -- The review --------------------------------------------------------------------


class TestTheReviewReadsTheWritersArtifacts:
    def test_an_unplanted_campaign_reviews_homogeneous(self, tmp_path: Path) -> None:
        # Before anything is planted there is no mix to find: the campaign
        # row declares its regime and neither half has landed.
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        _node(gate, campaign)
        plan = gate.review(campaign)
        assert plan.campaign_type == TYPE_R_CAMPAIGN_TYPE
        assert plan.unplanted is True

    def test_a_persisted_selection_is_read_back_as_the_type_r_half(
        self, tmp_path: Path
    ) -> None:
        # The review reads §7.1's file through the same writer feature 118
        # is, and a root is *selected* the moment the file holds any entry
        # for it — the bit itself is not the gate's question.
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        for _ in range(12):
            _node(gate, campaign)
        TypeRSelection(gate.database_url, gate.sidecar).persist(campaign)
        plan = gate.review(campaign)
        assert len(plan.root_selections) == 12  # every root, null and real
        assert plan.flip_branches == ()

    def test_a_persisted_flip_is_read_back_as_the_type_d_half(
        self, tmp_path: Path
    ) -> None:
        # The Type-D half is read off the node rows feature 119 wrote, by
        # the same writer this member ships.
        gate = _gate(tmp_path)
        campaign = _campaign(gate, campaign_type=TYPE_D_CAMPAIGN_TYPE)
        roots = [_node(gate, campaign) for _ in range(4)]
        store = FlipDepth(gate.database_url)
        for root in roots[:2]:
            store.persist(root, 0.4)
        plan = gate.review(campaign)
        assert plan.root_selections == ()
        assert set(plan.flip_branches) == set(roots[:2])

    def test_another_campaigns_selections_do_not_leak(
        self, tmp_path: Path
    ) -> None:
        # §7.1's file holds one map for the deployment, so another
        # campaign's entries sit beside this one's; a review that counted
        # them would refuse every world after the second campaign.
        gate = _gate(tmp_path)
        first = _campaign(gate)
        for _ in range(12):
            _node(gate, first)
        TypeRSelection(gate.database_url, gate.sidecar).persist(first)
        second = _campaign(gate, campaign_type=TYPE_D_CAMPAIGN_TYPE)
        branch = _node(gate, second)
        FlipDepth(gate.database_url).persist(branch, 0.4)
        plan = gate.review(second)
        assert plan.flip_branches == (branch,)
        assert plan.root_selections == ()

    def test_a_missing_campaign_row_is_refused(self, tmp_path: Path) -> None:
        # The plan is a fact about a campaign, and a gate that invented the
        # row would be inventing the declaration it exists to check.
        gate = _gate(tmp_path)
        with pytest.raises(KsGuardError, match="no row"):
            gate.review(CAMPAIGN)

    def test_a_malformed_campaign_id_is_refused_by_the_store(
        self, tmp_path: Path
    ) -> None:
        gate = _gate(tmp_path)
        with pytest.raises(KsGuardError, match="not a UUID"):
            gate.review("not-a-uuid")


class TestTheReviewRefusesTheMixedTree:
    """The store half of the sentence, in the three shapes the value states."""

    def test_a_selection_and_a_flip_in_one_tree_is_refused(
        self, tmp_path: Path
    ) -> None:
        # A Type-R world that a loop went on flipping: the selection is
        # sealed in the sidecar, the flip is on a node row, and the review
        # refuses the world the two writers jointly made.
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        roots = [_node(gate, campaign) for _ in range(12)]
        TypeRSelection(gate.database_url, gate.sidecar).persist(campaign)
        FlipDepth(gate.database_url).persist(roots[0], 0.4)
        with pytest.raises(HeterogeneousWorldError) as raised:
            gate.review(campaign)
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert campaign in str(raised.value)

    def test_a_flip_under_a_type_r_declaration_is_refused_with_no_sidecar_file(
        self, tmp_path: Path
    ) -> None:
        # The reachable hole this feature closes: feature 119's writer
        # confirms the campaign exists but not its type, so a flip drawn
        # onto a Type-R campaign persists today — and the review refuses it
        # with the sidecar never having existed.
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        root = _node(gate, campaign)
        FlipDepth(gate.database_url).persist(root, 0.4)
        assert not gate.sidecar.exists()
        with pytest.raises(HeterogeneousWorldError) as raised:
            gate.review(campaign)
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert root in str(raised.value)

    def test_a_selection_under_a_type_d_declaration_is_refused(
        self, tmp_path: Path
    ) -> None:
        # The mirror: root entries sealed for a Type-D campaign's wells —
        # the state a loop that ran feature 118's writer against the wrong
        # campaign id leaves behind.
        gate = _gate(tmp_path)
        campaign = _campaign(gate, campaign_type=TYPE_D_CAMPAIGN_TYPE)
        root = _node(gate, campaign)
        gate.sidecar.write(
            {root: NullAssignment(node_id=root, is_null=True, perm_seed=1)}
        )
        with pytest.raises(HeterogeneousWorldError) as raised:
            gate.review(campaign)
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
        assert root in str(raised.value)

    def test_a_corrupt_flip_depth_is_a_store_refusal_not_a_mix(
        self, tmp_path: Path
    ) -> None:
        # A geometric's support cannot produce 0; the row is corrupt and is
        # refused with the node named, not counted as a flipped branch —
        # and not logged under the mix's code, which would send an operator
        # hunting a second assignment that does not exist.
        gate = _gate(tmp_path)
        campaign = _campaign(gate, campaign_type=TYPE_D_CAMPAIGN_TYPE)
        root = _node(gate, campaign)
        with gate._connect() as connection, connection:
            connection.execute(
                f"UPDATE {NODE_TABLE} SET {FLIP_DEPTH_COLUMN} = 0 WHERE id = ?",
                (root,),
            )
        with pytest.raises(KsGuardError) as raised:
            gate.review(campaign)
        assert not isinstance(raised.value, HeterogeneousWorldError)
        assert root in str(raised.value)


class TestTheSidecarIsNeverGuessedAbout:
    def test_an_absent_file_is_no_selections_not_a_failure(self, tmp_path: Path) -> None:
        # The review runs at planning time, when a deployment's first
        # campaign has no sidecar.enc yet: absent means no selections are
        # recorded anywhere, which is true — the file is the only place
        # they could be.
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        _node(gate, campaign)
        assert not gate.sidecar.exists()
        assert gate.review(campaign).unplanted is True

    def test_an_unopenable_file_raises_unwrapped(self, tmp_path: Path) -> None:
        # The taxonomy's most important rule, from the gate's side of it: a
        # sidecar that will not authenticate must never read as "no
        # selections", because that reading would bless every mixed world
        # as homogeneous.
        sidecar = _sidecar(tmp_path)
        sidecar.write(
            {NODE: NullAssignment(node_id=NODE, is_null=True, perm_seed=1)}
        )
        sealed_elsewhere = NullSidecar(
            sidecar.path, SidecarKey.from_hex("1e" * 32)
        )
        gate = CampaignPlanGate(f"sqlite:///{tmp_path / 'plan.db'}", sealed_elsewhere)
        campaign = _campaign(gate)
        _node(gate, campaign)
        with pytest.raises(SidecarDecryptionError):
            gate.review(campaign)

    def test_the_gate_reads_the_bit_only_as_presence(self, tmp_path: Path) -> None:
        # Feature 118 seals **every** root of a Type-R campaign, the real
        # ones too, so a root recorded `is_null=False` still marks the tree
        # as claimed by the selection regime — presence is the question, not
        # the bit.
        gate = _gate(tmp_path)
        campaign = _campaign(gate, campaign_type=TYPE_D_CAMPAIGN_TYPE)
        root = _node(gate, campaign)
        gate.sidecar.write(
            {root: NullAssignment(node_id=root, is_null=False, perm_seed=1)}
        )
        with pytest.raises(HeterogeneousWorldError):
            gate.review(campaign)


# -- resolve and the module-level spelling -------------------------------------------


class TestResolve:
    def test_nothing_composes_without_a_database_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert CampaignPlanGate.resolve() is None

    def test_nothing_composes_without_a_sidecar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}"
        )
        assert CampaignPlanGate.resolve() is None

    def test_both_halves_compose(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            DATABASE_URL_ENV, f"sqlite:///{tmp_path / 'plan.db'}"
        )
        monkeypatch.setenv("NULL_SIDECAR_PATH", str(tmp_path / "sidecar.enc"))
        monkeypatch.setenv("NULL_SIDECAR_KEY_REF", f"hex:{TEST_KEY_HEX}")
        gate = CampaignPlanGate.resolve()
        assert gate is not None
        assert gate.sidecar.path == tmp_path / "sidecar.enc"

    def test_the_constructor_refuses_an_empty_url(self, tmp_path: Path) -> None:
        with pytest.raises(KsGuardError):
            CampaignPlanGate("  ", _sidecar(tmp_path))

    def test_the_constructor_refuses_a_non_sidecar(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(KsGuardError, match="sidecar"):
            CampaignPlanGate(f"sqlite:///{tmp_path / 'plan.db'}", "a string")

    def test_an_unspeakable_scheme_is_refused_at_first_use(
        self, tmp_path: Path
    ) -> None:
        gate = CampaignPlanGate("postgres:///db", _sidecar(tmp_path))
        with pytest.raises(KsGuardError, match="scheme"):
            gate.review(CAMPAIGN)

    def test_an_in_memory_database_is_refused(self, tmp_path: Path) -> None:
        gate = CampaignPlanGate("sqlite:///:memory:", _sidecar(tmp_path))
        with pytest.raises(KsGuardError, match="in-memory"):
            gate.review(CAMPAIGN)


class TestTheModuleLevelSpelling:
    def test_the_sentence_as_one_call(self, tmp_path: Path) -> None:
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        _node(gate, campaign)
        sidecar = gate.sidecar
        plan = review_campaign_plan(campaign, sidecar, database_url=gate.database_url)
        assert plan.campaign_type == TYPE_R_CAMPAIGN_TYPE

    def test_nothing_named_is_refused_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A gate that quietly skipped its review would let a mixed world
        # through believing it had been checked — the exact failure this
        # feature exists to rule out, so the refusal is loud and named.
        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        with pytest.raises(KsGuardError, match="names a store"):
            review_campaign_plan(CAMPAIGN, _sidecar(tmp_path))

    def test_the_mix_arrives_unwrapped_through_the_seam(
        self, tmp_path: Path
    ) -> None:
        gate = _gate(tmp_path)
        campaign = _campaign(gate)
        root = _node(gate, campaign)
        FlipDepth(gate.database_url).persist(root, 0.4)
        with pytest.raises(HeterogeneousWorldError) as raised:
            review_campaign_plan(
                campaign, gate.sidecar, database_url=gate.database_url
            )
        assert str(raised.value).startswith(HETEROGENEOUS_WORLD)
