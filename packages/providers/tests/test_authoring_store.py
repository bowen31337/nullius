"""Feature 4's suite: the authoring addition's persistence door.

additions_spec_llm_authoring.xml, "Authoring Foundation", feature 4: *System
persists authoring provenance with ``providers.record_authoring(record, *,
database_url=None, env=None)`` once the record's node row exists.  It also
persists a campaign's measured depth cache hit rate with
``providers.record_campaign_cache_rate(campaign_id, records, *,
database_url=None, env=None)``.*

What this suite pins is the door, not the stores: the three facts each store
already owns (feature 203's triple, 204's weights, 196/197's root pair, 200's
measured rate) arriving in the order the door states, routed by the record's
role, refused by the stores' own vocabulary unchanged, and idempotent because
each store is.  The stores' own suites pin their halves; this one pins the
wiring — the order (pin before weights before the root pair), the routing
(root records file the rotation pair, depth and policy records file no root
row), the propagation (a missing node row is
:class:`~providers.NodeNotRecordedError` verbatim, the spec's word
*"unchanged"*), and the filter (a campaign's rate is measured from its
depth-role records' usage, and nothing else's).

**Every database here is a throwaway SQLite file** — the per-test
``database_url`` fixture — with the schema brought to it by the migrations
that own it, exactly as the rest of this suite does.  **No test opens a
network connection, places a model call, or reads a credential**: the only
"providers" in this file are pin strings, which are names and not secrets;
the one environment variable read is the member's own ``DATABASE_URL``; and
the records are built in memory, never answered by a backend.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import replace
from fractions import Fraction
from types import SimpleNamespace

import pytest
from conftest import sqlite_path_of
from providers import (
    AgentSampling,
    AuthoringConfigError,
    AuthoringRecord,
    DepthCacheError,
    MeasuredCacheRate,
    ModelPin,
    ModelPinConflictError,
    ModelPinError,
    NodeNotRecordedError,
    RootProviderError,
    RootProviderRotation,
    RootRotation,
    UnassignedRootProviderError,
    UnplannedCampaignError,
    UnrotatedCampaignError,
    Usage,
    record_authoring,
    record_campaign_cache_rate,
    rotation_digest,
    rotation_index,
)

#: The three call sites the record's ``role`` is drawn from, spelled here
#: rather than imported so a reorder of the member's tuple is a failing test
#: about the *feature text* (the door routes on ``root`` and ``depth`` by
#: index) rather than a suite that follows the code.
ROLES = ("root", "depth", "policy")

#: §14.2's own roots and depth rows, as the pin strings a deployment writes —
#: names and snapshot dates, which are pins and not credentials.
ROOT_PINS = (
    "anthropic/claude-opus-5/20260401",
    "openai/gpt-5.6-sol/20260701",
    "google/gemini-3.1-pro/20260801",
)
DEPTH_PIN = "deepseek/deepseek-v4-flash/20260910"

#: A frontier family's snapshot date, by provider — so a record built for a
#: declared member carries a full ``p/m/v`` pin the way a deployment states one.
VERSIONS = {
    pin.split("/")[0]: pin.split("/")[2] for pin in (*ROOT_PINS, DEPTH_PIN)
}

#: The two tables features 196 and 197 own, spelled here so a rename is a
#: failing test about which tables a depth record must *not* bring into being.
ROOT_TABLES = ("root_serving_provider", "root_provider_rotation")

#: The environment variable naming the store, pinned the same way as ROLES.
DATABASE_URL_ENV = "DATABASE_URL"

#: The record's nine fields, restated for the foreign-copy test so the stub
#: carries exactly what recognition reads — no more, no less.
RECORD_PARTS = (
    "node_id",
    "campaign_id",
    "depth",
    "role",
    "pin",
    "sampling",
    "usage",
    "served_model",
    "tier",
)


def pin_for(member) -> ModelPin:
    """A full pin for a declared frontier member: family, line and snapshot."""
    return ModelPin(
        provider=member.provider,
        model=member.model,
        version=VERSIONS[member.provider],
    )


def make_record(**overrides) -> AuthoringRecord:
    """A depth record with sensible defaults, any field overridden.

    The defaults are the depth role's — the addition's workhorse tier and the
    one the campaign driver records most — with a fresh node and campaign, so
    a test that overrides nothing is a test about *the door*, and a root or
    policy test overrides ``role`` (and, for a root, the tier and the
    rotation-consistent pin) and is a test about *the routing*.
    """
    fields = {
        "node_id": str(uuid.uuid4()),
        "campaign_id": str(uuid.uuid4()),
        "depth": 2,
        "role": "depth",
        "pin": ModelPin(*DEPTH_PIN.split("/")),
        "sampling": AgentSampling(temperature=0.4),
        "usage": Usage(
            input_tokens=300_000, output_tokens=8_192, cache_read_tokens=240_000
        ),
        "served_model": "deepseek-v4-flash",
        "tier": None,
    }
    fields.update(overrides)
    return AuthoringRecord(**fields)


def root_record(database: str, tier, *, depth: int = 0):
    """A root record whose pin is the family the rotation assigns its node.

    Plants the node (a root row whose trio holds ``NULL``, so the door's
    writes are genuinely reachable) and builds the record feature 3's session
    would have: the pin drawn by the same :func:`rotation_index` arithmetic
    the recorder re-runs, which is why *the recorder never meets
    UnassignedRootProviderError* — the spec's own sentence, made testable by
    pinning the one family that files cleanly and its complement below.
    """
    node, campaign = plant_root(database, depth=depth)
    assigned = tier.providers[rotation_index(campaign, node, tier)]
    return (
        make_record(
            role="root",
            depth=depth,
            node_id=node,
            campaign_id=campaign,
            pin=pin_for(assigned),
            served_model=assigned.model,
            tier=tier,
        ),
        assigned,
    )


def plant_root(database: str, *, depth: int = 0):
    """Insert one node row whose trio columns hold ``NULL``; answer its ids.

    The state the door's every write branch is reachable on, planted here
    rather than through :func:`plant_node` because a root record must also
    agree with the tree about *which campaign* the node belongs to — the root
    path checks that agreement, and a fixture that minted the campaign
    inside itself would leave the test unable to build a record that does.
    Mirrors the conftest planters' own shape (raw SQL, only this suite's
    tree), with the trio explicitly ``NULL`` rather than defaulted.
    """
    node, campaign = str(uuid.uuid4()), str(uuid.uuid4())
    with closing(sqlite3.connect(sqlite_path_of(database))) as connection, connection:
        connection.execute(
            "INSERT INTO node (id, parent_id, campaign_id, theme_root, depth, "
            "agent_model_id, agent_sampling, agent_ckpt_hash) "
            "VALUES (?, ?, ?, 'macro', ?, ?, ?, ?)",
            (node, None, campaign, depth, None, None, None),
        )
    return node, campaign


def trio_of(database: str, node: str):
    """The node's three authoring columns, read straight from the table.

    A raw read rather than a call into the store, on the ground this suite's
    own conftest states for its readers: several of these tests are about
    *what the door did not change*, and asking a store to confirm that would
    be asking the thing under test.
    """
    with closing(sqlite3.connect(sqlite_path_of(database))) as connection:
        return connection.execute(
            "SELECT agent_model_id, agent_sampling, agent_ckpt_hash "
            "FROM node WHERE id = ?",
            (node,),
        ).fetchone()


def table_exists(database: str, table: str) -> bool:
    """Does the database hold this table? — ``sqlite_master``, never the rows."""
    with closing(sqlite3.connect(sqlite_path_of(database))) as connection:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )


def root_tables_exist(database: str) -> set[str]:
    """The rotation tables the database holds — usually asserted empty."""
    return {table for table in ROOT_TABLES if table_exists(database, table)}


# ── The trio: pin, dice, and no root row ──────────────────────────────────────


class TestTheTrio:
    """``record_authoring`` writes the author and the dice on the node row."""

    def test_the_pin_and_the_dice_land_on_the_node_row(
        self, weights_database: str, plant_node
    ) -> None:
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record = make_record(node_id=node)
        node_pin, weights, root_pair = record_authoring(
            record, database_url=weights_database
        )
        assert node_pin.pin.agent_model_id == DEPTH_PIN
        assert node_pin.recorded is True
        assert weights.recorded is True
        assert root_pair is None
        assert trio_of(weights_database, node) == (
            DEPTH_PIN,
            record.sampling.to_json(),
            None,
        )

    def test_the_checkpoint_hash_is_the_hosted_null(
        self, weights_database: str, plant_node
    ) -> None:
        # The door passes HOSTED_API_CKPT_HASH, whose SQL NULL is the recorded
        # fact — these weights live somewhere this system never hashed (§9.1:
        # non-null for self-hosted weights) — and not a column the door forgot.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        _, weights, _ = record_authoring(
            make_record(node_id=node), database_url=weights_database
        )
        assert weights.ckpt_hash is None
        assert not weights.self_hosted
        assert trio_of(weights_database, node)[2] is None

    def test_a_depth_record_writes_no_root_row(
        self, weights_database: str, plant_node
    ) -> None:
        # The spec's own routing: a depth record files the trio and nothing
        # else, and "nothing else" is observable as two tables that were never
        # created — the rotation stores create lazily, on a root record.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record_authoring(make_record(node_id=node), database_url=weights_database)
        assert root_tables_exist(weights_database) == set()

    def test_a_policy_record_writes_no_root_row(
        self, weights_database: str, plant_node
    ) -> None:
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        _, _, root_pair = record_authoring(
            make_record(role="policy", node_id=node), database_url=weights_database
        )
        assert root_pair is None
        assert root_tables_exist(weights_database) == set()

    def test_recording_the_same_record_twice_is_idempotent(
        self, weights_database: str, plant_node
    ) -> None:
        # The spec's sentence, and the property is the stores': the second
        # call answers recorded=False for both halves and the row it answers
        # is the one the first call wrote — no new row, no moved instant.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record = make_record(node_id=node)
        first = record_authoring(record, database_url=weights_database)
        row_after_first = trio_of(weights_database, node)
        second = record_authoring(record, database_url=weights_database)
        assert (first[0].recorded, first[1].recorded) == (True, True)
        assert (second[0].recorded, second[1].recorded) == (False, False)
        assert second[0].pin == first[0].pin
        assert second[1].sampling == first[1].sampling
        assert trio_of(weights_database, node) == row_after_first
        with closing(sqlite3.connect(sqlite_path_of(weights_database))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM node").fetchone()[0] == 1

    def test_a_missing_node_row_is_the_stores_own_refusal(
        self, weights_database: str
    ) -> None:
        # "A missing node row raises the stores' own NodeNotRecordedError,
        # unchanged" — pinned as the exact type (no wrapper, no translation)
        # and the store's own wording, for the depth role and the root role
        # alike: the pin store runs first for both.
        with pytest.raises(NodeNotRecordedError) as caught:
            record_authoring(make_record(), database_url=weights_database)
        assert caught.type is NodeNotRecordedError
        assert "there is no node" in str(caught.value)

    def test_a_stored_triple_that_disagrees_is_the_stores_conflict(
        self, weights_database: str, plant_node
    ) -> None:
        # The row already names another author and the door refuses through
        # the store's own conflict — provenance is append-once per node, and
        # the door adds no policy of its own in front of the one the store
        # states.
        node = plant_node(weights_database, str(uuid.uuid4()))
        with pytest.raises(ModelPinConflictError) as caught:
            record_authoring(make_record(node_id=node), database_url=weights_database)
        assert caught.type is ModelPinConflictError
        assert ROOT_PINS[0] in str(caught.value)

    def test_the_pin_lands_before_the_dice(
        self, weights_database: str, plant_node
    ) -> None:
        # The order is load-bearing, not stylistic: persist_weights refuses a
        # row with no agent_model_id, so a door that recorded the dice first
        # would refuse every unpinned node instead of pinning it.  Pinned by
        # planting a row with *no* author — the state only this order can
        # file — and observing both columns arrive.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record_authoring(make_record(node_id=node), database_url=weights_database)
        author, sampling, ckpt = trio_of(weights_database, node)
        assert author == DEPTH_PIN
        assert sampling is not None
        assert ckpt is None


# ── The root record: the rotation pair beside the trio ────────────────────────


class TestTheRootRecord:
    """A root record also files the assignment and the provenance pair."""

    def test_it_files_the_rotation_pair_beside_the_trio(
        self, weights_database: str, frontier_tier
    ) -> None:
        record, assigned = root_record(weights_database, frontier_tier)
        node_pin, weights, root_pair = record_authoring(
            record, database_url=weights_database
        )
        assert node_pin.recorded is True
        assert weights.recorded is True
        assert root_pair is not None
        assignment, served = root_pair
        assert assignment.assigned_provider == assigned
        assert served.serving_provider == assigned
        assert served.node_id == record.node_id
        assert served.recorded is True

    def test_the_pair_records_the_tiers_own_decision(
        self, weights_database: str, frontier_tier
    ) -> None:
        # The same arithmetic the session drew the pin by: the digest names
        # this campaign under this declared set, and the assigned family is
        # the slot the hash drew — so a caller can re-derive the rotation
        # from the campaign id and the tier alone.
        record, assigned = root_record(weights_database, frontier_tier)
        record_authoring(record, database_url=weights_database)
        stored = RootRotation(weights_database).get(
            record.campaign_id, record.node_id
        )
        assert stored is not None
        assert stored.assigned_provider == assigned
        assert stored.digest == rotation_digest(record.campaign_id, frontier_tier)
        serving = RootProviderRotation(weights_database).get(record.node_id)
        assert serving is not None
        assert serving.serving_provider == assigned

    def test_a_family_the_rotation_did_not_assign_is_refused_after_the_trio(
        self, weights_database: str, frontier_tier
    ) -> None:
        # The §14.1 silent re-route refusal, and the door's own order made
        # visible: the trio is on the row when the rotation refuses, because
        # the author is the fact every reader of the tree is owed and the
        # disagreement is about the *call*, not the author.
        record, assigned = root_record(weights_database, frontier_tier)
        other = next(
            member
            for member in frontier_tier.providers
            if member != assigned
        )
        unassigned = make_record(
            role="root",
            depth=0,
            node_id=record.node_id,
            campaign_id=record.campaign_id,
            pin=pin_for(other),
            served_model=other.model,
            tier=frontier_tier,
        )
        with pytest.raises(UnassignedRootProviderError):
            record_authoring(unassigned, database_url=weights_database)
        assert trio_of(weights_database, record.node_id) == (
            pin_for(other).agent_model_id,
            unassigned.sampling.to_json(),
            None,
        )
        assert (
            RootProviderRotation(weights_database).get(record.node_id) is None
        )

    def test_a_root_record_below_the_boundary_is_the_stores_refusal(
        self, weights_database: str, frontier_tier
    ) -> None:
        # A root record whose node the tree places at depth 2 is refused by
        # feature 196's boundary — the store's own, unchanged — after the
        # trio landed, for the same reason the unassigned family is.
        record, _ = root_record(weights_database, frontier_tier, depth=2)
        with pytest.raises(UnrotatedCampaignError):
            record_authoring(record, database_url=weights_database)
        assert trio_of(weights_database, record.node_id)[0] is not None

    def test_a_root_record_twice_answers_the_same_rows(
        self, weights_database: str, frontier_tier
    ) -> None:
        # The idempotence sentence for the root half: one assignment row and
        # one provenance row, whatever the retry's clock says, with the
        # original instants — the rows are the decision, and a retry is the
        # same decision arriving twice.
        record, _ = root_record(weights_database, frontier_tier)
        _, _, first_pair = record_authoring(record, database_url=weights_database)
        _, _, second_pair = record_authoring(record, database_url=weights_database)
        assert first_pair is not None and second_pair is not None
        assert second_pair[0].recorded is False
        assert second_pair[0].assigned_at == first_pair[0].assigned_at
        assert second_pair[1].recorded is False
        assert second_pair[1].recorded_at == first_pair[1].recorded_at
        with closing(sqlite3.connect(sqlite_path_of(weights_database))) as connection:
            for table in ROOT_TABLES:
                assert connection.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0] == 1

    def test_the_tier_is_required_and_refused_by_the_gate(
        self, weights_database: str
    ) -> None:
        # A root record with no tier cannot name the declared set the
        # rotation assigns out of, and the refusal is the rotation store's
        # own — the door neither supplies a default tier nor restates the
        # law.
        node, campaign = plant_root(weights_database)
        with pytest.raises(RootProviderError):
            record_authoring(
                make_record(
                    role="root", node_id=node, campaign_id=campaign, tier=None
                ),
                database_url=weights_database,
            )


# ── The door's own contract: the store, the record, the refusal ───────────────


class TestTheDoorItself:
    """Resolution, recognition, and the two refusals that are the door's own."""

    def test_the_store_is_named_by_database_url(
        self, weights_database: str, plant_node
    ) -> None:
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record_authoring(
            make_record(node_id=node), database_url=weights_database
        )
        assert trio_of(weights_database, node)[0] == DEPTH_PIN

    def test_the_store_is_read_from_env(
        self, weights_database: str, plant_node
    ) -> None:
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record_authoring(
            make_record(node_id=node), env={DATABASE_URL_ENV: weights_database}
        )
        assert trio_of(weights_database, node)[0] == DEPTH_PIN

    def test_the_store_is_read_from_the_environment_of_the_moment(
        self, weights_database: str, plant_node, monkeypatch
    ) -> None:
        # ``env=None`` is the composition-time spelling — the caller hands no
        # mapping and the door reads the environment it runs in.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        monkeypatch.setenv(DATABASE_URL_ENV, weights_database)
        record_authoring(make_record(node_id=node))
        assert trio_of(weights_database, node)[0] == DEPTH_PIN

    def test_nothing_names_a_store_is_refused_by_naming_the_variable(
        self
    ) -> None:
        # Not a silent skip: a provenance write that quietly failed would
        # leave a tree whose nodes carry no author.  The refusal names
        # DATABASE_URL — the pin store's base, because that is the store the
        # door writes through first.
        with pytest.raises(ModelPinError) as caught:
            record_authoring(make_record(), env={})
        assert DATABASE_URL_ENV in str(caught.value)
        assert caught.type is ModelPinError

    def test_a_missing_store_is_reported_before_a_malformed_record(
        self
    ) -> None:
        # The order the door states: with no store named, the missing store
        # is the first fact a caller must fix — the record cannot be filed
        # anywhere, well-formed or not.
        with pytest.raises(ModelPinError) as caught:
            record_authoring("a record", env={})
        assert DATABASE_URL_ENV in str(caught.value)

    def test_a_foreign_copy_of_the_record_files_through_this_module(
        self, weights_database: str, plant_node
    ) -> None:
        # The module loader imports every member twice, so the record a
        # caller holds may be the other copy's class.  Recognition is by
        # parts, and the answer is re-made through this module's record —
        # which is why a stub carrying the nine parts files cleanly.
        node = plant_node(
            weights_database, str(uuid.uuid4()), agent_model_id=None, agent_sampling=None
        )
        record = make_record(node_id=node)
        stub = SimpleNamespace(
            **{part: getattr(record, part) for part in RECORD_PARTS}
        )
        record_authoring(stub, database_url=weights_database)
        assert trio_of(weights_database, node)[0] == DEPTH_PIN

    @pytest.mark.parametrize(
        "shape", ["a record", None, 7, SimpleNamespace(node_id="7be0d3b2")]
    )
    def test_a_value_that_is_not_a_record_is_refused(
        self, weights_database: str, shape
    ) -> None:
        # Feature 2's vocabulary, because the record is feature 2's value —
        # and the code word, so the refusal is greppable in a launch log.
        with pytest.raises(AuthoringConfigError) as caught:
            record_authoring(shape, database_url=weights_database)
        assert str(caught.value).startswith("authoring_config: ")
        assert "AuthoringRecord" in str(caught.value)

    def test_the_records_own_guards_run_through_the_door(
        self, weights_database: str
    ) -> None:
        # A role outside the three call sites is refused by the record's own
        # guard, re-run because the door re-makes the record — one validation
        # path, so the door and the constructor cannot disagree.
        with pytest.raises(AuthoringConfigError):
            record_authoring(
                make_record(role="frontier"), database_url=weights_database
            )

    def test_a_policy_records_revision_ids_meet_the_stores_id_law(
        self, weights_database: str
    ) -> None:
        # Dreaming's revisions are keyed "revision-N", not tree nodes — and
        # the spec's routing hands every record to AgentModelPins.persist,
        # whose id law canonicalizes through uuid.UUID.  The refusal is the
        # store's own, unchanged: the door files where the tree holds a row,
        # and the reviser's caller is the later feature that decides where
        # its records' nodes live.
        with pytest.raises(ModelPinError) as caught:
            record_authoring(
                make_record(
                    role="policy", node_id="revision-3", campaign_id="policy-development"
                ),
                database_url=weights_database,
            )
        assert "revision-3" in str(caught.value)


