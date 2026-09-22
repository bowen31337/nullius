"""Feature 197's suite: the per-campaign root provider rotation.

The two halves the feature's sentence joins — *which declared family serves
a root*, and *the fact that the campaign's rotation is persisted* — tested
separately and then at the seam with feature 196, which owns the provenance
row this feature's ``record_root_provider`` writes through.

The arithmetic is tested as arithmetic (determinism, one family per root,
stability under reordering, reachability, family-invariance), the store as a
store (gates, idempotence, conflicts, drift, read-back re-verification) and
the pair as the act a discovery loop makes.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

import pytest
from conftest import sqlite_path_of
from providers import (
    FrontierProvider,
    FrontierTier,
    RootCall,
    RootNotRecordedError,
    RootProviderConflictError,
    RootProviderError,
    RootRotation,
    RootRotationError,
    RotationConflictError,
    UnassignedRootProviderError,
    UnknownRootProviderError,
    UnrotatedCampaignError,
    assign_root_provider,
    rotation_digest,
    rotation_index,
)
from providers._rotation import (
    ASSIGNED_AT_COLUMN,
    CAMPAIGN_ID_COLUMN,
    DECLARED_PROVIDERS_COLUMN,
    DEPTH_COLUMN,
    MODEL_COLUMN,
    NODE_ID_COLUMN,
    PROVIDER_COLUMN,
    ROOT_PROVIDER_ROTATION_TABLE,
    ROTATION_DIGEST_COLUMN,
    _tier_json,
)

# ── The arithmetic ────────────────────────────────────────────────────────────


class TestRotationIndex:
    """The decision itself, before any database exists."""

    def test_index_is_a_declared_slot(self, frontier_tier: FrontierTier) -> None:
        """Every root's index names a member the tier actually declares."""
        campaign = str(uuid.uuid4())
        for _ in range(32):
            index = rotation_index(campaign, str(uuid.uuid4()), frontier_tier)
            assert 0 <= index < len(frontier_tier.providers)

    def test_index_is_deterministic_across_processes(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The assignment is the same value in another process.

        Stated as the property the docstring gives for choosing ``sha256``
        over the salted builtin: the index is recomputed here from the
        pre-image the module documents, in this process, and must agree —
        which is what makes the persisted row re-derivable at all.
        """
        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        expected = int.from_bytes(
            hashlib.sha256(f"{campaign}\x1f{node}".encode()).digest(), "big"
        ) % len(frontier_tier.providers)
        assert rotation_index(campaign, node, frontier_tier) == expected

    def test_one_family_per_root_however_often_asked(
        self, frontier_tier: FrontierTier
    ) -> None:
        """§14.1's rotation assigns each root to exactly one family."""
        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        assert len({rotation_index(campaign, node, frontier_tier) for _ in range(5)}) == 1

    def test_index_is_stable_when_the_loop_reorders(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The family follows the root's identity, not the visiting order.

        The property a positional round-robin would not have, and the reason
        the rotation can be re-derived by a reader that never saw the loop.
        """
        campaign = str(uuid.uuid4())
        nodes = [str(uuid.uuid4()) for _ in range(8)]
        forwards = {
            node: rotation_index(campaign, node, frontier_tier) for node in nodes
        }
        backwards = {
            node: rotation_index(campaign, node, frontier_tier)
            for node in reversed(nodes)
        }
        assert forwards == backwards

    def test_a_campaign_spreads_across_the_declared_families(
        self, frontier_tier: FrontierTier
    ) -> None:
        """Enough roots reach every declared family — the point of rotating.

        Not an allocation guarantee (the module states the limit: the hash
        draws a multinomial and promises no count), only that the spread is
        real rather than a constant that would make §14.1's *"different
        families propose structurally different mechanisms"* a claim about
        one family.
        """
        campaign = str(uuid.uuid4())
        drawn = {
            rotation_index(campaign, str(uuid.uuid4()), frontier_tier)
            for _ in range(200)
        }
        assert drawn == set(range(len(frontier_tier.providers)))

    def test_two_roots_of_one_campaign_differ_somewhere(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The rotation is per *root*, not per campaign."""
        campaign = str(uuid.uuid4())
        drawn = {
            rotation_index(campaign, str(uuid.uuid4()), frontier_tier)
            for _ in range(200)
        }
        assert len(drawn) > 1

    def test_the_tier_order_is_what_the_index_reads(
        self, frontier_tier: FrontierTier
    ) -> None:
        """Only the set's *size* enters the arithmetic, never a family name.

        The digest's own blindness, restated at the index: a tier of the same
        arity answers the same index whatever its members are called, because
        the index is a slot and the names are the slot's occupants.
        """
        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        renamed = FrontierTier(
            providers=tuple(
                FrontierProvider(provider=f"p{i}", model=f"m{i}")
                for i in range(len(frontier_tier.providers))
            )
        )
        assert rotation_index(campaign, node, renamed) == rotation_index(
            campaign, node, frontier_tier
        )

    def test_a_different_root_is_a_different_slot_somewhere(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The pre-image carries the node, not only the campaign."""
        campaign = str(uuid.uuid4())
        drawn = {
            rotation_index(campaign, str(uuid.uuid4()), frontier_tier)
            for _ in range(32)
        }
        assert len(drawn) > 1

    def test_a_tier_of_one_assigns_every_root_to_it(self) -> None:
        """The degenerate rotation: one declared family, every root."""
        only = FrontierTier(
            providers=(FrontierProvider(provider="anthropic", model="claude-opus-5"),)
        )
        campaign = str(uuid.uuid4())
        assert {
            rotation_index(campaign, str(uuid.uuid4()), only) for _ in range(16)
        } == {0}

    def test_ids_are_canonicalised_before_hashing(
        self, frontier_tier: FrontierTier
    ) -> None:
        """A mixed-case spelling is one root, not two families.

        Deliberate: a drift here would be invisible — the id still resolves
        and the assignment is still stable, but about a different value than
        the row it keys.
        """
        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        assert rotation_index(
            campaign.upper(), node, frontier_tier
        ) == rotation_index(campaign, node, frontier_tier)
        assert rotation_index(
            uuid.UUID(campaign), uuid.UUID(node), frontier_tier
        ) == rotation_index(campaign, node, frontier_tier)

    def test_a_foreign_copy_of_the_tier_assigns_through_this_module(
        self, frontier_tier: FrontierTier
    ) -> None:
        """Recognition by parts: a second copy of a member is still a tier.

        The value that crosses this seam is the tier as the loader built it —
        two class objects over one source file — so an ``isinstance`` gate
        here would refuse the very declaration the deployment configured.  The
        stub carries the one part the arithmetic reads.
        """

        class Stub:
            providers = frontier_tier.providers

        campaign = str(uuid.uuid4())
        node = str(uuid.uuid4())
        assert rotation_index(campaign, node, Stub()) == rotation_index(
            campaign, node, frontier_tier
        )

    def test_a_value_that_is_not_an_id_is_refused(
        self, frontier_tier: FrontierTier
    ) -> None:
        with pytest.raises(RootRotationError) as caught:
            rotation_index("not-a-uuid", str(uuid.uuid4()), frontier_tier)
        assert "campaign_id" in str(caught.value)

    def test_a_value_that_is_not_a_tier_is_refused(self) -> None:
        with pytest.raises(RootProviderError):
            rotation_index(str(uuid.uuid4()), str(uuid.uuid4()), "anthropic")


class TestRotationDigest:
    """The rotation as one identifier."""

    def test_digest_is_sha256_hex_of_premise_and_scope(
        self, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        expected = hashlib.sha256(
            f"{campaign}\x1f{frontier_tier.text()}".encode()
        ).hexdigest()
        assert rotation_digest(campaign, frontier_tier) == expected

    def test_two_campaigns_declaring_the_same_set_are_two_rotations(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The digest names a *campaign's* rotation, not a tier."""
        assert rotation_digest(str(uuid.uuid4()), frontier_tier) != rotation_digest(
            str(uuid.uuid4()), frontier_tier
        )

    def test_a_different_set_is_a_different_rotation(
        self, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        smaller = FrontierTier(providers=frontier_tier.providers[:2])
        assert rotation_digest(campaign, smaller) != rotation_digest(
            campaign, frontier_tier
        )

    def test_the_digest_is_stable(self, frontier_tier: FrontierTier) -> None:
        campaign = str(uuid.uuid4())
        assert len({rotation_digest(campaign, frontier_tier) for _ in range(4)}) == 1

    def test_the_digest_moves_when_a_slot_holds_another_family(
        self, frontier_tier: FrontierTier
    ) -> None:
        """The digest is blind to family names — and that is not the same as
        being blind to the rotation.

        Nothing marks one family against another, so a deployment that swapped
        a slot's member keeps every *index* and changes every *family*: the
        digest moves (the canonical text moved) while
        :func:`rotation_index` does not.  Both halves asserted together,
        because each alone is misleading — the index equality looks like the
        swap was invisible, and the digest inequality looks like the index
        should have moved too.
        """
        campaign, node = str(uuid.uuid4()), str(uuid.uuid4())
        # The *same arity*, deliberately: the index reads the size of the set
        # and the two ids alone, so a swap that changed the arity would move
        # the index for a reason that has nothing to do with the names.
        swapped = FrontierTier(
            providers=tuple(
                member
                if member != frontier_tier.providers[0]
                else FrontierProvider(
                    provider=member.provider, model=member.model + "-successor"
                )
                for member in frontier_tier.providers
            )
        )
        assert len(swapped.providers) == len(frontier_tier.providers)
        assert swapped != frontier_tier
        assert rotation_digest(campaign, swapped) != rotation_digest(
            campaign, frontier_tier
        )
        assert rotation_index(campaign, node, swapped) == rotation_index(
            campaign, node, frontier_tier
        )

    def test_the_digest_reads_the_canonical_order_not_the_given_one(
        self, frontier_tier: FrontierTier
    ) -> None:
        """A set stated in another order is the same rotation, because the
        tier that carries it sorted itself on construction."""
        campaign = str(uuid.uuid4())
        reordered = FrontierTier(providers=tuple(reversed(frontier_tier.providers)))
        assert rotation_digest(campaign, reordered) == rotation_digest(
            campaign, frontier_tier
        )

    def test_the_digest_is_canonical_under_a_foreign_copy(
        self, frontier_tier: FrontierTier
    ) -> None:
        class Stub:
            providers = frontier_tier.providers

        campaign = str(uuid.uuid4())
        assert rotation_digest(campaign, Stub()) == rotation_digest(
            campaign, frontier_tier
        )


# ── The store: writes ─────────────────────────────────────────────────────────


class TestAssign:
    """``assign`` — the decision, persisted."""

    def test_assign_writes_one_row(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        assert assignment.recorded is True
        assert assignment.node_id == node
        assert assignment.campaign_id == call.campaign_id
        assert assignment.provider and assignment.model
        assert assignment.assigned_provider in frontier_tier
        assert assignment.declared == frontier_tier
        assert assignment.digest == rotation_digest(call.campaign_id, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            count = connection.execute(
                f"SELECT COUNT(*) FROM {ROOT_PROVIDER_ROTATION_TABLE}"
            ).fetchone()[0]
        assert count == 1

    def test_the_row_is_the_assignment(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """Every column read back raw matches the record's own mapping."""
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            row = connection.execute(
                f"SELECT {CAMPAIGN_ID_COLUMN}, {NODE_ID_COLUMN}, "
                f"{PROVIDER_COLUMN}, {MODEL_COLUMN}, {DEPTH_COLUMN}, "
                f"{DECLARED_PROVIDERS_COLUMN}, {ROTATION_DIGEST_COLUMN}, "
                f"{ASSIGNED_AT_COLUMN} FROM {ROOT_PROVIDER_ROTATION_TABLE}"
            ).fetchone()
        assert row == (
            assignment.campaign_id,
            assignment.node_id,
            assignment.provider,
            assignment.model,
            assignment.depth,
            _tier_json(frontier_tier),
            assignment.digest,
            assignment.row()[ASSIGNED_AT_COLUMN],
        )

    def test_assign_stores_the_trees_own_depth(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The row carries what the tree placed the root at, not the ask.

        Feature 196's probe answers the depth, so a bridge rebuilding a call
        from two ids cannot invent a constant — and the record re-derives its
        ``root_call`` from the stored value.
        """
        call, _ = root_call(root_rotation.database_url, depth=1)
        assignment = root_rotation.assign(call, frontier_tier)
        assert assignment.depth == 1
        assert assignment.root_call.depth == 1
        assert assignment.root_call.node_id == call.node_id

    def test_assign_is_idempotent_and_does_not_move_the_instant(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """A retry is one decision arriving twice."""
        call, _ = root_call(root_rotation.database_url)
        moment = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        first = root_rotation.assign(call, frontier_tier, now=moment)
        later = moment + timedelta(hours=3)
        retry = root_rotation.assign(call, frontier_tier, now=later)
        assert first.recorded is True
        assert retry.recorded is False
        assert retry.assigned_at == first.assigned_at
        assert replace(retry, recorded=True) == first

    def test_assign_stamps_the_writer_instant(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        moment = datetime(2026, 3, 1, 12, 0, 0, 123000, tzinfo=UTC)
        assignment = root_rotation.assign(call, frontier_tier, now=moment)
        assert assignment.assigned_at == moment
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            stored = connection.execute(
                f"SELECT {ASSIGNED_AT_COLUMN} FROM {ROOT_PROVIDER_ROTATION_TABLE}"
            ).fetchone()[0]
        assert stored == "2026-03-01T12:00:00.123Z"

    def test_an_offset_instant_is_converted_to_utc(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        moment = datetime(2026, 3, 1, 14, 0, tzinfo=timezone(timedelta(hours=2)))
        assignment = root_rotation.assign(call, frontier_tier, now=moment)
        assert assignment.row()[ASSIGNED_AT_COLUMN] == "2026-03-01T12:00:00.000Z"

    def test_a_naive_instant_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        with pytest.raises(RootRotationError):
            root_rotation.assign(
                call, frontier_tier, now=datetime(2026, 3, 1, 12, 0)  # noqa: DTZ001
            )

    def test_assigning_twice_into_one_campaign_is_one_rotation(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        first, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        second, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        a = root_rotation.assign(first, frontier_tier)
        b = root_rotation.assign(second, frontier_tier)
        assert a.digest == b.digest
        assert len(root_rotation.rotation(campaign)) == 2

    def test_a_second_declared_set_is_refused_naming_both(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The drift check, and the reason the premise is persisted."""
        campaign = str(uuid.uuid4())
        first, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        second, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        root_rotation.assign(first, frontier_tier)
        smaller = FrontierTier(providers=frontier_tier.providers[:2])
        with pytest.raises(RootRotationError) as caught:
            root_rotation.assign(second, smaller)
        message = str(caught.value)
        assert "1 root assigned" in message
        assert frontier_tier.text() in message
        assert smaller.text() in message

    def test_the_drift_refusal_names_the_count_of_rows(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        for _ in range(3):
            call, _ = root_call(root_rotation.database_url, campaign_id=campaign)
            root_rotation.assign(call, frontier_tier)
        fourth, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        smaller = FrontierTier(providers=frontier_tier.providers[:1])
        with pytest.raises(RootRotationError) as caught:
            root_rotation.assign(fourth, smaller)
        assert "3 roots assigned" in str(caught.value)

    def test_a_node_the_tree_does_not_hold_is_feature_196s_refusal(
        self, root_rotation: RootRotation, frontier_tier: FrontierTier
    ) -> None:
        """196's gate answers the tree question for both features."""
        ghost = RootCall(
            node_id=str(uuid.uuid4()),
            campaign_id=str(uuid.uuid4()),
            depth=0,
        )
        with pytest.raises(RootNotRecordedError):
            root_rotation.assign(ghost, frontier_tier)

    def test_a_depth_call_is_feature_196s_refusal(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url, depth=2)
        with pytest.raises(UnrotatedCampaignError):
            root_rotation.assign(call, frontier_tier)

    def test_a_malformed_call_is_refused_before_any_database_is_touched(
        self, tmp_path, frontier_tier: FrontierTier
    ) -> None:
        """Validation precedes the connection: the file is never created."""
        store = RootRotation(f"sqlite:///{tmp_path / 'untouched.db'}")
        with pytest.raises(RootRotationError) as caught:
            store.assign("a root call", frontier_tier)
        assert "node_id" in str(caught.value)
        assert not store.path.exists()
        assert store.database_url.endswith("untouched.db")

    def test_a_malformed_tier_is_refused_before_any_database_is_touched(
        self, tmp_path, root_call
    ) -> None:
        store = RootRotation(f"sqlite:///{tmp_path / 'untouched.db'}")
        with pytest.raises(RootProviderError):
            store.assign(
                RootCall(
                    node_id=str(uuid.uuid4()),
                    campaign_id=str(uuid.uuid4()),
                    depth=0,
                ),
                "anthropic",
            )
        assert not store.path.exists()

    def test_a_foreign_copy_of_the_call_is_accepted(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """Recognition by parts, applied at the call this feature re-makes."""
        call, node = root_call(root_rotation.database_url)

        class Stub:
            node_id = call.node_id
            campaign_id = call.campaign_id
            depth = call.depth

        assignment = root_rotation.assign(Stub(), frontier_tier)
        assert assignment.node_id == node
        assert assignment.root_call == call

    def test_assign_installs_the_table_lazily(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (ROOT_PROVIDER_ROTATION_TABLE,),
            ).fetchone() is None
        call, _ = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (ROOT_PROVIDER_ROTATION_TABLE,),
            ).fetchone() is not None


class TestRotationConflict:
    """One root, one family."""

    def test_a_row_naming_another_family_is_a_conflict(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """Forced by rewriting the row under the store, then re-assigning.

        The arithmetic cannot change its mind, so the only way a stored row
        can disagree is another writer — which is exactly the state the
        conflict refusal exists to make legible, and it names both families
        so the caller learns which is stored and which is now proposed.
        """
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        other = next(
            member
            for member in frontier_tier.providers
            if member != assignment.assigned_provider
        )
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET {PROVIDER_COLUMN} = ?, "
                f"{MODEL_COLUMN} = ? WHERE {NODE_ID_COLUMN} = ?",
                (other.provider, other.model, assignment.node_id),
            )
        with pytest.raises(RotationConflictError) as caught:
            root_rotation.assign(call, frontier_tier)
        message = str(caught.value)
        assert other.text() in message
        assert assignment.assigned_provider.text() in message

    def test_a_conflict_is_not_the_provider_error(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The taxonomy splits by question, not by call site."""
        assert not issubclass(RotationConflictError, RootProviderError)
        assert issubclass(RotationConflictError, RootRotationError)


# ── The store: reads ──────────────────────────────────────────────────────────


class TestGet:
    """One root's assignment."""

    def test_get_answers_the_stored_record(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        written = root_rotation.assign(call, frontier_tier)
        read = root_rotation.get(call.campaign_id, node)
        assert read is not None
        assert read.recorded is False
        assert replace(read, recorded=True) == written

    def test_get_answers_none_on_a_store_that_never_assigned(
        self, root_rotation: RootRotation
    ) -> None:
        """Absent is a state, and the read does not create the table."""
        assert root_rotation.get(str(uuid.uuid4()), str(uuid.uuid4())) is None
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (ROOT_PROVIDER_ROTATION_TABLE,),
            ).fetchone() is None

    def test_get_answers_none_for_an_unassigned_root(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        assert root_rotation.get(call.campaign_id, str(uuid.uuid4())) is None

    def test_get_does_not_answer_across_campaigns(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        assert root_rotation.get(str(uuid.uuid4()), node) is None

    def test_get_refuses_a_malformed_id(self, root_rotation: RootRotation) -> None:
        with pytest.raises(RootRotationError):
            root_rotation.get("not-a-uuid", str(uuid.uuid4()))

    def test_a_row_whose_digest_is_not_its_premises_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The premise and the digest are one fact stated twice."""
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET "
                f"{ROTATION_DIGEST_COLUMN} = ? WHERE {NODE_ID_COLUMN} = ?",
                ("0" * 64, node),
            )
        with pytest.raises(RootRotationError) as caught:
            root_rotation.get(call.campaign_id, node)
        assert "digest" in str(caught.value)

    def test_a_row_whose_premise_is_not_json_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET "
                f"{DECLARED_PROVIDERS_COLUMN} = ? WHERE {NODE_ID_COLUMN} = ?",
                ("not json", node),
            )
        with pytest.raises(RootRotationError):
            root_rotation.get(call.campaign_id, node)

    def test_a_row_premise_in_another_shape_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """A bare string where a pair is: the 202 read-back discipline."""
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET "
                f"{DECLARED_PROVIDERS_COLUMN} = ? WHERE {NODE_ID_COLUMN} = ?",
                (json.dumps(["anthropic", "claude-opus-5"]), node),
            )
        with pytest.raises(RootRotationError) as caught:
            root_rotation.get(call.campaign_id, node)
        assert "pairs" in str(caught.value)

    def test_a_row_whose_instant_does_not_parse_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET "
                f"{ASSIGNED_AT_COLUMN} = ? WHERE {NODE_ID_COLUMN} = ?",
                ("yesterday", node),
            )
        with pytest.raises(RootRotationError):
            root_rotation.get(call.campaign_id, node)

    def test_a_row_whose_depth_is_not_a_root_depth_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        with closing(sqlite3.connect(root_rotation.path)) as connection, connection:
            connection.execute(
                f"UPDATE {ROOT_PROVIDER_ROTATION_TABLE} SET {DEPTH_COLUMN} = 2 "
                f"WHERE {NODE_ID_COLUMN} = ?",
                (node,),
            )
        with pytest.raises(RootRotationError):
            root_rotation.get(call.campaign_id, node)


class TestRotationRead:
    """A campaign's whole rotation."""

    def test_rotation_is_keyed_by_node(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        nodes = []
        for _ in range(4):
            call, node = root_call(root_rotation.database_url, campaign_id=campaign)
            nodes.append(node)
            root_rotation.assign(call, frontier_tier)
        read = root_rotation.rotation(campaign)
        assert set(read) == set(nodes)
        assert all(record.recorded is False for record in read.values())

    def test_rotation_is_empty_on_a_fresh_store(
        self, root_rotation: RootRotation
    ) -> None:
        assert root_rotation.rotation(str(uuid.uuid4())) == {}
        with closing(sqlite3.connect(root_rotation.path)) as connection:
            assert connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (ROOT_PROVIDER_ROTATION_TABLE,),
            ).fetchone() is None

    def test_rotation_holds_one_campaign_only(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        mine = str(uuid.uuid4())
        call, _ = root_call(root_rotation.database_url, campaign_id=mine)
        root_rotation.assign(call, frontier_tier)
        other, _ = root_call(root_rotation.database_url)
        root_rotation.assign(other, frontier_tier)
        assert set(root_rotation.rotation(mine)) == {call.node_id}

    def test_one_campaigns_digest_names_its_whole_rotation(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The figure feature 214 keys a campaign by."""
        campaign = str(uuid.uuid4())
        for _ in range(5):
            call, _ = root_call(root_rotation.database_url, campaign_id=campaign)
            root_rotation.assign(call, frontier_tier)
        assert {record.digest for record in root_rotation.rotation(campaign).values()} == {
            rotation_digest(campaign, frontier_tier)
        }


# ── The pair: this feature's decision and 196's provenance ────────────────────


class TestRecordRootProvider:
    """The act a discovery loop makes."""

    def test_the_pair_writes_both_rows(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        expected = root_rotation.assign(call, frontier_tier).assigned_provider
        assignment, served = root_rotation.record_root_provider(
            call, expected, frontier_tier
        )
        assert assignment.recorded is False
        assert served.recorded is True
        assert served.node_id == node
        assert served.provider == expected.provider
        assert served.serving_provider == expected
        assert root_rotation.provider_rotation.get(node) is not None

    def test_the_pair_assigns_before_it_records(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The rotation row is written even when the provenance half refuses.

        Load-bearing and stated in the docstring: :meth:`assign` runs first,
        so a call whose serving family disagrees with the rotation is refused
        with the rotation row *already there* — which is precisely the record
        that makes the disagreement legible, rather than a failure that left
        the campaign's rotation with a hole in it.
        """
        call, node = root_call(root_rotation.database_url)
        first = root_rotation.assign(call, frontier_tier)
        other = next(
            member
            for member in frontier_tier.providers
            if member != first.assigned_provider
        )
        with pytest.raises(UnassignedRootProviderError):
            root_rotation.record_root_provider(call, other, frontier_tier)
        stored = root_rotation.get(call.campaign_id, node)
        assert stored is not None
        assert replace(stored, recorded=True) == first
        assert root_rotation.provider_rotation.get(node) is None

    def test_an_undeclared_family_cannot_reach_196s_unknown_refusal(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """This feature's gate is the stricter of the two, and answers first.

        Feature 196's ``UnknownRootProviderError`` refuses a serving family
        the *declared set* does not name; every such family is also one the
        rotation did not assign this root, so the pair's own refusal answers
        before 196's gate is reached.  That ordering is deliberate: the
        caller learns which family the rotation assigned, which is the
        actionable half, rather than only that the set does not hold the
        family it reported.
        """
        call, _ = root_call(root_rotation.database_url)
        stranger = FrontierProvider(provider="deepseek", model="deepseek-v4-flash")
        assert stranger not in frontier_tier
        with pytest.raises(UnassignedRootProviderError):
            root_rotation.record_root_provider(call, stranger, frontier_tier)
        assert not issubclass(UnassignedRootProviderError, UnknownRootProviderError)

    def test_a_family_the_rotation_did_not_assign_is_refused(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The §14.1 silent-re-route refusal, and it writes nothing."""
        call, node = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        other = next(
            member
            for member in frontier_tier.providers
            if member != assignment.assigned_provider
        )
        with pytest.raises(UnassignedRootProviderError) as caught:
            root_rotation.record_root_provider(call, other, frontier_tier)
        message = str(caught.value)
        assert other.text() in message
        assert assignment.assigned_provider.text() in message
        assert "Nothing has been written for this call." in message
        assert root_rotation.provider_rotation.get(node) is None

    def test_the_assigned_family_is_accepted(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The family the rotation drew is the one the gate admits."""
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        _, served = root_rotation.record_root_provider(
            call, assignment.assigned_provider, frontier_tier
        )
        assert served.serving_provider == assignment.assigned_provider
        assert served.recorded is True

    def test_every_declared_family_is_recordable_somewhere(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The assignment is what admits a family, never the family itself.

        Each declared member is accepted for *some* root and refused for
        others: a gate that admitted the set rather than the assignment would
        let a family the rotation never drew write a provenance row, which is
        the silent re-route this feature refuses.
        """
        accepted = set()
        while len(accepted) < len(frontier_tier.providers):
            call, _ = root_call(root_rotation.database_url)
            assignment = root_rotation.assign(call, frontier_tier)
            root_rotation.record_root_provider(
                call, assignment.assigned_provider, frontier_tier
            )
            accepted.add(assignment.provider)
        assert accepted == {member.provider for member in frontier_tier.providers}

    def test_the_serving_family_is_recognised_by_its_parts(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """A member from the workspace's other copy of this member is admitted."""
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)

        class Stub:
            provider = assignment.provider
            model = assignment.model

        _, served = root_rotation.record_root_provider(call, Stub(), frontier_tier)
        assert served.provider == assignment.provider

    def test_a_value_that_is_not_a_family_is_refused_by_196(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        with pytest.raises(RootProviderError):
            root_rotation.record_root_provider(call, "anthropic", frontier_tier)

    def test_196_refusals_propagate_untranslated(
        self, root_rotation: RootRotation, frontier_tier: FrontierTier
    ) -> None:
        """A tree refusal travels as 196's own error, not re-wrapped."""
        ghost = RootCall(
            node_id=str(uuid.uuid4()),
            campaign_id=str(uuid.uuid4()),
            depth=0,
        )
        with pytest.raises(RootNotRecordedError):
            root_rotation.record_root_provider(
                ghost, frontier_tier.providers[0], frontier_tier
            )

    def test_the_provenance_conflict_is_196s(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        root_rotation.record_root_provider(
            call, assignment.assigned_provider, frontier_tier
        )
        other = next(
            member
            for member in frontier_tier.providers
            if member != assignment.assigned_provider
        )
        with pytest.raises((RootProviderConflictError, UnassignedRootProviderError)):
            root_rotation.record_root_provider(call, other, frontier_tier)

    def test_a_second_identical_recording_is_idempotent(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(root_rotation.database_url)
        assignment = root_rotation.assign(call, frontier_tier)
        first_assignment, first_served = root_rotation.record_root_provider(
            call, assignment.assigned_provider, frontier_tier
        )
        second_assignment, second_served = root_rotation.record_root_provider(
            call, assignment.assigned_provider, frontier_tier
        )
        assert first_assignment.assigned_at == second_assignment.assigned_at
        assert second_served.recorded is False
        assert second_served.recorded_at == first_served.recorded_at

    def test_the_pair_re_reads_the_same_rotation_row(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The pair's assignment is the store's own row, not a second write."""
        campaign = str(uuid.uuid4())
        first, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        second, _ = root_call(root_rotation.database_url, campaign_id=campaign)
        first_family = root_rotation.assign(first, frontier_tier).assigned_provider
        second_family = root_rotation.assign(second, frontier_tier).assigned_provider
        written, _ = root_rotation.record_root_provider(
            first, first_family, frontier_tier
        )
        assignment, _ = root_rotation.record_root_provider(
            second, second_family, frontier_tier
        )
        assert len(root_rotation.rotation(campaign)) == 2
        assert assignment.digest == rotation_digest(campaign, frontier_tier)
        assert root_rotation.get(campaign, first.node_id) is not None
        assert written.assigned_at == root_rotation.get(
            campaign, first.node_id
        ).assigned_at


# ── Construction ──────────────────────────────────────────────────────────────


class TestConstruction:
    """The store's own contract."""

    def test_construction_performs_no_io(self, tmp_path) -> None:
        store = RootRotation(f"sqlite:///{tmp_path / 'never.db'}")
        assert not store.path.exists()

    def test_resolve_reads_the_environment(self, tree_database: str) -> None:
        assert RootRotation.resolve({"DATABASE_URL": tree_database}) is not None

    def test_resolve_answers_none_when_unset(self) -> None:
        assert RootRotation.resolve({}) is None
        assert RootRotation.resolve({"DATABASE_URL": "   "}) is None

    def test_resolve_answers_none_for_an_unset_environment(
        self, monkeypatch
    ) -> None:
        from providers._rotation import DATABASE_URL_ENV

        monkeypatch.delenv(DATABASE_URL_ENV, raising=False)
        assert RootRotation.resolve() is None

    def test_a_blank_url_is_refused(self) -> None:
        with pytest.raises(RootRotationError):
            RootRotation("")
        with pytest.raises(RootRotationError):
            RootRotation("   ")

    def test_a_non_sqlite_url_is_refused_by_name(self) -> None:
        store = RootRotation("postgresql://localhost/nullius")
        with pytest.raises(RootRotationError) as caught:
            _ = store.path
        assert "postgresql" in str(caught.value)

    def test_a_url_carrying_a_host_is_refused(self) -> None:
        with pytest.raises(RootRotationError):
            _ = RootRotation("sqlite://elsewhere/tree.db").path

    def test_an_in_memory_url_is_refused(self) -> None:
        # An in-memory database dies with the connection that opened it, and
        # a campaign's rotation must outlive the call that decided it: the
        # discovery loop places the roots in one process and the loader
        # re-derives the assignment in another.
        with pytest.raises(RootRotationError):
            _ = RootRotation("sqlite:///:memory:").path

    def test_the_provider_rotation_is_the_same_deployment(
        self, tree_database: str
    ) -> None:
        store = RootRotation(tree_database)
        assert store.provider_rotation.database_url == tree_database

    def test_a_repr_names_the_url(self, tree_database: str) -> None:
        assert tree_database in repr(RootRotation(tree_database))


# ── The module-level spelling ─────────────────────────────────────────────────


class TestAssignRootProvider:
    """``assign_root_provider`` — for the caller holding no store."""

    def test_it_assigns_through_a_named_store(
        self, tree_database: str, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(tree_database)
        assignment = assign_root_provider(call, frontier_tier, database_url=tree_database)
        assert assignment.node_id == node
        assert assignment.recorded is True

    def test_it_reads_the_environment(
        self, tree_database: str, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, _ = root_call(tree_database)
        assignment = assign_root_provider(
            call, frontier_tier, env={"DATABASE_URL": tree_database}
        )
        assert assignment.recorded is True

    def test_it_refuses_by_name_when_nothing_names_a_store(
        self, root_call, frontier_tier: FrontierTier
    ) -> None:
        call = RootCall(
            node_id=str(uuid.uuid4()),
            campaign_id=str(uuid.uuid4()),
            depth=0,
        )
        with pytest.raises(RootRotationError) as caught:
            assign_root_provider(call, frontier_tier, env={})
        assert "DATABASE_URL" in str(caught.value)

    def test_a_malformed_ask_is_refused_before_the_store_is_resolved(
        self, frontier_tier: FrontierTier
    ) -> None:
        """No store named, and a bad call: the call is what is reported only
        when a store exists — with none, the missing store is the first fact
        a caller must fix, which is the order the function states."""
        with pytest.raises(RootRotationError) as caught:
            assign_root_provider("a root call", frontier_tier, env={})
        assert "DATABASE_URL" in str(caught.value)


# ── Against the tree the fixture built ────────────────────────────────────────


class TestAgainstARealTree:
    """End to end, over a migration-built ``node`` table."""

    def test_a_campaigns_roots_rotate_across_the_families(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        campaign = str(uuid.uuid4())
        for _ in range(24):
            call, _ = root_call(root_rotation.database_url, campaign_id=campaign)
            root_rotation.assign(call, frontier_tier)
        families = {
            record.provider for record in root_rotation.rotation(campaign).values()
        }
        assert families == {member.provider for member in frontier_tier.providers}

    def test_the_rotation_survives_a_second_store(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        """The reason it is persisted at all: another process reads it."""
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        reopened = RootRotation(root_rotation.database_url)
        read = reopened.get(call.campaign_id, node)
        assert read is not None
        assert read.provider == root_rotation.get(call.campaign_id, node).provider
        assert reopened.rotation(call.campaign_id) != {}

    def test_a_mixed_case_campaign_id_reads_the_same_rotation(
        self, root_rotation: RootRotation, root_call, frontier_tier: FrontierTier
    ) -> None:
        call, node = root_call(root_rotation.database_url)
        root_rotation.assign(call, frontier_tier)
        assert root_rotation.get(call.campaign_id.upper(), node) is not None

    def test_the_tree_file_is_the_stores_own_path(
        self, root_rotation: RootRotation
    ) -> None:
        assert root_rotation.path == sqlite_path_of(root_rotation.database_url)