# ── The measured rate: the depth role's usage, and only that ──────────────────


class TestTheMeasuredRate:
    """``record_campaign_cache_rate`` — the filter, the store, the same row."""

    def test_it_measures_the_depth_records_of_that_campaign(
        self, campaign_database: str, plant_campaign
    ) -> None:
        campaign = plant_campaign(campaign_database)
        other = plant_campaign(campaign_database)
        records = [
            make_record(
                role="depth",
                campaign_id=campaign,
                usage=Usage(
                    input_tokens=300_000,
                    output_tokens=8_192,
                    cache_read_tokens=240_000,
                ),
            ),
            make_record(
                role="depth",
                campaign_id=campaign,
                usage=Usage(
                    input_tokens=300_000,
                    output_tokens=4_096,
                    cache_read_tokens=60_000,
                ),
            ),
            make_record(
                role="depth",
                campaign_id=campaign,
                usage=Usage(
                    input_tokens=300_000,
                    output_tokens=2_048,
                    cache_read_tokens=300_000,
                ),
            ),
            # Another campaign's depth record: ignored.
            make_record(
                role="depth",
                campaign_id=other,
                usage=Usage(
                    input_tokens=999_999,
                    output_tokens=1,
                    cache_read_tokens=999_999,
                ),
            ),
            # This campaign's root and policy records: ignored, each for its
            # own reason — the roots tier's spend is not the depth tier's
            # premise, and dreaming's revisions are not the depth model's calls.
            make_record(
                role="root",
                depth=0,
                campaign_id=campaign,
                usage=Usage(
                    input_tokens=500_000, output_tokens=2_000, cache_read_tokens=0
                ),
            ),
            make_record(
                role="policy",
                campaign_id=campaign,
                usage=Usage(
                    input_tokens=500_000, output_tokens=2_000, cache_read_tokens=0
                ),
            ),
        ]
        measured = record_campaign_cache_rate(
            campaign, records, database_url=campaign_database
        )
        assert isinstance(measured, MeasuredCacheRate)
        assert measured.campaign_id == campaign
        assert measured.input_tokens == 900_000
        assert measured.cache_read_tokens == 600_000
        assert measured.hit_rate == Fraction(600_000, 900_000)
        assert measured.recorded is True

    def test_repeating_the_call_answers_the_same_row(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # The spec's own sentence: identical records are identical totals,
        # and feature 200's own idempotence answers the stored row — the
        # measured_at the first call stamped, and recorded=False.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(role="depth", campaign_id=campaign),
            make_record(role="depth", campaign_id=campaign),
        ]
        first = record_campaign_cache_rate(
            campaign, records, database_url=campaign_database
        )
        second = record_campaign_cache_rate(
            campaign, records, database_url=campaign_database
        )
        assert first.recorded is True
        assert second.recorded is False
        assert second == replace(first, recorded=False)
        assert second.measured_at == first.measured_at

    def test_root_and_policy_records_never_reach_the_measurement(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # Only root and policy records of the campaign: the filter holds all
        # of them back, and the store's own refusal — a measurement of no
        # calls is not a measurement — is what answers.  The exclusion is
        # the door's, proven by the store refusing.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(role="root", depth=0, campaign_id=campaign),
            make_record(role="policy", campaign_id=campaign),
        ]
        with pytest.raises(DepthCacheError):
            record_campaign_cache_rate(
                campaign, records, database_url=campaign_database
            )

    def test_other_campaigns_records_never_reach_the_measurement(
        self, campaign_database: str, plant_campaign
    ) -> None:
        campaign = plant_campaign(campaign_database)
        other = plant_campaign(campaign_database)
        records = [make_record(role="depth", campaign_id=other)]
        with pytest.raises(DepthCacheError):
            record_campaign_cache_rate(
                campaign, records, database_url=campaign_database
            )

    def test_a_mixed_case_spelling_of_the_campaign_is_the_same_campaign(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # The filter compares canonical ids, so a record carrying an
        # upper-case spelling of the campaign belongs to it — one campaign,
        # one measurement, not two figures about the same spend.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(role="depth", campaign_id=campaign),
            make_record(role="depth", campaign_id=campaign.upper()),
        ]
        measured = record_campaign_cache_rate(
            campaign, records, database_url=campaign_database
        )
        assert measured.input_tokens == 2 * 300_000

    def test_a_policy_records_revision_campaign_is_ignored_not_refused(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # The role filter runs before the campaign is ever compared: dreaming
        # records carry "policy-development" as their campaign, which names
        # no UUID, and the sentence's *ignored* must not turn into a refusal
        # about a record the measurement was never about.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(
                role="depth",
                campaign_id=campaign,
                usage=Usage(input_tokens=100, output_tokens=10),
            ),
            make_record(role="policy", campaign_id="policy-development"),
        ]
        measured = record_campaign_cache_rate(
            campaign, records, database_url=campaign_database
        )
        assert measured.input_tokens == 100

    def test_a_depth_record_of_no_campaign_is_refused_rather_than_dropped(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # "Ignored" is for records that are provably of another campaign or
        # of another role; a depth record whose campaign names no campaign is
        # one the filter cannot decide about, and a measurement that quietly
        # dropped it would under-count the spend the depth tier made.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(role="depth", campaign_id="not-a-campaign"),
        ]
        with pytest.raises(DepthCacheError) as caught:
            record_campaign_cache_rate(
                campaign, records, database_url=campaign_database
            )
        assert "records[0]" in str(caught.value)

    def test_an_unplanned_campaign_is_the_stores_refusal(
        self, campaign_database: str
    ) -> None:
        # Feature 200's gate, unchanged: the campaign table holds no such
        # row, and a rate measured for a campaign nobody planned is a figure
        # about nothing.
        campaign = str(uuid.uuid4())
        with pytest.raises(UnplannedCampaignError):
            record_campaign_cache_rate(
                campaign,
                [make_record(role="depth", campaign_id=campaign)],
                database_url=campaign_database,
            )

    def test_a_malformed_campaign_id_is_refused(
        self, campaign_database: str
    ) -> None:
        with pytest.raises(DepthCacheError) as caught:
            record_campaign_cache_rate(
                "not-a-campaign", [], database_url=campaign_database
            )
        assert "campaign_id" in str(caught.value)

    def test_the_store_is_read_from_env(
        self, campaign_database: str, plant_campaign
    ) -> None:
        campaign = plant_campaign(campaign_database)
        measured = record_campaign_cache_rate(
            campaign,
            [make_record(role="depth", campaign_id=campaign)],
            env={DATABASE_URL_ENV: campaign_database},
        )
        assert measured.recorded is True

    def test_nothing_names_a_store_is_refused_by_naming_the_variable(
        self
    ) -> None:
        # The measure_cache_rate precedent, mirrored: the refusal names the
        # variable, never its value, and is the measurement store's own base.
        with pytest.raises(DepthCacheError) as caught:
            record_campaign_cache_rate(str(uuid.uuid4()), [], env={})
        assert DATABASE_URL_ENV in str(caught.value)
        assert caught.type is DepthCacheError

    def test_a_non_record_entry_is_refused_by_position(
        self, campaign_database: str, plant_campaign
    ) -> None:
        # A caller holding a campaign's records needs to know which entry to
        # look at, so the refusal names the position — and is feature 2's
        # vocabulary, because the record is feature 2's value.
        campaign = plant_campaign(campaign_database)
        records = [
            make_record(role="depth", campaign_id=campaign),
            "nope",
        ]
        with pytest.raises(AuthoringConfigError) as caught:
            record_campaign_cache_rate(
                campaign, records, database_url=campaign_database
            )
        assert "records[1]" in str(caught.value)


# ── The spelling: the exports and the roles the routing rests on ─────────────


class TestTheExports:
    """The sentence's last clause: both names in ``providers.__all__``."""

    def test_both_functions_are_exported(self) -> None:
        import providers

        assert "record_authoring" in providers.__all__
        assert "record_campaign_cache_rate" in providers.__all__
        assert callable(providers.record_authoring)
        assert callable(providers.record_campaign_cache_rate)

    def test_the_roles_the_door_routes_on_are_the_spec_order(self) -> None:
        # The door routes by index into the tuple feature 2 declares, so the
        # tuple's order is load-bearing here and pinned against the spec's
        # own three call sites.
        from providers._authoring import AUTHORING_ROLES

        assert AUTHORING_ROLES == ROLES
